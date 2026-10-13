"""Headless functional test for mseed2sac-gui (offscreen Qt).

1. Synthesises a miniSEED file with ObsPy.
2. Runs ConvertWorker with a Start/Stop window (real subprocess + trim).
3. Runs ConvertWorker with no window (full-file path).
4. Instantiates MainWindow offscreen as a GUI smoke test.
5. Verifies SAC outputs and trimmed durations.
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).parent))

import numpy as np
from obspy import read, Stream, Trace, UTCDateTime
from PyQt6.QtWidgets import QApplication

from mseed2sac_gui import ConvertWorker, MainWindow, find_binary

WORK = Path(__file__).parent / "_test_data"
import shutil
if WORK.exists():
    shutil.rmtree(WORK)          # clean slate: mseed2sac never overwrites
WORK.mkdir(exist_ok=True)
SRC = WORK / "synthetic.mseed"
OUT_TRIM = WORK / "out_trim"
OUT_FULL = WORK / "out_full"
OUT_TRIM.mkdir(exist_ok=True)
OUT_FULL.mkdir(exist_ok=True)

# --- 1. synthetic data: 3 chans, 600 s @ 20 Hz ---------------------------
t0 = UTCDateTime("2024-03-15T08:00:00")
st = Stream()
for ch in ("HHE", "HHN", "HHZ"):
    tr = Trace(data=np.random.randint(-5000, 5000, 600 * 20).astype(np.int32))
    tr.stats.network = "XX"
    tr.stats.station = "TEST"
    tr.stats.location = "00"
    tr.stats.channel = ch
    tr.stats.starttime = t0
    tr.stats.sampling_rate = 20.0
    st += tr
st.write(str(SRC), format="MSEED")
print(f"[setup] wrote {SRC} ({SRC.stat().st_size} bytes)")

binary = find_binary()
assert binary, "mseed2sac binary not found"
print(f"[setup] binary: {binary}")

app = QApplication([])


def run_worker(files, outdir, start, stop, **kw):
    from PyQt6.QtCore import Qt
    w = ConvertWorker(files, outdir, start, stop, binary, **kw)
    lines, result = [], {}
    w.log.connect(lines.append, Qt.ConnectionType.DirectConnection)
    w.finished_all.connect(
        lambda ok, fail: result.update(ok=ok, fail=fail),
        Qt.ConnectionType.DirectConnection)
    w.start()
    assert w.wait(60000), "worker timed out"
    return lines, result


# --- 2. trimmed conversion: 08:02:00 -> 08:04:00 (120 s) -----------------
lines, res = run_worker([SRC], OUT_TRIM, "2024-03-15T08:02:00",
                        "2024-03-15T08:04:00")
print("\n".join(lines))
assert res == {"ok": 1, "fail": 0}, f"trim run failed: {res}"

sacs = sorted(OUT_TRIM.glob("*.SAC"))
assert len(sacs) == 3, f"expected 3 SAC files, got {sacs}"
for sac in sacs:
    tr = read(str(sac))[0]
    dur = tr.stats.endtime - tr.stats.starttime
    print(f"[trim] {sac.name}: npts={tr.stats.npts} dur={dur:.2f}s "
          f"start={tr.stats.starttime}")
    assert 118.0 <= dur <= 122.0, f"bad trimmed duration {dur}"
    assert abs((tr.stats.starttime - UTCDateTime("2024-03-15T08:02:00"))) < 1.0

# --- 3. full-file conversion ----------------------------------------------
lines, res = run_worker([SRC], OUT_FULL, "", "")
assert res == {"ok": 1, "fail": 0}, f"full run failed: {res}"
sacs = sorted(OUT_FULL.glob("*.SAC"))
assert len(sacs) == 3, f"expected 3 SAC files, got {sacs}"
tr = read(str(sacs[0]))[0]
dur = tr.stats.endtime - tr.stats.starttime
print(f"[full] {sacs[0].name}: npts={tr.stats.npts} dur={dur:.2f}s")
assert 598.0 <= dur <= 600.5

# --- 4. batch: same file twice in a folder --------------------------------
BATCH = WORK / "batch"
BATCH.mkdir(exist_ok=True)
import shutil
for i in (1, 2):
    shutil.copy(SRC, BATCH / f"batch{i}.mseed")
OUT_BATCH = WORK / "out_batch"
OUT_BATCH.mkdir(exist_ok=True)
lines, res = run_worker(sorted(BATCH.glob("*.mseed")), OUT_BATCH, "", "")
assert res == {"ok": 2, "fail": 0}, f"batch run failed: {res}"
print(f"[batch] 2/2 files converted OK, "
      f"{len(list(OUT_BATCH.glob('*.SAC')))} SAC files written")

# --- 5. metadata flags: -k lat/lon, -m metafile, -msi ----------------------
META = WORK / "metadata.txt"
META.write_text(
    "#net,sta,loc,chan,lat,lon,elev,depth,azimuth,SACdip,instrument,"
    "scale,scalefreq,scaleunits,samplerate,start,end\n"
    "XX,TEST,00,HHZ,34.9459,-106.4571,1671.0,145.0,328.0,90.0,"
    "TestSensor,1.0,0.02,M/S,20.0,2024-03-15T00:00:00,"
    "2599-12-31T23:59:59\n")

OUT_META = WORK / "out_meta"
OUT_META.mkdir(exist_ok=True)
lines, res = run_worker([SRC], OUT_META, "", "",
                        metafile=str(META), lat="34.9459", lon="-106.4571",
                        msi=True)
print("\n".join(lines))
assert res == {"ok": 1, "fail": 0}, f"metadata run failed: {res}"

cmdline = next(l for l in lines if l.startswith("$ "))
assert "-m " in cmdline and str(META) in cmdline, f"-m missing: {cmdline}"
assert "-k 34.9459/-106.4571" in cmdline, f"-k missing: {cmdline}"
assert "-msi" in cmdline, f"-msi missing: {cmdline}"
print(f"[flags] command verified: {cmdline}")

sacs = sorted(OUT_META.glob("*.SAC"))
assert len(sacs) == 3
for sac in sacs:
    tr = read(str(sac))[0]
    stla, stlo = tr.stats.sac.stla, tr.stats.sac.stlo
    print(f"[meta] {sac.name}: stla={stla} stlo={stlo}")
    assert abs(stla - 34.9459) < 1e-4, f"stla wrong: {stla}"
    assert abs(stlo - (-106.4571)) < 1e-4, f"stlo wrong: {stlo}"
print("[meta] -k coordinates landed in SAC headers (stla/stlo) ✓")

# --- 5b. StationXML metadata source -----------------------------------------
from obspy.core.inventory import (Inventory, Network, Station, Channel,
                                  Site, InstrumentSensitivity, Response)
from obspy.core.inventory.response import PolesZerosResponseStage

XML = WORK / "station.xml"
cha_list = []
for code, az, dip in (("HHZ", 0.0, -90.0), ("HHN", 0.0, 0.0),
                      ("HHE", 90.0, 0.0)):
    cha = Channel(code=code, location_code="00",
                  latitude=34.9459, longitude=-106.4571,
                  elevation=1671.0, depth=145.0,
                  azimuth=az, dip=dip, sample_rate=20.0,
                  start_date=UTCDateTime("2024-01-01"))
    sens = InstrumentSensitivity(value=1500.0, frequency=0.02,
                                 input_units="M/S", output_units="COUNTS")
    if code == "HHZ":
        # full PAZ stage — SACPZ-exportable
        stage = PolesZerosResponseStage(
            stage_sequence_number=1, stage_gain=1500.0,
            stage_gain_frequency=0.02,
            input_units="M/S", output_units="COUNTS",
            pz_transfer_function_type="LAPLACE (RADIANS/SECOND)",
            normalization_factor=1.0, normalization_frequency=0.02,
            zeros=[0j, 0j],
            poles=[complex(-0.037, 0.037), complex(-0.037, -0.037),
                   complex(-131.0, 467.0), complex(-131.0, -467.0)])
        cha.response = Response(instrument_sensitivity=sens,
                                response_stages=[stage])
    else:
        # sensitivity only — must exercise the SACPZ skip path
        cha.response = Response(instrument_sensitivity=sens)
    cha_list.append(cha)
inv = Inventory(networks=[Network(
    code="XX",
    stations=[Station(code="TEST", latitude=34.9459, longitude=-106.4571,
                      elevation=1671.0, site=Site(name="Test Site"),
                      channels=cha_list,
                      creation_date=UTCDateTime("2024-01-01"))])],
    source="test", created=UTCDateTime("2024-01-01"))
inv.write(str(XML), format="STATIONXML")

# unit-level: translation correctness
from mseed2sac_gui import stationxml_to_metafile
meta_log = []
tmp_csv = stationxml_to_metafile(XML, log=meta_log.append)
rows = tmp_csv.read_text().strip().splitlines()
assert len(rows) == 4, f"header + 3 channels expected, got {rows}"
z_row = next(r for r in rows if ",HHZ," in r)
e_row = next(r for r in rows if ",HHE," in r)
assert ",0," in z_row.split(",")[9] + "," or z_row.split(",")[9] == "0", \
    f"HHZ SACdip should be 0 (was {-90+90}): {z_row.split(',')[9]}"
assert z_row.split(",")[9] == "0", f"HHZ SACdip: {z_row.split(',')[9]}"
assert e_row.split(",")[9] == "90", f"HHE SACdip: {e_row.split(',')[9]}"
assert "1500.0" in z_row and "M/S" in z_row
tmp_csv.unlink()
print(f"[xml] translation unit checks ✓  ({meta_log[0]})")

# end-to-end: worker with StationXML + msi=True (must be suppressed)
OUT_XML = WORK / "out_xml"
OUT_XML.mkdir(exist_ok=True)
lines, res = run_worker([SRC], OUT_XML, "", "",
                        metafile=str(XML), msi=True)
print("\n".join(lines))
assert res == {"ok": 1, "fail": 0}, f"StationXML run failed: {res}"
assert any("StationXML: translated 3 channel(s)" in l for l in lines)
assert any("ignoring the -msi toggle" in l for l in lines), \
    "msi-suppression note missing"
cmdline = next(l for l in lines if l.startswith("$ "))
assert "-m " in cmdline and "mseed2sac_meta_" in cmdline
assert "-msi" not in cmdline, "-msi must be suppressed for StationXML"

for sac in sorted(OUT_XML.glob("*.SAC")):
    tr = read(str(sac))[0]
    h = tr.stats.sac
    print(f"[xml] {sac.name}: stla={h.stla} stlo={h.stlo} stel={h.stel} "
          f"cmpaz={h.cmpaz} cmpinc={h.cmpinc}")
    assert abs(h.stla - 34.9459) < 1e-4
    assert abs(h.stlo - (-106.4571)) < 1e-4
    assert abs(h.stel - 1671.0) < 0.5
    ch = tr.stats.channel
    if ch.endswith("Z"):
        assert h.cmpinc == 0.0 and h.cmpaz == 0.0
    elif ch.endswith("N"):
        assert h.cmpinc == 90.0 and h.cmpaz == 0.0
    elif ch.endswith("E"):
        assert h.cmpinc == 90.0 and h.cmpaz == 90.0
print("[xml] StationXML end-to-end: headers incl. cmpaz/cmpinc ✓")

# --- 5c. SACPZ export ---------------------------------------------------------
OUT_PZ = WORK / "out_sacpz"
OUT_PZ.mkdir(exist_ok=True)
lines, res = run_worker([SRC], OUT_PZ, "", "",
                        metafile=str(XML), sacpz=True)
assert res == {"ok": 1, "fail": 0}, f"SACPZ run failed: {res}"
pz = OUT_PZ / "SACPZ.XX.TEST.00.HHZ"
assert pz.is_file(), f"missing {pz}"
body = pz.read_text()
assert "POLES" in body and "ZEROS" in body and "CONSTANT" in body, \
    "SACPZ file malformed"
assert any("SACPZ: wrote SACPZ.XX.TEST.00.HHZ" in l for l in lines)
assert sum("has no usable poles-and-zeros" in l for l in lines) == 2, \
    "expected 2 skip notes (HHN, HHE)"
assert any("SACPZ export: 1 written, 2 skipped" in l for l in lines)
print(f"[sacpz] {pz.name} written, skip path verified ✓")
for l in lines:
    if "SACPZ" in l:
        print("   " + l)

# --- 5d. SACPZ gating: checkbox only enabled for StationXML -------------------
win_gate = MainWindow()
assert not win_gate.sacpz_check.isEnabled(), "must start disabled"
win_gate.meta_edit.setText("/tmp/metadata.csv")
win_gate._set_running(False)
assert not win_gate.sacpz_check.isEnabled(), "csv must not enable SACPZ"
win_gate.meta_edit.setText("/tmp/station.xml")
win_gate._set_running(False)
assert win_gate.sacpz_check.isEnabled(), "xml must enable SACPZ"
win_gate._set_running(True)
assert not win_gate.sacpz_check.isEnabled(), "disabled during run"
print("[sacpz] UI gating rules ✓")

# --- 5e. Coordinate auto-fill from StationXML ---------------------------------
win_fill = MainWindow()
# 1) single-station XML → fills blank fields
win_fill._autofill_coords_from_xml(str(XML))
assert win_fill.lat_edit.text() == "34.9459", win_fill.lat_edit.text()
assert win_fill.lon_edit.text() == "-106.4571", win_fill.lon_edit.text()
# 2) pre-filled fields are preserved
win_fill.lat_edit.setText("11.111")
win_fill.lon_edit.setText("22.222")
win_fill._autofill_coords_from_xml(str(XML))
assert win_fill.lat_edit.text() == "11.111", "manual entry was clobbered"
# 3) multi-station XML → left blank with explanatory note
inv2 = Inventory(networks=[Network(
    code="XX",
    stations=[Station(code="AAA", latitude=1.0, longitude=2.0,
                      elevation=10.0, channels=[],
                      creation_date=UTCDateTime("2024-01-01")),
              Station(code="BBB", latitude=3.0, longitude=4.0,
                      elevation=20.0, channels=[],
                      creation_date=UTCDateTime("2024-01-01"))])],
    source="test", created=UTCDateTime("2024-01-01"))
XML2 = WORK / "multi.xml"
inv2.write(str(XML2), format="STATIONXML")
win_multi = MainWindow()
win_multi._autofill_coords_from_xml(str(XML2))
assert win_multi.lat_edit.text() == "", "multi-station XML must not fill"
assert "left blank on purpose" in \
    win_multi.console.toPlainText(), "explanatory note missing"
print("[autofill] single-station fill, manual preservation, "
      "multi-station guard ✓")

# --- 6. coordinate validation ----------------------------------------------
win = MainWindow()
win.lat_edit.setText("95.0")
win.lon_edit.setText("-106.4571")
assert win._validate_coords() is False, "lat 95 must be rejected"
win.lat_edit.setText("34.9459")
assert win._validate_coords() is True, "valid coords must pass"
win.lon_edit.setText("")
assert win._validate_coords() is False, "lone latitude must be rejected"
win.lat_edit.setText("")
assert win._validate_coords() is True, "both blank must pass"
print("[validate] coordinate validation rules ✓")

# --- 7. GUI smoke test (offscreen) ------------------------------------------
win.show()
win._log("smoke test")
win._on_progress(5, 20)
assert win.progress_label.text() == "Processing 5 of 20..."
assert win.progress.value() == 5
assert win.btn_convert.isEnabled()
assert hasattr(win, "msi_check") and hasattr(win, "btn_meta")
print("[gui] MainWindow offscreen: progress label, metadata controls — OK")

print("\nALL TESTS PASSED")
