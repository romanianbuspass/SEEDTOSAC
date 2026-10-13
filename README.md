# SEEDTOSAC — miniSEED → SAC Conversion Toolkit

Tools for converting **miniSEED** seismic time-series data (as recorded by
Gaiacode Affinity / OmegaBox digitizers) into **SAC** (Seismic Analysis
Code) format, with station metadata (coordinates, component orientation,
instrument response) injected into the SAC headers.

The repository bundles three front-ends around the same conversion
semantics:

| Component | Directory | Description |
|---|---|---|
| **mseed2sac** (C engine) | `src/`, `libmseed/`, `doc/` | EarthScope `mseed2sac` v2.4 command-line converter with bundled libmseed |
| **Desktop GUI** | `gui/` | PyQt6 desktop wrapper: batch conversion, time-window trimming (ObsPy), StationXML/CSV metadata injection, SACPZ response export |
| **Headless pipeline** | `OmegaBox/` | Cron-safe daemon that mirrors OmegaBox units over HTTP (wget) and converts mirrored miniSEED to SAC with StationXML metadata |

## Technology Stack

- **C** (C99) — `mseed2sac` engine + bundled **libmseed**; zlib for ZIP
  output; Makefiles for Unix (`make`), Watcom (`Makefile.wat`) and MSVC
  (`Makefile.win`).
- **Python 3** — GUI and pipeline: **PyQt6** (interface), **ObsPy**
  (miniSEED/SAC/StationXML I/O, time-window trimming, SACPZ export),
  **PyYAML** (pipeline config), **PyInstaller** (standalone builds),
  **wget** (HTTP mirroring).

## Hardware Dependencies

None for the CLI engine and GUI (they operate on miniSEED files).

The `OmegaBox/` pipeline targets **Gaiacode OmegaBox** digitizers on the
local network: each unit serves its continuous miniSEED archive over HTTP
at `http://<unit-address>/data/`. Units do **not** serve StationXML —
metadata files are kept alongside the pipeline (see `OmegaBox/README.md`).

## Setup & Installation

### C engine (CLI)

```bash
make            # builds bundled libmseed, then src/mseed2sac
./mseed2sac -V  # → "mseed2sac version: 2.4"
```

Requires a C compiler and zlib headers (`build-essential zlib1g-dev` on
Debian/Ubuntu). Without zlib, build with `NOZIP=1 make`. On Windows use
`nmake -f Makefile.win` from an MSVC tools prompt.

### Desktop GUI

```bash
cd gui
python3 -m venv venv
./venv/bin/pip install --upgrade pip
./venv/bin/pip install PyQt6 obspy pyinstaller

# compile the C engine (from the repo root) and stage it
cd .. && make && cp mseed2sac gui/bin/ && cd gui

# run from source
./venv/bin/python run.py

# or build a standalone executable
./venv/bin/python -m PyInstaller --noconfirm --clean mseed2sac_gui.spec
# result: dist/mseed2sac-gui   (Windows: dist/mseed2sac-gui.exe)
```

### Headless OmegaBox pipeline

```bash
cd OmegaBox
python3 -m venv venv
./venv/bin/pip install obspy pyyaml
sudo apt install wget        # if not already present
```

Edit `config.yaml` (archive roots + one entry per unit), then:

```bash
./venv/bin/python gaiacode_pipeline.py            # full mirror + convert
./venv/bin/python gaiacode_pipeline_recent.py --days 3   # last N days only
```

See `OmegaBox/README.md` for cron scheduling and archive-layout guidance.

## Usage Examples

Single file, verbose, with station coordinates:

```bash
mseed2sac -v -k 12.3456/78.9012 ST01.2024.075.mseed
```

Batch conversion with full metadata (CSV) and SEED→SAC dip conversion:

```bash
mseed2sac -v -m network_metadata.txt -msi *.mseed
```

GUI batch conversion with StationXML metadata and SACPZ export — see
`gui/README.md`. Full CLI option reference: `doc/mseed2sac.md` (man page:
`doc/mseed2sac.1`). End-user guide covering all options:
`docs/Gaiacode_miniSEED_to_SAC_Guide.md`.

## Data Formats & Protocols

- **miniSEED** (input) — SEED waveform records (Steim-1/Steim-2
  compression), extensions `.mseed` / `.miniseed` / `.seed`.
- **SAC** (output) — binary (host/little/big-endian selectable) or
  alphanumeric; one file per channel per continuous segment, named
  `NET.STA.LOC.CHAN.D.YYYY.JJJ.HHMMSS.SAC`.
- **FDSN StationXML** (metadata) — channel coordinates, orientation and
  response; translated to the mseed2sac CSV format by the GUI/pipeline,
  or exported as `SACPZ.NET.STA.LOC.CHAN` poles-and-zeros files.
- **mseed2sac CSV metadata** (`.txt`/`.csv`/`.dat`) — one channel per
  line with lat/lon/elev/azimuth/dip/sensitivity (see `doc/mseed2sac.md`).
- **HTTP** — OmegaBox units expose their `/data/` tree over plain HTTP;
  the pipeline mirrors it with wget timestamping.

## Repository Layout

```
├── src/, libmseed/   # mseed2sac C engine + bundled libmseed
├── doc/              # mseed2sac manual (man page + markdown)
├── docs/             # end-user conversion guide
├── gui/              # PyQt6 desktop application
├── OmegaBox/         # headless mirror-and-convert pipeline + StationXML
└── Makefile*         # engine build (Unix / Watcom / MSVC)
```

Bulk seismic data, virtualenvs, PyInstaller output and runtime logs are
deliberately excluded (see `.gitignore`); the miniSEED mirror is the
archive of record and lives outside the repository.

## Testing

```bash
cd libmseed && make test        # libmseed unit tests
cd ../gui && ./venv/bin/python test_headless.py     # GUI offscreen suite
cd ../OmegaBox && python _test_pipeline.py          # pipeline E2E (mock unit)
python _test_recent.py                              # recent-days variant E2E
```

The pipeline E2E tests synthesise miniSEED with ObsPy, serve it from a
mock HTTP server, and verify mirroring, SAC headers and failure handling.

## Licensing

`mseed2sac` and `libmseed` are developed by Chad Trabant, EarthScope
Consortium (formerly IRIS), and distributed under the Apache License 2.0
(see `LICENSE`).
