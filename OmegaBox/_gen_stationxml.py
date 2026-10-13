"""Generate StationXML for stations discovered in the mirrored OmegaBox data.

Per unit: enumerate (net, sta, loc, cha, rate, first_epoch) from the
mirrored miniSEED, then emit one FDSN StationXML per data-station.
Coordinates/elevation are inherited from sibling unit XMLs — VERIFY
before operational use.
"""
from collections import defaultdict
from pathlib import Path

from obspy import read, read_inventory, UTCDateTime
from obspy.core.inventory import (Inventory, Network, Station, Channel,
                                  Site)

BASE = Path(__file__).resolve().parent
MIRROR = Path("/data/seismic/omegabox_mirror")

# coordinate defaults harvested from the sibling units' XMLs
def unit_coords(xml_name):
    inv = read_inventory(str(BASE / xml_name))
    sta = inv[0][0]
    return sta.latitude, sta.longitude, sta.elevation or 0.0

# SANITIZED EXAMPLE mapping — replace unit labels with your own.
COORDS = {
    "UNIT1": unit_coords("XX.ST01.xml"),
    "UNIT3": unit_coords("XX.ST03.xml"),
}
COORDS["UNIT2"] = COORDS["UNIT1"]    # same bench — no XML of its own

ORIENTATION = {"Z": (0.0, -90.0), "N": (0.0, 0.0), "E": (90.0, 0.0)}
SEISMIC_BANDS = set("BCFHLMEN")     # SEED band codes (B)H/(C)H/(F)H…, EN, MN…


def scan_unit(unit_dir: Path):
    """(net,sta,loc,cha) -> (sampling_rate, earliest_start)"""
    out = {}
    for f in sorted(unit_dir.rglob("*.mseed")):
        try:
            st = read(str(f), headonly=True)
        except Exception:
            continue
        for tr in st:
            key = (tr.stats.network, tr.stats.station,
                   tr.stats.location, tr.stats.channel)
            t0 = tr.stats.starttime
            if key not in out:
                out[key] = (tr.stats.sampling_rate, t0)
            else:
                rate, first = out[key]
                out[key] = (rate, min(first, t0))
    return out


for unit_dir in sorted(p for p in MIRROR.iterdir() if p.is_dir()):
    unit = unit_dir.name
    codes = scan_unit(unit_dir)
    if not codes:
        continue
    lat, lon, elev = COORDS.get(unit, (None, None, 0.0))

    stations = defaultdict(list)     # (net, sta) -> [Channel]
    for (net, sta, loc, cha), (rate, first) in sorted(codes.items()):
        kw = {}
        last = cha[-1].upper()
        if len(cha) == 3 and cha[0].upper() in SEISMIC_BANDS \
                and last in ORIENTATION:
            az, dip = ORIENTATION[last]
            kw["azimuth"], kw["dip"] = az, dip
        stations[(net, sta)].append(Channel(
            code=cha, location_code=loc,
            latitude=lat, longitude=lon, elevation=elev, depth=0.0,
            sample_rate=rate, start_date=first, **kw))

    inv = Inventory(networks=[], source="GaiaCode pipeline auto-scan",
                    created=UTCDateTime())
    for (net_code, sta_code), chans in sorted(stations.items()):
        first_epoch = min(c.start_date for c in chans)
        sta = Station(code=sta_code, latitude=lat, longitude=lon,
                      elevation=elev,
                      site=Site(name=f"{sta_code} (auto-generated — "
                                     f"verify coordinates)"),
                      channels=chans, creation_date=first_epoch,
                      start_date=first_epoch)
        inv.networks.append(Network(code=net_code, stations=[sta]))
        out = BASE / f"{net_code}.{sta_code}.xml"
        inv.networks = [n for n in inv.networks]   # keep cumulative
        Inventory(networks=[Network(code=net_code, stations=[sta])],
                  source="GaiaCode pipeline auto-scan",
                  created=UTCDateTime()).write(str(out), format="STATIONXML")
        print(f"wrote {out.name}: {len(chans)} channels "
              f"({lat}, {lon}, {elev} m)")
