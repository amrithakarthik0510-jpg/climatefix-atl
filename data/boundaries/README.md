# NPU boundaries

To build areas by Atlanta NPU, download the city's NPU boundaries once:

1. Go to Atlanta's open data portal (search **"Atlanta Neighborhood Planning Unit"**
   on data-atlantaga.opendata.arcgis.com or the ArcGIS Hub).
2. Download the layer as **GeoJSON**.
3. Save it here as:  `data/boundaries/atlanta_npus.geojson`

Then:

```bash
python3 scripts/build_area.py --npu V --id npu-v
```

If you'd rather skip the download for now, use a place name instead — no file needed:

```bash
python3 scripts/build_area.py --place "Adair Park, Atlanta, Georgia" --id adair-park
```
