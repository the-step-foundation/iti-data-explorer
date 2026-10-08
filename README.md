# ITI Data Explorer

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

## Licence and data terms

No licence file is included yet. Until you add one, others cannot legally reuse the code; choose one before sharing widely. The data is published by the Government of India on data.gov.in under its open data terms, and the DGT dashboard figures were read from a public page. Check both sources' terms before reusing the data commercially.
