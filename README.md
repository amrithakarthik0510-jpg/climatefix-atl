# ClimateFix ATL

Turn resident-reported street problems into data-backed climate resilience investment decisions.
**Loop:** Report → Map → Score → Simulate → Prioritize → Fix

This repo is at **step 1**: the NPU dropdown + map. Pick an Atlanta Neighborhood
Planning Unit (all 25, from the city's official boundaries) and the map draws that
NPU. Walkability layers (added by teammates) overlay on top when ready.

## Run it (2 steps, no Python packages needed)

The page reads local files, so it must be served over HTTP — opening the .html
directly will NOT work.

```bash
# 1. from the project folder, start a tiny web server:
cd climatefix-atl
python3 -m http.server 8000
```

Then, **leaving the server running**, open any of these pages in your browser
(use the `localhost` URL — NOT a `file://` path, which won't load the data):

| Page | URL |
|---|---|
| Map + NPU dropdown (step 1) | http://localhost:8000/frontend/index.html |
| Resident report mode | http://localhost:8000/frontend/resident.html |
| Planner / scenario mode | http://localhost:8000/frontend/planner.html |

On the map page, pick an NPU from the dropdown — its boundary draws and the map
zooms to it. The sidebar shows population + area, and a slot where walkability
layers appear.

## Add walkability layers (teammates, later — needs internet)

`build_area.py` pulls real road + sidewalk geometry from OpenStreetMap inside an
NPU and writes `data/cache/<id>/segments.geojson`. The map auto-overlays it when
that NPU is selected — no front-end changes needed.

```bash
pip install -r requirements.txt
python3 scripts/build_area.py --npu V --id npu-v     # uses data/boundaries/atlanta_npus.geojson
```

`scripts/make_sample_data.py` still exists as an offline fallback (fake grid) if you
have no network — but prefer `build_area.py` for the real thing.

## Layout

```
data/
  areas.json                     # dropdown manifest (id, name, center, zoom, note)
  cache/<id>/segments.geojson    # baseline "current twin" per neighborhood  <-- THE base export
scripts/
  make_sample_data.py            # stub pipeline -> writes cache/<id>/segments.geojson
frontend/
  index.html                     # Leaflet map + dropdown (step 1)
  resident.html                  # resident report mode
  planner.html                   # planner / scenario mode
```

## How a neighborhood is added

1. Add an entry to `data/areas.json` (`id`, `name`, `center`, `zoom`, `note`).
2. Produce `data/cache/<id>/segments.geojson` for it — for now via
   `make_sample_data.py`; later via the real pipeline
   (`get_boundary` → `fetch_osm`/isochrone/heat/canopy/svi → `score_segments`).
3. It appears in the dropdown automatically. No code changes, no hand-drawn boundaries.

## Data contract (frozen — everyone builds against this)

Each segment in `segments.geojson` carries geometry + five 0–100 scores:

| field | meaning |
|---|---|
| `segment_id` | stable id |
| `walk_score` | walkability |
| `heat_risk` | urban heat exposure |
| `flood_risk` | stormwater / runoff risk |
| `green_access` | tree canopy / green space access |
| `equity` | social vulnerability (SVI) |

## Next steps

- Real pipeline writing the same `segments.geojson` shape (Analytics A).
- FastAPI + SQLite backend: `/areas`, `/complaints`, `/synthesize`, `/simulate` (Analytics B).
- Report mode (complaint form) + Plan mode (hotspots, scenario sliders, report) (Planning D).
