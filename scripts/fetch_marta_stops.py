"""
Download REAL MARTA stops (rail + bus) from the City of Atlanta / ARC ArcGIS
services and save them where build_transit.py expects them:

    data/sources/marta_stops.geojson       <- 38 rail stations
    data/sources/marta_bus_stops.geojson   <- ~3,800 bus stops within Atlanta

Run this ONCE locally (your Mac has open network; the cloud sandbox is firewalled):

    python3 scripts/fetch_marta_stops.py
    python3 scripts/build_transit.py --all     # then rebuild every NPU

Uses only the Python standard library.
"""

import json
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "data" / "sources"

RAIL_URL = ("https://services5.arcgis.com/5RxyIIJ9boPdptdo/arcgis/rest/services/"
            "Official_MARTA_Rail_Stations_2021/FeatureServer/0/query")
BUS_URL = ("https://services5.arcgis.com/5RxyIIJ9boPdptdo/arcgis/rest/services/"
           "MARTA_Stops_within_COA/FeatureServer/0/query")


def fetch_all(base_url):
    """Page through an ArcGIS FeatureServer layer and return all GeoJSON features."""
    features, offset, page = [], 0, 2000
    while True:
        params = {
            "where": "1=1", "outFields": "*", "f": "geojson",
            "resultOffset": offset, "resultRecordCount": page,
            "outSR": "4326",
        }
        url = base_url + "?" + urllib.parse.urlencode(params)
        with urllib.request.urlopen(url, timeout=60) as r:
            data = json.loads(r.read().decode())
        batch = data.get("features", [])
        features += batch
        print(f"  fetched {len(features)} ...")
        if len(batch) < page:      # last page
            break
        offset += page
    return features


def slim(features, mode):
    """Keep just point geometry + a name, tag the mode."""
    out = []
    for f in features:
        g = f.get("geometry") or {}
        if g.get("type") != "Point":
            continue
        p = f.get("properties", {})
        name = (p.get("stop_name") or p.get("STATION") or p.get("NAME")
                or p.get("Name") or f"MARTA {mode}")
        lon, lat = g["coordinates"][:2]
        out.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [round(lon, 6), round(lat, 6)]},
            "properties": {"stop_name": name, "mode": mode},
        })
    return out


def save(features, path):
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features}))
    print(f"  wrote {len(features)} -> {path.relative_to(ROOT)}")


def main():
    SOURCES.mkdir(parents=True, exist_ok=True)
    print("Rail stations:")
    save(slim(fetch_all(RAIL_URL), "rail"), SOURCES / "marta_stops.geojson")
    print("Bus stops (City of Atlanta):")
    save(slim(fetch_all(BUS_URL), "bus"), SOURCES / "marta_bus_stops.geojson")
    print("\nDone. Now run:  python3 scripts/build_transit.py --all")


if __name__ == "__main__":
    main()
