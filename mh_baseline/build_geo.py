#!/usr/bin/env python3
"""
Build mh_baseline/dashboard/districts.json: simplified Maharashtra district
boundary paths (SVG `d` strings in a small projected coordinate space), from
the raw Survey of India KML in raw/maharashtra_districts.kml.

Source: Survey of India (onlinemaps.surveyofindia.gov.in), redistributed by
opencity.in under Public Domain. The KML predates the 2021-2024 district
renames and uses inconsistent spellings, so names are normalised to match the
baseline CSV's 36 district names (RENAME below). Two placemark names were
garbled in the source file ("B|D", "WASH|M"); confirmed as Beed and Washim by
checking their coordinates against each district's known location.

The source geometry is far too detailed for a web map (370k+ coordinate
points total) so it's simplified with Douglas-Peucker before projecting.

Usage: python3 build_geo.py
"""
import xml.etree.ElementTree as ET
import json, math, os

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "raw", "maharashtra_districts.kml")
OUT = os.path.join(HERE, "dashboard", "districts.json")
NS = {"kml": "http://www.opengis.net/kml/2.2"}

RENAME = {
    "AHAMADNAGAR": "AHILYANAGAR",
    "AURANGABAD": "CHHATRAPATI SAMBHAJINAGAR",
    "USMANABAD": "DHARASHIV",
    "BULDHANA": "BULDANA",
    "RAYGAD": "RAIGAD",
    "GONDIA": "GONDIYA",
    "AMARAVATI": "AMRAVATI",
    "SUB URBAN MUMBAI": "MUMBAI SUBURBAN",
    "B|D": "BEED",
    "WASH|M": "WASHIM",
}

# Degrees of simplification tolerance (Douglas-Peucker). Tuned empirically to
# keep total points in the low thousands while still reading as the right
# shape at the dashboard's map size (~640px wide).
EPSILON = 0.012


def norm_name(raw):
    raw = raw.strip()
    return RENAME.get(raw, raw)


def parse_coords(text):
    pts = []
    for triple in text.split():
        lon, lat, *_ = triple.split(",")
        pts.append((float(lon), float(lat)))
    return pts


def perp_dist(p, a, b):
    (x, y), (x1, y1), (x2, y2) = p, a, b
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return math.hypot(x - x1, y - y1)
    t = ((x - x1) * dx + (y - y1) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    projx, projy = x1 + t * dx, y1 + t * dy
    return math.hypot(x - projx, y - projy)


def douglas_peucker(pts, epsilon):
    if len(pts) < 3:
        return pts
    dmax, idx = 0.0, 0
    for i in range(1, len(pts) - 1):
        d = perp_dist(pts[i], pts[0], pts[-1])
        if d > dmax:
            dmax, idx = d, i
    if dmax > epsilon:
        left = douglas_peucker(pts[: idx + 1], epsilon)
        right = douglas_peucker(pts[idx:], epsilon)
        return left[:-1] + right
    return [pts[0], pts[-1]]


def rings_of(placemark):
    """List of (outer_ring, [inner_rings]) - one entry per <Polygon> (a
    district may be a MultiPolygon: several disconnected pieces)."""
    out = []
    for poly in placemark.findall(".//kml:Polygon", NS):
        outer_el = poly.find(".//kml:outerBoundaryIs//kml:coordinates", NS)
        outer = parse_coords(outer_el.text) if outer_el is not None and outer_el.text else []
        inners = [parse_coords(el.text) for el in poly.findall(".//kml:innerBoundaryIs//kml:coordinates", NS) if el.text]
        if outer:
            out.append((outer, inners))
    return out


tree = ET.parse(SRC)
root = tree.getroot()

districts = {}
for pm in root.iter("{http://www.opengis.net/kml/2.2}Placemark"):
    name_el = pm.find("kml:name", NS)
    if name_el is None or not name_el.text:
        continue
    name = norm_name(name_el.text)
    districts[name] = rings_of(pm)

raw_points = sum(len(outer) + sum(len(r) for r in inners) for polys in districts.values() for outer, inners in polys)

simplified = {}
for name, polys in districts.items():
    simplified[name] = [(douglas_peucker(outer, EPSILON), [douglas_peucker(r, EPSILON) for r in inners]) for outer, inners in polys]

simp_points = sum(len(outer) + sum(len(r) for r in inners) for polys in simplified.values() for outer, inners in polys)

all_lons = [lon for polys in simplified.values() for outer, _ in polys for lon, _ in outer]
all_lats = [lat for polys in simplified.values() for outer, _ in polys for _, lat in outer]
min_lon, max_lon = min(all_lons), max(all_lons)
min_lat, max_lat = min(all_lats), max(all_lats)
mean_lat = sum(all_lats) / len(all_lats)
cos_lat = math.cos(math.radians(mean_lat))  # east-west correction so the shape isn't stretched

W = 640.0
H = (max_lat - min_lat) / ((max_lon - min_lon) * cos_lat) * W


def project(lon, lat):
    x = (lon - min_lon) * cos_lat / ((max_lon - min_lon) * cos_lat) * W
    y = (max_lat - lat) / (max_lat - min_lat) * H
    return round(x, 1), round(y, 1)


def ring_path(ring):
    pts = [project(lon, lat) for lon, lat in ring]
    return f"M{pts[0][0]},{pts[0][1]} " + " ".join(f"L{x},{y}" for x, y in pts[1:]) + " Z"


paths = {}
for name, polys in simplified.items():
    d = " ".join(ring_path(outer) + ("" if not inners else " " + " ".join(ring_path(r) for r in inners)) for outer, inners in polys)
    paths[name] = d

payload = {
    "viewBox": f"0 0 {W:.1f} {H:.1f}",
    "source": "Survey of India (onlinemaps.surveyofindia.gov.in), via opencity.in, Public Domain",
    "paths": paths,
}
os.makedirs(os.path.dirname(OUT), exist_ok=True)
json.dump(payload, open(OUT, "w"), separators=(",", ":"))
print(f"{len(paths)} districts, {raw_points} -> {simp_points} points (epsilon {EPSILON}°) -> {OUT} ({os.path.getsize(OUT)//1024} KB)")
