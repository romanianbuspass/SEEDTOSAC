#!/usr/bin/env python3
"""
mseed2sac-gui — customer-facing wrapper for the mseed2sac utility.

Converts miniSEED waveform files to SAC format via the bundled `mseed2sac`
C binary. Optional Start/Stop time windowing is applied with ObsPy
(pre-trim to a temporary miniSEED file) because mseed2sac itself has no
time-window CLI flags.

Material Design 3 inspired dark theme: slate surfaces, teal accents.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal, Qt
from PyQt6.QtGui import QFont, QIcon, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

APP_NAME = "miniSEED to SAC Converter"
MSEED_EXTENSIONS = (".mseed", ".miniseed", ".seed", ".msd")

# ---------------------------------------------------------------------------
# Theme — MD3-flavoured slate / teal
# ---------------------------------------------------------------------------
SLATE_950 = "#0F172A"   # window base
SLATE_900 = "#1E293B"   # cards / inputs
SLATE_800 = "#334155"   # borders
SLATE_400 = "#94A3B8"   # secondary text
SLATE_100 = "#F1F5F9"   # primary text
TEAL_500  = "#14B8A6"   # primary accent
TEAL_300  = "#5EEAD4"   # accent hover / highlight
TEAL_900  = "#134E4A"   # accent pressed
RED_400   = "#F87171"   # error

QSS = f"""
QMainWindow, QWidget {{
    background-color: {SLATE_950};
    color: {SLATE_100};
    font-family: "Inter", "Segoe UI", "Roboto", sans-serif;
    font-size: 13px;
}}
QLabel#title {{
    font-size: 20px;
    font-weight: 700;
    color: {TEAL_300};
}}
QLabel#subtitle {{
    color: {SLATE_400};
    font-size: 12px;
}}
QLabel#section {{
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 1.5px;
    color: {TEAL_500};
}}
QFrame#card {{
    background-color: {SLATE_900};
    border: 1px solid {SLATE_800};
    border-radius: 12px;
}}
QLineEdit {{
    background-color: {SLATE_950};
    border: 1px solid {SLATE_800};
    border-radius: 8px;
    padding: 8px 10px;
    color: {SLATE_100};
    selection-background-color: {TEAL_500};
}}
QLineEdit:focus {{
    border: 1px solid {TEAL_500};
}}
QLineEdit:disabled {{
    color: {SLATE_400};
}}
QPushButton {{
    background-color: {SLATE_800};
    border: none;
    border-radius: 8px;
    padding: 9px 16px;
    color: {SLATE_100};
    font-weight: 600;
}}
QPushButton:hover {{
    background-color: #3E4C63;
}}
QPushButton:pressed {{
    background-color: {SLATE_900};
}}
QPushButton:disabled {{
    color: {SLATE_400};
    background-color: {SLATE_900};
}}
QPushButton#primary {{
    background-color: {TEAL_500};
    color: {SLATE_950};
    font-size: 14px;
    padding: 11px 22px;
}}
QPushButton#primary:hover {{
    background-color: {TEAL_300};
}}
QPushButton#primary:pressed {{
    background-color: {TEAL_900};
    color: {SLATE_100};
}}
QPushButton#primary:disabled {{
    background-color: {SLATE_800};
    color: {SLATE_400};
}}
QPushButton#danger {{
    background-color: transparent;
    border: 1px solid {RED_400};
    color: {RED_400};
}}
QCheckBox {{
    color: {SLATE_100};
    spacing: 8px;
}}
QCheckBox::indicator {{
    width: 18px;
    height: 18px;
    border: 1px solid {SLATE_800};
    border-radius: 4px;
    background-color: {SLATE_950};
}}
QCheckBox::indicator:checked {{
    background-color: {TEAL_500};
    border: 1px solid {TEAL_500};
}}
QCheckBox::indicator:hover {{
    border: 1px solid {TEAL_300};
}}
QLabel#progressLabel {{
    color: {TEAL_300};
    font-weight: 600;
}}
QPlainTextEdit {{
    background-color: #020617;
    border: 1px solid {SLATE_800};
    border-radius: 8px;
    color: #A7F3D0;
    font-family: "JetBrains Mono", "Cascadia Code", "Consolas", monospace;
    font-size: 12px;
    padding: 8px;
}}
QProgressBar {{
    background-color: {SLATE_900};
    border: none;
    border-radius: 5px;
    height: 10px;
    text-align: center;
    color: {SLATE_950};
    font-size: 10px;
}}
QProgressBar::chunk {{
    background-color: {TEAL_500};
    border-radius: 5px;
}}
QToolTip {{
    background-color: {SLATE_800};
    color: {SLATE_100};
    border: none;
    padding: 6px;
}}
"""


# ---------------------------------------------------------------------------
# Resource resolution (source tree vs PyInstaller bundle)
# ---------------------------------------------------------------------------
def resource_dir() -> Path:
    """Directory holding bundled assets (the mseed2sac binary)."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent


def find_binary() -> Path | None:
    exe = "mseed2sac.exe" if os.name == "nt" else "mseed2sac"
    candidates = [
        resource_dir() / "bin" / exe,
        resource_dir() / exe,
        # Development fallback: repo root build output
        Path(__file__).resolve().parent.parent / exe,
    ]
    for c in candidates:
        if c.is_file():
            return c
    return None


def asset_path(name: str) -> Path | None:
    """Resolve a bundled asset (logo, icon) in source or frozen layouts."""
    p = resource_dir() / "assets" / name
    return p if p.is_file() else None


# mseed2sac metadata CSV header (see doc/mseed2sac.md, METADATA FILES)
METADATA_HEADER = ("#net,sta,loc,chan,lat,lon,elev,depth,azimuth,SACdip,"
                   "instrument,scale,scalefreq,scaleunits,samplerate,"
                   "start,end")
OPEN_END = "2599-12-31T23:59:59"


def stationxml_to_metafile(xml_path: Path, log=print) -> Path:
    """Translate StationXML into an mseed2sac metadata CSV (temp file).

    Dip handling: StationXML stores SEED-convention dip (positive down
    from horizontal). The mseed2sac metadata file takes SAC-convention
    dip (from vertical), so we convert here (SACdip = dip + 90) and the
    -msi flag must NOT be applied on top.
    """
    from obspy import read_inventory

    inv = read_inventory(str(xml_path))
    rows = [METADATA_HEADER]
    n_cha = 0
    for net in inv:
        for sta in net:
            for cha in sta:
                lat = cha.latitude if cha.latitude is not None \
                    else sta.latitude
                lon = cha.longitude if cha.longitude is not None \
                    else sta.longitude
                elev = cha.elevation if cha.elevation is not None \
                    else sta.elevation
                dip = cha.dip if cha.dip is not None else 0.0
                sacdip = dip + 90.0           # SEED dip → SAC convention
                sens = (cha.response.instrument_sensitivity
                        if cha.response else None)
                start = cha.start_date or sta.start_date or ""
                end = cha.end_date or sta.end_date or OPEN_END
                row = [
                    net.code, sta.code, cha.location_code, cha.code,
                    lat, lon, elev, cha.depth,
                    cha.azimuth if cha.azimuth is not None else "",
                    f"{sacdip:g}",
                    (cha.sensor.type if cha.sensor and cha.sensor.type
                     else ""),
                    sens.value if sens else "",
                    sens.frequency if sens else "",
                    sens.input_units if sens else "",
                    cha.sample_rate or "",
                    start, end,
                ]
                rows.append(",".join("" if v is None else str(v)
                                     for v in row))
                n_cha += 1
    if n_cha == 0:
        raise ValueError(f"no channels found in {xml_path.name}")

    fd, tmp = tempfile.mkstemp(prefix="mseed2sac_meta_", suffix=".csv")
    with os.fdopen(fd, "w") as fh:
        fh.write("\n".join(rows) + "\n")
    log(f"StationXML: translated {n_cha} channel(s) from "
        f"{xml_path.name} → mseed2sac metadata (dip converted to "
        f"SAC convention)")
    return Path(tmp)


# ---------------------------------------------------------------------------
# Conversion worker
# ---------------------------------------------------------------------------
class ConvertWorker(QThread):
    log = pyqtSignal(str)
    progress = pyqtSignal(int, int)          # done, total
    finished_all = pyqtSignal(int, int)      # succeeded, failed

    def __init__(self, files: list[Path], outdir: Path,
                 start: str, stop: str, binary: Path,
                 metafile: str = "", lat: str = "", lon: str = "",
                 msi: bool = False, sacpz: bool = False):
        super().__init__()
        self.files = files
        self.outdir = outdir
        self.start_str = start.strip()
        self.stop_str = stop.strip()
        self.binary = binary
        self.metafile = metafile.strip()
        self.lat = lat.strip()
        self.lon = lon.strip()
        self.msi = msi
        self.sacpz = sacpz
        self._cancelled = False
        self._proc: subprocess.Popen | None = None
        # Resolved in run(): StationXML sources are translated to a temp
        # metadata CSV; -msi is suppressed for them (dip already SAC).
        self._effective_metafile: str = self.metafile
        self._effective_msi: bool = self.msi
        self._meta_tmp: Path | None = None

    def cancel(self):
        self._cancelled = True
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()

    # -- helpers -----------------------------------------------------------
    def _emit(self, msg: str):
        self.log.emit(msg.rstrip())

    def _want_trim(self) -> bool:
        return bool(self.start_str or self.stop_str)

    def _trim_to_temp(self, src: Path) -> Path:
        """Slice `src` to the requested window; return temp miniSEED path."""
        from obspy import read, UTCDateTime  # deferred: optional dependency

        st = read(str(src))
        t1 = UTCDateTime(self.start_str) if self.start_str else None
        t2 = UTCDateTime(self.stop_str) if self.stop_str else None
        st.trim(starttime=t1, endtime=t2)
        if len(st) == 0:
            raise ValueError(
                f"time window {self.start_str or '-inf'} → "
                f"{self.stop_str or '+inf'} "
                "contains no data for this file"
            )
        fd, tmp = tempfile.mkstemp(prefix="mseed2sac_trim_", suffix=".mseed")
        os.close(fd)
        st.write(tmp, format="MSEED")
        return Path(tmp)

    def _run_binary(self, infile: Path) -> int:
        cmd = [str(self.binary), "-v"]
        if self._effective_metafile:
            cmd += ["-m", self._effective_metafile]
        if self.lat and self.lon:
            cmd += ["-k", f"{self.lat}/{self.lon}"]
        if self._effective_msi:
            cmd.append("-msi")
        cmd.append(str(infile))
        self._emit(f"$ {' '.join(cmd)}  (cwd={self.outdir})")
        self._proc = subprocess.Popen(
            cmd,
            cwd=str(self.outdir),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
        )
        assert self._proc.stdout is not None
        for line in self._proc.stdout:
            self._emit("  " + line)
        return self._proc.wait()

    def _write_sacpz(self, xml_path: Path):
        """Export per-channel SACPZ response files from a StationXML
        inventory into the output directory."""
        import warnings
        from obspy import read_inventory

        inv = read_inventory(str(xml_path))
        written = skipped = 0
        for net in inv:
            for sta in net:
                for cha in sta:
                    seed_id = (f"{net.code}.{sta.code}."
                               f"{cha.location_code}.{cha.code}")
                    try:
                        if cha.response is None:
                            raise ValueError("no response")
                        cha.response.get_paz()   # raises if not PAZ-able
                    except Exception:
                        self._emit(f"  SACPZ: {seed_id} has no usable "
                                   f"poles-and-zeros response — skipped.")
                        skipped += 1
                        continue
                    fname = self.outdir / f"SACPZ.{seed_id}"
                    try:
                        with warnings.catch_warnings():
                            warnings.simplefilter("ignore")
                            inv.select(
                                network=net.code, station=sta.code,
                                location=cha.location_code,
                                channel=cha.code,
                            ).write(str(fname), format="SACPZ")
                        written += 1
                        self._emit(f"  SACPZ: wrote {fname.name}")
                    except Exception as exc:
                        self._emit(f"  SACPZ: ERROR writing {seed_id}: {exc}")
                        skipped += 1
        self._emit(f"SACPZ export: {written} written, {skipped} skipped "
                   f"→ {self.outdir}")

    # -- main loop ---------------------------------------------------------
    def run(self):
        ok = fail = 0
        total = len(self.files)

        # --- metadata source resolution --------------------------------
        if self.metafile.lower().endswith(".xml"):
            try:
                self._meta_tmp = stationxml_to_metafile(
                    Path(self.metafile), log=self._emit)
                self._effective_metafile = str(self._meta_tmp)
                if self.msi:
                    self._emit("NOTE: StationXML dip is already converted "
                               "to SAC convention — ignoring the -msi "
                               "toggle for this run.")
                self._effective_msi = False
            except Exception as exc:
                self._emit(f"ERROR: StationXML translation failed: {exc}")
                self.finished_all.emit(0, len(self.files))
                return

        if self.sacpz:
            if self.metafile.lower().endswith(".xml"):
                try:
                    self._write_sacpz(Path(self.metafile))
                except Exception as exc:
                    self._emit(f"ERROR: SACPZ export failed: {exc}")
            else:
                self._emit("NOTE: SACPZ export requires StationXML "
                           "metadata — skipped for this run.")

        trim_available = True
        if self._want_trim():
            try:
                import obspy  # noqa: F401
                self._emit(
                    f"Time window: {self.start_str or '(file start)'} → "
                    f"{self.stop_str or '(file end)'}  [ObsPy pre-trim]"
                )
            except ImportError:
                trim_available = False
                self._emit(
                    "WARNING: ObsPy is not available; Start/Stop times "
                    "ignored — converting full files."
                )

        for i, f in enumerate(self.files, 1):
            if self._cancelled:
                self._emit("--- Cancelled by user ---")
                break
            self._emit(f"\n[{i}/{total}] {f.name}")
            work_file = f
            tmp: Path | None = None
            try:
                if self._want_trim() and trim_available:
                    tmp = self._trim_to_temp(f)
                    work_file = tmp
                    self._emit(f"  trimmed → temp file {tmp.name}")
                rc = self._run_binary(work_file)
                if rc == 0:
                    ok += 1
                    self._emit(f"  OK: {f.name} converted.")
                else:
                    fail += 1
                    self._emit(f"  ERROR: mseed2sac exited with code {rc}.")
            except Exception as exc:  # trim or spawn failure
                fail += 1
                self._emit(f"  ERROR: {exc}")
            finally:
                if tmp and tmp.exists():
                    tmp.unlink(missing_ok=True)
            self.progress.emit(i, total)

        self._emit(f"\n=== Done: {ok} succeeded, {fail} failed "
                   f"of {total} file(s) ===")
        if self._meta_tmp:
            self._meta_tmp.unlink(missing_ok=True)
        self.finished_all.emit(ok, fail)


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(720, 640)
        self.worker: ConvertWorker | None = None
        self.selected_files: list[Path] = []

        self.binary = find_binary()

        root = QWidget()
        self.setCentralWidget(root)
        lay = QVBoxLayout(root)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(12)

        # Header — title block left, GaiaCode logo top-right
        header = QHBoxLayout()
        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title = QLabel(APP_NAME)
        title.setObjectName("title")
        sub = QLabel("Powered by mseed2sac 2.4 · IRIS EarthScope Consortium")
        sub.setObjectName("subtitle")
        title_col.addWidget(title)
        title_col.addWidget(sub)
        header.addLayout(title_col)
        header.addStretch(1)

        logo_file = asset_path("logo.png")
        if logo_file:
            logo = QLabel()
            pm = QPixmap(str(logo_file)).scaledToHeight(
                56, Qt.TransformationMode.SmoothTransformation)
            logo.setPixmap(pm)
            logo.setToolTip("GaiaCode Ltd")
            header.addWidget(logo, 0, Qt.AlignmentFlag.AlignRight |
                           Qt.AlignmentFlag.AlignTop)
        lay.addLayout(header)

        # --- Input card ----------------------------------------------------
        input_card, il = self._card()
        il.addWidget(self._section("INPUT"))

        row = QHBoxLayout()
        self.btn_file = QPushButton("Select File…")
        self.btn_file.clicked.connect(self.pick_file)
        self.btn_folder = QPushButton("Select Folder…")
        self.btn_folder.clicked.connect(self.pick_folder)
        row.addWidget(self.btn_file)
        row.addWidget(self.btn_folder)
        il.addLayout(row)

        self.input_label = QLineEdit()
        self.input_label.setReadOnly(True)
        self.input_label.setPlaceholderText("No input selected")
        il.addWidget(self.input_label)

        # time window
        trow = QHBoxLayout()
        self.start_edit = QLineEdit()
        self.start_edit.setPlaceholderText("Start time  e.g. 2024-03-15T08:30:00")
        self.stop_edit = QLineEdit()
        self.stop_edit.setPlaceholderText("Stop time   e.g. 2024-03-15T09:00:00")
        trow.addWidget(self.start_edit)
        trow.addWidget(self.stop_edit)
        il.addLayout(trow)
        hint = QLabel("Optional — leave blank to convert the entire file. "
                      "Accepted: ISO-8601 or any ObsPy-parsable date/time.")
        hint.setObjectName("subtitle")
        il.addWidget(hint)
        lay.addWidget(input_card)

        # --- Metadata card ---------------------------------------------------
        meta_card, ml = self._card()
        ml.addWidget(self._section("METADATA  (OPTIONAL)"))

        mrow = QHBoxLayout()
        self.meta_edit = QLineEdit()
        self.meta_edit.setReadOnly(True)
        self.meta_edit.setPlaceholderText(
            "No metadata file selected  (-m · txt/csv/dat or StationXML)")
        self.btn_meta = QPushButton("Select Metadata File…")
        self.btn_meta.clicked.connect(self.pick_metadata)
        mrow.addWidget(self.meta_edit, 1)
        mrow.addWidget(self.btn_meta)
        ml.addLayout(mrow)

        crow = QHBoxLayout()
        self.lat_edit = QLineEdit()
        self.lat_edit.setPlaceholderText("Latitude   e.g. 34.946")
        self.lon_edit = QLineEdit()
        self.lon_edit.setPlaceholderText("Longitude  e.g. -106.457")
        crow.addWidget(self.lat_edit)
        crow.addWidget(self.lon_edit)
        ml.addLayout(crow)

        self.msi_check = QCheckBox(
            "Convert SEED to SAC Inclination  (-msi)")
        self.msi_check.setToolTip(
            "Convert component inclination/dip from SEED convention "
            "to SAC convention in the output headers.")
        ml.addWidget(self.msi_check)

        self.sacpz_check = QCheckBox(
            "Also write SACPZ response files  (requires StationXML)")
        self.sacpz_check.setToolTip(
            "For every channel in the StationXML inventory with a valid "
            "poles-and-zeros response, write a SACPZ.NET.STA.LOC.CHAN "
            "file alongside the SAC data (for instrument response "
            "removal in SAC).")
        self.sacpz_check.setEnabled(False)   # enabled when .xml selected
        ml.addWidget(self.sacpz_check)
        lay.addWidget(meta_card)

        # --- Output card ---------------------------------------------------
        out_card, ol = self._card()
        ol.addWidget(self._section("OUTPUT"))
        orow = QHBoxLayout()
        self.out_edit = QLineEdit()
        self.out_edit.setPlaceholderText("Choose where SAC files will be written…")
        self.btn_out = QPushButton("Browse…")
        self.btn_out.clicked.connect(self.pick_outdir)
        orow.addWidget(self.out_edit, 1)
        orow.addWidget(self.btn_out)
        ol.addLayout(orow)
        lay.addWidget(out_card)

        # --- Actions -------------------------------------------------------
        arow = QHBoxLayout()
        self.progress_label = QLabel("Idle")
        self.progress_label.setObjectName("progressLabel")
        self.progress = QProgressBar()
        self.progress.setValue(0)
        self.progress.setFormat("%v / %m")
        self.btn_convert = QPushButton("Convert")
        self.btn_convert.setObjectName("primary")
        self.btn_convert.clicked.connect(self.start_conversion)
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setObjectName("danger")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self.cancel_conversion)
        arow.addWidget(self.progress_label)
        arow.addWidget(self.progress, 1)
        arow.addWidget(self.btn_cancel)
        arow.addWidget(self.btn_convert)
        lay.addLayout(arow)

        # --- Log -----------------------------------------------------------
        lay.addWidget(self._section("CONSOLE LOG"))
        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setFont(QFont("monospace"))
        lay.addWidget(self.console, 1)

        # status line
        if self.binary:
            self._log(f"mseed2sac binary: {self.binary}")
        else:
            self._log("ERROR: mseed2sac binary not found next to the "
                      "application (expected in ./bin). Conversion disabled.")
            self.btn_convert.setEnabled(False)

    # -- UI helpers ---------------------------------------------------------
    def _card(self):
        card = QFrame()
        card.setObjectName("card")
        v = QVBoxLayout(card)
        v.setContentsMargins(16, 14, 16, 14)
        v.setSpacing(8)
        return card, v

    def _section(self, text: str) -> QLabel:
        lab = QLabel(text)
        lab.setObjectName("section")
        return lab

    def _log(self, msg: str):
        self.console.appendPlainText(msg)
        sb = self.console.verticalScrollBar()
        sb.setValue(sb.maximum())

    # -- Pickers ------------------------------------------------------------
    def pick_file(self):
        f, _ = QFileDialog.getOpenFileName(
            self, "Select miniSEED file", "",
            "miniSEED files (*.mseed *.miniseed *.seed *.msd);;All files (*)")
        if f:
            self.selected_files = [Path(f)]
            self.input_label.setText(f)

    def pick_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Select folder of miniSEED files")
        if d:
            p = Path(d)
            files = sorted(x for x in p.iterdir()
                           if x.suffix.lower() in MSEED_EXTENSIONS)
            self.selected_files = files
            self.input_label.setText(
                f"{d}  —  {len(files)} miniSEED file(s) found")
            if not files:
                self._log(f"WARNING: no miniSEED files "
                          f"{MSEED_EXTENSIONS} in {d}")

    def pick_outdir(self):
        d = QFileDialog.getExistingDirectory(self, "Select output directory")
        if d:
            self.out_edit.setText(d)

    def pick_metadata(self):
        f, _ = QFileDialog.getOpenFileName(
            self, "Select metadata file", "",
            "All supported (*.txt *.csv *.dat *.xml);;"
            "mseed2sac metadata (*.txt *.csv *.dat);;"
            "StationXML (*.xml);;All files (*)")
        if f:
            self.meta_edit.setText(f)
            is_xml = f.lower().endswith(".xml")
            self.sacpz_check.setEnabled(is_xml)
            if not is_xml:
                self.sacpz_check.setChecked(False)
            if is_xml:
                self._log("StationXML selected — it will be translated to "
                          "mseed2sac metadata format at conversion time "
                          "(dip converted to SAC convention automatically).")
                self._autofill_coords_from_xml(f)

    def _autofill_coords_from_xml(self, xml_path: str):
        """Populate Lat/Lon from a single-station StationXML.

        Only safe for exactly one station: -k stamps every output file
        with the same coordinates, while multi-station inventories get
        per-station positions via the -m metadata itself.
        """
        try:
            from obspy import read_inventory
            inv = read_inventory(xml_path)
        except Exception as exc:
            self._log(f"WARNING: StationXML parse failed during "
                      f"coordinate auto-fill: {exc}")
            return

        stations = [sta for net in inv for sta in net]
        if len(stations) != 1:
            self._log(f"StationXML holds {len(stations)} stations — "
                      f"Latitude/Longitude left blank on purpose: each "
                      f"station's position is injected from the metadata "
                      f"itself (-m), not from -k.")
            return
        sta = stations[0]
        cha = sta.channels[0] if sta.channels else None
        lat = cha.latitude if cha and cha.latitude is not None \
            else sta.latitude
        lon = cha.longitude if cha and cha.longitude is not None \
            else sta.longitude
        if lat is None or lon is None:
            self._log("StationXML station carries no coordinates — "
                      "cannot auto-fill.")
            return
        if self.lat_edit.text().strip() or self.lon_edit.text().strip():
            self._log(f"Keeping existing Latitude/Longitude entries; "
                      f"StationXML station {sta.code} sits at "
                      f"{lat}/{lon} — edit manually if you prefer those.")
            return
        self.lat_edit.setText(str(lat))
        self.lon_edit.setText(str(lon))
        self._log(f"Latitude/Longitude auto-filled from StationXML "
                  f"station {sta.code}: {lat} / {lon}")

    # -- Conversion ---------------------------------------------------------
    def _validate_coords(self) -> bool:
        lat, lon = self.lat_edit.text().strip(), self.lon_edit.text().strip()
        if not lat and not lon:
            return True
        if not lat or not lon:
            self._log("ERROR: Latitude and Longitude must be given "
                      "together, or both left blank.")
            return False
        try:
            flat, flon = float(lat), float(lon)
        except ValueError:
            self._log(f"ERROR: coordinates '{lat}/{lon}' are not numeric.")
            return False
        if not (-90.0 <= flat <= 90.0):
            self._log(f"ERROR: latitude {flat} outside [-90, 90].")
            return False
        if not (-180.0 <= flon <= 180.0):
            self._log(f"ERROR: longitude {flon} outside [-180, 180].")
            return False
        return True

    def _validate_times(self) -> bool:
        try:
            from obspy import UTCDateTime
        except ImportError:
            return True  # worker will warn and ignore
        for edit, name in ((self.start_edit, "Start"), (self.stop_edit, "Stop")):
            txt = edit.text().strip()
            if txt:
                try:
                    UTCDateTime(txt)
                except Exception:
                    self._log(f"ERROR: {name} time '{txt}' is not a valid "
                              f"date/time.")
                    return False
        return True

    def start_conversion(self):
        if not self.selected_files:
            self._log("ERROR: select an input file or folder first.")
            return
        outdir = self.out_edit.text().strip()
        if not outdir:
            self._log("ERROR: select an output directory first.")
            return
        outp = Path(outdir)
        outp.mkdir(parents=True, exist_ok=True)
        if not self._validate_times():
            return
        if not self._validate_coords():
            return
        metafile = self.meta_edit.text().strip()
        if metafile and not Path(metafile).is_file():
            self._log(f"ERROR: metadata file not found: {metafile}")
            return

        self._set_running(True)
        self.console.clear()
        self._log(f"Output directory: {outp}")
        self.progress.setMaximum(len(self.selected_files))
        self.progress.setValue(0)
        self.progress_label.setText(
            f"Processing 0 of {len(self.selected_files)}...")

        self.worker = ConvertWorker(
            self.selected_files, outp,
            self.start_edit.text(), self.stop_edit.text(),
            self.binary,
            metafile=metafile,
            lat=self.lat_edit.text(), lon=self.lon_edit.text(),
            msi=self.msi_check.isChecked(),
            sacpz=(self.sacpz_check.isChecked()
                   and self.sacpz_check.isEnabled()),
        )
        self.worker.log.connect(self._log)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished_all.connect(self._on_finished)
        self.worker.start()

    def _on_progress(self, done: int, total: int):
        self.progress.setValue(done)
        self.progress_label.setText(f"Processing {done} of {total}...")

    def cancel_conversion(self):
        if self.worker:
            self.worker.cancel()

    def _on_finished(self, ok: int, fail: int):
        self._set_running(False)
        colour = TEAL_300 if fail == 0 else RED_400
        self._log(f"Batch complete — {ok} OK, {fail} failed.")
        self.progress_label.setText(
            "Complete" if fail == 0 else f"Complete ({fail} failed)")

    def _set_running(self, running: bool):
        self.btn_convert.setEnabled(not running)
        self.btn_cancel.setEnabled(running)
        self.btn_file.setEnabled(not running)
        self.btn_folder.setEnabled(not running)
        self.btn_out.setEnabled(not running)
        self.btn_meta.setEnabled(not running)
        self.lat_edit.setEnabled(not running)
        self.lon_edit.setEnabled(not running)
        self.msi_check.setEnabled(not running)
        # SACPZ stays gated on a StationXML source even when re-enabled
        xml_selected = self.meta_edit.text().strip().lower().endswith(".xml")
        self.sacpz_check.setEnabled(not running and xml_selected)


def main() -> int:
    # Windows: a stable AppUserModelID is required for the taskbar icon to
    # group under our own identity instead of the Python host process.
    if os.name == "nt":
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "GaiaCode.Mseed2Sac.Gui")

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyleSheet(QSS)

    # Window / taskbar icon — .ico carries all sizes for Windows; the PNG
    # covers Linux and macOS.
    icon = QIcon()
    for name in ("logo.ico", "logo.png"):
        p = asset_path(name)
        if p:
            icon.addFile(str(p))
    if not icon.isNull():
        app.setWindowIcon(icon)

    w = MainWindow()
    w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
