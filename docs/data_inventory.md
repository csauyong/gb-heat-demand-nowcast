# Data inventory

Candidate sources for both projects. Compiled 2026-08-14.

**How to read this.** "Publication lag" is the gap between the period a
datum describes and the moment it became public. That gap — not the period
label — determines whether a feature is legal under the point-in-time rule in
`CLAUDE.md` §2. Anything marked **LEAK RISK** is usable for diagnostics only.

**Verify before you rely.** Licence terms and API endpoints change. Every
figure below should be re-checked against the source at the time you write the
loader, and the loader docstring records what you actually found (`CLAUDE.md`
§7).

---

## Summary: free vs paywalled

| Source | Free? | Notes |
|---|---|---|
| EPC Open Data (England & Wales) | **Free** | Free account + API key. OGL, except address/postcode fields |
| NESO Data Portal (demand, DA forecast) | **Free** | Open licence, CKAN API, no key |
| Elexon Insights / BMRS | **Free** | Free API; registration for some routes |
| National Gas Data Portal (NTS) | **Free** | Free; SOAP→REST migration in progress |
| Open-Meteo (forecast archive + ERA5 archive) | **Free** | CC-BY 4.0 data; free tier ≤10k calls/day non-commercial |
| ERA5 via Copernicus CDS | **Free** | Free account, CDS API key |
| Met Office HadUK-Grid (CEDA) | **Free** | Free CEDA account, OGL v3 |
| ONS Open Geography Portal | **Free** | OGL v3 |
| yfinance / Yahoo Finance | **Free (unofficial)** | No licence for redistribution — see caveat |
| **NBP forward curves / assessed prices** | **PAYWALLED** | Commercial. See §10 |
| **ICE/EEX settlement price history** | **PAYWALLED** | Delayed/limited free views only |
| Commercial NWP (ECMWF HRES operational) | **PAYWALLED** | Free open-data subset exists — see §5.3 |
| Scottish EPC register | Free but separate | Different publisher, different format |
| **Xoserve Postcode Exit Zone List** | **Free** | Postcode→LDZ, no registration. See §12 |

---

## 1. EPC Open Data — England & Wales

**Use:** Project A. The dwelling stock: floor area, wall/roof/floor
construction and insulation, glazing, main heating fuel and system,
efficiency ratings, at address level, aggregatable to LSOA.

- **URL:** https://epc.opendatacommunities.org/ (legacy);
  **bulk download has moved** to
  https://api.get-energy-performance-data.communities.gov.uk/api/files/domestic/csv
  — **verified 2026-08-15**, see the amendment note below.
- **Publisher:** MHCLG (Ministry of Housing, Communities and Local Government)
- **Access method:** (a) REST API with an API key — free registration via
  GOV.UK One Login, HTTP Basic auth with email + key; (b) bulk CSV download of
  the full register (~5–6 GB, all certificates including expired), or smaller
  per-local-authority files. **Use the bulk download for stock construction**;
  the API is rate-limited and paginated and is the wrong tool for a national
  panel.
- **Licence:** Open Government Licence v3.0, **with an important exception** —
  address and postcode fields carry more restrictive Royal Mail / Ordnance
  Survey terms. You may use them for the analysis; do not redistribute
  address-level data or commit it. Aggregate to LSOA before anything leaves
  `data/raw/`.
- **Update frequency:** Quarterly bulk refresh; API updated more often.
- **Publication lag:** A certificate is lodged within days of assessment, but
  the **quarterly bulk release means an effective lag of up to ~3–4 months**.
  For a nowcast this barely matters — the stock evolves slowly (~1–2% of
  dwellings gain a new EPC per year) — but the vintage must still be recorded,
  and a backtest of 2023 must not use the 2026 stock snapshot without
  acknowledging it.
- **Known problems, and they are serious:**
  - **Coverage is not the stock.** EPCs are triggered by sale, new build, or
    let. Roughly half of GB dwellings have one, and coverage is *selected* —
    rented and recently-transacted property is over-represented, long-held
    owner-occupied property under-represented. Any LSOA aggregate needs a
    reweighting step against ONS dwelling counts, and the reweighting is a
    modelling assumption that must be tested.
  - **Duplicates.** Multiple certificates per address over time. Deduplicate to
    latest-per-address *as of the analysis date*, not latest-ever (that is a
    leak).
  - **RdSAP is a model, not a measurement.** Floor areas and U-values are
    assessor estimates with known biases. Treat as noisy.
  - **RdSAP 10 / SAP 10.2 methodology changes** shift ratings discontinuously
    at the changeover; do not read a level shift as a physical change.
> **Amendment 2026-08-15 (Phase 1b).** The bulk route is now a bearer-token API,
> not HTTP Basic with email + key:
>
> ```
> GET https://api.get-energy-performance-data.communities.gov.uk/api/files/domestic/csv
> Authorization: Bearer <token>
> ```
>
> It 303-redirects to a presigned S3 object, `full-load/domestic-csv.zip`:
> **7.57 GB compressed, 87.8 GB uncompressed**, 36 members partitioned as
> `certificates-YYYY.csv` and `recommendations-YYYY.csv` for 2009–2026.
> Schema is **93 lowercase columns** (`postcode`, `uprn`, `lodgement_date`,
> `current_energy_efficiency`, `total_floor_area`, `construction_age_band`,
> `walls_description`, `main_fuel`, `mains_gas_flag`, `tenure`, …) — *not* the
> old uppercase `LMK_KEY` schema.
>
> **There is no LSOA column.** `postcode` is the only fine geography, so any
> LSOA or LDZ work needs a postcode lookup (see §6 and §12).
>
> The year partition means a point-in-time snapshot never needs to download
> years after the cutoff. Streaming the members over HTTP Range avoids landing
> 88 GB on disk — see `src/heat_nowcast/data/epc.py`.
>
> As at 2026-08-12 vintage: **23,076,423 certificates** lodged ≤ 2023-11-30,
> deduplicating to **17,741,503 dwellings**.

- **Scotland:** separate register, separate publisher
  (https://www.scottishepcregister.org.uk/). Different schema. Either
  incorporate it explicitly or scope the project to England & Wales and state
  that GB aggregation uses a Scotland uplift factor. **Do not silently ignore
  Scotland while claiming a GB model.**

---

## 2. NESO Data Portal — demand outturn and day-ahead forecast

**Use:** Project A. The truth series and the competitor forecast.

- **URL:** https://www.neso.energy/data-portal/
- **Publisher:** National Energy System Operator (NESO — took over from
  National Grid ESO in October 2024; older material and URLs still say ESO)
- **Access method:** CKAN Data API (`datastore_search_sql` / `datastore_search`)
  plus direct CSV resource download. No API key required.

### 2.1 Historic Demand Data

- **Dataset:** `historic-demand-data`, one resource per year
  (e.g. `historic_demand_data_2026`)
- **Content:** half-hourly National Demand (ND), Transmission System Demand
  (TSD), England–Wales demand, interconnector flows, embedded wind and solar
  estimates.
- **Frequency:** updated daily (also see `Demand Data Update` /
  `demand_data_update` for the daily-refresh resource).
- **Publication lag:** ~1 day for initial values; **subject to restatement**.
  Embedded wind/solar estimates in particular are revised.
- **Critical definitional point:** ND excludes station load, pumped-storage
  pumping and interconnector exports; TSD includes them. **Neither is domestic
  heat demand.** Both are *transmission-metered* and therefore net of embedded
  generation and net of everything behind the distribution boundary. A
  bottom-up domestic heat model predicts a component that is not directly
  observable in either series. This gap is the central measurement problem in
  Project A and must be handled explicitly, not assumed away.

### 2.2 Day Ahead Demand Forecast (the baseline to beat)

- **Datasets:** `1-day-ahead-demand-forecast` →
  `historic_day_ahead_demand_forecasts` (archive from 2018 to present) and
  `day_ahead_national_demand_forecast`; also `2-day-ahead-demand-forecast`.
- **Publication lag:** published on D-1 for delivery day D, at a known time of
  day. **Record the publication timestamp** — it defines the earliest moment
  the baseline (and anything conditioned on it) is knowable.
- **Also useful:** `day-ahead-half-hourly-demand-forecast-performance` — NESO's
  own published forecast error. This gives you the incumbent's error
  distribution for free and is the natural target for Project A claim 2.

### 2.3 Other NESO resources worth pulling

- `demand-profile-dates` — the triad and profiling calendar.
- Embedded generation estimates — needed to reconcile transmission-metered
  demand with underlying demand.
- **Licence:** NESO open data licence, OGL-compatible. Attribution required.

---

## 3. Elexon — Insights Solution / BMRS

**Use:** Project A. Settlement-grade demand, generation by fuel type, imbalance
prices, and the market data any signal would actually trade against.

- **URL:** https://developer.data.elexon.co.uk/ (developer portal);
  https://bmrs.elexon.co.uk/ (Insights UI);
  API base `https://data.elexon.co.uk/bmrs/api/v1/`
- **Access method:** REST/JSON. Free. Many endpoints are open; registration for
  an API key is available and required for some routes and for the Data Push
  service. Python wrappers exist (`ElexonDataPortal`, `elexon`) but check they
  target the current v1 API rather than the retired legacy BMRS.
- **Licence:** Free of charge to all users under Elexon's BMRS API terms —
  a revocable, non-transferable, limited licence. **Read the terms before
  publishing derived data**: it is free to use, but it is not OGL and it is not
  unconditionally redistributable.
- **Update frequency:** near-real-time for operational data; settlement data
  arrives in runs.
- **Publication lag — the part that matters:** settlement data is restated
  through Interim Initial (II) → Settlement Final (SF) → R1 → R2 → R3 → Final
  Reconciliation (RF), over **months**. **LEAK RISK:** using a final-run volume
  in a backtest of a gate-closure decision is a leak. Use II or the run
  available at the time, or state the contamination.
- **Specific series of interest:** INDO/ITSDO (initial national/transmission
  demand outturn), rolling system demand, generation by fuel type, MID (market
  index data — the reference price a power signal would trade against), system
  prices, and the physical notifications / BOA data if execution modelling gets
  detailed.

---

## 4. National Gas — NTS demand

**Use:** Project A. Gas-side demand, which is where domestic heat actually
shows up — roughly 85% of GB homes heat with gas, so the gas signal is the
stronger test of a domestic heat model than the electricity signal.

- **URL:** https://www.nationalgas.com/data-and-operations/ (Gas Data Portal);
  legacy MIPI at `marketinformation.natgrid.co.uk`
- **Access method:** Data Portal UI plus API. **Migration complete —
  verified 2026-08-14.** The SOAP MIPI service at `marketinformation.natgrid.co.uk`
  is **dead** (connection fails); National Gas describes the SOAP APIs as
  "permanently decommissioned". The documented REST catalogue at
  https://apideveloper.nationalgas.com/ sits behind account registration. The
  Gas Data Portal serves the same operational data **anonymously**:

  ```
  POST https://data.nationalgas.com/api/find-gas-data
  Content-Type: application/json
  User-Agent: <required — returns 403 without one>

  {"latestFlag":"N","applicableFor":"Y","dateFrom":"2025-01-01",
   "dateTo":"2025-12-31","dateType":"GASDAY","ids":"PUBOB609,PUBOB624"}
  ```

  Publication-object ids are harvested from
  `GET https://data.nationalgas.com/api/find-gas-data-folders` and should be
  **pinned in code**, not resolved at import, so a portal reorganisation cannot
  silently change which series a cached backtest used.
> **Amendment 2026-08-15 (Phase 1b) — the point-in-time trap on this source.**
> `Demand Forecast, LDZ (XX)` is **republished ~8 times per gas day**: 13:15 and
> 16:15 on D-1, then 00:15 / 10:15 / 13:15 / 16:15 / 21:15 on D, plus a final
> value at 00:15 on **D+1**. The portal default `latestFlag=Y` returns the
> **last** of these — generated *after the gas day has ended*. Scoring it as a
> day-ahead forecast is a severe leak: a near-outturn estimate wearing a
> forecast's name. Pull `latestFlag=N` and gate on `generatedTimeStamp`.
>
> The publication timestamp's timezone is **not determinable from the data** —
> times are identical in January and July, so the Phase 1 winter-vs-summer trick
> fails. Gate on **calendar dates**, which is correct under either reading.
>
> History for LDZ demand actuals (D+1 and D+6 vintages), the LDZ demand
> forecast, and forecast/actual CWV all begins **2021-12-01**. The D+1/D+6 pair
> is a genuine vintage pair of the kind `CLAUDE.md` §2.2 asks for: measured
> restatement is mean-absolute 0.068 mscm/day (0.76% of offtake), 83.8%
> unrevised.

- **Licence:** free to access; check the portal terms for redistribution.
- **Series of interest:** NTS LDZ (Local Distribution Zone) offtakes — this is
  as close to a direct measurement of domestic + small commercial heat demand
  as GB open data provides, and it is the natural validation target for a
  bottom-up domestic heat model, better than electricity demand. Also:
  aggregate NTS demand, forecast vs actual demand (D+1, within-day), linepack,
  Composite Weather Variable (CWV).
- **Publication lag:** within-day forecasts and actuals publish intraday; D+1
  actuals next gas day; reconciled figures later.
- **Gas day convention:** 05:00–05:00 UTC. **This is not the electricity day.**
  Mixing them is a leak and a silent one.
- **CWV is worth studying regardless** — the industry's own weather-to-gas-
  demand transform, published per LDZ. It is effectively the incumbent
  baseline on the gas side and a natural comparator alongside your HDD model.

---

## 5. Weather

The weather question is the single most important design decision in Project A,
because it is where the leak lives (`CLAUDE.md` §2.1).

### 5.1 Open-Meteo Historical Forecast API — **the point-in-time source**

- **URL:** https://open-meteo.com/en/docs/historical-forecast-api
- **What it is:** an archive of **what the forecast models actually said at the
  time**, initialised daily, from 2021 (some models 2022) onward. This is the
  series a point-in-time nowcast must use.
- **Access method:** REST/JSON, no API key on the free tier.
- **Licence:** data served under **CC BY 4.0** — attribution required,
  commercial use permitted. Free tier: non-commercial use up to ~10,000 calls
  per day; paid tiers above that. Self-hosting is possible for high volume.
- **Publication lag:** none — that is the point; it is archived forecast.
- **Constraint:** archive begins 2021. That caps the point-in-time backtest
  window at roughly five years. **Plan the evaluation around this**: ~5 winters
  is a small sample for a heating-signal study, and that fact should be stated
  up front rather than discovered at the end. It also constrains how many
  specifications you can honestly try.

### 5.2 Open-Meteo Historical Weather (ERA5-backed) / ERA5 direct

- **Open-Meteo archive:** https://open-meteo.com/en/docs/historical-weather-api
  — ERA5/ERA5-Land served through the same simple API, 1940→present.
- **ERA5 direct:** https://cds.climate.copernicus.eu/ — Copernicus Climate Data
  Store, free account, `cdsapi` Python client, CDS API key in `~/.cdsapirc`.
- **Licence:** Copernicus licence — free, attribution required.
- **Publication lag:** **~5 days** for the ERA5T preliminary release
  (`expver=5`); **~2–3 months** for the quality-controlled final release
  (`expver=1`), which overwrites the preliminary values. Both facts matter: the
  5-day lag alone disqualifies ERA5 from any nowcast, and the silent overwrite
  means an ERA5 pull is not reproducible unless you record the download date.
- **Status: `REALISED-WEATHER-DIAGNOSTIC` only.** Use for model-error
  decomposition and oracle upper bounds. Never in a signal.

### 5.3 ECMWF open data (optional, more work)

- **URL:** https://www.ecmwf.int/en/forecasts/datasets/open-data
- ECMWF publishes a free open-data subset of its operational forecasts
  (coarser resolution, subset of parameters) under CC-BY-4.0. Real-time only —
  there is no deep free archive — so it is not a substitute for Open-Meteo's
  historical forecast archive for backtesting, but it is the free route if the
  project ever runs forward in live mode. Full-resolution operational HRES is
  **paywalled**.

### 5.4 Met Office HadUK-Grid

- **URL:** https://catalogue.ceda.ac.uk/ (search HadUK-Grid);
  https://www.metoffice.gov.uk/research/climate/maps-and-data/data/haduk-grid/
- **Access method:** CEDA Archive, free registered account, HTTP/FTP or
  `ceda-download`. NetCDF.
- **Licence:** Open Government Licence v3.0.
- **Resolutions:** 1 km, 5 km, 12 km, 25 km, 60 km. Daily grids for temperature
  and rainfall; monthly for more variables.
- **Publication lag: annual.** A new version is released roughly yearly —
  v1.3.2.ceda (June 2026) covers to end-2025. Provisional recent-month data is
  published separately to extend the series.
- **Status: `REALISED-WEATHER-DIAGNOSTIC` only,** and even for diagnostics the
  annual release makes it awkward for recent periods.
- **Where it genuinely earns its place:** the 1 km grid is the right tool for
  **LSOA-level spatial weighting** — building the population- and stock-
  weighted temperature index that maps dwelling locations to a weather series.
  Estimate the spatial weighting scheme on HadUK-Grid climatology, then apply
  that fixed scheme to forecast weather at run time. The *scheme* is estimated
  on realised data; the *values* fed to the signal are forecast. That is legal.
  Document it clearly, because it looks like a leak until explained.

---

## 6. ONS — LSOA boundaries, population, dwelling counts

**Use:** Project A. The spatial backbone and the reweighting denominators.

- **URL:** https://geoportal.statistics.gov.uk/ (Open Geography Portal);
  https://www.ons.gov.uk/ for statistical tables;
  https://www.nomisweb.co.uk/ for census tables via API
- **Access method:** Open Geography Portal serves ArcGIS FeatureServer and
  GeoJSON endpoints per product ("View API Resources" gives GeoService and
  GeoJSON URLs); bulk shapefile/GeoPackage download also available. Nomis has a
  clean REST API for census tables.
- **Licence:** Open Government Licence v3.0 (contains OS data © Crown copyright
  and database right — attribution string required).
- **Products needed:**
  - LSOA 2021 boundaries (BFC full-clipped for area work, BGC generalised-
    clipped for mapping, BSC super-generalised for fast joins);
  - LSOA population and household counts (Census 2021);
  - **Dwelling counts by LSOA** — the denominator for EPC coverage
    reweighting, and the thing that makes the EPC selection problem tractable;
  - LSOA population-weighted centroids — for weather grid attribution;
  - Postcode-to-LSOA lookup (ONSPD / NSPL) — for joining EPC addresses.
- **Publication lag:** boundaries are static per census; population estimates
  annual with ~12-month lag. Not a constraint for this project.
- **Watch:** LSOA 2011 vs LSOA 2021 are different geographies. EPC records
  and older data may carry 2011 codes. Use the official lookup, and note that
  some LSOAs split or merged, so the mapping is not one-to-one.
- **Scotland:** LSOA has no Scottish equivalent — use Data Zones from
  https://spatialdata.gov.scot/. Another reason to scope carefully.

---

## 7. Equity prices — yfinance

**Use:** Project B.

- **Access method:** `yfinance` Python package against Yahoo Finance.
- **Licence: this is the weak link.** Yahoo Finance has **no public data
  licence** permitting programmatic bulk access or redistribution; `yfinance`
  is an unofficial scraper and its use is against Yahoo's terms. It is fine for
  a personal research project and is what most published event-study
  replication code uses, but:
  - **do not redistribute the price data** in the repo (already covered by the
    `data/` gitignore);
  - **state the source and its unofficial status** in the report;
  - be aware the API breaks without notice and historical values are
    occasionally revised silently.
- **Adjustment:** use `auto_adjust` deliberately and understand what it does.
  For event studies, total return (dividend-reinvested) is usually correct, but
  the adjustment factors are applied retroactively across the whole series —
  **a split in 2025 rewrites the 2020 prices**. For a strict point-in-time
  study, reconstruct returns from unadjusted prices plus a dated corporate
  action schedule, or state the approximation.
- **Free alternatives worth knowing:** Stooq (free daily EOD, ex-London
  coverage is patchy), Alpha Vantage (free tier, 25 calls/day, official terms),
  LSEG/Refinitiv and Bloomberg (paywalled; check university entitlement —
  as a PhD student you may already have WRDS, Datastream or Compustat access
  through your institution, and **if you do, use it**: institutional data with
  a proper licence is strictly better here and removes the yfinance caveat
  entirely). **Check this before building on yfinance.**
- **Universe for Project B:** housebuilders (Barratt Redrow, Persimmon,
  Taylor Wimpey, Bellway, Berkeley, Vistry, Crest Nicholson); insulation and
  building materials (Kingspan (IE), Rockwool (DK), SIG, Marshalls, Ibstock,
  Genuit, Travis Perkins); utilities and suppliers (Centrica, SSE, National
  Grid, Drax); residential landlords / REITs (Grainger, PRS REIT, Unite,
  Segro as a control). **Donor pool must be index membership as of the event
  date** (`CLAUDE.md` §2.4) — reconstruct FTSE 350 constituents historically,
  do not use today's index.

---

## 8. Policy announcement dates — Project B

Not in the original list but this is the project's primary input and deserves
the same provenance discipline.

- **Sources:** GOV.UK announcements and publications API
  (https://www.gov.uk/api/search.json — free, OGL, filterable by
  organisation and date); Hansard API (https://hansard-api.parliament.uk —
  free, OGL); Ofgem publications; DESNZ press releases; HM Treasury Budget and
  Spending Review documents.
- **Access method:** REST/JSON, free, no key.
- **Licence:** OGL v3.
- **Method note:** GOV.UK gives publication *date* reliably and publication
  *time* less reliably. Where the time is not recoverable, say so and widen the
  event window rather than guessing. Cross-check against news wire timestamps
  for the major announcements.
- **Candidate events:** ECO scheme phases (ECO3, ECO4, ECO+/GBIS), Boiler
  Upgrade Scheme launch and uplift, Green Homes Grant launch and cancellation
  (2020 — an unusually clean shock), MEES / minimum EPC rating for rentals
  (including the 2023 rollback announcement, which is a clean *negative* shock
  for insulation names), Future Homes Standard consultations and decisions,
  gas boiler phase-out date changes, Great British Insulation Scheme, Warm
  Homes Plan. **The 2023 policy rollback is probably the highest-value single
  event** — it was unscheduled, directional, and had clearly exposed names.

---

## 9. Calendar and holidays

- UK bank holidays: https://www.gov.uk/bank-holidays.json (free, OGL,
  England & Wales / Scotland / NI separately — they differ, and Scotland
  differing matters for a GB demand model).
- School holidays materially affect demand and are **not** available as a
  clean national series; local authority level, messy. Approximate and
  document the approximation.

---

## 10. Paywalled series and free proxies

**Be explicit: NBP forward curves are commercial data.** Assessed forward
prices and curve marks for UK NBP gas come from ICIS Heren, Argus, or LSEG.
There is no free source for a full NBP forward curve, and any project claiming
one is either using stale scraped data or misdescribing what it has.

| Wanted (paywalled) | Why it matters | Free proxy | What you lose |
|---|---|---|---|
| **NBP forward curve** (ICIS Heren / Argus / LSEG) | The tradeable instrument for a gas-demand signal beyond spot | ICE UK NBP futures front-month settlement from public/delayed sources; front-month continuous series via yfinance/Stooq where available; **or** restrict the study to day-ahead / within-day, where prices are observable | No curve shape, no seasonal spreads, no term structure. Restricting to DA/WD is the honest move and keeps the point-in-time story clean |
| **GB power forward curve** (EEX/ICE settlements) | Same, power side | Elexon MID (market index data) for the DA reference price; N2EX/EPEX day-ahead auction results (published, limited free access) | Front of curve only |
| **ICE/EEX full settlement history** | Backtest instrument prices | Delayed/limited free views on exchange sites; front-month continuous futures via free equity-data routes | Sparse history, no depth, no intraday |
| **Commercial NWP (ECMWF HRES full res, DTN, Speedwell)** | What the incumbent forecaster actually uses | Open-Meteo historical forecast archive (§5.1); ECMWF open data subset (§5.3) | Coarser resolution, fewer ensemble members. **This is a real and quantifiable disadvantage vs NESO and should be named as one in the write-up, not hidden** |
| **Speedwell / commercial UK weather indices** | Standardised HDD/CDD definitions for weather derivatives | Construct your own from Open-Meteo/HadUK-Grid; National Gas CWV is a published free analogue | Not the market-standard index, so not directly tradeable against weather derivatives |
| **Half-hourly settlement / smart meter consumption microdata** | Direct measurement of domestic demand | Smart Energy Research Lab (SERL) Observatory — free to academics via UK Data Service, application required, **you likely qualify**; NESO elexon profile classes as a coarse fallback | SERL needs an application and lead time. **Worth starting early** — it is the closest thing to ground truth for domestic heat and would materially strengthen Project A |
| **EPC + tenure/income linked microdata** | Better stock reweighting | ONS Census 2021 aggregate tables via Nomis; English Housing Survey (UK Data Service, free to academics) | Aggregate not individual |

### Institutional access — check this first

Before paying for or working around anything above: as a registered PhD
researcher you may already have entitlement to LSEG Datastream, WRDS,
Bloomberg (campus terminal), and UK Data Service SecureLab. **Using
institutional data with a proper licence removes the yfinance licensing
caveat and gives you survivorship-bias-free index constituents**, which is
the single biggest methodological upgrade available to Project B for zero
cost. Check with the library before building loaders around free proxies.

---

## 12. Gas Local Distribution Zone geography — Xoserve Postcode Exit Zone List

**Use:** Project A Phase 1b onward. Maps dwellings (via EPC `postcode`) to the
13 gas Local Distribution Zones that National Gas publishes demand and
forecasts for.

**Why this and not boundary polygons.** LDZ is a **gas-industry operational
geography**, not a statistical one — the area served by one distribution
network downstream of the NTS, inherited from the regional gas boards. ONS does
not publish it, so there is no LSOA-style boundary product, and **LSOA
boundaries cannot resolve it**: knowing a dwelling's coordinates tells you
nothing about its LDZ without LDZ geometry. Xoserve's list sidesteps geometry
entirely.

- **URL:** https://www.xoserve.com/a-to-z/ → "Postcode Exit Zone List"
  (`https://www.xoserve.com/media/2008/postcode-exit-zone-list-may-2017.zip`)
- **Publisher:** Xoserve, the gas industry's central data agent, compiling
  submissions from the Distribution Network Operators.
- **Access method:** direct download, no registration. 23 MB zip containing a
  34 MB xlsx with one sheet per network (WWU, SGN, NGN, NG).
- **Licence:** published freely by Xoserve for the GB gas DNOs. **Not OGL.**
  Free to access; check Xoserve's terms before redistributing derived data.
- **Content:** 1,382,477 rows of `Outcode` + `Incode` → `LDZ`, `Exit Zone`,
  `LPG Indicator`; 1,377,265 usable full postcodes after cleaning.
- **Authoritative, not approximate:** this is the mapping used for gas
  settlement, so it is the definition rather than an estimate of it.
- **Vintage: May 2017.** Older than a 2023 analysis cutoff, which is the *safe*
  direction — it cannot carry information from after the cutoff. But postcodes
  created since 2017 do not match; against the 2026-08 EPC register, **79.0%
  matched on full postcode and 21.0% needed an outcode fallback**.
- **Outcode alone is not sufficient: 188 of 3,100 outcodes (6.1%) span more
  than one LDZ.** Match on full postcode; fall back to outcode only where that
  outcode maps unambiguously to one zone, and leave the rest unmatched rather
  than guessing — the error would land directly on the regressor of interest.
- **18 LDZ codes, of which 13 matter.** The five others (LC, LO, LS, LT, LW,
  ~1,045 postcodes) are LPG or otherwise isolated networks, not on the NTS,
  with no published LDZ demand series. That the remaining thirteen match the
  National Gas LDZ set exactly is a useful independent check on the panel
  definition.
- **Coverage note:** the EPC register is England & Wales only, so the **SC
  (Scotland) zone receives only ~478 dwellings** — border postcodes, not
  coverage. Any LDZ stock feature is missing for SC and must say so rather than
  impute.

---

## 11. Attribution block

Any published output must carry, as applicable:

- "Contains public sector information licensed under the Open Government
  Licence v3.0."
- "Contains OS data © Crown copyright and database right 2026."
- "Contains Royal Mail data © Royal Mail copyright and database right 2026."
- "Contains National Statistics data © Crown copyright and database right 2026."
- "Weather data by Open-Meteo.com, licensed CC BY 4.0."
- "Generated using Copernicus Climate Change Service information 2026."
- "Contains data from Elexon Limited, used under the BMRS API terms."
- "Contains National Gas Transmission data, accessed via the Gas Data Portal."
- "Contains Xoserve Postcode Exit Zone data, published for the GB gas Distribution Network Operators."
- "Contains NESO data, © National Energy System Operator."

---

## Sources

- [EPC Open Data Communities — copyright and licence](https://epc.opendatacommunities.org/docs/copyright)
- [MHCLG blog — changes to the EPC open data service](https://mhclgdigital.blog.gov.uk/2024/01/29/changes-to-the-energy-performance-certificates-open-data-service)
- [NESO Data Portal](https://www.neso.energy/data-portal)
- [NESO Historic Demand Data](https://www.neso.energy/data-portal/historic-demand-data)
- [NESO Historic Day Ahead Demand Forecasts](https://www.neso.energy/data-portal/1-day-ahead-demand-forecast/historic_day_ahead_demand_forecasts)
- [NESO Day Ahead Half Hourly Demand Forecast Performance](https://www.neso.energy/data-portal/day-ahead-half-hourly-demand-forecast-performance/day_ahead_half_hourly_demand_forecast_performance)
- [Elexon API Developer Portal](https://developer.data.elexon.co.uk/)
- [Elexon — licence to use BMRS APIs](https://www.elexon.co.uk/bsc/data/balancing-mechanism-reporting-agent/copyright-licence-use-bmrs-api/)
- [National Gas — Gas Data Portal](https://www.nationalgas.com/our-businesses/operational-data/gas-data-portal)
- [National Gas — Operational Data](https://www.nationalgas.com/our-businesses/operational-data)
- [Open-Meteo licence](https://open-meteo.com/en/licence)
- [Open-Meteo Historical Forecast API](https://open-meteo.com/en/docs/historical-forecast-api)
- [Copernicus — ERA5 hourly data on single levels](https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels?tab=overview)
- [Copernicus — climate dataset at five days behind real time](https://climate.copernicus.eu/key-update-climate-dataset-brings-data-five-days-behind-real-time)
- [CEDA — HadUK-Grid dataset collection](https://catalogue.ceda.ac.uk/uuid/4dc8450d889a491ebb20e724debe2dfb/)
- [Met Office — HadUK-Grid](https://www.metoffice.gov.uk/research/climate/maps-and-data/data/haduk-grid/haduk-grid)
- [ONS Open Geography Portal — API Catalogue](https://www.api.gov.uk/ons/open-geography-portal/)
- [ONS — digital boundaries](https://www.ons.gov.uk/methodology/geography/geographicalproducts/digitalboundaries)
- [ICE — UK NBP Natural Gas Futures](https://www.ice.com/products/910/UK-NBP-Natural-Gas-Futures)
