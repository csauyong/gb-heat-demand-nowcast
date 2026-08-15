# Phase 1 findings — the naive baseline against the published NESO forecast

**Date:** 2026-08-14
**Scope:** Project A, Phase 1 (data layer + baselines). No bottom-up stock
model has been built. Nothing here tests a trading signal.

---

## The headline, stated plainly

**The HDD-plus-calendar baseline is 2.4× worse than NESO's published day-ahead
forecast: 1,650 MW MAE against 686 MW, on identical rows over identical
windows. The gap is 964 MW of MAE.**

**But almost none of that gap is heat-shaped.** Decomposing it:

| Component of the 964 MW gap | MW | Share of gap |
|---|---|---|
| Recoverable by perfect weather (oracle run) | 49 | **5%** |
| Recoverable by removing a constant level bias | 206 | 21% |
| Attributable to embedded wind and solar (regression on the baseline's error) | ~471 | ~49% |
| Structural remainder | ~240 | ~25% |

The single most important number in this report is the first one. **A perfect
temperature forecast would close 5% of the gap to NESO.** Day-ahead
population-weighted HDD is already almost exact — correlation 0.9965 against
realised, mean absolute difference 0.275 °C-days. There is essentially no
weather-forecast error left to remove, so any improvement a bottom-up model
offers must come from *converting temperature into demand better*, not from
knowing the temperature better.

Meanwhile roughly half the baseline's error is embedded wind and solar
generation — a quantity a building-stock model has no view of whatsoever, and
which NESO has already impounded (the same regression explains 33% of the
baseline's error variance but only 4.7% of NESO's).

---

## What was compared, and on what

| | |
|---|---|
| Target | NESO `Demand_Outturn`, half-hourly GB national demand |
| Evaluation window | 2024-02-04 → 2026-08-12 |
| Rows scored | 44,206 half-hourly settlement periods, 921 days |
| **Effective independent observations** | **~1,889** (NESO error), **~1,011** (baseline error) |
| Heating seasons covered | ~2.5 (tail of 2023/24, plus 2024/25 and 2025/26) |
| Walk-forward folds | 31, expanding window, monthly refit, 7-day embargo |
| Training history | from 2021-04-01 |
| Mean demand | 25,865 MW overall; 31,173 MW in winter |

The evaluation window was **not chosen**. It is forced by the start of the
only archive of point-in-time forecast weather available (2024-02-04, see
"Point-in-time discipline" below). That is the cleanest justification a test
period can have, and it means no test-period selection decision was made that
could be second-guessed.

The 44,206 figure should not be read as a sample size. Half-hourly demand
errors are enormously autocorrelated; the variance-inflation-corrected
effective sample is **~1,000–1,900**, i.e. roughly two orders of magnitude
smaller. Every inference below uses the corrected figure.

---

## Results

### Overall

| Model | MAE (MW) | RMSE (MW) | Bias (MW) | MAPE |
|---|---|---|---|---|
| **NESO day-ahead** | **686** | **927** | **+7** | **2.74%** |
| HDD+calendar baseline *(headline spec)* | 1,650 | 2,076 | −809 | 6.48% |
| HDD+calendar, no harmonics *(sensitivity)* | 2,149 | 2,855 | −511 | 8.38% |
| Seasonal naive, lag 7 days *(floor)* | 2,070 | 2,781 | +64 | 8.15% |
| ⚠️ Oracle — **REALISED** weather *(diagnostic)* | 1,601 | 2,028 | −720 | 6.31% |

Sign convention: `error = forecast − actual`. Negative bias means the forecast
runs low.

⚠️ The oracle row is driven by **realised ERA5 temperature**, which was not
knowable at prediction time. It is an upper bound and is never a headline
result (`CLAUDE.md` §2.1).

Three things in this table are worth stating explicitly.

1. **The baseline is a working weather model, not a broken one.** It beats the
   no-weather seasonal-naive floor by 20% (1,650 vs 2,070). The HDD term is
   doing real work. It is simply nowhere near NESO.
2. **The four-term specification in the Phase 1 brief is the weaker one.**
   Adding two annual harmonics — the seasonality `CLAUDE.md` §4 requires —
   improves MAE by 23% (2,149 → 1,650). Both were pre-specified; the harmonic
   version is reported as the headline and the four-term version as the
   sensitivity, and the difference is stated rather than buried.
3. **The baseline's bias is large and seasonal.** It under-predicts winter
   demand by 1,534 MW on average and autumn by 1,367 MW, while summer is
   near-neutral (−231 MW). NESO's bias is +7 MW overall and never exceeds
   ±32 MW by season. The oracle carries almost the same bias (−720 MW), so
   this is a *model* failure, not a weather failure: a linear-in-HDD response
   with a linear trend cannot track the winter demand shape.

### By season

MAE, MW:

| Season | NESO | Baseline | No harmonics | Seasonal naive | ⚠️ Oracle |
|---|---|---|---|---|---|
| Winter | 686 | 1,889 | 2,601 | 2,667 | 1,802 |
| Spring | 750 | 1,603 | 2,207 | 2,089 | 1,573 |
| Summer | 651 | 1,378 | 1,534 | 1,618 | 1,379 |
| Autumn | 637 | 1,836 | 2,415 | 2,003 | 1,729 |

Bias, MW:

| Season | NESO | Baseline | ⚠️ Oracle |
|---|---|---|---|
| Winter | +32 | −1,534 | −1,447 |
| Spring | +44 | −438 | −338 |
| Summer | +33 | −231 | −197 |
| Autumn | −112 | −1,367 | −1,217 |

**NESO's error is almost flat across seasons** (637–750 MW). The baseline's is
not: it is worst exactly where heating demand lives. In winter the ratio is
2.75×; restricted to winter evening peak (settlement periods 33–40, 16:00–20:00
London) it is 2.72× (699 vs 1,903 MW).

That NESO's error does not deteriorate in winter is itself informative. An
operational forecaster whose skill were weather-limited would show a winter
degradation. NESO does not.

### By day type

MAE, MW:

| Day type | n | NESO | Baseline | No harmonics | Seasonal naive | ⚠️ Oracle |
|---|---|---|---|---|---|---|
| Weekday | 30,240 | 683 | 1,615 | 2,127 | 2,085 | 1,567 |
| Saturday | 6,288 | 671 | 1,697 | 2,127 | 1,999 | 1,641 |
| Sunday | 6,334 | 702 | 1,728 | 2,252 | 1,802 | 1,674 |
| Bank holiday | 1,344 | 734 | 1,864 | 2,263 | 3,332 | 1,833 |

Bank holidays are where the seasonal-naive floor collapses (3,332 MW — last
week was a working day), and the holiday dummy earns its place. NESO handles
holidays with only a 7% MAE penalty over weekdays. The baseline's holiday
penalty is 15%. Note the small effective sample on holidays (~60–75
independent observations), so that row carries real uncertainty.

Full breakdown by season × day type: `reports/tables/phase1_by_season_and_day_type.csv`.

### Statistical comparison

Diebold-Mariano on squared-error loss, Newey-West HAC at 48 lags:

- Baseline vs NESO: statistic **28.2**, p ≈ 0.
- Oracle vs NESO: statistic **28.0**, p ≈ 0.

NESO is better by a margin that no reasonable correction for autocorrelation
or effective sample size touches. This is not a marginal result and does not
need careful inference to establish. (The low-power caveat that matters
elsewhere in this project — ~2.5 heating seasons — cuts the other way here:
the effect is enormous.)

---

## Why the gap is what it is

### 1. Weather forecast error is negligible — 5% of the gap

Serving the same model realised ERA5 temperature instead of the archived
day-ahead forecast improves MAE from 1,650 to 1,601 MW. **The entire value of
a perfect temperature forecast is 49 MW of MAE, 3.0% of the baseline's error
and 5.1% of its gap to NESO.**

The reason is that day-ahead temperature is nearly exact at GB aggregate
scale: forecast and realised population-weighted HDD correlate at 0.9965, with
a mean absolute difference of 0.275 °C-days.

This has a direct consequence for the project. `docs/data_inventory.md` §10
names coarser free NWP as "a real and quantifiable disadvantage vs NESO". At
the GB-aggregate, day-ahead horizon, **it is quantified here and it is small.**
The disadvantage is real but it is not what is costing the baseline its
accuracy, and buying better weather data would not change the picture.

### 2. Embedded wind and solar — about half the gap

Regressing each forecast's error on NESO's published embedded wind and
embedded solar generation:

| Forecast | R² | MAE before → after removing embedded generation |
|---|---|---|
| HDD+calendar baseline | **0.333** | 1,653 → 1,182 MW |
| NESO day-ahead | 0.047 | 685 → 666 MW |

The baseline's error carries a strong embedded-generation component
(+0.48 MW per MW of embedded wind, +0.29 per MW of embedded solar). NESO's
does not. This is the expected result and it is worth being blunt about it:
NESO has embedded generation telemetry and commercial wind and solar
forecasts, and National Demand is a *transmission-metered* series that
embedded generation directly suppresses (`docs/data_inventory.md` §2.1). No
temperature-driven model of any sophistication can see this, and **a
building-stock model cannot see it either**.

### 3. A constant level bias — 21% of the gap

Removing a single constant from the baseline's errors improves MAE from 1,650
to 1,444 MW. A fifth of the gap is recalibration, not modelling. This is
reported because it bounds how much of the remaining gap is genuinely
structural: after perfect weather *and* perfect recalibration, the baseline
would still sit around 1,400 MW against NESO's 686.

---

## What this implies about headroom for a bottom-up model

This is the question Phase 1 was built to answer. The honest answer has three
parts, and the second is the important one.

**1. There is a large absolute gap, so the baseline is not a ceiling.**
964 MW of MAE separates a standard utility HDD regression from the operational
forecast. Something is in NESO's forecast that the baseline does not have.

**2. That something is mostly not heat, and mostly not reachable from
building stock.** Roughly half is embedded renewables, which a stock model
cannot observe. Only 5% is weather-forecast error, which a stock model does
not improve. A further fifth is a level bias fixable by recalibration. The
residual heat-attributable headroom — the part where knowing more about
dwelling fabric, heating systems and floor area could plausibly help — is the
smallest slice of the gap, and Phase 1 cannot size it precisely.

**3. The first direct evidence on the Phase A3 question points toward the null.**
The scientific core of Project A is whether the bottom-up model contains
information *not already in the published NESO forecast*. That is a statement
about NESO's residual. Testing NESO's residual against the crudest possible
heat proxy:

- Correlation between NESO's daily mean error and forecast HDD over 921 days:
  **r = −0.013**.
- NESO's MAE on the coldest decile of days (93 days): **438 MW**, against
  **441 MW** across all days. Mean error on cold days: −60 MW.

**NESO's error shows no heating signal at all, and does not degrade in cold
weather.** If a simple population-weighted HDD had explanatory power over
NESO's residual, that correlation would not be −0.013.

This is preliminary, not a verdict. HDD is a much cruder heat proxy than the
bottom-up model Phase A1 would build, and the whole premise of the project is
that stock heterogeneity carries information HDD does not. But it is the right
direction to look first, and it came back empty on the obvious test. **Phase A3's
kill criterion should be treated as live rather than remote**, and Phase A1
should be sized accordingly.

### The load-bearing caveat: this is the wrong target series

`docs/research_plan.md` recommends **gas LDZ offtakes as the primary
validation target**, not electricity, because ~85% of GB homes heat with gas
and the domestic heat signal-to-noise ratio there is far better. Phase 1
scored the *secondary* target. Everything above is a statement about GB
electricity demand and about NESO's electricity forecast.

**Nothing here kills the gas strand.** In fact two of the three components of
the gap are electricity-specific: embedded wind and solar do not exist on the
gas side, and the transmission-metering problem that makes ND "not domestic
heat demand" has no gas analogue anywhere near as severe. The equivalent
exercise against National Gas LDZ offtakes and the published Composite Weather
Variable is the natural next diagnostic, and it should be run before Phase A1
commits three to four weeks to stock construction.

---

## Point-in-time discipline: what was found and what was done

Three findings changed the design. All are recorded in
`reports/decision_log.md` rows 2–5.

### The inventory's first-choice forecast resource is not half-hourly

`docs/data_inventory.md` §2.2 points at `historic_day_ahead_demand_forecasts`.
Inspected on 2026-08-14, that resource is **cardinal points** — roughly 19 rows
per delivery day keyed by `CARDINALPOINT` (peaks, troughs, named period
ranges), not 48 half-hourly values. It cannot be scored half-hourly against a
half-hourly baseline.

Phase 1 uses `day-ahead-half-hourly-demand-forecast-performance` instead. It is
half-hourly, it pairs the published forecast with the outturn NESO scores
itself against, and — decisively — it carries `Publish_Datetime`.

*Suggested inventory amendment:* §2.2 should name the performance dataset as
the scoring source and flag the cardinal-point structure of the other.

### The publication gate is 08:45 UTC on D−1

`Publish_Datetime` is London wall-clock. January rows carry 08:45 and July rows
09:45 — both **08:45 UTC**, so publication is fixed in UTC. A later regime
publishes at 08:33 UTC. Every row is D−1 for delivery day D. NESO's forecast is
therefore knowable from 08:45 UTC on D−1 and no earlier.

### The inventory's point-in-time weather source is a leak, and the fix costs three years of history

`docs/data_inventory.md` §5.1 names Open-Meteo's **Historical Forecast API** as
the point-in-time route, with an archive from 2021. Tested on 2026-08-14:

- it archives the *most recent* forecast for each timestamp — a rolling 0–24 h
  lead. For an 18:00 timestamp on delivery day D the value comes from a model
  run initialised **on day D**, hours after NESO published. Using it would hand
  the baseline a later and better weather forecast than its competitor had;
- its `temperature_2m_previous_dayN` fields return all-null.

Phase 1 uses the **Previous Model Runs API** (`temperature_2m_previous_day1`)
instead — the same provider, the same CC-BY-4.0 licence, the same free tier,
and a genuinely fixed ≥1-day lead. Its archive was bisected and **begins
2024-02-04**, not 2021.

That is the binding constraint on this project. **Point-in-time forecast
weather for GB exists for ~2.5 years, not five.** `docs/research_plan.md` §5.1
plans the evaluation around "~5 winters"; the real figure is about two.

*Suggested inventory amendment:* §5.1 should distinguish the two Open-Meteo
endpoints and record the 2024-02-04 archive start, because it changes the
power of every downstream test.

**Residual uncertainty, stated rather than hidden.** Open-Meteo documents
`previous_day1` as the forecast initialised one day earlier but does not
publish the initialisation *hour*. If that snapshot comes from a 12Z run on
D−1 rather than 00Z, it lands after NESO's 08:45 UTC publication and the lead-1
series is very slightly optimistic. `lead_days` is a parameter and
`lead_days=2` is the strictly-safe variant; given that a perfect forecast is
worth only 49 MW of MAE, this cannot plausibly change any conclusion here.

### Where realised weather is used, and why it is legal

Realised ERA5 temperature appears in exactly two places, both marked
`REALISED-WEATHER-DIAGNOSTIC` at the call site with `_realised`-suffixed
columns:

1. **Training the baseline.** Legal because the walk-forward embargo is 7 days,
   which exceeds ERA5's ~5-day preliminary publication lag — the realised
   temperature in any training row had genuinely published by the refit date.
2. **The oracle run.** Reported as an upper bound only, hatched in every figure
   and flagged with ⚠️ in every table.

The model is therefore **fitted on realised HDD and served forecast HDD**. This
mismatch is real and disclosed. Its direction is known: fitting on a clean
regressor and predicting with a noisy one is classical errors-in-variables,
which leaves the slope unattenuated and inflates prediction error. It makes the
baseline look *worse*, never better, relative to NESO. Given the forecast/
realised HDD correlation of 0.9965, its magnitude is negligible.

---

## Limitations

- **Two and a half heating seasons.** Small effective sample (~1,000–1,900
  independent observations). The NESO-vs-baseline comparison is not remotely
  close, so this does not threaten *that* conclusion — but the
  NESO-error-vs-HDD null in the headroom section is an underpowered
  preliminary test, and no minimum detectable effect has been computed for it.
  That belongs in Phase A3, done properly.
- **Restatement contamination in the target.** NESO's `Demand_Outturn` is its
  restated value as of the 2026-08-14 download, not a first publication, and
  NESO publishes no vintage archive (`CLAUDE.md` §2.2). It affects both
  forecasts identically, so it cannot flatter the baseline relative to NESO,
  but the level of both error series carries it.
- **Two published outturns disagree slightly.** NESO's `Demand_Outturn` and its
  `historic-demand-data` ND series differ by a mean 34 MW (mean absolute 56 MW,
  max 2,764 MW) across 93,162 overlapping periods; only 3% agree to within
  1 MW. Scoring used `Demand_Outturn` throughout so both forecasts face an
  identical truth. Worth knowing that "GB demand outturn" is not a single
  number even within one publisher.
- **Population, not dwellings, as the spatial weight.** The heat-correct weight
  is dwelling count; Phase A1 will use it. For a national temperature index the
  two are near-identical, and the choice is immaterial next to the base
  temperature.
- **Weather grid resolution.** 39 cells at 0.75° × 1.5°, covering 99.5% of GB
  population from 43,064 LSOA/Data Zone points. Not varied; a sensitivity was
  not run because the forecast/realised HDD correlation of 0.9965 leaves almost
  no room for spatial detail to matter at this horizon.
- **Not a heat model.** National Demand is transmission-metered and is not
  domestic heat demand. Phase 1 compares two forecasts of the same published
  quantity, which is the only comparison that can be made on identical rows.

## What did not work

- The inventory's nominated day-ahead forecast resource (cardinal points, not
  half-hourly) — replaced.
- The inventory's nominated point-in-time weather endpoint (rolling 0–24 h
  lead, a leak against a D−1 08:45 UTC decision) — replaced, at the cost of
  three years of backtest history.
- The bare four-term specification named in the Phase 1 brief (HDD +
  day-of-week + holiday + trend) is 23% worse than the same model with two
  annual harmonics. Kept and reported as a sensitivity rather than dropped.
- Unpaged pulls from both Nomis and the ArcGIS services silently returned short
  pages, losing a third of England & Wales' LSOAs in a *geographically*
  correlated way. Both loaders now page and assert coverage before building a
  national weighting.

---

## Reproducing

```bash
make setup && make phase1
```

Cold cache: ~40 minutes, dominated by the Open-Meteo pull. Warm cache: ~1
minute. Every cached artefact in `data/raw/` has a sidecar JSON recording the
URLs requested, the retrieval timestamp, the licence, the vintage, the
publication lag and a SHA-256 of the payload — re-pull with `refresh=True` and
compare hashes to detect upstream restatement.

Outputs: `reports/tables/phase1_*.csv`, `reports/tables/phase1_diagnostics.json`,
`reports/figures/phase1_*.png`.

---

## Attribution

Contains NESO data, © National Energy System Operator.
Contains public sector information licensed under the Open Government Licence v3.0.
Contains OS data © Crown copyright and database right 2026.
Contains National Statistics data © Crown copyright and database right 2026.
Weather data by Open-Meteo.com, licensed CC BY 4.0.
Generated using Copernicus Climate Change Service information 2026.
