"""End-to-end test for gaiacode_pipeline.py against a mock OmegaBox.

1. Serves a synthetic /data/ tree over HTTP (python http.server).
2. Runs the real pipeline (real wget subprocess, real ObsPy conversion)
   with a test config: station MOCK (reachable) + station DEAD (closed
   port, exercises the network-failure path).
3. Verifies mirrored files, SAC output headers (stla/stlo/stel/cmpaz/
   cmpinc with dip+90), the log file, and a non-zero exit (DEAD failed).
"""
import functools
import http.server
import shutil
import socketserver
import subprocess
import sys
import threading
from pathlib import Path

import numpy as np
import yaml
from obspy import read, Stream, Trace, UTCDateTime
from obspy.core.inventory import (Inventory, Network, Station, Channel,
                                  Site)

BASE = Path(__file__).resolve().parent
PY = sys.executable
WORK = BASE / "_test_run"
PORT = 18231

if WORK.exists():
    shutil.rmtree(WORK)
srv_root = WORK / "srv"
srv_root.mkdir(parents=True)

# --- synthetic remote tree: /data/2024/075/*.mseed -------------------------
t0 = UTCDateTime("2024-03-15T00:00:00")
data_dir = srv_root / "data" / "2024" / "075"
data_dir.mkdir(parents=True)
st = Stream()
for ch in ("HHE", "HHN", "HHZ"):
    tr = Trace(data=np.random.randint(-999, 999, 3600 * 20).astype(np.int32))
    tr.stats.network = "XX"
    tr.stats.station = "MOCK"
    tr.stats.location = "00"
    tr.stats.channel = ch
    tr.stats.starttime = t0
    tr.stats.sampling_rate = 20.0
    st += tr
st.write(str(data_dir / "XX.MOCK.00.HH.D.2024.075.mseed"), format="MSEED")

# --- StationXML for MOCK ----------------------------------------------------
cha_list = []
for code, az, dip in (("HHZ", 0.0, -90.0), ("HHN", 0.0, 0.0),
                      ("HHE", 90.0, 0.0)):
    cha_list.append(Channel(
        code=code, location_code="00",
        latitude=12.345, longitude=78.901, elevation=500.0, depth=2.0,
        azimuth=az, dip=dip, sample_rate=20.0,
        start_date=UTCDateTime("2024-01-01")))
inv = Inventory(networks=[Network(
    code="XX",
    stations=[Station(code="MOCK", latitude=12.345, longitude=78.901,
                      elevation=500.0, site=Site(name="Mock Ridge"),
                      channels=cha_list,
                      creation_date=UTCDateTime("2024-01-01"))])],
    source="test", created=UTCDateTime("2024-01-01"))
xml_path = WORK / "MOCK.xml"
inv.write(str(xml_path), format="STATIONXML")

# --- test config -------------------------------------------------------------
cfg = {
    "archive_paths": {"sds_root": str(WORK / "mirror"),
                      "sac_root": str(WORK / "sac")},
    "settings": {"wget_timeout_s": 60,
                 "log_file": str(WORK / "pipeline.log")},
    "stations": [
        {"name": "MOCK",
         "web_url": f"http://127.0.0.1:{PORT}/data/",
         "stationxml_path": str(xml_path)},
        {"name": "DEAD",
         "web_url": "http://127.0.0.1:9/data/",   # discard port: refused
         "stationxml_path": str(xml_path)},
    ],
}
cfg_path = WORK / "config_test.yaml"
cfg_path.write_text(yaml.safe_dump(cfg))

# --- mock HTTP server ----------------------------------------------------------
handler = functools.partial(http.server.SimpleHTTPRequestHandler,
                            directory=str(srv_root))
socketserver.TCPServer.allow_reuse_address = True
httpd = socketserver.TCPServer(("127.0.0.1", PORT), handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
print(f"[setup] mock OmegaBox serving {srv_root} on :{PORT}")

try:
    r = subprocess.run(
        [PY, str(BASE / "gaiacode_pipeline.py"), "--config", str(cfg_path)],
        capture_output=True, text=True, cwd=str(WORK), timeout=300)
    print(r.stderr)
finally:
    httpd.shutdown()

log_text = (WORK / "pipeline.log").read_text()

# --- assertions ------------------------------------------------------------------
mirrored = list((WORK / "mirror" / "MOCK").rglob("*.mseed"))
assert len(mirrored) == 1, f"mirror failed: {mirrored}"
print(f"[mirror] {mirrored[0].relative_to(WORK)} mirrored ✓")

sacs = sorted((WORK / "sac" / "MOCK").glob("*.SAC"))
assert len(sacs) == 3, f"expected 3 SAC files, got {sacs}"
for sac in sacs:
    tr = read(str(sac))[0]
    h = tr.stats.sac
    ch = tr.stats.channel
    print(f"[sac] {sac.name}: stla={h.stla} stlo={h.stlo} stel={h.stel} "
          f"cmpaz={h.cmpaz} cmpinc={h.cmpinc}")
    assert abs(h.stla - 12.345) < 1e-4
    assert abs(h.stlo - 78.901) < 1e-4
    assert abs(h.stel - 500.0) < 0.5
    if ch.endswith("Z"):
        assert h.cmpinc == 0.0 and h.cmpaz == 0.0
    elif ch.endswith("N"):
        assert h.cmpinc == 90.0 and h.cmpaz == 0.0
    elif ch.endswith("E"):
        assert h.cmpinc == 90.0 and h.cmpaz == 90.0
print("[headers] dip+90 conversion and coordinates ✓")

assert "[ERROR] [DEAD] wget exited" in log_text or \
       "DEAD" in log_text and "wget" in log_text, "DEAD failure not logged"
assert "pipeline run complete: 1 file(s) converted, 1 failed" in log_text
assert r.returncode == 1, f"expected exit 1 (DEAD failed), got {r.returncode}"
print(f"[resilience] DEAD station logged + exit code 1, MOCK unaffected ✓")

shutil.rmtree(WORK)
print("PIPELINE E2E TEST PASSED")
