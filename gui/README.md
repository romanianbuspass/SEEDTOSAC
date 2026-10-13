# mseed2sac-gui

Customer-facing desktop wrapper for the IRIS EarthScope `mseed2sac` utility.
Converts miniSEED waveform data to SAC format through a modern dark
(slate/teal, Material Design 3 style) PyQt6 interface.

## Features

- **Select File…** — convert a single `.mseed` / `.miniseed` / `.seed` file.
- **Select Folder…** — batch-convert every miniSEED file in a directory.
- **Start / Stop time** — optional time window. `mseed2sac` has no native
  time-window flags, so the GUI pre-trims with **ObsPy** to a temporary
  miniSEED file before conversion. Leave blank to convert the full file.
- **Output Directory** — all SAC files are written there.
- **Metadata injection (optional)** — *Select Metadata File…* maps to the
  `-m` flag and accepts the mseed2sac CSV format (`.txt/.csv/.dat`) **or
  StationXML (`.xml`)**. StationXML is translated to the CSV format at
 conversion time via ObsPy (`stationxml_to_metafile`), including
 SEED-dip → SAC-dip conversion — the `-msi` toggle is automatically
 suppressed for StationXML sources to prevent double conversion.
 For a **single-station** StationXML, the Latitude/Longitude fields are
 auto-filled from the inventory (manual entries are never overwritten;
 multi-station inventories are deliberately not auto-filled because
 `-k` would stamp one position onto every station).
 *Latitude / Longitude* fields map to `-k lat/lon` (validated,
 both-or-neither); the *Convert SEED to SAC Inclination* checkbox appends
 `-msi` for CSV-sourced metadata.
- **SACPZ response export (optional)** — when StationXML metadata is
  selected, a second checkbox *"Also write SACPZ response files"* becomes
  available. For every channel with a usable poles-and-zeros response, a
  `SACPZ.NET.STA.LOC.CHAN` file is written alongside the SAC data (for
  instrument response removal / `transfer` in SAC). Channels without a
  PAZ-able response are skipped with a log note. The checkbox is disabled
  unless the selected metadata file is `.xml`.
- **Convert / Cancel** — conversion runs in a background `QThread`; the UI
  stays responsive. A progress bar and a *"Processing N of M…"* label track
  batch jobs file by file.
- **Console log** — live stdout/stderr from `mseed2sac` (`-v` verbose mode)
  plus trim and error diagnostics.

## Layout

```
gui/
├── mseed2sac_gui.py      # application (UI + conversion worker)
├── run.py                # PyInstaller entry point
├── mseed2sac_gui.spec    # PyInstaller spec (bundles bin/ + assets/)
├── bin/mseed2sac         # compiled C binary (internal asset)
├── assets/
│   ├── logo.png          # header logo (110×110 RGBA, teal on transparent)
│   └── logo.ico          # window/taskbar/exe icon (16→256 px multi-size)
├── test_headless.py      # offscreen functional test suite
└── venv/                 # build environment (do not distribute)
```

## Branding & icons

- **Header logo** — `assets/logo.png` rendered top-right at 56 px; resolved
  through `resource_dir()` so it works identically from source and inside
  the frozen bundle. Missing asset degrades gracefully (no logo, no crash).
- **Window/taskbar icon** — `QApplication.setWindowIcon()` with both
  `logo.ico` (all Windows sizes) and `logo.png` (Linux/macOS).
- **Windows taskbar grouping** — `main()` calls
  `SetCurrentProcessExplicitAppUserModelID("GaiaCode.Mseed2Sac.Gui")`
  before QApplication creation; without it the taskbar shows the generic
  Python icon.
- **Exe file icon** — the spec passes `icon="assets/logo.ico"` on Windows
  (ignored on Linux ELF builds). If Explorer keeps showing a stale icon
  after a rebuild, rename the exe once — that is the Windows icon cache.

## Building the standalone executable

```bash
cd gui
python3 -m venv venv
./venv/bin/pip install --upgrade pip
./venv/bin/pip install PyQt6 obspy pyinstaller

# compile the C utility (from the repo root) and stage it
cd .. && make && cp mseed2sac gui/bin/ && cd gui

# one-file build
./venv/bin/python -m PyInstaller --noconfirm --clean mseed2sac_gui.spec
# result: dist/mseed2sac-gui   (Windows: dist/mseed2sac-gui.exe)
```

On Windows use `python -m PyInstaller …` (the module invocation form) and
copy `mseed2sac.exe` into `bin\`. The spec detects the platform suffix
automatically. Add an `assets/icon.ico` and uncomment the `icon=` line for
a branded icon.

## Running from source

```bash
./venv/bin/python run.py
```

## Testing

```bash
./venv/bin/python test_headless.py
```

Synthesises miniSEED data with ObsPy, then verifies: trimmed conversion
(exact window duration + start time), full-file conversion, batch folder
processing, and an offscreen GUI smoke test.

## Notes for the customer

- Output file names follow `mseed2sac` convention:
  `NET.STA.LOC.CHAN.D.YYYY.JJJ.HHMMSS.SAC`. Existing files are never
  overwritten — a numeric suffix (`-1`, `-2`, …) is appended instead.
- Time fields accept ISO-8601 (`2024-03-15T08:30:00`) and most common
  date/time formats understood by ObsPy's `UTCDateTime`.
- The executable is fully self-contained: the `mseed2sac` binary, Qt,
  and ObsPy are bundled internally. No installation is required.
