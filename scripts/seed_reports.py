"""
Seed realistic demo resident reports so the planner Feedback view is populated.
Merges into data/reports/reports.geojson (keeps any existing reports).
Points are jittered around each NPU centre from areas.json.

RUN:  python3 scripts/seed_reports.py
"""
import json, uuid, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AREAS = json.loads((ROOT / "data" / "areas.json").read_text())
CATS = json.loads((ROOT / "data" / "report_categories.json").read_text())
OUT = ROOT / "data" / "reports" / "reports.geojson"

metric = {c["id"]: c["index_metric"] for c in CATS["categories"]}
center = {a["name"].split()[-1]: a["center"] for a in AREAS}  # code -> [lat, lng]

# (npu, category, severity, time, user, text, day, lat_jit, lng_jit)
SEED = [
 ("V","no_sidewalk","high","daytime","resident","No sidewalk on this stretch — I have to walk in the road with my kids.",1,0.004,-0.006),
 ("V","feels_unsafe","high","night","resident","Feels really unsafe walking here after dark, no one around.",2,-0.005,0.004),
 ("V","poor_lighting","medium","night","student","Streetlights are out, it's pitch black by the station.",2,0.002,0.007),
 ("V","bus_no_shelter","medium","daytime","rider","Bus stop has no shelter — brutal in the heat and rain.",3,-0.003,-0.003),
 ("V","needs_crosswalk","high","daytime","senior","No safe place to cross Peachtree here, cars don't stop.",4,0.006,0.002),
 ("E","floods_after_rain","high","after_rain","resident","Floods every time it rains, the whole corner is underwater.",1,0.004,-0.004),
 ("E","broken_sidewalk","medium","daytime","disability","Sidewalk is cracked and uneven, my wheelchair can't pass.",2,-0.004,0.005),
 ("E","speeding_traffic","high","daytime","resident","Cars speed down this road constantly, scary for kids.",3,0.003,0.006),
 ("E","no_shade","medium","daytime","senior","No trees at all, no shade the entire walk to the store.",5,-0.006,-0.002),
 ("A","too_hot","medium","daytime","resident","Too hot to walk midday — zero shade anywhere.",1,0.005,0.003),
 ("A","crosswalk_faded","low","daytime","resident","The crosswalk paint is completely faded, drivers ignore it.",3,-0.003,-0.005),
 ("A","lacking_benches","low","daytime","senior","Nowhere to sit and rest while waiting for the bus.",4,0.002,0.004),
 ("M","feels_unsafe","high","night","student","Underpass feels dangerous at night, would never walk it alone.",1,0.003,-0.004),
 ("M","trash_dumping","medium","daytime","resident","Constant illegal dumping on this corner, attracts rats.",2,-0.004,0.003),
 ("M","needs_ped_signal","high","daytime","resident","Crossing here needs a pedestrian light, six lanes of traffic.",4,0.005,0.005),
 ("R","no_sidewalk","high","daytime","resident","There is literally no sidewalk in this whole area.",1,0.006,-0.003),
 ("R","poor_drainage","medium","after_rain","resident","Standing water sits here for days after any rain.",3,-0.005,0.004),
 ("R","no_shade","high","daytime","senior","Walking to the bus in summer is miserable, no canopy at all.",5,0.003,0.006),
]

fc = {"type": "FeatureCollection", "features": []}
if OUT.exists():
    try: fc = json.loads(OUT.read_text())
    except Exception: pass
existing_texts = {f["properties"].get("text") for f in fc["features"]}

base = datetime.datetime(2026, 6, 16, 9, 0, 0)
added = 0
for npu, cat, sev, tc, ut, text, day, dlat, dlng in SEED:
    if text in existing_texts:  # idempotent
        continue
    c = center.get(npu)
    if not c:
        continue
    lat, lng = c[0] + dlat, c[1] + dlng
    fc["features"].append({
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [round(lng, 6), round(lat, 6)]},
        "properties": {
            "id": uuid.uuid4().hex[:8], "npu": npu, "category": cat,
            "index_metric": metric.get(cat), "severity": sev, "time_context": tc,
            "user_type": ut, "text": text,
            "created_at": (base - datetime.timedelta(days=day)).isoformat(timespec="seconds"),
        },
    })
    added += 1

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(fc, indent=2))
print(f"added {added} reports; total now {len(fc['features'])}")
import collections
print("by npu:", dict(collections.Counter(f["properties"]["npu"] for f in fc["features"])))
