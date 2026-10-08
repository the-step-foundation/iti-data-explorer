#!/usr/bin/env python3
"""
Pull ITI (Craftsmen Training Scheme) tables from data.gov.in and merge them
into tidy state-level datasets.

Almost all national ITI statistics on data.gov.in are Rajya Sabha answer
tables: one-off tables with different column layouts, year ranges and state
spellings. This script

  1. downloads every table listed in TABLES (cached in <out>/raw/),
  2. maps each column to (metric, breakdown, period) using the curated specs,
  3. normalises state names and session labels,
  4. writes:
       long.csv              every value, one row per source cell
       panel_state_year.csv  state x session (enrolled / trained / certified ...)
       snapshot_state.csv    state x as-of date (ITI counts, seats)
       conflicts.csv         same state/metric/period reported differently
       totals_check.csv      reported "Total" rows vs sum of states
       manifest.csv          every table: status, rows, dates, link
  5. with --discover, also searches data.gov.in for ITI tables that are not
     yet in TABLES and lists them in new_tables.csv so the spec can be extended.

Usage:
  python3 iti_datagovin.py --out iti_data                 # uses cache
  python3 iti_datagovin.py --out iti_data --refresh       # re-download
  python3 iti_datagovin.py --out iti_data --discover
  DATA_GOV_IN_API_KEY=... python3 iti_datagovin.py ...    # your own key

Standard library only (Python 3.8+).
"""
import argparse, csv, json, os, re, sys, time, urllib.error, urllib.parse, urllib.request
from collections import defaultdict

# data.gov.in's published sample key works but is shared and throttled.
# Register at data.gov.in for your own key and pass it via env/--api-key.
SAMPLE_KEY = "579b464db66ec23bdd0000015ccfae5e282347146ed579583a2c4559"
# api.data.gov.in is the documented host; the site's backend serves the same
# data and is used as a fallback (api.data.gov.in is blocked on some networks).
DATA_HOSTS = ["https://api.data.gov.in/resource/{rid}",
              "https://www.data.gov.in/backend/dataapi/v1/resource/{rid}"]
SEARCH_URL = "https://www.data.gov.in/backend/dmspublic/v1/search"
UA = {"User-Agent": "Mozilla/5.0 (iti-datagovin script)"}

# --------------------------------------------------------------------------
# Table specs
#
# kind:
#   "series"   values by period (session) -> panel_state_year.csv
#   "snapshot" values as on a date        -> snapshot_state.csv
#   "other"    flows / cumulative totals   -> long.csv only
# cols: {column name (as shown on data.gov.in): (metric, breakdown, period)}
#   period None  -> parsed from the column name
#   metric None  -> table default metric
# Columns not listed are ignored (serial numbers, location text, etc.).
# --------------------------------------------------------------------------
def yrs(metric, names, breakdown="total"):
    return {n: (metric, breakdown, None) for n in names}

TABLES = [
  # ---------------- enrolment (admissions) by session ----------------
  dict(rid="4de52cc2-0bf6-4072-8dcc-ae60d4d0fc5c", kind="series",
       cols=yrs("enrolled", ["Year 2015", "Year 2016", "Year 2017"])),
  dict(rid="d5a26bc1-6a98-4147-afd2-10e545e43af9", kind="series",
       cols=yrs("enrolled", ["2016", "2017", "2018", "2019", "2020"])),
  dict(rid="a342ecbe-1bf7-41ee-bdd5-54a7d0c50e74", kind="series",
       cols=yrs("enrolled", ["2017", "2018", "2019"])),
  dict(rid="7ca95fc4-e255-4d18-b121-d288c0da6920", kind="series",
       cols=yrs("enrolled", ["Enrollment in 2018", "Enrollment in 2019", "Enrollment in 2020"])),
  dict(rid="36b9567e-6c21-405c-847f-fe1c876195c9", kind="series",
       cols=yrs("enrolled", ["2017-18", "2018-19", "2019-20"])),
  dict(rid="c123ed4d-63db-4313-bc3f-2ecaa76413af", kind="series",
       cols=yrs("enrolled", ["2019-20", "2020-21", "2021-22", "2022-23"])),
  dict(rid="cfc747c8-dbb4-455f-81cf-bdcc244a592b", kind="series",
       cols=yrs("enrolled", ["2019-20", "2020-21", "2021-22", "2022-23", "2023-24"])),
  # titled "Youth Trained" but columns are enrolment
  dict(rid="68e53cc1-7c22-41d4-ba71-9d84ba70e607", kind="series",
       cols=yrs("enrolled", ["Enrolment 2019", "Enrolment 2020", "Enrolment 2021"])),
  dict(rid="55d77373-f0de-46e3-b68b-5f3d3e074d35", kind="series",
       cols=yrs("enrolled", ["Enrolment 2019", "Enrolment 2020", "Enrolment 2021", "Enrolment 2022"])),
  dict(rid="5e97937f-3ff3-4f7e-86e3-987e87d32dd3", kind="series",
       cols=yrs("enrolled", ["2018", "2019", "2020"])),
  # titled "Training Data" but values match the enrolment tables exactly
  dict(rid="ba097f68-3882-4c3f-bb75-1b1973285b8b", kind="series",
       cols={**yrs("enrolled", ["2018", "2019", "2020", "2021"]),
             "2022 (upto September, 2022)": ("enrolled_partial", "total", None)}),
  dict(rid="799ec786-a14e-413f-a39b-ee27b1569679", kind="series",
       cols={f"{y} - {k}": (m, "total", None) for y in (2014, 2015, 2016)
             for k, m in (("Enrolled", "enrolled"), ("Certified", "certified"))}),
  dict(rid="0fec4669-0e92-473a-835f-f6616ce23c3f", kind="series",
       cols={f"Enrolment in {s} - {c}": ("enrolled", c.lower(), None)
             for s in ("2018-19", "2019-20", "2020-21") for c in ("OBC", "SC", "ST", "Gen", "Divyang")}),
  dict(rid="89bce479-067c-48ee-966a-ac6f551995bc", kind="series",
       cols={"2020 - Seating Capacity": ("seats", "total", None),
             "2020 - Enrolment": ("enrolled", "total", None),
             "2020 - Vacancies": ("vacant_seats", "total", None)}),

  # Since ~2018 MSDE answers use "trained" to mean "enrolled under CTS": the
  # next two tables match the enrolment tables state-for-state, so they are
  # mapped to enrolled.
  dict(rid="7cc46a5e-4210-4160-a64f-acbfcc789be0", kind="series",
       cols=yrs("enrolled", ["2021-22", "2022-23", "2023-24"])),
  dict(rid="62036996-b17e-4e54-b5c8-007738ccc4b7", kind="series",
       cols={f"{y} - {g}": ("enrolled", g.lower(), None) for y in (2019, 2020, 2021) for g in ("Male", "Female")}),

  # ---------------- trained (completed / passed out), 2014-15 to 2017-18 ----------------
  *[dict(rid=r, kind="series",
         cols={**yrs("trained", [f"Total Trainees Trained - {s}" for s in ("2014-15", "2015-16", "2016-17", "2017-18")]),
               "Trainees being Trained in 2018-19 in the Trades of 1 & 2 Years": ("in_training", "total", None)})
    for r in ("c23ae710-1458-4c0f-a3ed-4ef3286f8777", "1ac18fe2-1537-438e-82e4-7e9338e08a07",
              "dd020189-3d18-40f4-86a3-51a014d8d8ac")],
  dict(rid="51c8e446-0677-4dd4-97bd-64c009cb4794", kind="series",
       cols=yrs("trained_in_women_itis", [f"Women Candidates Trained in Women ITIs - {y}" for y in (2019, 2020, 2021)], "female")),

  # ---------------- ITI counts / seats as on a date ----------------
  *[dict(rid=r, kind="snapshot", as_of=d,
         # one table spells it "Number of Govt. it is"; listed as an alternative
         cols={"Number of Govt. ITIs": ("itis", "govt", None), "Number of Govt. it is": ("itis", "govt", None),
               "Number of Pvt. ITIs": ("itis", "pvt", None), "Total ITIs": ("itis", "total", None),
               "Seating Capacity (Govt.)": ("seats", "govt", None), "Seating Capacity (Pvt.)": ("seats", "pvt", None),
               "Total Seating Capacity": ("seats", "total", None)})
    for r, d in (("1b355466-49c3-472f-a89e-b2820f409cc4", "2015-06-23"),
                 ("2e56e75f-eb35-4284-ab27-014c2ce45195", "2016-04-30"),
                 ("04dab8e6-592d-44b0-887f-9950cbce4e23", "2016-07-28"))],
  dict(rid="7a16313d-c4aa-4d58-aa8d-8b20d95f2dcc", kind="snapshot", as_of="2016-12-01",
       cols={"Total ITIs as on date": ("itis", "total", None)}),
  dict(rid="c72013bf-6edb-4ff6-8f5d-28eb423e12e4", kind="snapshot", as_of="2017-02-09",
       cols={"ITI Count": ("itis", "total", None), "Total Seat sanctioned": ("seats", "total", None)}),
  dict(rid="0a348746-d4a8-4f27-8dd8-b10cea46c3d2", kind="snapshot", as_of="2017-03-09",
       note="ITIs admitting trainees, NCVT-affiliated",
       cols={"ITI Count": ("itis_admitting", "total", None), "Seat sanctioned*": ("seats", "total", None)}),
  dict(rid="354dfda5-50a2-43e5-bad5-5132b6f6ea47", kind="snapshot", as_of="2017-03-23",
       cols={"No. of ITIs": ("itis", "total", None), "Total Seating Capacity": ("seats", "total", None),
             "No. of Instructors required": ("instructors_required", "total", None)}),
  dict(rid="f96fb075-36e3-4f6c-a0cf-ab9e9cab1ef5", kind="snapshot", as_of="2017-08-03",
       cols={"Total No. of ITI(s)": ("itis", "total", None), "Govt. ITIs": ("itis", "govt", None),
             "Private ITIs": ("itis", "pvt", None)}),
  dict(rid="36d04fdc-b804-4a74-858c-ef77f176f516", kind="snapshot", as_of="2016-08-01",
       cols={"Seating capacity August, 2014 session": ("seats", "total", "2014-08-01"),
             "Seating capacity as on date i.e. August, 2016 session": ("seats", "total", "2016-08-01")}),
  dict(rid="63d81eb9-28f3-49b8-937f-460388ed3194", kind="snapshot", as_of="2018-12-28",
       cols={"ITI Count": ("itis", "total", None)}),
  dict(rid="f6e88ccd-ea62-4288-9c04-6ee538e965f6", kind="snapshot", as_of="2021-01-01",
       cols={"ITI Count": ("itis", "total", None)}),
  dict(rid="117f6967-4b9e-40ce-ae40-d5b8877d1f2f", kind="snapshot", as_of="2021-02-12",
       cols={"ITIs": ("itis", "total", None)}),
  dict(rid="597f89f5-350e-40b0-a895-4bf7b00f0944", kind="snapshot", as_of="2021-07-13",
       cols={"Total Govt it is": ("itis", "govt", None), "Total Private it is": ("itis", "pvt", None),
             "Total": ("itis", "total", None)}),
  dict(rid="0955ba2f-3be6-4cf0-a608-434409fd6f21", kind="snapshot", as_of="2021-12-15",
       cols={"Nos. of Govt. ITIs": ("itis", "govt", None), "Nos. of Pvt. ITIs": ("itis", "pvt", None),
             "Nos. of Total ITIs": ("itis", "total", None)}),
  dict(rid="288d7261-4c8c-4867-8041-abfe6c55e64a", kind="snapshot", as_of="2021-12-31",
       cols={"ITI - Govt. ITIs": ("itis", "govt", None), "ITI - Pvt. ITIs": ("itis", "pvt", None)}),
  dict(rid="b81f053c-5668-4e13-92cc-7bebe85ceeb5", kind="snapshot", as_of="2022-02-09",
       cols={"Nos. of Total ITIs under CTS (a)": ("itis", "total", None)}),
  dict(rid="8da0d40b-6a9e-449e-b8cd-e803244ee418", kind="snapshot", as_of="2022-04-06",
       cols={"Nos. of Govt. ITIs": ("itis", "govt", None), "Nos. of Pvt. ITIs": ("itis", "pvt", None),
             "Total Nos. of ITIs": ("itis", "total", None)}),
  dict(rid="8310287f-fc77-45b5-bf09-6aca4c067ea2", kind="snapshot", as_of="2022-06-30",
       cols={"ITIs": ("itis", "total", None)}),
  dict(rid="4908bd73-3942-4498-b1d4-e132838d0793", kind="snapshot", as_of="2022-06-30",
       cols={"ITI - Govt.": ("itis", "govt", None), "ITI - Pvt.": ("itis", "pvt", None)}),
  dict(rid="29b6c84e-4b08-4d61-a3e5-c6acce749ce9", kind="snapshot", as_of="2022-09-30",
       cols={"ITI - Govt. ITIs": ("itis", "govt", None), "ITI - Pvt. ITIs": ("itis", "pvt", None),
             "ITI - NSTIs": ("nstis", "total", None)}),
  dict(rid="2af9602e-db00-49db-ba25-a1823a13384c", kind="snapshot", as_of="2023-03-31",
       cols={"Govt. ITIs": ("itis", "govt", None), "Pvt. ITIs": ("itis", "pvt", None)}),
  dict(rid="2c87a4b3-f9d5-4b23-bb09-927855bbe555", kind="snapshot", as_of="2023-12-31",
       cols={"Govt. ITIs": ("itis", "govt", None), "Pvt. ITIs": ("itis", "pvt", None)}),
  dict(rid="943c6962-2001-45d1-9a24-5a1668eb9c89", kind="snapshot", as_of="2024-06-30",
       cols={"Total ITIs (Government and Private) - Total ITIs": ("itis", "total", None),
             "Total ITIs (Government and Private) - Exclusively for women": ("itis", "women_only", None),
             "NSTI (for Women)": ("nstis", "women_only", None)}),
  dict(rid="605183f9-4387-4735-a6ec-ebd7f4298c49", kind="snapshot", as_of="2024-10-31",
       cols={"Number of Training Centres (TCs) - CTS": ("itis", "total", None)}),

  # ---------------- flows and cumulative totals (long.csv only) ----------------
  dict(rid="810a4879-18f0-451a-a060-a68e93d41a70", kind="other",
       cols={f"{s} - {b}": ("itis_new", b.lower(), None) for s in ("2014-15", "2015-16", "2016-17")
             for b in ("Govt", "Pvt", "Total")}),
  dict(rid="9b00bdb5-e106-4f86-94e6-6e0629d43aa2", kind="other",
       cols=yrs("itis_new_govt_opened", [f"Nos. of new ITIs opened in {y}" for y in (2018, 2019, 2020)])),
  dict(rid="f65d0a51-905e-4f19-b95a-81a2a9384fca", kind="other",
       cols={"Total": ("itis_new_affiliated", "total", "2020-21..2021-22")}),
  dict(rid="6a772839-2804-4247-b097-b97f55f47d13", kind="other",
       cols={"Government ITIs": ("itis_new", "govt", "3 yrs to 2022-02"),
             "Private ITIs": ("itis_new", "pvt", "3 yrs to 2022-02")}),
  dict(rid="0d076054-30c2-49d1-99f1-1262d9dd544c", kind="other",
       cols=yrs("itis_third_shift", [f"Numbers of ITIs in {y}" for y in (2017, 2018, 2019)])),
  dict(rid="321a9674-4bc2-45cf-a84e-a7ac313db3ed", kind="other",
       cols={"Total": ("trained_cumulative", "total", "2015..2018")}),
  dict(rid="87289d07-80fa-4a51-a7a0-433b87cd0c36", kind="other",
       cols={"Total": ("trained_cumulative", "total", "to 2022-10-30")}),
  dict(rid="a9346fe0-d3da-4802-8bf9-5e042a431f01", kind="other",
       cols={"CTS in ITIs (Since 2018-19 to 2023-24)": ("trained_cumulative", "total", "2018-19..2023-24")}),
  dict(rid="c482cf64-7add-45d0-89b9-0b10b859adf5", kind="other",
       cols={"Total": ("trained_cumulative", "female", "2014..2018")}),
  dict(rid="b38ea205-d4f2-4410-83c2-9a868e545037", kind="other",
       cols={"ITIs Enrolment": ("enrolled_cumulative", "total", "2017-18..2021-22")}),
  dict(rid="1b29067a-f08a-41fe-88dc-b5aa5d7cb68b", kind="other",
       cols={"Number of Trainee": ("trained_strive", "total", "2022..2024")}),
]

# --------------------------------------------------------------------------
# State names
# --------------------------------------------------------------------------
STATES = {
  "Andaman and Nicobar Islands": ["a&n", "a&nisland", "a&nislands", "a&nicobar", "a&dislands", "andaman&nicobarislands"],
  "Andhra Pradesh": ["ap", "a.p"], "Arunachal Pradesh": ["arunachalpr", "arunchalpradesh", "ar.p"],
  "Assam": [], "Bihar": [], "Chandigarh": [],
  "Chhattisgarh": ["chattisgarh", "chattishgarh", "chhatisgarh"],
  "Dadra and Nagar Haveli and Daman and Diu": [
      "dadra&nagarhavelianddaman&diu", "dadraandnagarhavelidamananddiu", "thedadraandnagarhavelianddamananddiu",
      "damananddiuanddadraandnagarhaveli"],
  "Dadra and Nagar Haveli": ["d&nhaveli", "dadra&nagarhaveli"], "Daman and Diu": ["daman&diu"],
  "Delhi": ["delhincr", "nctofdelhi"], "Goa": [], "Gujarat": [], "Haryana": [],
  "Himachal Pradesh": ["hp", "h.p", "himachalpr"], "Jammu and Kashmir": ["jammu&kashmir"], "Jharkhand": [],
  "Karnataka": [], "Kerala": [], "Ladakh": [], "Lakshadweep": ["lakshdweep"],
  "Madhya Pradesh": ["mp", "m.p", "madhayapradesh"], "Maharashtra": [], "Manipur": [], "Meghalaya": [],
  "Mizoram": [], "Nagaland": [], "Odisha": ["orissa", "orisha"], "Puducherry": ["poducherry", "puduchhery", "pondicherry"],
  "Punjab": [], "Rajasthan": [], "Sikkim": ["sikim"], "Tamil Nadu": [], "Telangana": [], "Tripura": [],
  "Uttar Pradesh": [], "Uttarakhand": ["uttrakhand", "uttaranchal"], "West Bengal": [],
}
TOTAL_ALIASES = {"total", "grandtotal", "allindia", "india"}
MIN_STATES_FOR_TOTAL = 33  # only derive an All India sum from (near-)complete tables

_ALIAS = {}
for canon, al in STATES.items():
    for a in [canon] + al:
        _ALIAS[re.sub(r"[^a-z&.]", "", a.lower())] = canon
        _ALIAS[re.sub(r"[^a-z&.]", "", a.lower().replace(" and ", "&"))] = canon
        _ALIAS[re.sub(r"[^a-z]", "", a.lower())] = canon

def norm_state(raw):
    s = re.sub(r"\(.*?\)|\*", "", str(raw)).strip()
    k1 = re.sub(r"[^a-z&.]", "", s.lower())
    k2 = re.sub(r"[^a-z]", "", s.lower())
    if k2 in TOTAL_ALIASES:
        return "All India"
    return _ALIAS.get(k1) or _ALIAS.get(k1.replace("and", "&")) or _ALIAS.get(k2)

# --------------------------------------------------------------------------
# Periods: ITI sessions start in August, so calendar year Y == session Y-(Y+1).
# (Verified: e.g. A&N 2019 = 441 in the calendar-year tables and 2019-20 = 441
# in the session tables.)
# --------------------------------------------------------------------------
def parse_period(label):
    m = re.search(r"(20\d\d)\s*-\s*(\d{2,4})", label) or re.search(r"FY\s*(\d\d)\s*-\s*(\d\d)", label)
    if m:
        y = int(m.group(1)) if len(m.group(1)) == 4 else 2000 + int(m.group(1))
        return f"{y}-{str(y + 1)[2:]}", y, "session"
    m = re.search(r"\b(20\d\d)\b", label)
    if m:
        y = int(m.group(1))
        return f"{y}-{str(y + 1)[2:]}", y, "calendar->session"
    return label, None, "unparsed"

def to_num(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace(",", "").strip()
    if s in ("", "-", "NA", "N.A.", "na", "--"):
        return None
    try:
        return float(s)
    except ValueError:
        return None

# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------
def http_json(url, tries=6):
    for a in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429 or e.code >= 500:
                time.sleep(5 * 2 ** a)
                continue
            raise
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            if a >= 1:
                raise
            time.sleep(3)
    raise RuntimeError(f"gave up after {tries} tries: {url}")

def fetch_table(rid, key, raw_dir, refresh, pause):
    path = os.path.join(raw_dir, f"{rid}.json")
    if os.path.exists(path) and not refresh:
        with open(path) as f:
            return json.load(f), "cached"
    cached = None
    if os.path.exists(path):
        with open(path) as f:
            cached = json.load(f)
    err = None
    for host in DATA_HOSTS:
        url = host.format(rid=rid) + "?" + urllib.parse.urlencode(
            {"api-key": key, "format": "json", "limit": 5000})
        try:
            j = http_json(url)
            break
        except Exception as e:  # try next host
            err = e
    else:
        if cached:
            return cached, "cached (re-download failed)"
        raise RuntimeError(f"all hosts failed: {err}")
    time.sleep(pause)
    if j.get("status") == "error" or "title" not in j or \
            int(j.get("total") or 0) > len(j.get("records", [])):
        if cached:
            return cached, "cached (re-download failed)"
        raise RuntimeError(j.get("message") or "no data or truncated")
    with open(path, "w") as f:
        json.dump(j, f)
    return j, "downloaded"

# --------------------------------------------------------------------------
# Parse one table into long rows
# --------------------------------------------------------------------------
STATE_COL = re.compile(r"state|name of|^region$", re.I)

def parse_table(spec, j, unknown_states):
    fields = j["field"]
    canon = lambda n: re.sub(r"\s+", " ", n).strip().lower()  # match names ignoring case/spacing
    name2id = {}
    for f in fields:
        name2id.setdefault(canon(f["name"]), f["id"])
    # state column = first keyword column whose name mentions state / name of
    state_ids = [f["id"] for f in fields if re.search(r"state|name of", f["name"], re.I)]
    if not state_ids:
        raise RuntimeError("no state column")
    sid = state_ids[0]
    used = {c: v for c, v in spec["cols"].items() if canon(c) in name2id}
    # a spec column is only "missing" if no other found column fills the same target
    targets = set(used.values())
    missing = [c for c, v in spec["cols"].items() if canon(c) not in name2id and v not in targets]
    if not used:
        raise RuntimeError(f"none of the spec columns found; table has {[f['name'] for f in fields]}")
    published = (j.get("created_date") or "")[:10]
    out = []
    for rec in j["records"]:
        raw_state = rec.get(sid)
        st = norm_state(raw_state)
        if st is None:
            unknown_states[str(raw_state)] += 1
            continue
        for col, (metric, breakdown, period) in used.items():
            val = to_num(rec.get(name2id[canon(col)]))
            if val is None:
                continue
            if spec["kind"] == "series":
                plabel, pyear, ptype = parse_period(period or col)
            elif spec["kind"] == "snapshot":
                plabel, pyear, ptype = (period or spec["as_of"]), None, "as_of"
            else:
                plabel, pyear, ptype = parse_period(period or col) if period is None else (period, None, "range")
            out.append(dict(state=st, state_raw=str(raw_state).strip(), metric=metric, breakdown=breakdown,
                            period=plabel, session_start=pyear or "", period_type=ptype, value=val,
                            kind=spec["kind"], resource_id=spec["rid"], published=published,
                            source_column=col, table_title=j["title"]))
    return out, missing

# --------------------------------------------------------------------------
# Discovery of ITI tables not yet in TABLES
# --------------------------------------------------------------------------
ITI_RE = re.compile(r"\bITIs?\b|industrial training|craftsm[ae]n training|\bNSTIs?\b|national skill training", re.I)

def discover(known, pause):
    found = {}
    for q in ["ITI", "ITIs", "Industrial Training Institutes", "Craftsmen Training Scheme",
              "Craftsman Training Scheme", "National Skill Training Institutes"]:
        off, total = 0, 1
        while off < min(total, 2000):
            p = urllib.parse.urlencode({"limit": 100, "offset": off, "query": q, "filters[type]": "resources",
                                        "filters[domain_visibility]": 4, "sort[_score]": "desc"})
            d = http_json(f"{SEARCH_URL}?{p}")
            total = d.get("total", 0)
            for r in d["data"].get("rows", []):
                t = re.sub("<[^>]+>", "", r["title"][0])
                rid = r["uuid"][0]
                if ITI_RE.search(t) and rid not in known:
                    found[rid] = dict(resource_id=rid, title=t,
                                      publisher=(r.get("catalog_resource_ministry") or r.get("catalog_resource_state") or [""])[0],
                                      api=(r.get("is_api_available") or [""])[0],
                                      page="https://www.data.gov.in" + (r.get("node_alias") or [""])[0])
            off += 100
            time.sleep(pause)
    return list(found.values())

# --------------------------------------------------------------------------
def write_csv(path, rows, fields=None):
    fields = fields or (list(rows[0].keys()) if rows else [])
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

def fmt(v):
    return int(v) if v is not None and float(v).is_integer() else v

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="iti_data")
    ap.add_argument("--api-key", default=os.environ.get("DATA_GOV_IN_API_KEY") or SAMPLE_KEY)
    ap.add_argument("--refresh", action="store_true", help="re-download tables even if cached")
    ap.add_argument("--discover", action="store_true", help="list ITI tables on data.gov.in not yet in TABLES")
    ap.add_argument("--pause", type=float, default=1.5, help="seconds between API calls")
    a = ap.parse_args()
    if a.api_key == SAMPLE_KEY:
        print("note: using data.gov.in's shared sample key; set DATA_GOV_IN_API_KEY for your own.", file=sys.stderr)

    raw_dir = os.path.join(a.out, "raw")
    os.makedirs(raw_dir, exist_ok=True)

    long_rows, manifest = [], []
    unknown_states = defaultdict(int)
    for spec in TABLES:
        m = dict(resource_id=spec["rid"], kind=spec["kind"], status="", rows_out=0, title="", published="",
                 missing_columns="", note=spec.get("note", ""),
                 page=f"https://www.data.gov.in/resource/{spec['rid']}")
        try:
            j, how = fetch_table(spec["rid"], a.api_key, raw_dir, a.refresh, a.pause)
            m.update(title=j["title"], published=(j.get("created_date") or "")[:10])
            rows, missing = parse_table(spec, j, unknown_states)
            long_rows += rows
            m.update(status=how, rows_out=len(rows), missing_columns="; ".join(missing))
        except Exception as e:
            m["status"] = f"ERROR: {e}"
        manifest.append(m)
        print(f"{m['status'][:40]:40} {m['rows_out']:5}  {m['title'][:90]}", file=sys.stderr)

    # National totals: several tables have no "Total" row. Where a table covers
    # every state, add an All India row summed from the states.
    have_total = {(r["resource_id"], r["metric"], r["breakdown"], r["period"])
                  for r in long_rows if r["state"] == "All India"}
    sums = defaultdict(list)
    for r in long_rows:
        k = (r["resource_id"], r["metric"], r["breakdown"], r["period"])
        if r["state"] != "All India" and k not in have_total:
            sums[k].append(r)
    for k, rs in sums.items():
        if len({r["state"] for r in rs}) >= MIN_STATES_FOR_TOTAL:
            long_rows.append({**rs[0], "state": "All India", "state_raw": "(sum of states)",
                              "value": sum(r["value"] for r in rs), "source_column": rs[0]["source_column"] + " [sum of states]"})

    write_csv(os.path.join(a.out, "manifest.csv"), manifest)
    write_csv(os.path.join(a.out, "long.csv"), long_rows)

    # ---- group identical (state, metric, breakdown, period) across sources
    groups = defaultdict(list)
    for r in long_rows:
        groups[(r["kind"], r["state"], r["metric"], r["breakdown"], r["period"])].append(r)

    def pick(rs):
        # latest-published table wins (later answers carry revised figures)
        return sorted(rs, key=lambda r: (r["published"], r["resource_id"]))[-1]

    conflicts = []
    for (kind, st, met, bd, per), rs in groups.items():
        vals = {r["value"] for r in rs}
        if len(vals) > 1:
            lo, hi = min(vals), max(vals)
            conflicts.append(dict(kind=kind, state=st, metric=met, breakdown=bd, period=per,
                                  n_sources=len(rs), min=fmt(lo), max=fmt(hi),
                                  spread_pct=round(100 * (hi - lo) / hi, 1) if hi else "",
                                  chosen=fmt(pick(rs)["value"]),
                                  values="; ".join(f"{fmt(r['value'])} [{r['resource_id'][:8]} {r['published']}]"
                                                   for r in sorted(rs, key=lambda r: r["published"]))))
    conflicts.sort(key=lambda c: -(c["spread_pct"] or 0))
    write_csv(os.path.join(a.out, "conflicts.csv"), conflicts)

    # ---- wide outputs
    def wide(kind, index_name):
        cells, srcs, cols = defaultdict(dict), defaultdict(dict), set()
        for (k, st, met, bd, per), rs in groups.items():
            if k != kind:
                continue
            col = met if bd == "total" else f"{met}_{bd}"
            cols.add(col)
            p = pick(rs)
            cells[(st, per)][col] = fmt(p["value"])
            srcs[(st, per)][col] = f"{p['resource_id'][:8]}" + (f" (+{len(rs) - 1})" if len(rs) > 1 else "")
        order = sorted(cols, key=lambda c: (c.split("_")[0] != "enrolled", c.split("_")[0] != "trained", c))
        rows = []
        for (st, per) in sorted(cells, key=lambda k: (k[0] != "All India", k[0], k[1])):
            row = {"state": st, index_name: per}
            row.update({c: cells[(st, per)].get(c, "") for c in order})
            row["sources"] = "; ".join(f"{c}={s}" for c, s in sorted(srcs[(st, per)].items()))
            rows.append(row)
        return rows, ["state", index_name] + order + ["sources"]

    panel, pf = wide("series", "session")
    write_csv(os.path.join(a.out, "panel_state_year.csv"), panel, pf)
    snap, sf = wide("snapshot", "as_of")
    write_csv(os.path.join(a.out, "snapshot_state.csv"), snap, sf)

    # ---- reported national totals vs sum of states (per source table)
    by_src = defaultdict(lambda: {"total": None, "sum": 0.0, "n": 0})
    for r in long_rows:
        k = (r["resource_id"], r["metric"], r["breakdown"], r["period"])
        if r["state"] == "All India":
            by_src[k]["total"] = r["value"]
        else:
            by_src[k]["sum"] += r["value"]
            by_src[k]["n"] += 1
    checks = []
    for (rid, met, bd, per), v in by_src.items():
        if v["total"] is None:
            continue
        diff = v["total"] - v["sum"]
        checks.append(dict(resource_id=rid, metric=met, breakdown=bd, period=per, reported_total=fmt(v["total"]),
                           sum_of_states=fmt(v["sum"]), n_states=v["n"], diff=fmt(diff),
                           diff_pct=round(100 * diff / v["total"], 2) if v["total"] else ""))
    checks.sort(key=lambda c: -abs(c["diff_pct"] or 0))
    write_csv(os.path.join(a.out, "totals_check.csv"), checks)

    if a.discover:
        new = discover({t["rid"] for t in TABLES}, a.pause)
        write_csv(os.path.join(a.out, "new_tables.csv"), new,
                  ["resource_id", "title", "publisher", "api", "page"])
        print(f"discover: {len(new)} ITI tables not in TABLES -> new_tables.csv", file=sys.stderr)

    ok = sum(1 for m in manifest if not m["status"].startswith("ERROR"))
    print(f"\n{ok}/{len(manifest)} tables parsed, {len(long_rows)} values, "
          f"{len(panel)} panel rows, {len(snap)} snapshot rows, {len(conflicts)} conflicts", file=sys.stderr)
    if unknown_states:
        print("skipped non-state rows:", dict(sorted(unknown_states.items(), key=lambda x: -x[1])[:15]), file=sys.stderr)

if __name__ == "__main__":
    main()
