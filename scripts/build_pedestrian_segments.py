"""
PEDESTRIAN INFRASTRUCTURE — unified road-segment network for the PLANNER side.

Input: ATLNPU_Roads_with_Sidewalks.json (Esri JSON, esriGeometryPolyline).
Each road carries Sidewalk_Present (1 = a sidewalk exists within 15 ft of the
road centerline, 0 = none) plus name / type / Shape_Length.

This is the canonical SEGMENT network for the planner: each road gets several
normalized 0-100 scores so the segment view can colour by one and toggle to the
others on the very same lines:

    sidewalk : 100 if Sidewalk_Present==1 else 0   (pedestrian infrastructure)
    safety   : averaged from the nearby 10 m safety segments (crash+crime)
    overall  : mean of the available metrics above

Outputs:
    data/cache/<npu-id>/road_segments.geojson   (per NPU; the segment layer)
    data/cache/pedestrian_index.json            (NPU: % road length with sidewalk)

RUN (resumable per NPU — call until it prints "ALL DONE"):
    pip install shapely
    python3 scripts/build_pedestrian_segments.py --src /path/to/ATLNPU_Roads_with_Sidewalks.json
"""

import argparse
import glob
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "data" / "sources"
BOUNDARIES = ROOT / "data" / "boundaries" / "atlanta_npus.geojson"
AREAS = ROOT / "data" / "areas.json"
CACHE = ROOT / "data" / "cache"
JOIN_RADIUS = 0.00035   # ~30 m in degrees: how far to look for safety segments
COORD_PREC = 6


def find_src():
    cands = glob.glob(str(SOURCES / "**" / "*oad*idewalk*.json"), recursive=True) \
        + glob.glob(str(SOURCES / "**" / "*Roads_with_Sidewalks*.json"), recursive=True)
    return cands[0] if cands else None


def esri_to_geom(g):
    """Esri polyline {paths:[[[x,y]...]]} -> (geojson_geometry, sample_points)."""
    paths = (g or {}).get("paths") or []
    if not paths:
        return None, []
    if len(paths) == 1:
        geom = {"type": "LineString", "coordinates": paths[0]}
    else:
        geom = {"type": "MultiLineString", "coordinates": paths}
    p0 = paths[0]
    idx = sorted(set([0, len(p0) // 2, len(p0) - 1]))
    samples = [(p0[i][0], p0[i][1]) for i in idx]
    return geom, samples


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", help="path to ATLNPU_Roads_with_Sidewalks.json (Esri JSON)")
    ap.add_argument("--budget", type=float, default=34.0)
    ap.add_argument("--join-safety", action="store_true",
                    help="enrich existing road_segments with safety + blended overall (resumable)")
    args = ap.parse_args()

    npus = json.loads(BOUNDARIES.read_text())["features"]
    areas = {a["name"].split()[-1]: a["id"] for a in json.loads(AREAS.read_text())}
    codes = [str(n["properties"]["npu"]).upper() for n in npus]

    if args.join_safety:
        return join_safety(npus, areas, codes, args.budget)

    from shapely.geometry import shape, Point
    from shapely.strtree import STRtree

    src = args.src or find_src()
    if not src or not Path(src).exists():
        raise SystemExit("No roads-with-sidewalks json found. Pass --src ...")
    polys = [shape(n["geometry"]) for n in npus]

    # ---- vectorized assignment (25 polygon queries, not 84k point checks) ----
    print("Reading + assigning roads...")
    roads = json.loads(Path(src).read_text())["features"]
    parsed, mids = [], []
    for f in roads:
        geom, samples = esri_to_geom(f.get("geometry"))
        if not geom or not samples:
            continue
        a = f.get("attributes", {})
        try: oid = int(a.get("osm_id"))
        except (TypeError, ValueError): oid = None
        parsed.append({"geom": geom, "sw": 1 if a.get("Sidewalk_Present") == 1 else 0,
                       "name": (a.get("name") or "").strip(), "type": a.get("type") or "",
                       "len": a.get("Shape_Length") or 0.0, "osm": oid})
        m = samples[len(samples) // 2]
        mids.append(Point(m[0], m[1]))
    mtree = STRtree(mids)
    per_npu = {c: [] for c in codes}
    for pi, poly in enumerate(polys):
        for ri in mtree.query(poly, predicate="contains"):
            per_npu[codes[pi]].append(parsed[int(ri)])
    print(f"{sum(len(v) for v in per_npu.values()):,} of {len(parsed):,} roads assigned to NPUs")

    # canopy/comfort joined by osm_id (from build_comfort.py); preserve existing safety
    comfort = {}
    cl = CACHE / "comfort_lookup.json"
    if cl.exists():
        comfort = json.loads(cl.read_text()); print(f"comfort_lookup: {len(comfort):,} osm_ids")

    # ---- write per-NPU road_segments + pedestrian/comfort indices (resumable) ----
    ped_path = CACHE / "pedestrian_index.json"
    com_path = CACHE / "comfort_index.json"
    done_path = CACHE / "_ped_done.json"
    ped = json.loads(ped_path.read_text()) if ped_path.exists() else {}
    com = json.loads(com_path.read_text()) if com_path.exists() else {}
    done = set(json.loads(done_path.read_text())) if done_path.exists() else set()
    t0 = time.time()
    for code in codes:
        area_id = areas.get(code)
        if not area_id or code in done:
            continue
        if time.time() - t0 > args.budget:
            done_path.write_text(json.dumps(sorted(done)))
            print("budget hit — run again to continue.")
            return
        rds = per_npu[code]
        out_file = CACHE / area_id / "road_segments.geojson"
        # preserve any safety already computed (same deterministic order + count)
        old_safety = []
        if out_file.exists():
            try:
                of = json.loads(out_file.read_text())["features"]
                if len(of) == len(rds): old_safety = [x["properties"].get("safety") for x in of]
            except Exception: old_safety = []
        feats, sw_len, tot_len, can_sum, com_sum, can_n = [], 0.0, 0.0, 0.0, 0.0, 0
        for i, r in enumerate(rds):
            tot_len += r["len"]; sw_len += r["len"] if r["sw"] else 0
            sidewalk = 100 if r["sw"] else 0
            cinfo = comfort.get(str(r["osm"])) if r["osm"] is not None else None
            canopy = cinfo["canopy"] if cinfo else None
            comf = cinfo["comfort"] if cinfo else None
            if canopy is not None: can_sum += canopy; can_n += 1
            if comf is not None: com_sum += comf
            safety = old_safety[i] if i < len(old_safety) else None
            parts = [sidewalk] + ([safety] if safety is not None else []) + ([canopy] if canopy is not None else [])
            overall = round(sum(parts) / len(parts))
            feats.append({"type": "Feature", "geometry": r["geom"],
                "properties": {"overall": overall, "safety": safety, "sidewalk": sidewalk,
                               "sidewalk_present": r["sw"], "canopy": canopy, "comfort": comf,
                               "name": r["name"], "road_type": r["type"], "osm_id": r["osm"]}})
        (CACHE / area_id).mkdir(parents=True, exist_ok=True)
        out_file.write_text(json.dumps({"type": "FeatureCollection", "features": feats}, separators=(",", ":")))
        ped[code] = {"sidewalk_pct": round(100 * sw_len / tot_len) if tot_len else None,
                     "roads": len(rds), "sidewalk_roads": sum(1 for r in rds if r["sw"])}
        com[code] = {"canopy_pct": round(can_sum / can_n) if can_n else None,
                     "comfort": round(com_sum / can_n) if can_n else None}
        done.add(code)
        ped_path.write_text(json.dumps(ped, indent=2))
        com_path.write_text(json.dumps(com, indent=2))
        done_path.write_text(json.dumps(sorted(done)))
        print(f"NPU {code}: {len(feats):,} roads · {ped[code]['sidewalk_pct']}% sidewalk · canopy {com[code]['canopy_pct']}")
    print(f"Wrote pedestrian_index.json + comfort_index.json ({len(ped)} NPUs)")
    print("ALL DONE")


def join_safety(npus, areas, codes, budget):
    """Enrich each NPU's road_segments with a safety score sampled from the 10 m
    safety network, and recompute overall = mean(sidewalk, safety). Resumable:
    skips road_segments that already carry a non-null safety value."""
    import numpy as np
    from shapely.geometry import Point
    from shapely import points as shp_points
    from shapely.strtree import STRtree

    done_path = CACHE / "_ped_safety_done.json"
    done = set(json.loads(done_path.read_text())) if done_path.exists() else set()
    t0 = time.time()
    for code in codes:
        area_id = areas.get(code)
        if not area_id or code in done:
            continue
        rf = CACHE / area_id / "road_segments.geojson"
        sf = CACHE / area_id / "safety_segments.geojson"
        if not rf.exists():
            continue
        if time.time() - t0 > budget:
            print("budget hit — run again to continue.")
            done_path.write_text(json.dumps(sorted(done)))
            return
        roads = json.loads(rf.read_text())
        stree = None; saf_val = None
        if sf.exists():
            sfeats = json.loads(sf.read_text())["features"]
            if sfeats:
                coords = np.array([s["geometry"]["coordinates"][0] for s in sfeats], dtype=float)
                saf_val = np.array([(s["properties"].get("safety") if s["properties"].get("safety") is not None else np.nan)
                                    for s in sfeats], dtype=float)
                stree = STRtree(shp_points(coords))
        for f in roads["features"]:
            g = f["geometry"]; coords = g["coordinates"] if g["type"] == "LineString" else g["coordinates"][0]
            samp = [coords[0], coords[len(coords)//2], coords[-1]]
            safety = None
            if stree is not None:
                vals = []
                for sx, sy in samp:
                    for i in stree.query_nearest(Point(sx, sy), max_distance=JOIN_RADIUS, all_matches=True):
                        v = saf_val[int(i)]
                        if not np.isnan(v):
                            vals.append(v)
                if vals:
                    safety = round(sum(vals)/len(vals))
            f["properties"]["safety"] = safety
            sw = f["properties"]["sidewalk"]
            parts = [sw] + ([safety] if safety is not None else [])
            f["properties"]["overall"] = round(sum(parts)/len(parts))
        rf.write_text(json.dumps(roads))
        done.add(code)
        done_path.write_text(json.dumps(sorted(done)))
        n_saf = sum(1 for f in roads["features"] if f["properties"]["safety"] is not None)
        print(f"NPU {code}: safety joined to {n_saf:,}/{len(roads['features']):,} roads")
    print("ALL DONE (safety joined)")


if __name__ == "__main__":
    main()
