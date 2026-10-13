# GaiaCode OmegaBox → SAC Headless Pipeline

Automated, cron-safe pipeline that periodically mirrors continuous seismic
data from GaiaCode OmegaBox digitizers, converts miniSEED to SAC, and
injects station metadata (coordinates, component orientation) from
StationXML into the SAC headers.

## Files

| File | Purpose |
|---|---|
| `config.yaml` | Station list, archive paths, pipeline settings |
| `gaiacode_pipeline.py` | The daemon (one-shot per invocation; cron drives the schedule) |
| `gaiacode_pipeline_recent.py` | Testing variant — mirrors only the last N days (default 3) |
| `_test_pipeline.py` | End-to-end self-test against a mock local OmegaBox HTTP server |
| `_test_recent.py` | End-to-end self-test for the recent-days variant |
| `pipeline.log` | Runtime log (created on first run) |

## Testing variant (bounded download)

`gaiacode_pipeline_recent.py` is identical to the main daemon except the
mirror step fetches only the last N calendar days (including today),
addressed directly against the OmegaBox archive layout
(`/data/YYYY/YYYYMM/YYYYMMDD/`) — ideal for shakedown tests against live
units without pulling the entire archive:

```bash
./venv/bin/python gaiacode_pipeline_recent.py --days 3
```

A day with no data on the unit (404) is logged as a warning and skipped
without failing the run. It writes to `pipeline_recent.log` and shares
`config.yaml` with the main daemon — note that it converts *all* files
currently in the local mirror, so point `sds_root` at a scratch directory
if you want to keep test output separate from the production mirror.

## Prerequisites

```bash
sudo apt install wget python3-yaml     # Debian/Ubuntu
pip install obspy                      # or into a dedicated venv
```

The pipeline is designed for a virtual environment:

```bash
cd /opt/seedtosac/OmegaBox
python3 -m venv venv
./venv/bin/pip install obspy pyyaml
```

## Configuration

Edit `config.yaml`:

- `archive_paths.sds_root` — local mirror of the OmegaBox file trees
  (one subdirectory per station, created automatically).
- `archive_paths.sac_root` — converted SAC output (one subdirectory per
  station).
- `settings.wget_timeout_s` — per-station mirror timeout.
- `stations` — one entry per OmegaBox unit:
  - `name` — station code (must match the SEED station code in the data
    and the StationXML).
  - `web_url` — the unit's data endpoint, e.g. `http://<INTERNAL_IP>/data/`.
  - `stationxml_path` — the station's StationXML file **on this host**.
    OmegaBox units do not serve StationXML; keep one file per station next
    to the pipeline, named `<net>.<sta>.<loc>.xml`
    (e.g. `XX.ST01.00.xml`).

## Where the data lives

The shipped default follows seismic community convention — a dedicated
data volume at `/data`, separate from the OS disk:

```
/data/seismic/
├── omegabox_mirror/     ← sds_root: raw miniSEED (archive of record)
├── sac_archive/         ← sac_root: SAC output (regenerable projection)
└── metadata/            ← StationXML (or keep them beside the pipeline)
```

Create it once as root, then hand it to the service user:

```bash
sudo mkdir -p /data/seismic
sudo chown -R seismic:seismic /data/seismic
```

Rationale:

- **Isolation** — continuous data must not share a filesystem with the
  OS; a full data disk stops archiving, a full OS disk stops the host.
- **Capacity** — a 3-channel 100 sps 24-bit station yields roughly
  30–50 MB/day of compressed miniSEED and ~100 MB/day of SAC.
- **The mirror is the archive of record.** The SAC tree can always be
  rebuilt from it; the reverse is not true.

For small single-disk deployments, a `~/data/seismic/` fallback is
commented into `config.yaml` — the pipeline is agnostic; everything
flows from the config.

## Manual run

```bash
./venv/bin/python gaiacode_pipeline.py
# or against a different config:
./venv/bin/python gaiacode_pipeline.py --config /etc/gaiacode/config.yaml
```

Exit code is `0` when every file converted, `1` if any file failed
(failures are itemised in `pipeline.log`; the loop never aborts early).

## Scheduling with cron

Run every hour at 5 minutes past, logging nothing extra to the console
(the daemon writes its own `pipeline.log`):

```cron
5 * * * * /opt/seedtosac/OmegaBox/venv/bin/python /opt/seedtosac/OmegaBox/gaiacode_pipeline.py >> /opt/seedtosac/OmegaBox/cron.out 2>&1
```

Install with `crontab -e`. Use absolute paths throughout — cron has no
`PATH` beyond a minimal default and no working directory.

## Behaviour notes

- **Mirror** uses `wget -m -np -nH --cut-dirs=1 -R "index.html*"`, so only
  new/changed files are transferred on each run (timestamping).
- **Header injection** — `STLA/STLO/STEL` from the StationXML channel (or
  station) coordinates; `CMPAZ` from azimuth; `CMPINC = dip + 90`
  (SEED dip → SAC inclination convention, matching the `-msi` behaviour
  of the desktop converter).
- **Naming** — `NET.STA.LOC.CHAN.D.YYYY.JJJ.HHMMSS.SAC`, one file per
  continuous segment per channel; gappy day-files yield multiple files.
- Traces with no matching channel in the StationXML are skipped with a
  warning; unreadable files are logged as errors. Neither aborts the run.
- `pipeline.log` grows unbounded — rotate it with `logrotate` or a
  monthly cron `truncate -s 0` if the pipeline runs for years.
