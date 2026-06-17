"""
COMFORT / TREE CANOPY lookup for the PLANNER side.

Source: "Comfort Index.zip" — a shapefile of the SAME OSM road network
(84,924 roads, keyed by osm_id) with canopy + heat-comfort attributes. The
upload arrived truncated (missing the .shp geometry + zip directory), but the
.dbf attribute table is fully intact and we already have these roads' geometry
from ATLNPU_Roads_with_Sidewalks, so we only need the attributes joined by osm_id.

This script recovers the .dbf straight out of the (truncated) zip by walking the
local file headers, then writes:

    data/cache/comfort_lookup.json   ->  { "<osm_id>": {"canopy": 0-100, "comfort": 0-100}, ... }

canopy  = Canopy_Sco  (higher = more tree canopy = cooler/greener)
comfort = Comfort__1  (higher = more thermally comfortable)

RUN:
    python3 scripts/build_comfort.py --src "/path/to/Comfort Index.zip"
"""

import argparse
import json
import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "cache"
SIG = b'PK\x03\x04'


def recover_dbf(zip_bytes):
    """Walk local file headers, return decompressed bytes of the .dbf entry."""
    i = 0
    entries = []
    while True:
        j = zip_bytes.find(SIG, i)
        if j < 0:
            break
        (_sig, _v, flags, method, _mt, _md, _crc, _cs, _us, nlen, elen) = \
            struct.unpack('<IHHHHHIIIHH', zip_bytes[j:j + 30])
        name = zip_bytes[j + 30:j + 30 + nlen].decode('utf-8', 'replace')
        data_start = j + 30 + nlen + elen
        entries.append((name, data_start))
        i = j + 4
    dbf = next((e for e in entries if e[0].lower().endswith('.dbf')), None)
    if not dbf:
        raise SystemExit("No .dbf entry found in archive.")
    start = dbf[1]
    end = zip_bytes.find(SIG, start)          # next local header = end of this stream
    if end < 0:
        end = len(zip_bytes)
    d = zlib.decompressobj(-15)
    try:
        out = d.decompress(zip_bytes[start:end]) + d.flush()
    except zlib.error:
        out = d.decompress(zip_bytes[start:end])  # tolerate a truncated tail
    return out


def parse_dbf(dbf):
    nrec = struct.unpack('<I', dbf[4:8])[0]
    hsize = struct.unpack('<H', dbf[8:10])[0]
    rsize = struct.unpack('<H', dbf[10:12])[0]
    fields, p = [], 32
    while dbf[p] != 0x0D:
        fname = dbf[p:p + 11].split(b'\x00')[0].decode('latin1')
        flen = dbf[p + 16]
        fields.append((fname, flen))
        p += 32
    # column offsets within each record (record byte 0 = deletion flag)
    offs, pos = {}, 1
    for fn, fl in fields:
        offs[fn] = (pos, fl)
        pos += fl
    for r in range(nrec):
        base = hsize + r * rsize
        row = dbf[base:base + rsize]
        if len(row) < rsize:
            break
        rec = {}
        for fn, (o, l) in offs.items():
            rec[fn] = row[o:o + l].decode('latin1').strip()
        yield rec


def fnum(s):
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help='path to "Comfort Index.zip"')
    args = ap.parse_args()

    dbf = recover_dbf(Path(args.src).read_bytes())
    print(f"recovered .dbf: {len(dbf):,} bytes")
    lookup = {}
    n = 0
    for rec in parse_dbf(dbf):
        oid = fnum(rec.get("osm_id"))
        if oid is None:
            continue
        canopy = fnum(rec.get("Canopy_Sco"))
        comfort = fnum(rec.get("Comfort__1"))
        lookup[str(int(oid))] = {
            "canopy": None if canopy is None else round(canopy, 1),
            "comfort": None if comfort is None else round(comfort, 1),
        }
        n += 1
    CACHE.mkdir(parents=True, exist_ok=True)
    (CACHE / "comfort_lookup.json").write_text(json.dumps(lookup))
    cv = [v["canopy"] for v in lookup.values() if v["canopy"] is not None]
    print(f"wrote comfort_lookup.json: {len(lookup):,} osm_ids ({n} rows)")
    if cv:
        print(f"canopy score range: {min(cv):.1f}–{max(cv):.1f}, mean {sum(cv)/len(cv):.1f}")


if __name__ == "__main__":
    main()
