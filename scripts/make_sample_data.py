"""
Generate placeholder baseline data for each neighborhood in data/areas.json.

This is a STUB that stands in for the real pipeline
(get_boundary -> fetch_osm/isochrone/heat/canopy/svi -> score_segments).
It writes one cached file per neighborhood:

    data/cache/<id>/segments.geojson

Each segment is a short LineString on a grid around the area center, carrying
the five baseline scores the rest of the app reads. Replace this with the real
pipeline output later — the OUTPUT SHAPE is the contract, not how it's made.

Run:  python scripts/make_sample_data.py
"""

import json
import math
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AREAS = ROOT / "data" / "areas.json"
CACHE = ROOT / "data" / "cache"

# meters -> degrees (approx, at Atlanta's latitude)
M_PER_DEG_LAT = 111_320.0


def m_per_deg_lon(lat):
    return 111_320.0 * math.cos(math.radians(lat))


def build_segments(area, n_rows=6, n_cols=6, spacing_m=90):
    """Lay a small street grid around the center and score each block face."""
    random.seed(area["id"])  # reproducible per neighborhood
    lat0, lon0 = area["center"]
    dlat = spacing_m / M_PER_DEG_LAT
    dlon = spacing_m / m_per_deg_lon(lat0)

    # bias the area's overall profile so neighborhoods look different
    bias = {
        "heat": random.randint(-10, 20),
        "flood": random.randint(-15, 20),
        "walk": random.randint(-15, 10),
    }

    features = []
    sid = 0
    # horizontal segments
    for r in range(n_rows):
        for c in range(n_cols - 1):
            lat = lat0 + (r - n_rows / 2) * dlat
            lon_a = lon0 + (c - n_cols / 2) * dlon
            lon_b = lon0 + (c + 1 - n_cols / 2) * dlon
            features.append(make_feature(sid, [[lon_a, lat], [lon_b, lat]], bias))
            sid += 1
    # vertical segments
    for c in range(n_cols):
        for r in range(n_rows - 1):
            lon = lon0 + (c - n_cols / 2) * dlon
            lat_a = lat0 + (r - n_rows / 2) * dlat
            lat_b = lat0 + (r + 1 - n_rows / 2) * dlat
            features.append(make_feature(sid, [[lon, lat_a], [lon, lat_b]], bias))
            sid += 1

    return {"type": "FeatureCollection", "features": features}


def clamp(v):
    return max(0, min(100, int(round(v))))


def make_feature(sid, coords, bias):
    walk = clamp(random.gauss(55 + bias["walk"], 18))
    heat = clamp(random.gauss(60 + bias["heat"], 16))
    flood = clamp(random.gauss(50 + bias["flood"], 18))
    green = clamp(random.gauss(45, 18))
    equity = clamp(random.gauss(58, 16))
    return {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": coords},
        "properties": {
            "segment_id": f"seg_{sid:03d}",
            "walk_score": walk,
            "heat_risk": heat,
            "flood_risk": flood,
            "green_access": green,
            "equity": equity,
        },
    }


def main():
    areas = json.loads(AREAS.read_text())
    for area in areas:
        fc = build_segments(area)
        out_dir = CACHE / area["id"]
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / "segments.geojson"
        out_file.write_text(json.dumps(fc))
        print(f"wrote {out_file.relative_to(ROOT)}  ({len(fc['features'])} segments)")


if __name__ == "__main__":
    main()
