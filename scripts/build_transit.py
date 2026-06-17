"""
TRANSIT ACCESSIBILITY layer (one piece of the walkability index).

Method follows the MARTA 0.5-mile walkshed study + EPA's transit-proximity
variable (D4a): a stop is "accessible" within a 0.5-mile walk. RAIL is weighted
higher than BUS, because transit-accessibility indices (e.g. TfL's PTAL) and the
"rail bias" literature consistently value fixed rail above bus for its higher
frequency, capacity, permanence, and documented ridership / property-value
premium. Default weights: rail 2, bus 1 (configurable below).

For one NPU this writes:
    data/cache/<id>/transit.geojson
  - dissolved 0.5-mile walkshed polygon (kind: "walkshed")
  - every stop, tagged mode = rail | bus  (kind: "stop")
  - properties: rail_coverage_pct, coverage_pct (any stop), counts, transit_index
And if a segments file already exists it writes a 0-100 `transit_score` onto each
segment = the rail/bus-weighted distance-decay to the nearest stops (the index).

------------------------------------------------------------------------------
SOURCE FILES (save locally — the sandbox is firewalled):
  RAIL: data/sources/marta_stops.geojson         (already included: 38 stations)
  BUS : data/sources/marta_bus_stops.geojson  OR  marta_bus_stops.txt (GTFS)
        -> MARTA GTFS stops.txt, or a MARTA bus-stops point layer.
At least RAIL is required; BUS is optional (added when you have it).

RUN:
  pip install shapely pyproj
  python3 scripts/build_transit.py --all          # every NPU at once
  python3 scripts/build_transit.py --npu V --id npu-v   # one NPU
------------------------------------------------------------------------------
"""

import argparse
import csv
import json
from pathlib import Path

from pyproj import Transformer
from shapely.geometry import shape, mapping, Point
from shapely.ops import transform as shp_transform, unary_union

ROOT = Path(__file__).resolve().parents[1]
BOUNDARIES = ROOT / "data" / "boundaries" / "atlanta_npus.geojson"
SOURCES = ROOT / "data" / "sources"
CACHE = ROOT / "data" / "cache"

HALF_MILE_FT = 2640.0          # 0.5 mi in US survey feet
WALK_LIMIT_MI = 1.0            # access score decays to 0 at 1 mile
MODE_WEIGHT = {"rail": 2.0, "bus": 1.0}   # rail weighted 2x bus (PTAL convention)

TO_FT = Transformer.from_crs("EPSG:4326", "EPSG:2240", always_xy=True).transform
TO_LL = Transformer.from_crs("EPSG:2240", "EPSG:4326", always_xy=True).transform


def npu_polygon(code):
    data = json.loads(BOUNDARIES.read_text())
    want = code.strip().upper()
    for f in data["features"]:
        if str(f["properties"].get("npu", "")).strip().upper() == want:
            return shape(f["geometry"])
    raise SystemExit(f"NPU '{code}' not found in {BOUNDARIES.name}")


def _read_points(path, mode):
    out = []
    if path.suffix == ".geojson":
        for f in json.loads(path.read_text())["features"]:
            if f["geometry"]["type"] != "Point":
                continue
            lon, lat = f["geometry"]["coordinates"][:2]
            p = f.get("properties", {})
            name = p.get("stop_name") or p.get("STATION") or p.get("NAME") or p.get("name") or f"{mode} stop"
            out.append((lat, lon, name, mode))
    else:  # GTFS stops.txt (CSV)
        with open(path, newline="") as fh:
            for row in csv.DictReader(fh):
                try:
                    out.append((float(row["stop_lat"]), float(row["stop_lon"]),
                                row.get("stop_name", f"{mode} stop"), mode))
                except (KeyError, ValueError):
                    continue
    return out


def load_stops():
    """Load rail (required) + bus (optional), each tagged with its mode."""
    stops = []
    rail = SOURCES / "marta_stops.geojson"
    if rail.exists():
        stops += _read_points(rail, "rail")
    for cand in ("marta_bus_stops.geojson", "marta_bus_stops.txt"):
        bus = SOURCES / cand
        if bus.exists():
            stops += _read_points(bus, "bus")
            break
    if not stops:
        raise SystemExit(f"No stop files found in {SOURCES}. Need at least marta_stops.geojson.")
    return stops


def decay(dist_ft):
    """1.0 at the stop, 0.0 at 1 mile."""
    return max(0.0, 1 - (dist_ft / 5280.0) / WALK_LIMIT_MI)


def weighted_score(rail_d_ft, bus_d_ft, have_bus):
    """Rail/bus-weighted 0-100 access score for a point."""
    num = MODE_WEIGHT["rail"] * decay(rail_d_ft)
    den = MODE_WEIGHT["rail"]
    if have_bus:
        num += MODE_WEIGHT["bus"] * decay(bus_d_ft)
        den += MODE_WEIGHT["bus"]
    return round(100 * num / den)


def coverage_pct(stops_ft, npu_ft):
    if not stops_ft:
        return 0.0
    shed = unary_union([p.buffer(HALF_MILE_FT) for p in stops_ft])
    return round(100 * shed.intersection(npu_ft).area / npu_ft.area, 1)


def build_one(npu_code, area_id, all_stops):
    npu_ll = npu_polygon(npu_code)
    npu_ft = shp_transform(TO_FT, npu_ll)
    search = npu_ft.buffer(HALF_MILE_FT)

    # Stops in the SEARCH area (NPU + 0.5-mi margin) drive the walkshed, so the
    # coverage isn't cut off at the border. But only stops INSIDE the NPU are
    # counted and plotted (no floating markers, no inflated counts).
    rail_ft, bus_ft, stop_feats = [], [], []
    rail_in = bus_in = 0
    for lat, lon, name, mode in all_stops:
        p_ft = shp_transform(TO_FT, Point(lon, lat))
        if not search.contains(p_ft):
            continue
        (rail_ft if mode == "rail" else bus_ft).append(p_ft)
        if npu_ft.contains(p_ft):                       # inside NPU only
            if mode == "rail":
                rail_in += 1
            else:
                bus_in += 1
            stop_feats.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [round(lon, 6), round(lat, 6)]},
                "properties": {"kind": "stop", "name": name, "mode": mode},
            })

    have_bus = len(bus_ft) > 0
    all_ft = rail_ft + bus_ft
    rail_cov = coverage_pct(rail_ft, npu_ft)
    any_cov = coverage_pct(all_ft, npu_ft)

    # served area (within 0.5-mi walk) + the gap (rest of the NPU)
    walk_feat = []
    if all_ft:
        shed = unary_union([p.buffer(HALF_MILE_FT) for p in all_ft])
        served = shed.intersection(npu_ft)
        gap = npu_ft.difference(shed)
        walk_feat.append({
            "type": "Feature", "geometry": mapping(shp_transform(TO_LL, served)),
            "properties": {"kind": "walkshed", "buffer_mi": 0.5},
        })
        if not gap.is_empty:
            walk_feat.append({
                "type": "Feature", "geometry": mapping(shp_transform(TO_LL, gap)),
                "properties": {"kind": "gap"},
            })

    # area-level transit index: rail/bus-weighted coverage
    den = MODE_WEIGHT["rail"] + (MODE_WEIGHT["bus"] if have_bus else 0)
    idx = round((MODE_WEIGHT["rail"] * rail_cov +
                 (MODE_WEIGHT["bus"] * any_cov if have_bus else 0)) / den)

    out_dir = CACHE / area_id
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "transit.geojson").write_text(json.dumps({
        "type": "FeatureCollection", "features": walk_feat + stop_feats,
        "properties": {
            "coverage_pct": any_cov, "rail_coverage_pct": rail_cov,
            "stop_count": rail_in + bus_in, "rail_stop_count": rail_in,
            "bus_stop_count": bus_in, "transit_index": idx,
            "weights": MODE_WEIGHT,
        }}))
    print(f"NPU {npu_code}: {rail_in} rail + {bus_in} bus inside | "
          f"rail {rail_cov}% / any {any_cov}% within 0.5 mi | index {idx} "
          f"-> data/cache/{area_id}/transit.geojson")

    # index contribution: per-segment transit_score (if segments exist)
    seg_file = out_dir / "segments.geojson"
    if seg_file.exists() and all_ft:
        seg = json.loads(seg_file.read_text())
        for f in seg["features"]:
            c = f["geometry"]["coordinates"]
            mid = c[len(c) // 2]
            p_ft = shp_transform(TO_FT, Point(mid[0], mid[1]))
            rd = min((p_ft.distance(s) for s in rail_ft), default=9e9)
            bd = min((p_ft.distance(s) for s in bus_ft), default=9e9)
            f["properties"]["transit_score"] = weighted_score(rd, bd, have_bus)
        seg_file.write_text(json.dumps(seg))
        print(f"  added transit_score to {len(seg['features'])} segments.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="build every NPU in areas.json")
    ap.add_argument("--npu", help="NPU code, e.g. V")
    ap.add_argument("--id", help="area id, e.g. npu-v")
    args = ap.parse_args()

    stops = load_stops()
    n_rail = sum(1 for s in stops if s[3] == "rail")
    n_bus = len(stops) - n_rail
    print(f"Loaded {n_rail} rail + {n_bus} bus stops. Weights: {MODE_WEIGHT}\n")

    if args.all:
        for a in json.loads((ROOT / "data" / "areas.json").read_text()):
            build_one(a["name"].split()[-1], a["id"], stops)
    elif args.npu and args.id:
        build_one(args.npu, args.id, stops)
    else:
        raise SystemExit("Pass --all, or both --npu and --id.")


if __name__ == "__main__":
    main()
