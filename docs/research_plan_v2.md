# Research plan v2 — Project A after the A3 kill

**Written:** 2026-11-17. **Status:** plan only. No code, no new trials, nothing
committed. Supersedes nothing in `docs/research_plan.md`; it starts where that
plan stopped (kill criterion A3 fired, 2026-08-15).

**For the next session:** read this file, then `CLAUDE.md`, then
`reports/phase1b_findings.md`. Start at "First session checklist" at the bottom.

Two options. **Option 1 is the one to do now** (2–3 weeks, data already on
disk). **Option 2 is parked until after thesis submission (April 2027)** apart
from its feasibility phase, which is cheap.

---

## 0. A correction to carry forward first

`reports/phase1b_findings.md` leads with: National Gas's D−1 LDZ forecast is
"3.8× less accurate on the coldest decile" (MAE 0.422 vs 0.110 mscm/day), read
as a heat-shaped unforecast residual.

That comparison is in absolute units, and offtake on cold days is several times
offtake on warm days. `reports/tables/phase1b_by_season.csv` already shows the
relative picture:

| Season | Incumbent MAE (mscm/day) | Incumbent MAPE | Incumbent bias |
|---|---|---|---|
| Winter | 0.604 | **4.39%** | +0.127 |
| Spring | 0.479 | 5.99% | +0.045 |
| Summer | 0.226 | **6.65%** | −0.049 |
| Autumn | 0.423 | 5.37% | −0.050 |

In relative terms the incumbent is most accurate in winter. The 3.8× figure is
therefore mostly demand level, not forecast failure. What survives is a modest
**winter over-forecast bias** (+0.127 mscm/day; error = forecast − actual).

This has been checked by season only, not by CWV decile. Phase C0 below does
the decile check properly. Until then, do not quote the 3.8× figure anywhere.

---

# Option 1 — Is the published gas demand forecast efficient, and is its error priced?

## Research question

> National Gas republishes its LDZ demand forecast about eight times per gas
> day. (1) Are those forecasts weakly efficient — unbiased, with unpredictable
> revisions and errors given public information at issue time? (2) If not, does
> the predictable component of the error show up in GB gas prices or system
> balance, after costs?

Three claims, tested in order, each can fail alone:

1. **Efficiency fails in-sample** (bias, Mincer–Zarnowitz, Nordhaus revisions).
2. **The inefficiency is exploitable out of sample**: a corrected forecast
   beats the raw incumbent in walk-forward evaluation.
3. **It is priced or tradeable**: the predictable error relates to price or
   balance moves, net of a stated cost model.

Claim 1 failing means "the operator's forecast is efficient" — a clean,
reportable result. Claim 2 failing after claim 1 passes is the most likely
outcome and must be written up as such.

## Why this is the right pivot

- The data is already cached: `data/raw/ng_ldz_demand_forecast_all_pubs_*`
  holds every publication (13:15, 16:15 on D−1; 00:15, 10:15, 13:15, 16:15,
  21:15 on D; 00:15 on D+1) for 13 LDZs from 2021-12-01, plus D+1 and D+6
  actuals and forecast/actual CWV.
- It does not depend on the 12-zone cross-section that killed the stock test.
  Identification is in the time series (≈1,700 gas days) and the vintage
  dimension.
- It ends at a price, which the original project never reached.

## Prior work to read before C1 (not yet a literature review)

- Nordhaus (1987), forecast efficiency via revisions; Mincer & Zarnowitz (1969).
- Thomas, Massol & Sévi (2022, *The Energy Journal* 43(5)): whether day-ahead
  prices predict next-day gas consumption better than TSO forecasts, France.
- Forbes & Zampelli (2014) on electricity load and day-ahead prices.
- One search found no revision-efficiency test for GB LDZ forecasts. Treat
  novelty as unconfirmed until a proper search is done (C1, first task).

## Holdout policy — decide before touching data

> **Amended 2026-11-17 (decision log row 40).** The Phase 1b core test ran on
> 979 gas days ending **2026-08-07** (n = 11,748 = 12 × 979), one day past the
> baseline window. That day is touched, so the boundary moves by one day.

The window 2023-12-01 → 2026-08-07 was scored in Phase 1b. It is contaminated
for anything resembling the Phase 1b tests. Therefore:

- **Development sample:** 2021-12-01 → 2026-08-07.
- **Confirmation sample 1:** 2026-08-08 → date of first pull in the new
  session. Never looked at. Shoulder season only, so low power; say so.
- **Confirmation sample 2 (prospective):** winter 2026/27, scored once in
  March 2027 against the specification frozen now. This is the strongest
  evidence the project can produce; freezing the spec with a dated commit
  before the winter is the point.

## Phase C0 — the scale check (1 day)

**Do:** incumbent error by forecast-CWV decile in (a) MAE, (b) MAPE, (c) MAE
scaled by baseline-fitted demand, and (d) signed mean error with a
day-clustered interval. GB aggregate and per LDZ.

**Outcome, not a kill:** amend the headline of `phase1b_findings.md` with a
dated correction note (do not rewrite history), and log as a new trial.
Determines whether "cold-regime bias" is a pre-specified regime in C1.

## Phase C1 — efficiency tests (4–5 days)

**Build:** vintage panel `f[ldz, gas_day, k]`, k = publication index, with
`generatedTimeStamp`; revisions `r_k = f_k − f_{k−1}`; errors
`e_k = f_k − actual_D+1`. Gate everything on publication date as in
`tests/test_gas_gating.py`.

**Target vintage (added 2026-11-17 after C0, row 42).** The D+1 first-published
actual is sometimes badly wrong: 121 LDZ-days (~1%) restate by more than 10%
from D+1 to D+6, 55 of them in SE (worst: 0.23 vs 3.45 mscm). An error measured
against D+1 partly measures the actual's own error. **Proposed, pending owner
decision 5:** the efficiency target is the **D+6** actual (closer to truth);
the "most recent known error" regressor uses only the vintage published by
issue time; the primary test is reported on both targets with D+6 as headline.

**Unresolved prerequisite:** the publication-timestamp timezone (London vs
UTC) was never determined. C1 can run on ordinal vintages; C2 cannot run
without it. Resolve by documentation or by asking National Gas.

**Compute the MDE first**, by simulation on the real panel, as in Phase 1b.

**Pre-specified primary test (one):** GB aggregate (sum of LDZs). Regress the
error of the last D−1 publication (16:15) on the D−1 13:15→16:15 revision.
Weak efficiency ⇒ coefficient zero. HAC inference; report effective N.

**Pre-specified secondary tests (Bonferroni across them):**
- Mincer–Zarnowitz per vintage: actual on forecast, joint α = 0, β = 1.
- Nordhaus chain: `r_k` on `r_{k−1}` across within-day vintages.
- Error on information knowable at issue: forecast CWV level, day-ahead
  change in forecast CWV, day type, and the most recent error whose actual
  was already published at issue time (check the D+1 publication lag — using
  D−1's actual on D−1 is a leak).
- Cold regime (bottom CWV decile, thresholds fixed on the development sample).

**Panel version (secondary):** LDZ × day with day-clustered or Driscoll–Kraay
errors. The 13 zones share weather and one forecaster; they are not 13
independent series. Do not cluster by LDZ alone.

**Baselines (implemented first):** (1) the raw incumbent forecast; (2) "no
further revision" persistence; (3) the existing CWV+calendar baseline.

**Kill criterion C1.**
> Kill the price strand if the primary coefficient is below the MDE **and** a
> walk-forward bias/revision-corrected forecast does not beat the raw 16:15
> D−1 forecast on MAE (Diebold–Mariano, HAC) on the development sample.
> Write up: "the published forecast is weakly efficient at D−1." Stop.

**Deliverable:** `reports/phase2_efficiency.md`.

## Phase C2 — price and balance (5–7 days) — only if C1 passes

**The data problem, stated first.** No free timestamped NBP day-ahead or
within-day price series has been verified. Candidates, in order:

1. National Gas Gas Data Portal: System Average Price (SAP) and System
   Marginal Prices (SMP buy/sell), opening/closing linepack, system
   imbalance. **Unverified this session** — harvest the folder list and pin
   ids as `gas.py` does. SAP is a gas-day volume-weighted average, not a
   timestamped tradeable price.
2. A Bloomberg terminal at UCL for NBP day-ahead and within-day assessments.
   Check access and licence; data cannot be redistributed in the repo.
3. Front-month ICE NBP via free delayed sources — wrong tenor for a D−1
   signal; use only as a control.

**Design depends on what C2 finds:**
- *Timestamped DA/WD prices available:* signal knowable at 16:15 D−1 (once
  the timezone is resolved) → position in DA or WD → P&L with the full
  `CLAUDE.md` §6 cost model, break-even cost as the headline, deflated for
  the trial count in the decision log.
- *Only SAP/SMP/linepack available:* **no P&L is produced.** Run an
  information test instead: does the predictable error component explain
  (a) system length (linepack change), (b) SMP buy–sell asymmetry, (c)
  SAP(D) − SAP(D−1)? Report as "priced / not priced", not as a strategy.

**Reverse test (cheap, do either way):** does the D−1 price change predict the
forecast error? If yes, the market knows what the operator's forecast misses,
which is the Thomas–Massol–Sévi question for GB.

**Kill criterion C2.**
> Kill if break-even cost is below a realistic round-trip cost, or (information
> test) no relation exceeds the pre-computed MDE. Report the break-even or the
> MDE either way.

**Deliverable:** `reports/phase3_price.md`.

## Phase C3 — write-up (3–4 days)

`reports/final_report.md`: electricity null, gas stock null, the scale
correction, efficiency result, price result, "what did not work", decision
log. Then freeze the spec for confirmation sample 2 and score it in March 2027.

**Venues:** *International Journal of Forecasting* or *Energy Economics*
(journal). Conference options: ACM e-Energy (2026 deadline was 22 Jan; 2027
unconfirmed, and likely too close to the thesis), International Symposium on
Forecasting 2027, ICAIF 2027 (2026 deadline was early August). Verify all
dates before planning around them.

**Time box:** 3 weeks of part-time work. If C1 kills, the project closes in
about 8 days with a complete report.

---

# Option 2 — Does dwelling stock explain the temperature sensitivity of electricity demand, at feeder level?

**Park until after April 2027, except Phase D0.**

## Research question

> Across GB low-voltage feeders, does EPC-derived dwelling stock (electric
> heating and heat-pump share, fabric efficiency, floor area) explain the
> slope of smart-meter electricity demand on cold weather; and does knowing
> the stock improve day-ahead load forecasts where a feeder has little or no
> history?

This is the original Project A hypothesis moved from 12 gas zones to a
cross-section of the order of 100,000 units, where it is testable.

## Data (all to be verified in D0)

- DNO open data: half-hourly smart-meter consumption aggregated per LV feeder
  (minimum 5 meters), published by SSEN, NGED, UKPN, NPg, SPEN; Weave
  (Centre for Net Zero) aggregates several. Publication began in 2024, so
  expect ~2–3 heating seasons.
- Geography: SSEN publishes a postcode ↔ feeder lookup; NGED data has been
  linked to LSOA in a derived release. Other DNOs unknown.
- EPC stock by postcode: already built (`data/raw/epc_dwellings_*`,
  17.3 M dwellings, England & Wales only → SSEN north and SPEN Scotland
  drop out).
- Weather: realised gridded temperature is legitimate for the *explanatory*
  phases (mark `REALISED-WEATHER-DIAGNOSTIC`, `_realised` suffix). The
  forecasting phase must use the Open-Meteo forecast archive (from
  2024-02-04).

## Phase D0 — feasibility (2–3 days; can be done now)

For each DNO: history start, feeder count, meter-count field, geography key,
licence, download size, revision policy. Join rate of feeders to EPC
postcodes on a sample.

**Kill criterion D0.**
> Kill if fewer than two DNOs offer two full heating seasons with a usable
> feeder → postcode/LSOA key, or if under ~50% of sampled feeders can be
> matched to at least 5 EPC dwellings.

## Phase D1 — panel construction (2 weeks)

Feeder × day: kWh per contributing meter (meter counts change over time —
normalise, and drop feeder-days with large count jumps). Feeder stock
features from EPC by postcode. Daily HDD at feeder location.

**Known threats, each needs a stated direction:** non-domestic meters on a
feeder; smart-meter take-up selection; EPC coverage selection (~60%, biased
to sold/let homes); postcode-to-feeder misassignment; storage heaters
(night load, different temperature response from heat pumps); export from
rooftop PV if only import is reported.

## Phase D2 — the core test (1–2 weeks)

`kwh_per_meter[f, d] ~ a[f] + b[d] + β·(stock_z[f] × HDD[f, d]) + ε`

- **One pre-specified primary feature:** share of dwellings with electric
  main heating (resistive + heat pump) from EPC.
- MDE by simulation first; placebo with permuted stock first; summer
  placebo (HDD ≈ 0 months); cluster by primary substation or LSOA, with a
  spatial-HAC sensitivity. Not by DNO (5 clusters).
- Secondary: heat-pump share alone, mean SAP, floor area; Bonferroni.

**Kill criterion D2.**
> Kill if the primary interaction is below the MDE with the placebo passing.
> This time the null would be powered — write it up as such.

## Phase D3 — forecasting value (2 weeks) — only if D2 passes

Day-ahead feeder load, forecast weather only, walk-forward. Baselines:
feeder-own-history seasonal model; pooled model without stock. The claim to
test is **cold-start**: feeders with under N weeks of history, where a
stock-based prior should help most. Report skill by history length.

## Phase D4 — aggregation and write-up

Aggregate fitted slopes to GSP group; state what the cross-section implies
for peak thermosensitivity as electric heating share rises. Do not claim
incremental information over the NESO forecast unless it is tested.

**Venues:** ACM e-Energy, ACM BuildSys, *Applied Energy*, *Energy and
Buildings*. **Fit:** energy analytics and retail/trading firms more than
hedge-fund research.

---

## Open decisions for the owner

1. Option 1 holdout: accept winter 2026/27 as a prospective confirmation
   sample (result in March 2027), or close the project on the development
   sample alone?
2. Is a UCL Bloomberg terminal acceptable as a price source, given the data
   cannot live in the repo?
3. Option 2: same repo as new phases, or a new repo? (A new repo keeps
   Project A's decision log and trial count clean.)
4. Does Option 2 overlap any thesis chapter or existing side paper closely
   enough to raise a dual-submission question?
5. (Added 2026-11-17.) C1 target vintage: D+6 actual as headline, D+1 as
   sensitivity? Must be fixed before the C1 MDE is computed.

## First session checklist

1. ~~Add decision-log rows for: this plan, the scale correction (§0), and the
   holdout policy — before any computation.~~ Done 2026-11-17, rows 38–41.
2. ~~Run Phase C0. Append the dated correction note to `phase1b_findings.md`.~~
   Done 2026-11-17, row 42. §0's hypothesis confirmed: the 3.8× figure is
   withdrawn; a small CWV-monotone signed bias survives and goes into C1.
3. Literature search for GB gas forecast revision efficiency (30 minutes,
   written up in the decision log). **First pass done 2026-11-17:**
   `docs/paper1_literature.md`, decision log row 50.
4. Harvest the National Gas folder list for price, linepack and imbalance
   series; record ids and history start in `docs/data_inventory.md` §4.
   **Moot after the C1 kill** unless the owner opens a new hypothesis.
   (Note: `heat_nowcast.data.gas.USER_AGENT` sends the owner's email address
   to the portal as a contact. Owner approved keeping it, 2026-11-17.)
5. Resolve the publication-timestamp timezone. **Moot after the C1 kill**, as
   for 4.
6. ~~MDE for the C1 primary test. Then, and only then, estimate.~~ Done
   2026-11-17 (rows 43–47). MDE 0.254; primary β = −0.044 (p = 0.72).
   **Kill criterion C1 fired**: revision-efficient, not unbiased (bias peaked
   in 2022/23). See `reports/phase2_efficiency.md`. Next: C3 write-up, or an
   owner decision to freeze a new post-hoc hypothesis (ΔCWV under-response /
   cold over-forecast) for the confirmation samples only.
