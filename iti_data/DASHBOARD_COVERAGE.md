# ITI data: DGT dashboard vs data.gov.in

Checked 2026-10-07. Dashboard: "DGT Schemes Dashboard" (Power BI, embedded on
dgt.skillindiadigital.gov.in, last refreshed 07-10-2026). data.gov.in: 55 tables
merged by `iti_datagovin.py` (see `manifest.csv`).

## Bottom line

data.gov.in does **not** cover everything on the dashboard. It covers the
state-level enrolment trend and ITI counts well, and covers 2014–2022 better than
the dashboard does. It has nothing at district, institute or trade level for
recent years, and no assessed/passed/certified figures after 2016.

## What the dashboard contains

Scheme filter: CTS only. Admission years 2019–2026.

| Page | Visuals |
|---|---|
| Summary | Funnel: Enrolled, Trained, Assessed, Passed, Certified · Top 5 institutes by trained · Decomposition tree State → District → Institute → Gender · Top 10 trades by trained · Top 10 sectors by trained |
| Candidate Details | Enrolled by gender · by institute type (Govt/Pvt) × gender · by institute · by state (map) · by trade |
| Matrix Data | Table builder: any of State, District, Institute name/code/type, Trade name/type, Sector × Enrolled, Trained, Assessed, Passed, Certified |
| Filters (all pages) | Admission year, Exam session, State, District, Institute, Institute type, ITI code, Trade, Trade type, Institute location type, Scheme, Trade duration |

## Coverage, item by item

| Dashboard item | On data.gov.in? | Where / gap |
|---|---|---|
| Enrolled, national & state, by year | **Yes**, 2015-16 → 2023-24 | `panel_state_year.csv` `enrolled` |
| Enrolled by gender, state | Partly, 2019-20 → 2021-22 | `enrolled_male`, `enrolled_female` |
| Enrolled by social category | Partly, 2018-19 → 2020-21 (OBC/SC/ST/Gen/Divyang) | not on dashboard either |
| Trained | Only 2014-15 → 2017-18 (true completions) | after 2018 MSDE's "trained" = enrolled |
| Assessed | **No** | — |
| Passed | **No** | — |
| Certified | Only 2014-15 → 2016-17 | `certified` |
| By institute type (Govt/Pvt) | Counts of ITIs only, not candidates | `snapshot_state.csv` `itis_govt`, `itis_pvt` |
| By district | **No** national series; one-offs for Karnataka, Punjab, Rajasthan, West Bengal, Chhattisgarh | not merged |
| By institute | **No** | — |
| By trade / sector | **No**, except new-age trades 2022-23 → 2024-25 and tourism trades | not merged |
| Exam session, trade duration, location type | **No** | — |
| Admission years 2024, 2025, 2026 | **No** | latest data.gov.in session is 2023-24 |
| Number of ITIs, seats | Not on dashboard | data.gov.in only: `snapshot_state.csv`, 2015 → 2024 |

## Enrolment reconciliation (All India)

The dashboard's yearly figures add up exactly to its all-years cards (Enrolled
58,31,787; Trained 42,63,802; Passed 38,50,350; Certified 28,92,072), so the
readings below are reliable. Full readings: `dashboard_kpis_by_admission_year.csv`.

| Admission year | Dashboard enrolled | data.gov.in enrolled (session) | Dashboard / data.gov.in |
|---|---:|---:|---:|
| 2019 | 1,30,323 | 13,59,489 | 10% |
| 2020 | 3,24,970 | 12,19,446 | 27% |
| 2021 | 3,08,330 | 12,25,851 | 25% |
| 2022 | 9,39,877 | 12,50,679 | 75% |
| 2023 | 14,47,395 | 14,46,247 | **100%** |
| 2024 | 13,28,065 | — | — |
| 2025 | 13,02,346 | — | — |
| 2026 | 50,482 (admissions in progress) | — | — |

The dashboard is complete only from admission year 2023. For 2019–2022 it holds
a fraction of candidates, apparently only part of the older records were
loaded into the new portal. **For 2019–2022, data.gov.in is the better source for
totals; for 2024 onwards the dashboard is the only one.**

## Caveats in the data.gov.in tables

- Calendar-year columns ("2019") equal session columns ("2019-20"); the script maps them.
- "Trained" in answers from ~2018 onwards matches enrolment state-for-state; those
  tables are mapped to `enrolled`.
- Answers from 2021–22 report higher 2019-20/2020-21 enrolment than later answers
  (provisional, revised down). The script keeps the latest-published value; every
  version is in `conflicts.csv`.

## To get what's missing

Assessed/passed/certified, district, institute and trade detail, and admission
years 2024+, exist only in the dashboard (Matrix Data page) or DGT's own systems.
Options: export from the Matrix Data page by hand, or ask DGT/MSDE for an extract.
