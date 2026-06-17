"""
SAFETY INDEX layer (one piece of the walkability index) for the PLANNER side.

Reads the per-NPU weighted safety index shapefile and writes a small lookup the
planner uses to color each NPU by its safety score:

    data/cache/safety_index.json   ->  { "E": {"safety_score": 72.4, "safety_norm": 81}, ... }

Only the attribute table is needed (one safety value per NPU), so no reprojection.

------------------------------------------------------------------------------
SETUP (run locally — the cloud sandbox is firewalled / out of space):

  1. Unzip the uploaded file into:  data/sources/safety/
     (so data/sources/safety/Atlanta_NPU_Safety_Index_Weighted.shp exists)
  2. pip install pyshp
  3. python3 scripts/build_safety.py
        # auto-detects the NPU + safety columns. If it guesses wrong:
        python3 scripts/build_safety.py --npu-field NAME --field SafetyIdx
        # if a HIGHER value means LESS safe (e.g. crime), add:  --invert
------------------------------------------------------------------------------
"""

import argparse
import glob
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "data" / "sources"
OUT = ROOT / "data" / "cache" / "safety_index.json"

NPU_CANDIDATES = ["NAME", "NPU", "NPU_NAME", "npu", "Name"]
SAFETY_HINTS = ["saf", "index", "idx", "score", "weight", "wgt", "crime"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--npu-field", help="column holding the NPU letter")
    ap.add_argument("--field", help="column holding the safety value")
    ap.add_argument("--invert", action="store_true",
                    help="use if a HIGHER value means LESS safe")
    args = ap.parse_args()

    try:
        import shapefile  # pyshp
    except ImportError:
        raise SystemExit("pyshp not installed. Run:  pip install pyshp")

    # find the safety shapefile anywhere under data/sources/ (any unzip folder name)
    all_shp = glob.glob(str(SOURCES / "**" / "*.shp"), recursive=True)
    safety_shp = [s for s in all_shp if "saf" in s.lower()]
    shp = safety_shp or all_shp
    if not shp:
        raise SystemExit(f"No .shp found under {SOURCES}. Unzip the safety file there first.")
    print(f"Reading {Path(shp[0]).name}")
    r = shapefile.Reader(shp[0])
    fields = [f[0] for f in r.fields[1:]]
    records = r.records()

    # find the NPU id column
    npu_field = args.npu_field or next((f for f in NPU_CANDIDATES if f in fields), None)
    if not npu_field:
        raise SystemExit(f"Couldn't find an NPU column. Fields are: {fields}\n"
                         "Re-run with --npu-field <name>.")

    # find the safety value column (first numeric field whose name hints at safety)
    safety_field = args.field
    if not safety_field:
        for f in fields:
            if f == npu_field:
                continue
            if any(h in f.lower() for h in SAFETY_HINTS):
                idx = fields.index(f)
                if all(isinstance(rec[idx], (int, float)) for rec in records[:5]):
                    safety_field = f
                    break
    if not safety_field:
        raise SystemExit(f"Couldn't guess the safety column. Fields are: {fields}\n"
                         "Re-run with --field <name>.")

    ni, si = fields.index(npu_field), fields.index(safety_field)
    raw = {}
    for rec in records:
        npu = str(rec[ni]).strip().upper().replace("NPU ", "")
        try:
            raw[npu] = float(rec[si])
        except (TypeError, ValueError):
            continue

    vals = list(raw.values())
    lo, hi = min(vals), max(vals)
    out = {}
    for npu, v in raw.items():
        norm = 50 if hi == lo else round(100 * (v - lo) / (hi - lo))
        if args.invert:
            norm = 100 - norm
        out[npu] = {"safety_score": round(v, 2), "safety_norm": norm}

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2))
    print(f"Using NPU column '{npu_field}', safety column '{safety_field}'"
          f"{' (inverted)' if args.invert else ''}.")
    print(f"Wrote {len(out)} NPUs -> data/cache/safety_index.json")
    print("Higher safety_norm = safer." if not args.invert else "Higher safety_norm = safer (inverted input).")


if __name__ == "__main__":
    main()
