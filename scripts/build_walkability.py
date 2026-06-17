"""
WALKABILITY — corridor / segment detail layer (zoom-in level).

NPU-LEVEL walkability already comes from data/cache/walkability_index.json
(sidewalk density per NPU, from Sidewalk_Summary.xlsx). This script adds the
SEGMENT level: it clips the real Atlanta sidewalk network (ATLSidewalk.geojson)
to each NPU so the planner can zoom in and see the actual sidewalks vs. gaps.

    data/cache/<npu-id>/sidewalks.geojson   (one per NPU)

------------------------------------------------------------------------------
SETUP (run locally — needs the sidewalk geojson + shapely):
  1. Put ATLSidewalk.geojson in  data/sources/   (any subfolder is fine)
  2. pip install shapely
  3. python3 scripts/build_walkability.py
Then the planner's "Walkability — corridor detail" toggle shows real sidewalks.
------------------------------------------------------------------------------
"""

import glob
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "data" / "sources"
BOUNDARIES = ROOT / "data" / "boundaries" / "atlanta_npus.geojson"
AREAS = ROOT / "data" / "areas.json"
CACHE = ROOT / "data" / "cache"


def main():
    try:
        from shapely.geometry import shape, mapping
        from shapely.prepared import prep
    except ImportError:
        raise SystemExit("shapely not installed. Run:  pip install shapely")

    found = [s for s in glob.glob(str(SOURCES / "**" / "*.geojson"), recursive=True)
             if "sidewalk" in s.lower()]
    if not found:
        raise SystemExit(f"No *sidewalk*.geojson found under {SOURCES}. "
                         "Put ATLSidewalk.geojson there.")
    print(f"Reading {Path(found[0]).name}")
    sidewalks = json.loads(Path(found[0]).read_text())["features"]

    # pre-shape every sidewalk feature once (+ its bounds for fast prefilter)
    feats = []
    for f in sidewalks:
        try:
            g = shape(f["geometry"])
        except Exception:
            continue
        feats.append((g, g.bounds, f.get("properties", {})))
    print(f"{len(feats)} sidewalk features loaded")

    npus = json.loads(BOUNDARIES.read_text())["features"]
    areas = {a["name"].split()[-1]: a["id"] for a in json.loads(AREAS.read_text())}

    for npu in npus:
        code = str(npu["properties"]["npu"]).upper()
        area_id = areas.get(code)
        if not area_id:
            continue
        poly = shape(npu["geometry"])
        pb = poly.bounds
        pgeom = prep(poly)
        out = []
        for g, b, props in feats:
            if b[2] < pb[0] or b[0] > pb[2] or b[3] < pb[1] or b[1] > pb[3]:
                continue  # bbox miss
            if pgeom.intersects(g):
                out.append({"type": "Feature", "geometry": mapping(g),
                            "properties": {"surface": props.get("surface", ""),
                                           "highway": props.get("highway", "")}})
        out_dir = CACHE / area_id
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "sidewalks.geojson").write_text(
            json.dumps({"type": "FeatureCollection", "features": out}))
        print(f"NPU {code}: {len(out)} sidewalk features -> data/cache/{area_id}/sidewalks.geojson")


if __name__ == "__main__":
    main()
