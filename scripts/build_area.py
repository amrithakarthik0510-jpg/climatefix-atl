"""
Build ONE neighborhood's baseline from REAL data.

Pulls real street + sidewalk geometry from OpenStreetMap (via osmnx) for either:
  (a) an Atlanta NPU polygon you downloaded once, or
  (b) any place name OSM can geocode (e.g. "Adair Park, Atlanta, Georgia").

Output (the data contract — same shape the frontend already reads):
    data/cache/<id>/segments.geojson
Each feature is a real road/sidewalk LineString with the five 0-100 scores.

Right now the five scores are PLACEHOLDERS (deterministic per segment) so the
map renders. Analytics B replaces score_segments() with real heat/flood/walk/
green/equity values — the geometry and file shape stay identical.

------------------------------------------------------------------------------
RUN LOCALLY (network is open on your Mac; the cloud sandbox is firewalled):

  pip install -r requirements.txt

  # Easiest — real OSM data, no download needed:
  python3 scripts/build_area.py --place "Adair Park, Atlanta, Georgia" --id adair-park

  # By NPU (honors the NPU requirement) — needs the boundary file, see README:
  python3 scripts/build_area.py --npu V --id npu-v

Then it auto-adds the area to data/areas.json and you refresh the web page.
------------------------------------------------------------------------------
"""

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "cache"
AREAS = ROOT / "data" / "areas.json"
BOUNDARIES = ROOT / "data" / "boundaries"

# OSM highway values we treat as walking-relevant. Everything else is dropped.
ROAD_TYPES = {"primary", "secondary", "tertiary", "residential", "living_street",
              "unclassified", "service", "trunk", "road"}
WALK_TYPES = {"footway", "path", "pedestrian", "steps", "cycleway", "track"}


def get_osmnx():
    try:
        import osmnx as ox
    except ImportError:
        raise SystemExit("osmnx not installed. Run:  pip install -r requirements.txt")
    return ox


def geocode_polygon(ox, place):
    """Real boundary for a place name via OSM/Nominatim."""
    try:
        gdf = ox.geocode_to_gdf(place)
    except AttributeError:
        from osmnx import geocoder
        gdf = geocoder.geocode_to_gdf(place)
    return gdf.geometry.iloc[0]


def npu_polygon(npu_code):
    """
    Read a single Atlanta NPU polygon from a boundary file you downloaded once to
    data/boundaries/atlanta_npus.geojson  (see README for the one-time download).
    """
    f = BOUNDARIES / "atlanta_npus.geojson"
    if not f.exists():
        raise SystemExit(
            f"Missing {f}.\nDownload Atlanta NPU boundaries as GeoJSON (see README), "
            "save to that path, then re-run."
        )
    from shapely.geometry import shape
    data = json.loads(f.read_text())
    want = npu_code.strip().upper()
    for feat in data["features"]:
        props = {k.upper(): v for k, v in feat["properties"].items()}
        code = str(props.get("NPU") or props.get("NPU_NAME") or props.get("NAME") or "").strip().upper()
        if code == want or code == f"NPU {want}":
            return shape(feat["geometry"])
    raise SystemExit(f"NPU '{npu_code}' not found in {f.name}.")


def fetch_osm_segments(ox, poly):
    """Real roads + sidewalks inside the polygon, one feature per segment."""
    try:
        gdf = ox.features_from_polygon(poly, tags={"highway": True})
    except AttributeError:
        from osmnx import features
        gdf = features.features_from_polygon(poly, tags={"highway": True})

    gdf = gdf[gdf.geometry.type.isin(["LineString", "MultiLineString"])]
    gdf = gdf.explode(index_parts=False).reset_index(drop=True)

    feats = []
    for i, row in gdf.iterrows():
        hwy = row.get("highway")
        if isinstance(hwy, list):
            hwy = hwy[0]
        if hwy not in ROAD_TYPES and hwy not in WALK_TYPES:
            continue
        kind = "sidewalk" if hwy in WALK_TYPES else "road"
        coords = [[round(x, 6), round(y, 6)] for x, y in row.geometry.coords]
        if len(coords) < 2:
            continue
        sid = f"seg_{i:04d}"
        feats.append({
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": coords},
            "properties": {"segment_id": sid, "road_type": hwy, "kind": kind,
                           **score_segment(sid)},
        })
    return {"type": "FeatureCollection", "features": feats}


def score_segment(sid):
    """PLACEHOLDER scores, deterministic per segment id. Replace with real engine."""
    h = int(hashlib.md5(sid.encode()).hexdigest(), 16)
    def pick(shift, lo, hi):
        return lo + (h >> shift) % (hi - lo + 1)
    return {
        "walk_score": pick(0, 25, 90),
        "heat_risk": pick(8, 35, 95),
        "flood_risk": pick(16, 20, 90),
        "green_access": pick(24, 10, 85),
        "equity": pick(32, 30, 90),
    }


def update_areas(area_id, name, center, note):
    areas = json.loads(AREAS.read_text()) if AREAS.exists() else []
    areas = [a for a in areas if a["id"] != area_id]
    areas.append({"id": area_id, "name": name, "center": center, "zoom": 15, "note": note})
    AREAS.write_text(json.dumps(areas, indent=2))


def centroid_latlon(poly):
    c = poly.centroid
    return [round(c.y, 5), round(c.x, 5)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--place", help='e.g. "Adair Park, Atlanta, Georgia"')
    ap.add_argument("--npu", help="Atlanta NPU code, e.g. V")
    ap.add_argument("--id", required=True, help="short id, e.g. adair-park")
    ap.add_argument("--name", help="display name for the dropdown")
    args = ap.parse_args()

    ox = get_osmnx()
    if args.npu:
        poly = npu_polygon(args.npu)
        name = args.name or f"NPU {args.npu.upper()}"
        note = f"Atlanta NPU {args.npu.upper()} — real OSM streets + sidewalks"
    elif args.place:
        poly = geocode_polygon(ox, args.place)
        name = args.name or args.place.split(",")[0]
        note = f"{name} — real OSM streets + sidewalks"
    else:
        raise SystemExit("Pass either --place or --npu.")

    print(f"Pulling OSM roads + sidewalks for {name} ...")
    fc = fetch_osm_segments(ox, poly)
    out_dir = CACHE / args.id
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "segments.geojson").write_text(json.dumps(fc))
    update_areas(args.id, name, centroid_latlon(poly), note)
    print(f"Wrote {len(fc['features'])} real segments -> data/cache/{args.id}/segments.geojson")
    print(f"Added '{name}' to the dropdown. Refresh the web page.")


if __name__ == "__main__":
    main()
