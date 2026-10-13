#!/usr/bin/env python3
"""
gaiacode_pipeline.py — headless OmegaBox → SAC data pipeline.

For each configured GaiaCode OmegaBox station:
  1. MIRROR   — synchronise the unit's remote /data/ tree locally (wget).
  2. CONVERT  — read every mirrored miniSEED file with ObsPy, inject
                station coordinates and component orientation from the
                station's StationXML into the SAC headers.
  3. SAVE     — write SAC files under <sac_root>/<STATION>/.

Designed for unattended cron execution: all output goes through the
`logging` module (file + stderr), every per-station and per-file failure
is caught and logged, and the loop always proceeds to the next item.

Usage:
    python3 gaiacode_pipeline.py [--config config.yaml]
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

from obspy import read, read_inventory, UTCDateTime
from obspy.core import AttribDict

log = logging.getLogger("gaiacode_pipeline")

DEFAULT_WGET_TIMEOUT = 300
DEFAULT_EXTENSIONS = (".mseed", ".miniseed", ".seed")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
def load_config(path: Path) -> dict:
    with open(path) as fh:
        cfg = yaml.safe_load(fh)
    for key in ("archive_paths", "stations"):
        if key not in cfg:
            raise KeyError(f"config missing required key: '{key}'")
    for sub in ("sds_root", "sac_root"):
        if sub not in cfg["archive_paths"]:
            raise KeyError(f"config missing archive_paths.{sub}")
    if not cfg["stations"]:
        raise ValueError("config defines no stations")
    for st in cfg["stations"]:
        for key in ("name", "web_url", "stationxml_path"):
            if key not in st:
                raise KeyError(f"station entry missing '{key}': {st}")
    return cfg


def setup_logging(log_file: Path):
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")
    fh = logging.FileHandler(log_file)
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(fmt)
    log.addHandler(fh)
    log.addHandler(sh)


# ---------------------------------------------------------------------------
# Step 1 — Mirror
# ---------------------------------------------------------------------------
def mirror_station(station: dict, sds_root: Path, timeout: int) -> bool:
    """wget-mirror one OmegaBox /data/ tree. Returns True on success."""
    name, url = station["name"], station["web_url"]
    dest = sds_root / name
    dest.mkdir(parents=True, exist_ok=True)
    cmd = [
        "wget", "-m", "-np", "-nH", "--cut-dirs=1",
        "-R", "index.html*",
        "--timeout=30", "--tries=2",
        "-P", str(dest), url,
    ]
    log.info("[%s] mirror start: %s -> %s", name, url, dest)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout)
    except subprocess.TimeoutExpired:
        log.error("[%s] mirror timed out after %ds — skipping station",
                  name, timeout)
        return False
    except FileNotFoundError:
        log.error("[%s] wget not installed on this host — aborting mirror",
                  name)
        raise
    # wget exit codes: 0 ok; 8 = server error response; others see man page
    if proc.returncode != 0:
        log.error("[%s] wget exited %d: %s", name, proc.returncode,
                  (proc.stderr or proc.stdout).strip()[-400:])
        return False
    log.info("[%s] mirror complete", name)
    return True


# ---------------------------------------------------------------------------
# Incremental-conversion state
# ---------------------------------------------------------------------------
STATE_NAME = ".pipeline_state.json"


def load_state(sds_root: Path) -> dict:
    """{str(file_path): {"mtime": float, "size": int}} of converted files."""
    p = sds_root / STATE_NAME
    if p.is_file():
        try:
            return json.loads(p.read_text())
        except Exception:
            log.warning("state file %s unreadable — starting fresh", p)
    return {}


def save_state(sds_root: Path, state: dict):
    (sds_root / STATE_NAME).write_text(json.dumps(state, indent=0))


# ---------------------------------------------------------------------------
# Step 2/3 — Convert, inject metadata, save
# ---------------------------------------------------------------------------
def find_channel(inv, tr):
    """Locate the inventory channel matching a trace (code + epoch)."""
    for net in inv:
        if net.code != tr.stats.network:
            continue
        for sta in net:
            if sta.code != tr.stats.station:
                continue
            for cha in sta:
                if (cha.location_code == tr.stats.location
                        and cha.code == tr.stats.channel
                        and cha.is_active(time=tr.stats.starttime)):
                    return cha
    return None


def inject_metadata(tr, cha):
    """Map StationXML channel fields onto the trace's SAC header."""
    if not hasattr(tr.stats, "sac"):
        tr.stats.sac = AttribDict()
    sac = tr.stats.sac
    # coordinates — channel level, falling back to station level
    sac.stla = cha.latitude
    sac.stlo = cha.longitude
    sac.stel = cha.elevation
    # orientation — SEED dip (from horizontal) → SAC CMPINC (from vertical)
    if cha.azimuth is not None:
        sac.cmpaz = float(cha.azimuth)
    if cha.dip is not None:
        sac.cmpinc = float(cha.dip) + 90.0


def sac_filename(tr) -> str:
    return (f"{tr.stats.network}.{tr.stats.station}.{tr.stats.location}."
            f"{tr.stats.channel}.D."
            f"{tr.stats.starttime.strftime('%Y.%j.%H%M%S')}.SAC")


def convert_file(mseed: Path, inv, station_name: str,
                 sac_root: Path) -> int:
    """Convert one miniSEED file; returns number of SAC files written."""
    out_dir = sac_root / station_name
    out_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    for tr in read(str(mseed)):
        cha = find_channel(inv, tr)
        if cha is None:
            seed_id = (f"{tr.stats.network}.{tr.stats.station}."
                       f"{tr.stats.location}.{tr.stats.channel}")
            log.warning("[%s] %s: no StationXML channel for %s @ %s — "
                        "skipped", station_name, mseed.name, seed_id,
                        tr.stats.starttime)
            continue
        inject_metadata(tr, cha)
        out = out_dir / sac_filename(tr)
        tr.write(str(out), format="SAC")
        written += 1
    return written


def process_station(station: dict, sds_root: Path, sac_root: Path,
                    extensions: tuple[str, ...],
                    state: dict | None = None) -> tuple[int, int]:
    """Convert every mirrored file for one station. Returns (ok, failed).

    When `state` is given, files whose recorded mtime+size are unchanged
    since their last successful conversion are skipped (incremental mode).
    """
    name = station["name"]
    xml_path = Path(station["stationxml_path"])
    if not xml_path.is_file():
        log.error("[%s] StationXML not found: %s — skipping station",
                  name, xml_path)
        return 0, 1
    try:
        inv = read_inventory(str(xml_path))
    except Exception as exc:
        log.error("[%s] StationXML unparseable (%s) — skipping station",
                  name, exc)
        return 0, 1

    station_root = sds_root / name
    files = sorted(p for p in station_root.rglob("*")
                   if p.suffix.lower() in extensions)
    if not files:
        log.warning("[%s] no miniSEED files under %s", name, station_root)
        return 0, 0

    todo = []
    skipped = 0
    for f in files:
        st_ = f.stat()
        ent = state.get(str(f)) if state is not None else None
        if ent and ent.get("mtime") == st_.st_mtime \
                and ent.get("size") == st_.st_size:
            skipped += 1
            continue
        todo.append((f, st_))
    if skipped:
        log.info("[%s] %d file(s) unchanged since last conversion — "
                 "skipped", name, skipped)

    ok = failed = 0
    for f, st_ in todo:
        try:
            n = convert_file(f, inv, name, sac_root)
            log.info("[%s] %s → %d SAC file(s)", name, f.name, n)
            ok += 1
            if state is not None:
                state[str(f)] = {"mtime": st_.st_mtime, "size": st_.st_size}
        except Exception as exc:
            log.error("[%s] failed to convert %s: %s", name, f, exc)
            failed += 1
    return ok, failed


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    default_cfg = Path(__file__).resolve().parent / "config.yaml"
    ap.add_argument("--config", type=Path, default=default_cfg)
    args = ap.parse_args()

    cfg = load_config(args.config)
    settings = cfg.get("settings", {})
    setup_logging(Path(settings.get("log_file", "pipeline.log")))

    sds_root = Path(cfg["archive_paths"]["sds_root"])
    sac_root = Path(cfg["archive_paths"]["sac_root"])
    timeout = int(settings.get("wget_timeout_s", DEFAULT_WGET_TIMEOUT))
    extensions = tuple(settings.get("mseed_extensions", DEFAULT_EXTENSIONS))

    # pre-flight: archive roots must exist and be writable
    for root in (sds_root, sac_root):
        try:
            root.mkdir(parents=True, exist_ok=True)
        except PermissionError:
            log.error("cannot create archive root %s — check ownership "
                      "and permissions of that path (or its parent)", root)
            return 2

    log.info("=== pipeline run start (%d station(s)) ===",
             len(cfg["stations"]))
    state = load_state(sds_root)
    tot_ok = tot_fail = 0
    for station in cfg["stations"]:
        name = station["name"]
        try:
            if not mirror_station(station, sds_root, timeout):
                tot_fail += 1      # a dark station must fail the run
                continue
            ok, failed = process_station(station, sds_root, sac_root,
                                         extensions, state)
            tot_ok += ok
            tot_fail += failed
        except Exception:
            log.exception("[%s] unhandled station-level error — "
                          "continuing with next station", name)
            tot_fail += 1
    save_state(sds_root, state)
    log.info("=== pipeline run complete: %d file(s) converted, "
             "%d failed ===", tot_ok, tot_fail)
    return 0 if tot_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
