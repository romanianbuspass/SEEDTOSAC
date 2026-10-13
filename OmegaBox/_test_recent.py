"""E2E test for gaiacode_pipeline_recent.py (bounded last-N-days mirror).

Mock OmegaBox serves day dirs for today-4 .. today EXCEPT today-2.
Run with --days 3 → must mirror only today-1 and today, warn on the
today-2 404, and never touch today-3/today-4.
"""
import functools
import http.server
import shutil
import socketserver
import subprocess
import sys
import threading
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import yaml
from obspy import read, Stream, Trace, UTCDateTime
from obspy.core.inventory import (Inventory, Network, Station, Channel,
                                  Site)

BASE = Path(__file__).resolve().parent
PY = sys.executable
WORK = BASE / "_test_recent"
PORT = 18232

if WORK.exists():
    shutil.rmtree(WORK)
srv_root = WORK / "srv"
srv_root.mkdir(parents=True)

today = date.today()
present_offsets = [0, 1, 3, 4]          # today-2 intentionally absent
for off in present_offsets:
    d = today - timedelta(days=off)
    day_dir = (srv_root / "data" / str(d.year) / d.strftime("%Y%m")
               / d.strftime("%Y%m%d"))
    day_dir.mkdir(parents=True)
    st = Stream()
    for ch in ("HHE", "HHN", "HHZ"):
        tr = Trace(data=np.random.randint(-99, 99, 60 * 20).astype(np.int32))
        tr.stats.network = "XX"
        tr.stats.station = "MOCK"
        tr.stats.location = "00"
        tr.stats.channel = ch
        tr.stats.starttime = UTCDateTime(d.isoformat())
        tr.stats.sampling_rate = 20.0
        st += tr
    # real OmegaBox file naming: YYYY-MM-DDT00-00-00-XX.STA.00.CHA.mseed
    for tr in st:
        fname = (f"{d.isoformat()}T00-00-00-XX.MOCK.00."
                 f"{tr.stats.channel}.mseed")
        tr.write(str(day_dir / fname), format="MSEED")

cha_list = [Channel(code=c, location_code="00", latitude=12.34,
                    longitude=78.90, elevation=500.0, depth=2.0,
                    azimuth=az, dip=dip, sample_rate=20.0,
                    start_date=UTCDateTime("2024-01-01"))
            for c, az, dip in (("HHZ", 0.0, -90.0), ("HHN", 0.0, 0.0),
                               ("HHE", 90.0, 0.0))]
inv = Inventory(networks=[Network(code="XX", stations=[Station(
    code="MOCK", latitude=12.34, longitude=78.90, elevation=500.0,
    site=Site(name="Mock"), channels=cha_list,
    creation_date=UTCDateTime("2024-01-01"))])],
    source="test", created=UTCDateTime("2024-01-01"))
xml_path = WORK / "MOCK.xml"
inv.write(str(xml_path), format="STATIONXML")

cfg = {
    "archive_paths": {"sds_root": str(WORK / "mirror"),
                      "sac_root": str(WORK / "sac")},
    "settings": {"wget_timeout_s": 60,
                 "log_file": str(WORK / "pipeline.log")},
    "stations": [{"name": "MOCK",
                  "web_url": f"http://127.0.0.1:{PORT}/data/",
                  "stationxml_path": str(xml_path)}],
}
cfg_path = WORK / "config_test.yaml"
cfg_path.write_text(yaml.safe_dump(cfg))

requests_log = []


class RecordingHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        requests_log.append(self.path)
        super().do_GET()

    def log_message(self, *a):
        pass


handler = functools.partial(RecordingHandler, directory=str(srv_root))
socketserver.ThreadingTCPServer.allow_reuse_address = True
httpd = socketserver.ThreadingTCPServer(("127.0.0.1", PORT), handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
print(f"[setup] mock OmegaBox on :{PORT}; day dirs present for offsets "
      f"{present_offsets}")

r = subprocess.run(
    [PY, str(BASE / "gaiacode_pipeline_recent.py"),
     "--config", str(cfg_path), "--days", "3"],
    capture_output=True, text=True, cwd=str(WORK), timeout=300)
print(r.stderr)

log_text = (WORK / "pipeline_recent.log").read_text()

# --- assertions -------------------------------------------------------------
mirror = WORK / "mirror" / "MOCK"
mirrored_days = sorted(p.name for p in mirror.rglob("*") if p.is_dir()
                       and len(p.name) == 8)
d = lambda off: (today - timedelta(days=off)).strftime("%Y%m%d")
assert mirrored_days == [d(1), d(0)], \
    f"expected only {[d(1), d(0)]}, got {mirrored_days}"
mseed_files = list(mirror.rglob("*.mseed"))
assert len(mseed_files) == 6, \
    f"expected 6 mseed (2 days × 3 chans), got {len(mseed_files)}"
print(f"[mirror] only in-scope days mirrored: {mirrored_days}, "
      f"{len(mseed_files)} files ✓")

m2 = (today - timedelta(days=2)).isoformat()
assert f"no data for" in log_text and m2 in log_text, \
    "missing 404 warning for absent day"
print(f"[404] absent day {m2} warned, not failed ✓")

sacs = sorted((WORK / "sac" / "MOCK").glob("*.SAC"))
assert len(sacs) == 6, f"expected 6 SAC (2 days × 3 chans), got {len(sacs)}"
tr = read(str(sacs[0]))[0]
assert tr.stats.sac.cmpinc == 90.0 and abs(tr.stats.sac.stla - 12.34) < 1e-3
print(f"[convert] {len(sacs)} SAC files, headers populated ✓")

assert r.returncode == 0, f"expected exit 0, got {r.returncode}"
assert "0 failed" in log_text
print("[exit] code 0 — 404 day correctly not counted as failure ✓")

# --- incremental re-run: -nc must slash the download volume -----------------
gets_first = sum(1 for p in requests_log if p.endswith(".mseed"))
requests_log.clear()
r2 = subprocess.run(
    [PY, str(BASE / "gaiacode_pipeline_recent.py"),
     "--config", str(cfg_path), "--days", "3"],
    capture_output=True, text=True, cwd=str(WORK), timeout=300)
gets_second = sum(1 for p in requests_log if p.endswith(".mseed"))
today_str = today.strftime("%Y%m%d")
gets_second_today = sum(1 for p in requests_log
                        if p.endswith(".mseed") and today_str in p)
print(f"[incremental] mseed GETs: first run {gets_first}, "
      f"second run {gets_second} (of which today: {gets_second_today})")
assert gets_first == 6, f"first run should fetch all 6, got {gets_first}"
assert gets_second == gets_second_today, \
    f"re-run touched past-day files: {gets_second - gets_second_today}"
print("[incremental] -nc no-clobber: past days untouched on re-run ✓")

# --- incremental conversion: state file must skip unchanged inputs ----------
log2 = (WORK / "pipeline_recent.log").read_text()
second_half = log2[log2.rindex("=== recent-data run start"):]
assert "6 file(s) unchanged since last conversion — skipped" in second_half, \
    "state-file skip line missing on re-run"
assert "0 file(s) converted, 0 failed" in second_half, \
    "re-run should convert nothing"
assert (WORK / "mirror" / ".pipeline_state.json").is_file()
print("[incremental] conversion state: re-run converted 0 files ✓")

httpd.shutdown()
shutil.rmtree(WORK)
print("RECENT PIPELINE E2E TEST PASSED")
