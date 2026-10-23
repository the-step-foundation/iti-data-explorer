#!/usr/bin/env python3
"""
Build mh_baseline/dashboard/data.json from mh_baseline/raw/maharashtra_govt_iti_data.csv.

The source sheet has one column per tracked indicator per year (e.g. seats_2024,
pass_rate_male_2025); most of those columns are still blank statewide. Label,
group and aggregation rule for each indicator are defined once below, keyed by
its column name with the trailing _<year> stripped. A column is written out
either way (marked "filled": true/false) so the dashboard can show what is
tracked but not yet reported, and so a column that is empty today starts
appearing automatically, with no dashboard code change, once a future refresh
of the CSV fills it in.

Usage: python3 build_data.py   (after updating raw/maharashtra_govt_iti_data.csv)
"""
import csv, json, os, re, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "raw", "maharashtra_govt_iti_data.csv")
OUT = os.path.join(HERE, "dashboard", "data.json")

# Always-present identity/capacity columns: shown on every row, not part of the
# filled/pending indicator coverage (they're complete for all 419 institutes).
IDENTITY = ["district", "iti_name", "year_established", "total_trades"]

# metric key (column name with _<year> stripped, if any) -> (label, group, unit, agg)
#   unit: count | pct | text   agg (how the dashboard rolls a metric up): sum | avg | distribution
METRICS = {
    "seats":                    ("Seats",                        "Seats & enrolment", "count", "sum"),
    "enrolled_male":            ("Enrolled — male",         "Seats & enrolment", "count", "sum"),
    "enrolled_female":          ("Enrolled — female",       "Seats & enrolment", "count", "sum"),
    "pass_rate_male":           ("Pass rate — male",        "Pass rates",        "pct",   "avg"),
    "pass_rate_female":         ("Pass rate — female",      "Pass rates",        "pct",   "avg"),
    "trainer_vacancy_rate":     ("Trainer vacancy rate",         "Trainers",          "pct",   "avg"),
    "pct_employability_skills": ("Employability-skills score",  "Employability",     "pct",   "avg"),
    "dropout_rate_male":        ("Dropout rate — male",     "Dropout",           "pct",   "avg"),
    "dropout_rate_female":      ("Dropout rate — female",   "Dropout",           "pct",   "avg"),
}

# non-year columns: column name -> (label, group, unit, agg)
FLAGS = {
    "at_district_hq":                     ("At district HQ",                                    "Institute status", "flag",  "count_yes"),
    "pm_setu_iti":                        ("PM-SETU ITI",                                        "Institute status", "flag",  "count_yes"),
    "principal_in_position":              ("Principal in position",                              "Institute status", "flag",  "count_yes"),
    "nigf_grading":                       ("NIGF grading",                                       "Institute status", "text",  "distribution"),
    "trainers_iti_craft_instructor_cert": ("Trainers — ITI/CITS craft instructor cert",     "Trainers",          "count", "sum"),
    "trainers_diploma":                   ("Trainers — diploma",                             "Trainers",          "count", "sum"),
    "trainers_graduate":                  ("Trainers — graduate",                            "Trainers",          "count", "sum"),
    "trainers_postgraduate":              ("Trainers — postgraduate",                        "Trainers",          "count", "sum"),
    "trainers_cits":                      ("Trainers — CITS",                                "Trainers",          "count", "sum"),
    "msmes_engaged":                      ("MSMEs engaged",                                       "Industry linkage",  "count", "sum"),
    "active_industry_mous":               ("Active industry MoUs",                                "Industry linkage",  "count", "sum"),
}

YEAR_RE = re.compile(r"^(?P<metric>.+?)_(?P<year>20\d{2})$")


def to_num(v):
    v = (v or "").strip()
    if not v:
        return None
    try:
        f = float(v)
        return int(f) if f.is_integer() else f
    except ValueError:
        return v  # non-numeric indicator (e.g. nigf_grading, or a Yes/No flag)


with open(SRC, newline="", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    header = reader.fieldnames
    records = list(reader)

columns = []
for key in header:
    if key in ("s_no",) or key in IDENTITY:
        continue
    m = YEAR_RE.match(key)
    if m and m.group("metric") in METRICS:
        metric, year = m.group("metric"), int(m.group("year"))
        label, group, unit, agg = METRICS[metric]
    elif key in FLAGS:
        metric, year = key, None
        label, group, unit, agg = FLAGS[key]
    else:
        continue  # unrecognised column: skip rather than guess at its meaning
    filled = any(to_num(r.get(key)) not in (None, "") for r in records)
    columns.append({"key": key, "metric": metric, "year": year, "label": label,
                     "group": group, "unit": unit, "agg": agg, "filled": filled})

rows = []
for r in records:
    row = {k: (r[k].strip() if k in ("district", "iti_name") else to_num(r[k])) for k in IDENTITY}
    for c in columns:
        row[c["key"]] = to_num(r.get(c["key"]))
    rows.append(row)

years = sorted({c["year"] for c in columns if c["year"]})
districts = sorted({r["district"] for r in rows})

payload = {
    "built": datetime.date.today().isoformat(),
    "source": os.path.basename(SRC),
    "years": years,
    "districts": districts,
    "columns": columns,
    "rows": rows,
}
os.makedirs(os.path.dirname(OUT), exist_ok=True)
# Keep the old build date when nothing changed, so a re-run without new data commits nothing.
if os.path.exists(OUT):
    old = json.load(open(OUT))
    if {k: v for k, v in old.items() if k != "built"} == {k: v for k, v in payload.items() if k != "built"}:
        payload["built"] = old.get("built", payload["built"])
json.dump(payload, open(OUT, "w"), ensure_ascii=False, separators=(",", ":"))

n_filled = sum(1 for c in columns if c["filled"])
print(f"{len(rows)} institutes, {len(districts)} districts, {len(columns)} year/flag indicators "
      f"({n_filled} filled, {len(columns) - n_filled} pending) -> {OUT} ({os.path.getsize(OUT) // 1024} KB)")
