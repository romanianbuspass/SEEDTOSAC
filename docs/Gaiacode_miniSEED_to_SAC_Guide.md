# Gaiacode Seismic Data Conversion Guide: miniSEED to SAC

**Gaiacode Limited** — Technical Guide & Tutorial
**Audience:** Academic research users of Gaiacode digitizer networks
**Applies to:** Gaiacode Affinity and OmegaBox digitizers · mseed2sac 2.4 · Gaiacode SEED-to-SAC Desktop Application
**Version:** 1.1 — adds StationXML metadata, SACPZ response export, and the headless OmegaBox automation pipeline (Option 4)

---

## Table of Contents

1. [Overview & Data Architecture](#1-overview--data-architecture)
2. [Option 1: Gaiacode SEED-to-SAC Desktop Application (Recommended)](#2-option-1-gaiacode-seed-to-sac-desktop-application-recommended)
3. [Option 2: Command-Line Conversion via mseed2sac](#3-option-2-command-line-conversion-via-mseed2sac)
4. [Option 3: Python & ObsPy Scripting Pipeline](#4-option-3-python--obspy-scripting-pipeline)
5. [Option 4: Headless Automation — the OmegaBox Pipeline](#5-option-4-headless-automation--the-omegabox-pipeline)
6. [Troubleshooting & Field Best Practices](#6-troubleshooting--field-best-practices)

---

## 1. Overview & Data Architecture

### 1.1 How Gaiacode digitizers record data

Gaiacode **Affinity** and **OmegaBox** units sample the attached sensor (broadband, short-period, or strong-motion) with a 24-bit analogue-to-digital converter and write the resulting continuous time-series to local storage in **standard miniSEED** format. Each miniSEED file is a sequence of fixed-length data records (typically 512 or 4096 bytes). Every record carries a compact fixed header containing:

- Stream identifiers: network, station, location, and channel codes (e.g. `XX.ST01.00.HHZ`)
- The record start time, to microsecond precision
- The sample rate and sample count
- The compressed data payload itself (Steim-1/Steim-2 compression)

This design makes miniSEED an excellent **archival and telemetry** format: records are self-describing, files can be concatenated freely, and gaps or overlaps in a continuous recording are represented honestly rather than being padded.

### 1.2 miniSEED vs. SAC: the structural difference that matters

The **SAC** (Seismic Analysis Code) format takes a different philosophy. A SAC file is a *single, contiguous, evenly sampled time-series* preceded by a large, rigidly structured header block. Two consequences follow directly:

1. **One SAC file = one continuous segment.** A miniSEED day-file containing many records for three components becomes several SAC files — one per channel per continuous segment. The converter merges records that belong together and starts a new output file where the series is not continuous.
2. **The SAC header expects station metadata that miniSEED does not carry.** miniSEED headers contain no station coordinates, no component orientation, and no elevation. SAC reserves explicit fields for them:

| SAC header field | Meaning | Source of the value |
|---|---|---|
| `STLA`, `STLO`, `STEL` | Station latitude, longitude, elevation (m) | Supplied by you: `-k` flag, metadata file, or scripting |
| `CMPAZ` | Component azimuth, degrees clockwise from North (N=0, E=90) | Metadata file / `-M` line |
| `CMPINC` | Component inclination from vertical (SAC convention: Z=0, horizontals=90) | Metadata file; `-msi` converts from the SEED dip convention |
| `DELTA` | Sample interval (s) | Read directly from miniSEED |
| `KNETWK`, `KSTNM`, `KCMPNM` | Network / station / channel names | Read directly from miniSEED |

> **Field note.** An untouched SAC header marks unknown numeric fields with the SAC "undefined" sentinel value (`-12345.0`). If you see `-12345.0` for `STLA` in a downstream tool, the conversion ran without coordinate information — see §6.1.

### 1.3 The SEED vs. SAC dip convention

SEED describes a channel's tilt from *horizontal* (a vertical-down sensor has dip −90°); SAC's `CMPINC` measures from the *upward vertical* (the same sensor is 0°). The `-msi` option of `mseed2sac` performs this translation automatically and is **strongly recommended** whenever you inject orientation metadata — it prevents the classic polarity error in which vertical traces appear inverted in moment-tensor or receiver-function workflows.

### 1.4 Conversion workflow architecture

All three options in this guide converge on the same engine — the EarthScope `mseed2sac` utility (v2.4), or ObsPy's native SAC writer:

```
miniSEED file(s) ──► [ optional time-window trim ]
                  ──► [ optional metadata/coordinate injection ]
                  ──► mseed2sac ──► NET.STA.LOC.CHAN.D.YYYY.JJJ.HHMMSS.SAC
```

Output file names follow the IRIS convention, e.g. `XX.ST01.00.HHZ.D.2024.075.080200.SAC` (year 2024, Julian day 075, segment start 08:02:00). Existing files are never overwritten — a numeric suffix (`-1`, `-2`, …) is appended instead.

---

## 2. Option 1: Gaiacode SEED-to-SAC Desktop Application (Recommended)

The **Gaiacode SEED-to-SAC Desktop Application** is a self-contained graphical utility for Windows and Linux that wraps `mseed2sac`. No installation is required: the converter engine, the Qt interface, and the ObsPy time-windowing library are bundled inside a single executable (`mseed2sac-gui.exe` / `mseed2sac-gui`).

### 2.1 The interface at a glance

| Control | Function |
|---|---|
| **Select File…** | Choose one `.mseed` / `.miniseed` / `.seed` file |
| **Select Folder…** | Batch-convert every miniSEED file in a directory |
| **Start time / Stop time** | Optional event window (ISO-8601) |
| **Select Metadata File…** | External station metadata (`-m`) — CSV or StationXML |
| **Latitude / Longitude** | Quick station coordinate injection (`-k`) |
| **Convert SEED to SAC Inclination** | Dip-convention correction toggle (`-msi`) |
| **Also write SACPZ response files** | Export instrument response alongside the data (requires StationXML) |
| **Browse…** (Output) | Destination directory for SAC files |
| **Convert / Cancel** | Start or abort the batch |
| Progress bar + status label | Per-file progress ("Processing 5 of 20…") |
| **CONSOLE LOG** | Live output and error stream from the engine |

### 2.2 Converting a single file

1. Click **Select File…** and choose the `.mseed` file.
2. Click **Browse…** under OUTPUT and choose the destination directory.
3. (Optional) Enter a time window — see §2.4.
4. (Optional) Add coordinates or metadata — see §2.5.
5. Click **Convert**. The console log streams the engine's verbose output, ending with `Done: 1 succeeded, 0 failed`. The SAC files appear in the output directory.

### 2.3 Batch-processing a station folder

1. Click **Select Folder…** and choose the station's data directory. The input line reports how many miniSEED files were found (e.g. `… — 37 miniSEED file(s) found`).
2. Choose the output directory as before.
3. Click **Convert**. Files are processed sequentially in a background thread; the interface remains responsive throughout. The status label and progress bar advance per file (`Processing 12 of 37…`), and the log records an `OK` or `ERROR` line for each.
4. To abort a long batch, click **Cancel** — the current file finishes its engine call, then the batch stops cleanly.

### 2.4 Time-windowed event extraction

Enter **Start time** and/or **Stop time** in ISO-8601 form, e.g. `2024-03-15T08:30:00`. Either bound may be left blank (open-ended). Internally the application slices the waveform with ObsPy *before* conversion — the `mseed2sac` engine itself has no time-window flags — so the resulting SAC files contain exactly the requested window, sample-accurate.

> **Validation.** Unparseable dates are rejected with an `ERROR` line in the log before any conversion starts; no partial output is produced.

### 2.5 Header injection: coordinates and metadata

**Quick coordinates.** Type the station position into **Latitude** and **Longitude** (decimal degrees, e.g. `12.345` / `78.901`). Both fields must be given together, latitude within ±90°, longitude within ±180° — invalid entries are rejected before launch. This maps to `mseed2sac -k <lat>/<lon>` and lands in `STLA`/`STLO` of every output file.

**Full metadata file.** Click **Select Metadata File…** to load a station metadata file. Two formats are accepted:

- **mseed2sac CSV** (`.txt` / `.csv` / `.dat`) — the native format documented in §3.4.
- **StationXML** (`.xml`) — the FDSN standard, and the format you will typically receive from network operators or export from your own inventory tooling. The application translates it to the CSV format internally via ObsPy at conversion time, mapping channel coordinates, elevation, depth, azimuth, sample rate, and instrument sensitivity. SEED-convention dips are converted to SAC convention during translation — so **leave the `-msi` toggle off when using StationXML** (the application detects this combination, logs a note, and suppresses `-msi` automatically to prevent double conversion).

One metadata file can hold every station in your network; the engine matches channels automatically by code and validity epoch, which makes it the correct choice for multi-station campaigns.

### 2.6 The "-msi" inclination toggle

Tick **Convert SEED to SAC Inclination (-msi)** whenever you supply orientation metadata in the **CSV format** (§3.4). It converts the SEED dip convention to SAC's `CMPINC` convention in the output headers, ensuring vertical and horizontal components carry the polarity that SAC-based analysis tools expect. See §1.3 for the underlying convention difference. Do not combine it with StationXML metadata — dip conversion is already applied during translation (see §2.5).

### 2.7 SACPZ response export

When a **StationXML** metadata file is selected, a second checkbox becomes available: **Also write SACPZ response files**. For every channel whose inventory entry carries a usable poles-and-zeros response, a `SACPZ.NET.STA.LOC.CHAN` file is written to the output directory alongside the SAC data — the response representation SAC's `transfer` command needs for instrument deconvolution. Channels without a complete response are skipped with a named note in the console log; the summary line reports how many were written and skipped.

> **Note.** The checkbox remains disabled for CSV metadata — the CSV format carries sensitivity scalars but no poles and zeros, so there is nothing to export.

### 2.8 Reading the console log

The console shows, for every file: the exact engine command executed (prefixed `$`), per-channel `Writing SAC for …` / `Wrote N samples to …` lines, metadata match confirmations (`Inserting metadata for N: … S: …`), and a batch summary. If a file fails — corrupt records, an empty time window, a missing metadata file — the `ERROR` line names the file and cause, and the batch continues with the remaining files.

---

## 3. Option 2: Command-Line Conversion via `mseed2sac`

The desktop application is a wrapper; the underlying `mseed2sac` engine (v2.4, EarthScope Consortium) can be compiled and driven directly — the natural choice for headless servers, cron jobs, and HPC environments.

### 3.1 Compiling

**Linux and macOS** (requires a C compiler and zlib headers — `build-essential zlib1g-dev` on Debian/Ubuntu, `xcode-select --install` on macOS):

```bash
cd SEEDTOSAC
make            # builds bundled libmseed, then src/mseed2sac
./mseed2sac -V  # → "mseed2sac version: 2.4"
```

**Windows** (MSVC Build Tools; open the *x64 Native Tools Command Prompt*):

```bat
cd D:\SEEDTOSAC
nmake -f Makefile.win
mseed2sac.exe -V
```

### 3.2 Core syntax

```
mseed2sac [options] input1.mseed [input2.mseed ...]
```

| Option | Effect |
|---|---|
| `-v` | Verbose logging (repeatable: `-vv`) |
| `-O` | Overwrite existing output files (default: append `-1`, `-2`, …) |
| `-k lat/lon` | Inject station coordinates into every output header |
| `-m metafile` | Match channels against an external metadata file |
| `-M metaline` | Inject a single metadata line directly on the command line |
| `-msi` | Convert dip/inclination from SEED to SAC convention |
| `-f format` | 1=SAC alphanumeric, 2=binary host order (default), 3=binary little-endian, 4=binary big-endian |
| `-E event` | Inject event origin (`Time[/Lat][/Lon][/Depth][/Name]`) |
| `-i` | Process each input file independently (bounded memory for large batches) |
| `-l selectfile` | Subset records via a selection file (record-level granularity) |

Output files are written to the **current working directory**, so `cd` to your target directory or invoke from a script that does.

### 3.3 Worked examples

Single file, verbose:

```bash
cd /data/sac_out
mseed2sac -v /data/mseed/ST01.2024.075.mseed
```

With station coordinates:

```bash
mseed2sac -v -k 12.3456/78.9012 ST01.2024.075.mseed
```

Full metadata with dip correction (recommended for analysis-ready headers):

```bash
mseed2sac -v -m network_metadata.txt -msi ST01.2024.075.mseed
```

### 3.4 Metadata file format

Comma-separated, one channel per line, with an optional `#` header row. Time ranges delimit the validity of each entry (channels are matched by code *and* epoch — useful when a station is re-sited):

```text
#net,sta,loc,chan,lat,lon,elev,depth,azimuth,SACdip,instrument,scale,scalefreq,scaleunits,samplerate,start,end
XX,ST01,00,HHZ,12.3456,78.9012,500.0,2.0,0.0,90.0,Gaiacode-Affinity,1.0,0.02,M/S,100,2024-01-01T00:00:00,2599-12-31T23:59:59
XX,ST01,00,HHN,12.3456,78.9012,500.0,2.0,0.0,90.0,Gaiacode-Affinity,1.0,0.02,M/S,100,2024-01-01T00:00:00,2599-12-31T23:59:59
XX,ST01,00,HHE,12.3456,78.9012,500.0,2.0,90.0,90.0,Gaiacode-Affinity,1.0,0.02,M/S,100,2024-01-01T00:00:00,2599-12-31T23:59:59
```

Note `SACdip=90` for the horizontals and `0.0` for the vertical when `-msi` conversion is *not* used; with `-msi`, supply SEED-convention dips and let the engine translate.

### 3.5 Automated directory processing

**Linux / macOS (bash):**

```bash
#!/usr/bin/env bash
# convert_all.sh — batch convert every miniSEED file under a root directory
set -u
SRC_ROOT="${1:?usage: convert_all.sh <mseed_root> <sac_out>}"
OUT_DIR="${2:?usage: convert_all.sh <mseed_root> <sac_out>}"
META="${3:-}"                       # optional metadata file
mkdir -p "$OUT_DIR"

find "$SRC_ROOT" -type f \( -iname '*.mseed' -o -iname '*.miniseed' \) | while read -r f; do
    args=(-v -i)                    # -i keeps memory bounded on large sets
    [[ -n "$META" ]] && args+=(-m "$META" -msi)
    ( cd "$OUT_DIR" && mseed2sac "${args[@]}" "$f" )
done
echo "Batch complete. SAC files in: $OUT_DIR"
```

**Windows (cmd batch):**

```bat
@echo off
rem convert_all.bat — usage: convert_all.bat <mseed_root> <sac_out> [metafile]
setlocal enabledelayedexpansion
set SRC=%1
set OUT=%2
set META=%3
if not exist "%OUT%" mkdir "%OUT%"
pushd "%OUT%"
for /r "%SRC%" %%F in (*.mseed) do (
    if defined META (
        mseed2sac.exe -v -i -m "%META%" -msi "%%F"
    ) else (
        mseed2sac.exe -v -i "%%F"
    )
)
popd
echo Batch complete. SAC files in: %OUT%
```

---

## 4. Option 3: Python & ObsPy Scripting Pipeline

For full programmatic control — nested station directories, per-station headers, time windows, custom naming — [ObsPy](https://docs.obspy.org) reads miniSEED and writes SAC natively. Install with `pip install obspy`.

The script below walks a directory tree of the form `<root>/<STATION>/*.mseed`, injects coordinates and component orientation into every trace's SAC header, applies an optional time window, and writes one SAC file per channel segment under a mirrored output tree:

```python
#!/usr/bin/env python3
"""
obspy_mseed2sac.py — batch miniSEED→SAC with full header injection.

Directory layout expected:
    <mseed_root>/<STATION>/*.mseed

Usage:
    python obspy_mseed2sac.py <mseed_root> <sac_root> \
        [--start 2024-03-15T08:30:00] [--stop 2024-03-15T09:00:00]
"""
import argparse
import sys
from pathlib import Path

from obspy import read, UTCDateTime
from obspy.core import AttribDict

MSEED_EXT = (".mseed", ".miniseed", ".seed")

# --- Station metadata table (edit for your network) -----------------------
# SAC convention: CMPINC 0 = vertical (up), 90 = horizontal;
#                 CMPAZ 0 = North, 90 = East.
STATIONS = {
    "ST01": {"stla": 12.3456, "stlo": 78.9012, "stel": 500.0},
    "ST02": {"stla": 12.4500, "stlo": 78.9500, "stel": 550.0},
}
ORIENTATION = {           # cmpaz, cmpinc per channel suffix
    "Z": (0.0, 0.0), "N": (0.0, 90.0), "E": (90.0, 90.0),
    "1": (0.0, 90.0), "2": (90.0, 90.0), "3": (0.0, 0.0),
}


def convert_file(mseed: Path, out_root: Path, station: str,
                 t1: UTCDateTime | None, t2: UTCDateTime | None) -> int:
    st = read(str(mseed))
    if t1 or t2:
        st.trim(starttime=t1, endtime=t2)
    if len(st) == 0:
        print(f"  skip (empty after trim): {mseed.name}")
        return 0

    meta = STATIONS.get(station, {})
    out_dir = out_root / station
    out_dir.mkdir(parents=True, exist_ok=True)

    n = 0
    for tr in st:
        # tr.stats.sac only exists natively on traces READ from SAC;
        # for miniSEED input it must be created explicitly.
        if not hasattr(tr.stats, "sac"):
            tr.stats.sac = AttribDict()
        sac = tr.stats.sac
        if meta:
            sac.stla, sac.stlo, sac.stel = (
                meta["stla"], meta["stlo"], meta["stel"])
        az, inc = ORIENTATION.get(tr.stats.channel[-1].upper(),
                                  (0.0, -12345.0))
        sac.cmpaz, sac.cmpinc = az, inc
        if inc == -12345.0:
            del sac.cmpinc            # leave undefined, don't write sentinel

        name = (f"{tr.stats.network}.{tr.stats.station}."
                f"{tr.stats.location}.{tr.stats.channel}.D."
                f"{tr.stats.starttime.strftime('%Y.%j.%H%M%S')}.SAC")
        tr.write(str(out_dir / name), format="SAC")
        n += 1
    print(f"  {mseed.name}: wrote {n} SAC file(s)")
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("mseed_root", type=Path)
    ap.add_argument("sac_root", type=Path)
    ap.add_argument("--start", default=None, help="ISO start time")
    ap.add_argument("--stop", default=None, help="ISO stop time")
    args = ap.parse_args()

    t1 = UTCDateTime(args.start) if args.start else None
    t2 = UTCDateTime(args.stop) if args.stop else None
    total = 0

    for sta_dir in sorted(p for p in args.mseed_root.iterdir()
                          if p.is_dir()):
        station = sta_dir.name
        files = sorted(f for f in sta_dir.iterdir()
                       if f.suffix.lower() in MSEED_EXT)
        if not files:
            continue
        print(f"[{station}] {len(files)} miniSEED file(s)")
        for f in files:
            try:
                total += convert_file(f, args.sac_root, station, t1, t2)
            except Exception as exc:
                print(f"  ERROR {f.name}: {exc}", file=sys.stderr)

    print(f"Done — {total} SAC file(s) written under {args.sac_root}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

**Key points for adaptation:**

- `tr.stats.sac` exists natively only on traces *read from* SAC; for miniSEED input create it first (`tr.stats.sac = AttribDict()`), as the script does. Only the fields you set are written. Never write the literal `-12345.0` sentinel yourself — omit the field instead.
- The orientation map covers both `HHZ/N/E` and `HH1/2/3` channel-naming schemes; borehole or rotated sensors need their measured azimuths entered per station.
- `st.trim()` *before* writing is the sample-accurate equivalent of the desktop application's Start/Stop fields.
- For gappy day-files, `read()` returns one Trace per continuous segment automatically — each is written as its own SAC file, mirroring `mseed2sac` behaviour.

---

## 5. Option 4: Headless Automation — the OmegaBox Pipeline

For permanent observatory installations, Gaiacode ships a cron-driven pipeline (`SEEDTOSAC/OmegaBox/`) that periodically mirrors continuous data directly from OmegaBox units over HTTP, converts to SAC, and injects StationXML metadata — no GUI, no operator. It reuses the conversion semantics of Option 3 (ObsPy trim-free whole-file conversion, `CMPINC = dip + 90`, IRIS file naming).

### 5.1 Configuration

One `config.yaml` defines the archive roots and the station list:

```yaml
archive_paths:
  sds_root: /data/omegabox_mirror    # local mirror of the remote trees
  sac_root: /data/sac_archive        # SAC output, one subdir per station

settings:
  wget_timeout_s: 300
  log_file: pipeline.log

stations:
  - name: ST01
    web_url: http://<INTERNAL_IP>/data/
    stationxml_path: /data/metadata/ST01.xml
```

### 5.2 What each run does

1. **Mirror** — per station, `wget -m -np -nH --cut-dirs=1 -R "index.html*"` synchronises the unit's `/data/` tree locally; only new or changed files are transferred.
2. **Convert & inject** — every mirrored miniSEED file is read with ObsPy; each trace is matched against the station's StationXML (codes *and* epoch) and the SAC header is populated (`STLA/STLO/STEL`, `CMPAZ`, `CMPINC = dip + 90`).
3. **Save** — output is written as `<sac_root>/<STATION>/NET.STA.LOC.CHAN.D.YYYY.JJJ.HHMMSS.SAC`.

All activity is written to `pipeline.log` via the standard `logging` module. Missing metadata, unreadable files, and network failures are logged and isolated — a station that cannot be reached fails the run's exit code (so cron monitoring can alert on it) without disturbing the remaining stations.

### 5.3 Scheduling

Hourly, at five minutes past, via `crontab -e` (absolute paths are essential — cron provides neither a working directory nor a full `PATH`):

```cron
5 * * * * /opt/gaiacode/pipeline/venv/bin/python /opt/gaiacode/pipeline/gaiacode_pipeline.py >> /opt/gaiacode/pipeline/cron.out 2>&1
```

The full deployment guide ships with the pipeline as `README.md`.

---

## 6. Troubleshooting & Field Best Practices

### 6.1 Empty coordinate headers in SAC output

**Symptom:** `STLA`/`STLO` read as `-12345.0` (SAC's undefined sentinel) in SAC, ObsPy, or your analysis code.

**Cause:** miniSEED carries no coordinates; unless you inject them, the engine leaves the fields undefined. This is expected behaviour, not a fault.

**Remedies, in order of preference:**
- Desktop app: fill **Latitude/Longitude**, or load a metadata file (§2.5).
- CLI: add `-k <lat>/<lon>` or `-m <metafile>` (§3.3).
- ObsPy: set `tr.stats.sac.stla/stlo/stel` before writing (§4).

Verify after conversion: `obspy` one-liner `python -c "from obspy import read; print(read('FILE.SAC')[0].stats.sac.stla)"` should echo your latitude, not `-12345.0`.

### 6.2 Multi-day continuous files and trace gaps

- **Spanning days:** `mseed2sac` buffers all input records and merges records of the same channel into one continuous series, so a single SAC file can span midnight boundaries. Pass all day-files of a station in one invocation (or one folder batch) rather than converting day-by-day if you want merged output.
- **Bounded memory:** for very large batches add `-i` (process each input file independently) — output is then per-input-file, but memory stays flat.
- **Gaps:** a genuine acquisition gap (power loss, telemetry outage) ends the current SAC file and starts a new one when data resumes — identifiable by the timestamp in the file name. Do **not** zero-fill gaps before analysis; SAC consumers expect honest segmentation.
- **Overlaps:** duplicated records (re-requested telemetry) are reconciled during merge; verbose mode (`-v`) reports what was done.

### 6.3 Julian-date file naming

SAC output names encode the segment start as `YYYY.JJJ.HHMMSS`, where `JJJ` is the **day-of-year** (001–366), not month-day. `2024.075` = 15 March 2024 (a leap year). Quick conversions:

```bash
# calendar date → Julian day
date -d 2024-03-15 +%j          # → 075
# Julian day → calendar date
date -d "2024-01-01 +74 days"   # → day 075
```

In Python: `UTCDateTime("2024-03-15").julday` or `datetime.strptime("2024 075", "%Y %j")`. When scripting retrieval by calendar date, always convert via `%j`/julday rather than string arithmetic — off-by-one errors around leap years are the most common silent failure in retrieval cron jobs.

### 6.4 General field checklist

1. **Record station coordinates at installation** (handheld GPS at the vault) and keep one StationXML (or `network_metadata.txt`) per network under version control.
2. **StationXML users:** load the `.xml` directly in the desktop application — dip conversion is handled for you; leave `-msi` off. **CSV users:** always use `-msi` (or the GUI toggle) when injecting orientation metadata.
3. **Convert a small sample first** and inspect headers before batch runs over an entire field campaign.
4. **Never delete source miniSEED** after conversion; SAC is an analysis projection, miniSEED remains the archive of record.
5. **Keep the converter version in your methods section**: "miniSEED data were converted to SAC format with mseed2sac v2.4 (EarthScope Consortium)" satisfies reproducibility requirements for publication.

---

*Gaiacode Limited — Technical Support. For questions regarding Affinity/OmegaBox data extraction or this guide, contact your Gaiacode support channel. mseed2sac is developed by the EarthScope Consortium (formerly IRIS) and distributed under its open-source licence.*
