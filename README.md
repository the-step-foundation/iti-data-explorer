# ITI Data Explorer

**Live dashboard: [the-step-foundation.github.io/iti-data-explorer](https://the-step-foundation.github.io/iti-data-explorer/)**

A dashboard for India's Industrial Training Institutes (ITIs) under the Craftsmen Training Scheme. You can read the charts, or ask questions in plain language and get an answer, a chart and the exact values and sources behind it.

The data comes from 55 tables on [data.gov.in](https://www.data.gov.in/) (almost all are Rajya Sabha answers, state level) plus All-India figures read from the [DGT Schemes Dashboard](https://dgt.skillindiadigital.gov.in/). What the data can and cannot answer is written up in [iti_data/DASHBOARD_COVERAGE.md](iti_data/DASHBOARD_COVERAGE.md). In short: state-level enrolment (2014-15 to 2023-24), counts of ITIs and seats, and women's share are covered. Anything per institute, per trade or per district is not.

## How it fits together

```
data.gov.in ──► iti_datagovin.py ──► iti_data/*.csv ──┐
                                                       ├─► build_dashboard_data.py ──► dashboard/data.json
extra/*.csv (your own sources) ────────────────────────┘                                      │
iti_data/dashboard_kpis_by_admission_year.csv (typed in from the DGT dashboard) ──────────────┤
                                                                                              ▼
                                         GitHub Pages serves dashboard/  ◄── charts read data.json in the browser
                                                    │
                                    question box ───┘──► worker/ (Cloudflare Worker, holds the API key) ──► Claude
```

- The page keeps the data and the lookup tool in the browser. Claude only asks for lookups, so every number in an answer comes from `data.json` and is listed under "Data used".
- The Worker forwards each turn to the Claude API. It fixes the model, the one allowed tool, the system prompt and the size limits, and only answers requests from your site.
- Without the Worker the charts and tables still work. The question box says it is turned off.
- Opened inside Claude (as an artifact), the page uses Claude directly and needs no Worker.

## Code walkthrough

Start here if you're new to the project; each file does one job in the pipeline above.

**`iti_datagovin.py`** — the scraper. `TABLES` is the heart of it: one entry per data.gov.in
resource, each a hand-written spec mapping that table's column names to `(metric, breakdown,
period)`. There's no schema to infer because every Rajya Sabha answer table has a different
layout, so a new source always means adding an entry here (see "Add to it over time" below).
`norm_state()`/`STATES` collapse the many spellings of each state name to one canonical form;
`parse_period()` turns a column header or value into a session label (`"2019-20"`). After every
table is fetched and parsed into `long.csv`, the script re-groups by `(state, metric, breakdown,
period)` across all sources to build `conflicts.csv` (same cell, different values — see below)
and `totals_check.csv` (does a table's own "Total" row match the sum of its states).

**`build_dashboard_data.py`** — the merge step. It re-reads `long.csv` plus any CSV dropped in
`extra/`, groups by the same key as above, and for each group keeps the value from the
latest-published table (ties broken by resource id) — this is "where tables disagree, the newest
answer wins," the same rule `iti_datagovin.py` uses for `conflicts.csv`. The result is one flat
array of rows (`[kind, state, metric, breakdown, period, value, source, n_sources, revised]`)
plus the hand-entered `dashboard` array from `dashboard_kpis_by_admission_year.csv`, written to
`dashboard/data.json`. The `built` date is only bumped when the payload actually changes, so the
monthly refresh commits nothing when nothing moved.

**`dashboard/index.html`** — the whole front end, as one file with Chart.js loaded from a CDN.
Reading order inside the `<script>` block:
1. **data** — `load()` fetches `data.json` and expands the compact row arrays plus the DGT
   dashboard KPIs into one `ROWS` array of objects.
2. **query engine** — `query()` is the single read path over `ROWS`: the overview charts, the
   state explorer and Claude's `query_data` tool all call it, so a chart and an answer can never
   disagree about what a metric means. `catalog()` turns `ROWS` into the plain-text index of
   available data that gets embedded in Claude's system prompt.
3. **charts** — thin Chart.js wrappers (`baseOpts`, `numAxis`, `seriesColor`) shared by the
   overview charts, the state explorer and any chart Claude's answer asks for.
4. **state explorer** — the "compare states" panel; purely derived from `query()`, no network calls.
5. **ask Claude** — `rules()` builds the system prompt (data model, caveats, output format) fresh
   per question; `TOOLS` declares the one tool Claude can call (kept in sync with `QUERY_TOOL` in
   the Worker — see its comment). `ask()` runs the tool loop against whichever backend is
   available: inside Claude it uses `window.claude.use("sample")` directly; on a plain page it
   uses `makeProxy()`, which replays the same loop against the Worker, one HTTP call per round.
6. **boot** — wires up the form, loads the data, and picks a backend (`sample` vs proxy vs "off").

**`worker/src/index.js`** — the Cloudflare Worker. It does not run the tool loop itself; it is a
narrow, stateless forwarder: validate the shape of the incoming messages (`validateMessages`),
attach the fixed model/system prompt/tool/effort (`buildUpstream`), check the origin
(`allowedOrigin`), rate-limit by IP, and relay the Claude API's response back unchanged. Those
three functions are exported and unit-testable without a Workers runtime.

## DGT dashboard vs data.gov.in: what differs

The full comparison (page by page, with an item-by-item coverage table) is in
[iti_data/DASHBOARD_COVERAGE.md](iti_data/DASHBOARD_COVERAGE.md). The headline:

- **Enrolment totals don't match for 2019–2022.** The DGT dashboard's admission-year figures hold
  only part of those candidates — 10% of data.gov.in's total for 2019, ~25–27% for 2020–21, 75%
  for 2022 — apparently only part of the older records were migrated into the new portal. 2023
  onward the two agree almost exactly (100% for 2023), and the dashboard is the only source from
  2024 on (data.gov.in's latest session is 2023-24).
- **Different granularity.** data.gov.in only has state-level figures; the dashboard also breaks
  enrolment down by district, institute, trade and sector, and tracks Assessed/Passed/Certified,
  none of which data.gov.in has after 2016-17 (completions) or 2016-17 (certifications).
- **data.gov.in has the longer history.** It goes back to 2014-15 and also has ITI/seat counts
  (2015–2024), which aren't on the dashboard at all.
- **Within data.gov.in itself, the same state/year is often reported differently by different
  Rajya Sabha answers** — see `iti_data/conflicts.csv` for every case (180 rows). Most are
  provisional-vs-revised figures a few percent apart; a handful (e.g. Ladakh 2018-19, reported as
  both 0 and 75) are clearly one source being wrong. The build always keeps the latest-published
  figure and flags the row `revised` so the dashboard and Claude's answers can say so.

**Practical takeaway:** for 2019–2022 totals, data.gov.in is the better source; for 2024+, or for
anything below state level, only the DGT dashboard (or a fresh ask to DGT/MSDE) has it.

## Run it on your machine

```bash
python3 iti_datagovin.py --out iti_data            # uses the cached tables in iti_data/raw
python3 build_dashboard_data.py                    # writes dashboard/data.json
python3 -m http.server 8000 --directory dashboard  # open http://localhost:8000
```

Python 3.8 or later, standard library only. The question box stays off locally unless you set `proxyUrl` in `dashboard/config.js`.

## Put it on GitHub

1. **Create the repository** on GitHub (public) and push this folder:

   ```bash
   git remote add origin https://github.com/YOUR-USER/YOUR-REPO.git
   git push -u origin main
   ```

2. **Turn on Pages.** Repository → Settings → Pages → Source: **GitHub Actions**. The "Deploy dashboard" workflow publishes `dashboard/` on every push to `main`. The site is at `https://YOUR-USER.github.io/YOUR-REPO/`.

3. **Deploy the answer service** (skip this to keep the question box off):

   ```bash
   cd worker
   # edit wrangler.toml: set ALLOWED_ORIGINS to https://YOUR-USER.github.io  (site only, no path)
   npm install
   npx wrangler login
   npx wrangler secret put ANTHROPIC_API_KEY     # paste the key when asked; it is stored by Cloudflare, not in git
   npx wrangler deploy                           # prints https://iti-explorer-answers.<you>.workers.dev
   ```

4. **Tell the site where the service is.** Repository → Settings → Secrets and variables → Actions → **Variables** → New: `PROXY_URL` = `https://iti-explorer-answers.<you>.workers.dev/ask`. Then Actions → "Deploy dashboard" → Run workflow. The workflow writes this into `dashboard/config.js` on the server; you don't commit it.

5. **Cap the spend.** Anyone who opens the site can ask questions, and your key pays. Use a key from a dedicated workspace in the Anthropic Console and set a monthly spend limit there. The Worker's rate limit (8 requests a minute per visitor, per Cloudflare location) slows abuse but does not cap cost. The origin check stops other websites from using your service from a browser. It does not stop someone calling it directly.

**Cost.** Each question takes 2 to 4 requests to Claude. The model defaults to `claude-opus-5-5` at medium effort. My rough estimate is 10 to 20 US cents per question at current prices (not measured). Change `MODEL` and `EFFORT` in `wrangler.toml` to trade quality for cost, then redeploy. Check answers after any change, since the instructions in `dashboard/index.html` were written and tested against Opus.

**Privacy.** Questions and the data they look up are sent to Anthropic through your Worker. The page says so above the question box.

## Keep the data fresh

The "Refresh data" workflow runs on the 1st of each month (and on demand): it re-downloads the tables, rebuilds `dashboard/data.json`, commits only if something changed, and redeploys. If any table fails to download it stops without committing, so the dashboard never loses data silently. A failed download that has a cached copy keeps the cached copy and logs a warning.

Optional: register for a free key at data.gov.in and store it as the repository secret `DATA_GOV_IN_API_KEY`. Without it the shared sample key is used, which is slower and easy to rate limit.

## Add to it over time

| To add | Do this |
|---|---|
| More data.gov.in tables | `python3 iti_datagovin.py --discover` lists ITI tables not yet used (`iti_data/new_tables.csv`). Add an entry to `TABLES` in `iti_datagovin.py` mapping its columns to (metric, breakdown, period). |
| Figures from the DGT dashboard | Add a row to `iti_data/dashboard_kpis_by_admission_year.csv`. |
| A new source (state admission data, grading results, anything) | Drop a CSV into `extra/` using the columns in `extra/_template.csv` (`kind` is `series`, `snapshot` or `other`; use the state names already in the data). Run `build_dashboard_data.py`. New metrics appear in the state comparison and in Claude's catalog automatically. Add friendly names for new metrics in `LABEL` in `dashboard/index.html`. A newer `published` date wins over an older figure for the same state, metric and period and is marked "revised". |

Questions that need data this project does not have (seat fill rate by ITI, pass rate by trade, trainer vacancy and so on) need new sources. The notes in `iti_data/DASHBOARD_COVERAGE.md` list what is missing and where it might come from.

## Files

| Path | What it is |
|---|---|
| `iti_datagovin.py` | Downloads and merges the data.gov.in tables into `iti_data/` |
| `build_dashboard_data.py` | Turns `iti_data/` and `extra/` into `dashboard/data.json` |
| `dashboard/` | The site: `index.html`, `data.json`, `config.js` |
| `worker/` | The Cloudflare Worker (answer service) |
| `iti_data/` | Merged CSVs, the cached source tables (`raw/`) and the coverage notes |
| `datagovin_iti_skilling_inventory.csv` | All 949 skilling-related datasets found on data.gov.in |
| `.github/workflows/` | Deploy and monthly refresh |
| `LICENSE` | MIT licence for the code |

## Licence and data terms

The code is MIT-licensed (see [LICENSE](LICENSE)). The data is published by the Government of India on data.gov.in under its open data terms, and the DGT dashboard figures were read from a public page. Check both sources' terms before reusing the data commercially.
