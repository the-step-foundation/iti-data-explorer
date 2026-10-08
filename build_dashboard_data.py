#!/usr/bin/env python3
"""
Build dashboard/data.json for the ITI Data Explorer from iti_data/ outputs.

One value per (kind, state, metric, breakdown, period): where tables disagree,
the latest-published table wins (same rule as iti_datagovin.py) and the number
of sources is kept so the dashboard can flag revised figures.

Usage: python3 build_dashboard_data.py   (after iti_datagovin.py)
"""
import csv, glob, json, os, datetime
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "iti_data")
OUT = os.path.join(HERE, "dashboard", "data.json")

def sid(resource_id):
    """Short source key: first 8 characters of a data.gov.in UUID, the full id for anything else."""
    return resource_id[:8] if len(resource_id) == 36 else resource_id

groups = defaultdict(list)
titles = {}
urls = {}
# Main input: the merged data.gov.in tables. Extra input: any CSV in extra/ with the same columns
# (plus optional source_url), so new sources can be added without touching this script.
inputs = [os.path.join(DATA, "long.csv")] + sorted(glob.glob(os.path.join(HERE, "extra", "*.csv")))
for path in inputs:
    for r in csv.DictReader(open(path)):
        if not r.get("value", "").strip():
            continue
        groups[(r["kind"], r["state"], r["metric"], r["breakdown"], r["period"])].append(r)
        titles[r["resource_id"]] = (r["table_title"], r["published"])
        if r.get("source_url"):
            urls[r["resource_id"]] = r["source_url"]

states = sorted({k[1] for k in groups}, key=lambda s: (s != "All India", s))
sidx = {s: i for i, s in enumerate(states)}
rows = []
for (kind, st, met, bd, per), rs in sorted(groups.items()):
    best = sorted(rs, key=lambda r: (r["published"], r["resource_id"]))[-1]
    v = float(best["value"])
    vals = sorted({float(r["value"]) for r in rs})
    rows.append([kind, sidx[st], met, bd, per, int(v) if v.is_integer() else v,
                 sid(best["resource_id"]), len(rs), 1 if len(vals) > 1 else 0])

# Several snapshot tables give only Govt and Pvt ITI counts: add the total.
have = {(r[1], r[4]) for r in rows if r[0] == "snapshot" and r[2] == "itis" and r[3] == "total"}
parts = defaultdict(dict)
for r in rows:
    if r[0] == "snapshot" and r[2] == "itis" and r[3] in ("govt", "pvt"):
        parts[(r[1], r[4])][r[3]] = r
for (s, per), p in parts.items():
    if (s, per) not in have and len(p) == 2:
        rows.append(["snapshot", s, "itis", "total", per, p["govt"][5] + p["pvt"][5],
                     p["govt"][6], p["govt"][7], 0])

dash = []
for r in csv.DictReader(open(os.path.join(DATA, "dashboard_kpis_by_admission_year.csv"))):
    if not r["admission_year"].isdigit():
        continue
    dash.append({k: (int(v) if v.isdigit() else None) for k, v in r.items() if k != "note"})

sources = {sid(rid): {"id": rid, "title": t, "published": p,
                      "url": urls.get(rid) or f"https://www.data.gov.in/resource/{rid}"} for rid, (t, p) in titles.items()}

os.makedirs(os.path.dirname(OUT), exist_ok=True)
payload = {"built": datetime.date.today().isoformat(), "states": states,
           "cols": ["kind", "state", "metric", "breakdown", "period", "value", "source", "n_sources", "revised"],
           "rows": rows, "dashboard": dash, "sources": sources}
# Keep the old build date when nothing changed, so scheduled refreshes commit only real changes.
if os.path.exists(OUT):
    old = json.load(open(OUT))
    if {k: v for k, v in old.items() if k != "built"} == {k: v for k, v in payload.items() if k != "built"}:
        payload["built"] = old.get("built", payload["built"])
json.dump(payload, open(OUT, "w"), separators=(",", ":"))
print(f"{len(rows)} values, {len(states)} states, {len(sources)} sources -> {OUT} ({os.path.getsize(OUT)//1024} KB)")
