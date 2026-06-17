"""
ClimateFix ATL local server.

Replaces `python3 -m http.server`. It serves the site AND saves resident reports
(a plain file server can't save anything). Pure standard library — no installs.

RUN:
    python3 scripts/server.py
    # then open http://localhost:8000/frontend/

Endpoints:
    POST /api/report          body: {lat,lng,npu,category,severity,time_context,user_type,text}
                              -> appends a GeoJSON point to data/reports/reports.geojson
    GET  /api/reports         -> all reports (GeoJSON)
    GET  /api/reports?npu=V   -> reports for one NPU
Everything else is served as a static file from the project root.
"""

import datetime
import http.server
import json
import socketserver
import urllib.parse
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "data" / "reports" / "reports.geojson"
CATEGORIES = ROOT / "data" / "report_categories.json"
PORT = 8000


def category_to_metric():
    """Map each report category id -> the walkability-index metric it informs."""
    try:
        cats = json.loads(CATEGORIES.read_text())["categories"]
        return {c["id"]: c.get("index_metric") for c in cats}
    except Exception:
        return {}


def load_reports():
    if REPORTS.exists():
        return json.loads(REPORTS.read_text())
    return {"type": "FeatureCollection", "features": []}


def save_reports(fc):
    REPORTS.parent.mkdir(parents=True, exist_ok=True)
    REPORTS.write_text(json.dumps(fc, indent=2))


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(ROOT), **k)

    def _send_json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if urllib.parse.urlparse(self.path).path == "/api/reports":
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            fc = load_reports()
            npu = qs.get("npu", [None])[0]
            if npu:
                fc = {"type": "FeatureCollection",
                      "features": [f for f in fc["features"]
                                   if f["properties"].get("npu") == npu]}
            return self._send_json(fc)
        return super().do_GET()

    def do_POST(self):
        if self.path != "/api/report":
            return self.send_error(404)
        length = int(self.headers.get("Content-Length", 0))
        try:
            data = json.loads(self.rfile.read(length).decode())
        except Exception:
            return self._send_json({"error": "invalid JSON"}, 400)

        lat, lng = data.get("lat"), data.get("lng")
        if lat is None or lng is None:
            return self._send_json({"error": "lat and lng are required"}, 400)

        category = data.get("category")
        feature = {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lng, lat]},
            "properties": {
                "id": uuid.uuid4().hex[:8],
                "npu": data.get("npu"),
                "category": category,
                "index_metric": category_to_metric().get(category),  # links report -> index
                "severity": data.get("severity", "medium"),
                "time_context": data.get("time_context"),
                "user_type": data.get("user_type"),
                "text": (data.get("text") or "").strip(),
                "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
            },
        }
        fc = load_reports()
        fc["features"].append(feature)
        save_reports(fc)
        print(f"  + report {feature['properties']['id']} "
              f"({feature['properties']['category']}) in NPU {feature['properties']['npu']}")
        return self._send_json({"ok": True, "id": feature["properties"]["id"]})


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    try:
        httpd = Server(("", PORT), Handler)
    except OSError as e:
        print("\n" + "=" * 60)
        print(f"  Could not start — port {PORT} is already in use.")
        print("  Another server/Terminal is probably still running.")
        print("  Close it (or close all Terminal windows) and try again.")
        print("=" * 60)
        raise SystemExit(1)
    print("\n" + "=" * 60)
    print("  ClimateFix ATL is RUNNING. ✅  Leave this window open.")
    print(f"  Open in your browser:  http://localhost:{PORT}/frontend/index.html")
    print("  Press Ctrl+C here to stop.")
    print("=" * 60 + "\n")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
