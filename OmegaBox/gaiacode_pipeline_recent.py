#!/usr/bin/env python3
"""
gaiacode_pipeline_recent.py — bounded OmegaBox → SAC pipeline (testing).

Identical to gaiacode_pipeline.py except the mirror step fetches only the
last N calendar days (default 3, including today) instead of the full
archive. Day directories are addressed directly as <web_url><YYYY>/<JJJ>/
— matching the OmegaBox /data/ tree layout — so a day with no data simply
404s, is logged, and is skipped without failing the run.

Usage:
    python3 gaiacode_pipeline_recent.py [--config config.yaml] [--days 3]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

# Reuse everything except the mirror step from the main pipeline.
from gaiacode_pipeline import (  # noqa: E402
    load_config, setup_logging, process_station,
    load_state, save_state,
    DEFAULT_WGET_TIMEOUT, DEFAULT_EXTENSIONS, log,
)


def day_urls(web_url: str, days: int) -> list[tuple[str, str]]:
    """Return [(url, label)] for the last `days` calendar days (incl. today).

    OmegaBox archive layout: /data/<YYYY>/<YYYYMM>/<YYYYMMDD>/<files>.mseed
    """
    out = []
    today = date.today()
    for i in range(days - 1, -1, -1):
        d = today - timedelta(days=i)
        out.append((f"{web_url.rstrip('/')}/{d.year}/"
                    f"{d.strftime('%Y%m')}/{d.strftime('%Y%m%d')}/",
                    d.isoformat()))
    return out


def mirror_station_recent(station: dict, sds_root: Path, timeout: int,
                          days: int) -> bool:
    """Mirror only the last `days` day-directories for one station.
    Returns True if at least the mirror attempts completed (a day with no
    data is not an error)."""
    name = station["name"]
    dest = sds_root / name
    dest.mkdir(parents=True, exist_ok=True)
    hard_failure = False
    saved = 0

    for url, label in day_urls(station["web_url"], days):
        if label != date.today().isoformat():
            # Past days are immutable once the hour rotates: plain
            # recursion + no-clobber skips files already mirrored.
            # (-m implies -N/timestamping, which wget forbids with -nc.)
            cmd = [
                "wget", "-r", "-l", "inf", "-nc",
                "-np", "-nH", "--cut-dirs=1",
                "-R", "index.html*",
                "--timeout=30", "--tries=2",
            ]
        else:
            # TODAY keeps full mirror+timestamping: the current hour file
            # is still being written — -nc would freeze a partial
            # download forever.
            cmd = [
                "wget", "-m",
                "-np", "-nH", "--cut-dirs=1",
                "-R", "index.html*",
                "--timeout=30", "--tries=2",
            ]
        cmd += ["-P", str(dest), url]
        log.info("[%s] mirror %s : %s", name, label, url)
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=timeout)
        except subprocess.TimeoutExpired:
            log.error("[%s] mirror of %s timed out — skipping day",
                      name, label)
            hard_failure = True
            continue
        # wget logs progress ("Saving to: ...") to stderr, not stdout
        day_saved = (proc.stderr or "").count("Saving to:")
        saved += day_saved
        if proc.returncode == 0:
            log.info("[%s] %s mirrored", name, label)
        elif proc.returncode == 8:
            # server error response — almost always a 404 for a day the
            # unit has not written (yet); normal near "now"
            log.warning("[%s] no data for %s (server refused/404)",
                        name, label)
        elif proc.returncode == 4 and day_saved > 0:
            # network failure AFTER files were saved — characteristic of
            # the unit actively writing the current hour's file
            # ("No data received"). The day is usable; the in-progress
            # file arrives on the next run via timestamping.
            log.warning("[%s] %s partially mirrored (%d files saved) — "
                        "wget exit 4, likely the in-progress current "
                        "file; remainder syncs next run",
                        name, label, day_saved)
        else:
            log.error("[%s] wget exited %d for %s: %s", name,
                      proc.returncode, label,
                      (proc.stderr or proc.stdout).strip()[-300:])
            hard_failure = True

    if saved == 0 and not hard_failure:
        # wget exits 0 even when the server answered with an HTML shell
        # and nothing was downloaded — never let that pass silently.
        log.warning("[%s] mirror completed but downloaded 0 files — "
                    "check the unit's archive layout against the "
                    "YYYY/YYYYMM/YYYYMMDD pattern", name)
    return not hard_failure


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    default_cfg = Path(__file__).resolve().parent / "config.yaml"
    ap.add_argument("--config", type=Path, default=default_cfg)
    ap.add_argument("--days", type=int, default=3,
                    help="calendar days to fetch, including today "
                         "(default: 3)")
    args = ap.parse_args()

    cfg = load_config(args.config)
    settings = cfg.get("settings", {})
    setup_logging(Path(settings.get("log_file", "pipeline.log"))
                  .with_name("pipeline_recent.log"))

    sds_root = Path(cfg["archive_paths"]["sds_root"])
    sac_root = Path(cfg["archive_paths"]["sac_root"])
    timeout = int(settings.get("wget_timeout_s", DEFAULT_WGET_TIMEOUT))
    extensions = tuple(settings.get("mseed_extensions", DEFAULT_EXTENSIONS))

    for root in (sds_root, sac_root):
        try:
            root.mkdir(parents=True, exist_ok=True)
        except PermissionError:
            log.error("cannot create archive root %s — check ownership "
                      "and permissions of that path (or its parent)", root)
            return 2

    log.info("=== recent-data run start: last %d day(s), %d station(s) ===",
             args.days, len(cfg["stations"]))
    state = load_state(sds_root)
    tot_ok = tot_fail = 0
    for station in cfg["stations"]:
        name = station["name"]
        try:
            if not mirror_station_recent(station, sds_root, timeout,
                                         args.days):
                tot_fail += 1
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
    log.info("=== recent-data run complete: %d file(s) converted, "
             "%d failed ===", tot_ok, tot_fail)
    return 0 if tot_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
