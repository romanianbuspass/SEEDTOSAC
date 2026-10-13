"""Enumerate NET.STA.LOC.CHAN codes present in the mirrored OmegaBox data."""
import sys
from collections import defaultdict
from pathlib import Path

from obspy import read

MIRROR = Path("/data/seismic/omegabox_mirror")
codes = defaultdict(lambda: defaultdict(int))   # unit -> (net,sta,loc,cha) -> files

for unit_dir in sorted(p for p in MIRROR.iterdir() if p.is_dir()):
    for f in sorted(unit_dir.rglob("*.mseed")):
        try:
            st = read(str(f), headonly=True)
        except Exception as exc:
            print(f"  unreadable: {f.name}: {exc}")
            continue
        for tr in st:
            key = (tr.stats.network, tr.stats.station,
                   tr.stats.location, tr.stats.channel)
            codes[unit_dir.name][key] += 1

for unit, chans in codes.items():
    print(f"\n=== {unit} ===")
    for (net, sta, loc, cha), n in sorted(chans.items()):
        print(f"  {net}.{sta}.{loc}.{cha}  ({n} files)")

# summary of unique stations
print("\n=== unique stations per unit ===")
for unit, chans in codes.items():
    stas = sorted({f"{n}.{s}" for n, s, l, c in chans})
    print(f"  {unit}: {', '.join(stas)}")
