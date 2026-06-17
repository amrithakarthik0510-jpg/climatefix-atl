"""
SAFETY — segment/corridor detail layer + network-derived NPU roll-up (PLANNER side).

Mirrors build_walkability.py (which clips sidewalks per NPU), but for the
crime+crash road-safety network (Chopped_Road_Network_Safety / Safety.geojson).
Every feature is a ~10 m road segment carrying:
    segment_safety_index  (0-100, HIGHER = SAFER)  weighted_crime  crash_count

It produces TWO things:

1. SEGMENT LEVEL (analyze street by street):
       data/cache/<npu-id>/safety_segments.geojson   (one per NPU)
   Each 10 m segment is kept individually with its exact score so the planner
   can click any segment. The frontend renders these on a Leaflet canvas layer.

2. NPU LEVEL (roll-up of the same network — kept SEPARATE from the existing
   weighted safety_index.json so the two sources can be compared):
       data/cache/safety_network_index.json
   { "E": {"safety_score": 71.4, "safety_norm": 71, "crashes": 1820,
            "weighted_crime": 540.2, "km": 412.6, "segments": 41203}, ... }
   safety_score = length-weighted mean of segment_safety_index (0-100).

------------------------------------------------------------------------------
WHY a custom parser: Safety.geojson is ~1.3 GB / ~3.9 M features — too big to
json.load(). The file stores one Feature per line, so we stream line-by-line
and spatial-join each segment's first vertex to its NPU with a shapely STRtree.
(Falls back to ijson if the one-feature-per-line assumption ever breaks.)

RUN (resumable — call repeatedly until it prints "ALL DONE"):
    pip install shapely
    python3 scripts/build_safety_segments.py --src /path/to/Safety.geojson
    # Each call streams a time-budgeted chunk (default 38 s, under any 45 s cap),
    # checkpoints a byte offset + running aggregates, and resumes where it left
    # off. When it reaches EOF it auto-finalizes the per-NPU geojson + index.
    # auto-detects data/sources/**/*afety*.geojson if --src is omitted.
------------------------------------------------------------------------------
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
TMP = CACHE / "_tmp_safety_segments"   # overridable with --tmp (use a writable scratch dir)
STATE = None  # set in main() once TMP is finalized
COORD_PREC = 6  # ~0.1 m, plenty for 10 m segments
FEAT_PREFIXES = (b'{ "type": "Feature"', b'{"type": "Feature"')

# NOTE: the source `segment_safety_index` field is degenerate — 99.95% of
# segments are exactly 100, so it carries no signal. The real safety signal is
# weighted_crime + crash_count. We therefore score safety ourselves from those:
#   segment risk = crash_count + weighted_crime  (incident load on the segment)
#   segment safety = 100 * (1 - min(risk / RISK_CAP, 1))   (HIGHER = SAFER)
# RISK_CAP = 80 is the ~95th percentile of segment risk across the Atlanta NPU
# network, so the top ~5% most-incident-heavy segments saturate at 0 (red) and
# outliers (max ~3000) don't flatten the rest of the scale.
RISK_CAP = 80.0


def seg_safety(crash, crime):
    risk = (crash or 0.0) + (crime or 0.0)
    return round(100 * (1 - min(risk / RISK_CAP, 1.0)))


def find_src():
    cands = [s for s in glob.glob(str(SOURCES / "**" / "*.geojson"), recursive=True)
             if "afety" in Path(s).name.lower() or "road_network" in s.lower()]
    return cands[0] if cands else None


def load_state():
    if STATE.exists():
        return json.loads(STATE.read_text())
    return None


def save_state(st):
    STATE.write_text(json.dumps(st))


def build_index(codes, areas, agg):
    """NPU safety = incident DENSITY (crash+crime per km) normalized across the
    25 NPUs and inverted so HIGHER = SAFER."""
    valid = {c: agg[c] for c in codes if areas.get(c) and agg.get(c, {}).get("sum_len", 0)}
    dens = {c: (a["crashes"] + a["crime"]) / (a["sum_len"] / 1000) for c, a in valid.items()}
    lo, hi = (min(dens.values()), max(dens.values())) if dens else (0, 1)
    index = {}
    for code in codes:
        if not areas.get(code):
            continue
        a = agg.get(code, {})
        km = a.get("sum_len", 0.0) / 1000
        if not km:
            index[code] = {"safety_score": None, "safety_norm": None, "crashes": 0,
                           "weighted_crime": 0.0, "km": 0.0, "risk_per_km": None,
                           "segments": 0}
            continue
        rd = dens[code]
        norm = 50 if hi == lo else round(100 * (1 - (rd - lo) / (hi - lo)))
        index[code] = {
            "safety_score": norm,
            "safety_norm": norm,
            "crashes": round(a["crashes"]),
            "weighted_crime": round(a["crime"], 1),
            "km": round(km, 1),
            "risk_per_km": round(rd, 1),
            "segments": a.get("segments", 0),
        }
    return index


def finalize(codes, areas, agg, budget=38.0):
    """Build per-NPU segment geojson (segment safety scored from crash+crime) +
    the network roll-up index. Resumable/budgeted via a progress marker so it
    can be called repeatedly under a wall-clock cap."""
    done_file = TMP / "_fin_done.json"
    done = set(json.loads(done_file.read_text())) if done_file.exists() else set()
    t0 = time.time()
    for code in codes:
        area_id = areas.get(code)
        if not area_id or code in done:
            continue
        if time.time() - t0 > budget:
            print("finalize: budget hit — run again to continue.")
            return
        out_dir = CACHE / area_id
        out_dir.mkdir(parents=True, exist_ok=True)
        feats = []
        jf = TMP / f"{code}.jsonl"
        if jf.exists():
            with open(jf) as fh:
                for line in fh:
                    r = json.loads(line)
                    feats.append({
                        "type": "Feature",
                        "geometry": {"type": "LineString", "coordinates": r["g"]},
                        "properties": {"safety": seg_safety(r["c"], r["w"]),
                                       "crash_count": r["c"], "weighted_crime": r["w"],
                                       "length_m": r["L"]},
                    })
        (out_dir / "safety_segments.geojson").write_text(
            json.dumps({"type": "FeatureCollection", "features": feats}))
        done.add(code)
        done_file.write_text(json.dumps(sorted(done)))
        print(f"NPU {code}: {len(feats):,} segments -> data/cache/{area_id}/safety_segments.geojson")

    # all per-NPU files written -> write index + clean up
    (CACHE / "safety_network_index.json").write_text(
        json.dumps(build_index(codes, areas, agg), indent=2))
    print("Wrote data/cache/safety_network_index.json")
    for code in codes:
        try:
            (TMP / f"{code}.jsonl").unlink()
        except OSError:
            pass  # scratch temp; cleared between sessions if delete is restricted
    try:
        STATE.unlink()
    except OSError:
        pass
    try:
        TMP.rmdir()
    except OSError:
        pass
    print("ALL DONE")


def safety_band(s):
    """0..4 band from a 0-100 safety score (matches the frontend colour ramp)."""
    return min(int((s or 0) // 20), 4)


def build_corridors(codes, areas, budget=38.0):
    """Default street view: dissolve each NPU's 10 m segments into corridors that
    share a safety band, so the planner gets a light safe->unsafe heatmap.
    Reads the per-NPU safety_segments.geojson already on disk. Resumable."""
    from shapely.geometry import shape, mapping
    from shapely.ops import linemerge

    t0 = time.time()
    for code in codes:
        area_id = areas.get(code)
        if not area_id:
            continue
        out_dir = CACHE / area_id
        seg_file = out_dir / "safety_segments.geojson"
        cor_file = out_dir / "safety_corridors.geojson"
        if cor_file.exists() or not seg_file.exists():
            continue
        if time.time() - t0 > budget:
            print("corridors: budget hit — run again to continue.")
            return
        segs = json.loads(seg_file.read_text())["features"]
        bands = {}  # band -> {geoms, crashes, crime, len, n}
        for f in segs:
            p = f["properties"]
            b = safety_band(p.get("safety"))
            d = bands.setdefault(b, {"geoms": [], "crashes": 0.0, "crime": 0.0,
                                     "len": 0.0, "n": 0})
            d["geoms"].append(shape(f["geometry"]))
            d["crashes"] += p.get("crash_count", 0) or 0
            d["crime"] += p.get("weighted_crime", 0) or 0
            d["len"] += p.get("length_m", 0) or 0
            d["n"] += 1
        feats = []
        for b in sorted(bands):
            d = bands[b]
            merged = linemerge(d["geoms"])
            feats.append({
                "type": "Feature",
                "geometry": mapping(merged),
                "properties": {
                    "band": b, "safety_lo": b * 20, "safety_hi": b * 20 + 19,
                    "segments": d["n"], "crashes": round(d["crashes"]),
                    "weighted_crime": round(d["crime"], 1),
                    "km": round(d["len"] / 1000, 1),
                },
            })
        cor_file.write_text(json.dumps({"type": "FeatureCollection", "features": feats}))
        print(f"NPU {code}: {len(segs):,} segs -> {len(feats)} corridor bands "
              f"-> data/cache/{area_id}/safety_corridors.geojson")
    print("CORRIDORS DONE")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", help="path to the safety road-network geojson")
    ap.add_argument("--budget", type=float, default=38.0,
                    help="seconds to stream per call before checkpointing")
    ap.add_argument("--tmp", help="writable scratch dir for checkpoint + temp jsonl")
    ap.add_argument("--corridors", action="store_true",
                    help="dissolve existing per-NPU segment files into corridor bands")
    args = ap.parse_args()

    global TMP, STATE
    if args.tmp:
        TMP = Path(args.tmp)
    STATE = TMP / "_state.json"

    npus = json.loads(BOUNDARIES.read_text())["features"]
    areas = {a["name"].split()[-1]: a["id"] for a in json.loads(AREAS.read_text())}
    codes = [str(n["properties"]["npu"]).upper() for n in npus]

    if args.corridors:
        build_corridors(codes, areas, budget=args.budget)
        return

    from shapely.geometry import shape, Point
    from shapely.strtree import STRtree
    from shapely.prepared import prep

    src = args.src or find_src()
    if not src or not Path(src).exists():
        raise SystemExit("No safety geojson found. Pass --src /path/to/Safety.geojson")

    # --- NPU polygons + spatial index ---
    npus = json.loads(BOUNDARIES.read_text())["features"]
    areas = {a["name"].split()[-1]: a["id"] for a in json.loads(AREAS.read_text())}
    geoms, codes, prepped = [], [], []
    for npu in npus:
        code = str(npu["properties"]["npu"]).upper()
        geoms.append(shape(npu["geometry"]))
        codes.append(code)
        prepped.append(prep(geoms[-1]))
    tree = STRtree(geoms)

    # --- resume state ---
    TMP.mkdir(parents=True, exist_ok=True)
    st = load_state()
    if st is None:
        st = {"offset": 0, "seen": 0, "matched": 0, "outside": 0, "done": False,
              "agg": {c: {"sum_len": 0.0, "sum_li": 0.0, "crashes": 0.0,
                          "crime": 0.0, "segments": 0} for c in codes}}
        for c in codes:                       # truncate any partial temp files
            open(TMP / f"{c}.jsonl", "w").close()
    agg = st["agg"]

    if st["done"]:
        finalize(codes, areas, agg)
        return

    writers = {c: open(TMP / f"{c}.jsonl", "a") for c in codes}
    f = open(src, "rb")
    f.seek(st["offset"])
    t0 = time.time()
    seen = matched = outside = 0
    while time.time() - t0 < args.budget:
        line = f.readline()
        if not line:
            st["done"] = True
            break
        ls = line.lstrip()
        if not ls.startswith(FEAT_PREFIXES):
            continue
        if ls.rstrip().endswith(b","):
            ls = ls.rstrip()[:-1]
        try:
            feat = json.loads(ls)
        except json.JSONDecodeError:
            continue
        seen += 1
        coords = (feat.get("geometry") or {}).get("coordinates") or []
        if not coords:
            continue
        pt = Point(coords[0][0], coords[0][1])
        code = None
        for i in tree.query(pt):
            if prepped[int(i)].contains(pt):
                code = codes[int(i)]
                break
        if code is None:
            outside += 1
            continue
        matched += 1
        p = feat["properties"]
        s = p.get("segment_safety_index")
        L = p.get("segment_length_m") or 0.0
        cr = p.get("crash_count") or 0.0
        wc = p.get("weighted_crime") or 0.0
        a = agg[code]
        a["segments"] += 1
        a["sum_len"] += L
        if s is not None:
            a["sum_li"] += L * float(s)
        a["crashes"] += cr
        a["crime"] += wc
        rc = [[round(c[0], COORD_PREC), round(c[1], COORD_PREC)] for c in coords]
        writers[code].write(json.dumps(
            {"s": None if s is None else round(float(s), 1), "c": round(float(cr), 1),
             "w": round(float(wc), 2), "L": round(float(L), 1), "g": rc}) + "\n")

    st["offset"] = f.tell()
    st["seen"] += seen
    st["matched"] += matched
    st["outside"] += outside
    for w in writers.values():
        w.close()
    f.close()
    save_state(st)
    print(f"chunk: +{seen:,} read · +{matched:,} matched · +{outside:,} outside "
          f"· {time.time()-t0:.0f}s | total {st['seen']:,} read, "
          f"{st['matched']:,} matched, offset {st['offset']:,}")

    if st["done"]:
        finalize(codes, areas, agg)
    else:
        print("NOT DONE — run again to continue.")


if __name__ == "__main__":
    main()
