# Phase 1b findings — the gas baseline against National Gas's published D−1 LDZ forecast

**Date:** 2026-08-15
**Scope:** Project A, Phase 1b, all five items of the brief — gas data layer,
LDZ baseline, LDZ stock features, the two-way fixed effects core test, and the
power analysis. No bottom-up stock model has been built and Phase 2 has not
been started.

---

## The headline, stated plainly

**On the primary target, the picture is materially different from Phase 1, and
it points the other way.**

| | Phase 1 (electricity, GB) | Phase 1b (gas, LDZ panel) |
|---|---|---|
| Baseline ÷ incumbent MAE | **2.41×** | **1.57×** |
| Weather-forecast error, share of gap | 5% | **~0%** (oracle is not better) |
| Incumbent error vs weather severity | r = −0.013 | **r = −0.168** |
| Incumbent MAE, coldest vs warmest decile | 438 vs 441 MW (**flat**) | 0.422 vs 0.110 mscm/day (**3.8×**) |
| Error correlation, baseline vs incumbent | 0.373 | 0.678 |
| Non-heat wedge (embedded renewables) | ~49% of gap | **absent by construction** |

The single most important result: **National Gas's own published day-ahead LDZ
forecast is 3.8× less accurate on the coldest decile of days than on the
warmest** (MAE 0.422 vs 0.110 mscm/day), and its error correlates with weather
severity at r = −0.168 over 978 gas days. Phase 1 found the electricity
incumbent's error completely flat across the temperature distribution
(438 vs 441 MW, r = −0.013).

**There is a heat-shaped residual in the incumbent gas forecast. There was not
one in the incumbent electricity forecast.** That is exactly the asymmetry
`docs/research_plan.md` predicted when it recommended gas as the primary target,
and it is the reason Phase 1's near-null does not transfer.

**But building-stock heterogeneity does not explain it.** The core test —
two-way fixed effects on the LDZ × day panel, stock × weather-severity
interaction, wild cluster bootstrap over 13 clusters — returns a **null on the
pre-specified primary feature (β = 0.29 × MDE, p = 0.248)** and on all five
secondary features. A placebo run first confirmed the pipeline returns nothing
when nothing is there. Details below.

So Phase 1b splits the question in two, and the two halves point opposite ways:
there **is** an unforecast heat-shaped residual in the gas incumbent's error,
and EPC-derived stock composition at LDZ resolution **does not** account for
it.

---

## Read this before the estimates: the minimum detectable effect

Phase 1 reported a null without an MDE and flagged that as a defect in its own
write-up. Phase 1b computes the MDE **first**, by simulation on the real panel,
so that whatever the core test eventually returns is interpretable.

Simulating on the actual 13 × 978 panel of published forecast errors —
within-transformed by LDZ and day, residuals resampled **by whole cluster** to
preserve within-zone serial correlation, tested with the wild cluster bootstrap
over 13 clusters at α = 0.05:

| | |
|---|---|
| **MDE at 80% power** | **0.0838 mscm/day** |
| in MW-equivalent | **38.7 MW** |
| as a share of mean absolute incumbent error | **19.1%** |
| units | per SD of the stock score, per SD of cold severity |
| Simulated size at zero effect | 0.040 (nominal 0.05 — well calibrated, mildly conservative) |
| Panel | 12,714 rows, 13 clusters, 978 days |
| Within-transformed residual SD | 0.838 mscm/day |

**The core test can only detect a large interaction.** An effect worth a fifth
of the incumbent's mean absolute error would be a substantial finding; anything
appreciably smaller will be invisible at this sample size, and a null would
then be uninformative rather than negative. Power reaches 60% at 0.042 mscm/day
(9.6% of mean error) and 26% at 0.025 mscm/day (5.7%).

This number should govern expectations for items 3–4 before a single stock
feature is built. Full power curve: `reports/figures/phase1b_power_curve.png`,
`reports/tables/phase1b_power.json`.

---

## What was compared, and on what

| | |
|---|---|
| Target | `Demand Actual, LDZ (XX), D+1` — first-publication daily offtake, mscm/gas day |
| Competitor | `Demand Forecast, LDZ (XX)`, gated to the last publication dated D−1 |
| Weather | `Composite Weather Variable, Forecast, LDZ(XX), D−1` — the incumbent's own input |
| Panel | 13 LDZs × 978 gas days = **12,714 rows** |
| Evaluation window | 2023-12-01 → 2026-08-06 |
| Training history | from 2021-12-01 (24 months before evaluation opens) |
| Walk-forward folds | 33, expanding window, monthly refit, 7-day embargo |
| **Effective independent observations** | **~3,370** (incumbent error), ~1,303 (baseline error) |
| Mean offtake | 8.97 mscm/day per LDZ (≈ 4,151 MW-equivalent) |

The evaluation window was **chosen**, not forced — unlike Phase 1, where the
Open-Meteo archive dictated it. The rule was fixed before scoring: 24 months of
training to identify the annual harmonics and the trend, then everything after.
It is recorded as row 21 of `reports/decision_log.md`.

Gas history runs from 2021-12-01, giving **~4.7 years** against electricity's
2.5 — the gas side is better powered as well as better motivated.

---

## Results

### Overall (mscm per gas day)

| Model | MAE | RMSE | Bias | MAPE | n_eff |
|---|---|---|---|---|---|
| **National Gas D−1** | **0.438** | **0.948** | **+0.026** | **5.60%** | 3,370 |
| CWV+calendar baseline *(headline)* | 0.690 | 1.193 | −0.450 | 9.77% | 1,303 |
| CWV+calendar, no harmonics *(sensitivity)* | 0.681 | 1.180 | −0.434 | 9.62% | 1,376 |
| Seasonal naive, lag 7d *(floor)* | 1.629 | 2.644 | +0.084 | 18.26% | 317 |
| ⚠️ Oracle — **REALISED** CWV *(diagnostic)* | 0.702 | 1.202 | −0.490 | 10.00% | 1,220 |

Sign convention: `error = forecast − actual`.

⚠️ The oracle row is driven by the **outturn** CWV, published D+1 and not
knowable at prediction time. Upper bound only, never a headline
(`CLAUDE.md` §2.1).

Four things deserve stating explicitly.

1. **The gap is much smaller than on electricity.** 0.252 mscm/day, a ratio of
   1.57× against Phase 1's 2.41×. A standard weather regression gets
   substantially closer to the incumbent on gas.
2. **The baseline crushes the no-weather floor** — 0.690 against 1.629, a 58%
   improvement, versus 20% on electricity. Weather does far more work here,
   which is what one expects when ~85% of the load is heat.
3. **The oracle is not better; it is very slightly worse** (0.702 vs 0.690).
   Weather-forecast error is not a binding constraint on gas at all. See the
   caveat below — this number carries a train/serve mismatch and should be read
   as "indistinguishable from zero", not as a precise negative.
4. **The harmonics do not earn their place here** (0.681 without vs 0.690
   with) — the opposite of Phase 1, where they improved MAE by 23%. The CWV is
   already a seasonally-aware construct, so the harmonics add little and cost a
   degree of freedom. Both were pre-specified; the with-harmonics version
   remains the headline because it was declared as such, and the difference is
   reported rather than used to relabel the winner after the fact.

### By LDZ (MAE, mscm/day)

| LDZ | Name | National Gas | Baseline | Ratio | Mean offtake |
|---|---|---|---|---|---|
| EA | East Anglia | 0.417 | 0.554 | 1.33 | 9.53 |
| EM | East Midlands | 0.535 | 0.825 | 1.54 | 12.57 |
| NE | North East | 0.316 | 0.547 | 1.73 | 7.76 |
| NO | Northern | 0.313 | 0.423 | 1.35 | 6.41 |
| NT | North Thames | 0.418 | 0.572 | 1.37 | 11.40 |
| NW | North West | 0.588 | 0.933 | 1.59 | 14.53 |
| SC | Scotland | 0.383 | 0.551 | 1.44 | 10.68 |
| SE | South East | 1.064 | 1.955 | 1.84 | 11.82 |
| SO | Southern | 0.362 | 0.585 | 1.62 | 8.80 |
| SW | South West | 0.307 | 0.424 | 1.38 | 6.54 |
| WM | West Midlands | 0.524 | 0.807 | 1.54 | 10.15 |
| WN | Wales North | 0.070 | 0.109 | 1.56 | 1.46 |
| WS | Wales South | 0.401 | 0.684 | 1.71 | 5.04 |

The ratio is remarkably stable across zones (1.33–1.84) — the baseline is
uniformly behind, not failing in particular places. **South East is the
outlier in level**: both forecasts are roughly twice as inaccurate there as in
comparably-sized zones, which is worth understanding before the panel test
treats it as one of 13 equal clusters.

### By season and day type

MAE by season (mscm/day):

| Season | National Gas | Baseline | ⚠️ Oracle | Naive |
|---|---|---|---|---|
| Winter | 0.604 | 0.743 | 0.734 | 2.506 |
| Spring | 0.479 | 0.749 | 0.757 | 1.719 |
| Summer | 0.226 | 0.564 | 0.576 | 0.537 |
| Autumn | 0.423 | 0.695 | 0.743 | 1.687 |

**The incumbent's error is strongly seasonal on gas** (0.226 summer → 0.604
winter, a 2.7× swing), where on electricity it was flat (637–750 MW). The
baseline's seasonality is much weaker (0.564 → 0.743). In relative terms the
baseline is *closest* to the incumbent in winter (1.23×) and furthest in summer
(2.50×) — i.e. the incumbent's advantage is concentrated in the shoulder and
summer months, where gas demand is least heat-driven.

MAE by day type is essentially flat for every model (baseline 0.681–0.694,
incumbent 0.419–0.523), with holidays the only mild exception. Full breakdown:
`reports/tables/phase1b_by_season_and_day_type.csv`.

---

## The gas equivalent of the Phase 1 decomposition

Phase 1 decomposed its 964 MW gap into weather-forecast error (5%), a constant
bias (21%), embedded renewables (~49%) and a structural remainder (~25%). The
gas gap of 0.252 mscm/day decomposes very differently.

| Component of the 0.252 mscm/day gap | mscm/day | Share |
|---|---|---|
| Recoverable by perfect weather (oracle) | −0.012 | **~0%** |
| Recoverable by removing a constant level bias | 0.067 | 27% |
| **Embedded generation analogue** | **0.000 — does not exist** | **0%** |
| Structural remainder | ~0.197 | ~78% |

### The embedded-generation component is absent, and its absence is measurable

The brief asked for confirmation that the largest component of the electricity
gap is missing on gas. It is, and not merely by assertion:

* **Structurally**, there is no gas analogue. LDZ offtake is metered gas
  leaving the transmission system into the distribution network; there is no
  behind-the-meter generation suppressing it, and no equivalent of the
  transmission-metering problem that makes NESO's National Demand "not domestic
  heat demand".
* **Empirically**, the consequence shows up in the error correlation. On
  electricity the baseline's and NESO's errors correlated at **0.373** — they
  diverged because NESO could see something the baseline could not. On gas the
  baseline's and National Gas's errors correlate at **0.678**. The two
  forecasts make much more similar mistakes, which is what you see when neither
  has access to a large private information source the other lacks.

That single number is the cleanest confirmation available that the electricity
gap's dominant term is genuinely absent here.

### Weather-forecast error contributes nothing

The forecast CWV is essentially exact: correlation **0.998** with the outturn
CWV, mean absolute difference **0.194** CWV units. Substituting the outturn for
the forecast does not improve the baseline (0.702 vs 0.690).

**Caveat, stated rather than buried.** That oracle number carries a train/serve
mismatch of its own: the model is fitted on forecast CWV and served outturn
CWV, so the −0.012 is a mixture of "no weather-forecast error to remove" and
"a small mismatch penalty". A clean oracle would fit and serve the outturn, and
that is a *new specification* — a sixth trial against this test period. Given
a forecast/outturn correlation of 0.998 it cannot change the conclusion, so it
was not run rather than spending a trial on it. The honest reading is
**"weather-forecast error is indistinguishable from zero"**, not "it is
precisely −0.012".

### Spatial weather resolution matters enormously

The brief required HDD and CWV both be reported. On the overlapping window
where point-in-time forecast HDD exists (from 2024-03-31, n = 11,141):

| Weather variable | MAE (mscm/day) |
|---|---|
| National Gas D−1 (incumbent) | 0.417 |
| Per-LDZ **CWV** | 0.673 |
| **National** population-weighted HDD | 2.642 |

**A national HDD is 3.9× worse than the per-LDZ CWV** in the identical model on
identical rows. Some of that is CWV's construction (it is built to be linear in
gas demand, and includes wind); some is spatial resolution. They cannot be
separated without per-LDZ HDD, which needs LDZ polygons — see below.

Either way the direction is unambiguous and it validates the Phase 1b design
decision: **at LDZ level, a national weather variable is not competitive**, and
the GB-aggregate framing of Phase 1 was throwing away most of the signal.

### Restatement, measured rather than assumed

`CLAUDE.md` §2.2 requires vintage discipline. On the electricity side NESO
publishes no vintage archive and Phase 1 could only acknowledge the problem.
Gas publishes both a D+1 first value and a D+6 reconciled value, so the
restatement is directly measurable across all 22,230 LDZ-days:

| | |
|---|---|
| Mean revision (D+6 − D+1) | −0.0009 mscm/day |
| Mean absolute revision | 0.068 mscm/day (**0.76%** of mean offtake) |
| Share unrevised (exactly equal) | 83.8% |

Restatement is small and unbiased. Scoring used the D+1 first publication
throughout — the value a real-time decision-maker would have been scored
against — and the D+6 series confirms that choice costs little.

---

## Point-in-time discipline: what was found and what was done

Three findings, all recorded in `reports/decision_log.md` rows 12–15.

### The inventory's gas endpoint is dead, and its replacement is gated

`docs/data_inventory.md` §4 warned that National Gas was mid-migration and
instructed the loader author to check. Checked 2026-08-14:

* the legacy MIPI SOAP service at `marketinformation.natgrid.co.uk` **fails to
  connect**; National Gas confirms the SOAP APIs are "permanently
  decommissioned";
* the documented REST catalogue at `apideveloper.nationalgas.com` sits behind
  **account registration**;
* the Gas Data Portal at `data.nationalgas.com` — which §4 already names —
  serves the same operational data anonymously from
  `POST /api/find-gas-data`, with a request shape mirroring the retired MIPI
  `GetPublicationDataWM` call.

Phase 1b uses the portal endpoint. It is the inventoried source and needs no
credentials. Two operational details: it returns **403 without a `User-Agent`**
header, and the 65 publication-object ids are **pinned in code** rather than
resolved at import, so a portal reorganisation cannot silently change which
series a cached backtest used. `refresh_publication_object_ids()` re-harvests
and compares; it was run and matched 65/65.

*Suggested inventory amendment:* §4 should record the SOAP decommissioning as
complete, name `POST /api/find-gas-data` with its parameter shape, note the
`User-Agent` requirement, and record the 2021-12-01 history start.

### The severe trap: the "day-ahead" forecast is republished eight times a day

**This is the finding most likely to have silently ruined this phase.**

`Demand Forecast, LDZ (XX)` is not a daily number. For each gas day it
publishes roughly eight times: twice on D−1 (13:15, 16:15), then repeatedly
through D itself (00:15, 10:15, 13:15, 16:15, 21:15), and once more at 00:15 on
**D+1**.

The portal's default — `latestFlag=Y`, the setting the UI uses and the obvious
thing to pass — returns **the last of these**, generated *after the gas day has
ended*. It is a near-outturn estimate. Scoring it as a day-ahead forecast would
have made the incumbent look far better than it is, produced a much larger
apparent gap, and been completely untradeable. Nothing in the output would have
looked wrong.

The loader therefore pulls `latestFlag=N` — the full publication history — and
selects by `generatedTimeStamp`. Seven tests in
`tests/test_gas_gating.py`, all marked `pointintime`, assert that no gate can
admit a publication issued at or after the gas day opens, and that a gas day
with no eligible publication is **dropped rather than back-filled** from a later
one.

### The publication-timestamp timezone cannot be resolved — so the gate avoids needing it

Phase 1 pinned NESO's publication clock to 08:45 UTC by comparing January
(08:45) against July (09:45) renderings. That trick fails here: gas publication
times are **identical in January and July** (00:15, 10:15, 13:15, 16:15,
21:15), which is equally consistent with a London-local clock and a UTC clock.

Rather than guess, the gate is defined on **calendar dates**: the default
`LAST_ON_D_MINUS_1` takes the last publication *dated* D−1, which is correct
under either reading. Two alternatives are exposed and documented —
`LAST_BEFORE_GAS_DAY` (also admits the 00:15 publication on D, which genuinely
precedes the 05:00 UTC gas-day start) and `FIRST_ON_D_MINUS_1` (13:15, most
conservative). All results here use the default.

### Where realised weather is used

The outturn CWV appears in exactly one place — the oracle run — marked
`REALISED-WEATHER-DIAGNOSTIC` at the call site, carried in a
`cwv_actual_realised` column whose suffix survives every downstream join, and
hatched and flagged ⚠️ in every table and figure.

**Unlike Phase 1, the baseline has no train/serve mismatch.** The forecast CWV
is published across the whole history, so the model is fitted and served on the
identical feature. The errors-in-variables caveat that qualified every Phase 1
number does not arise.

---

## The core test: does stock heterogeneity explain that residual?

This is the question Phase 1b exists to answer. The baseline comparison above
establishes that *something* heat-shaped is unforecast. It does not say that
**dwelling stock** is what explains it.

### What was tested

Panel of 13 LDZs × 979 gas days. Outcome is the **published forecast error**,
not the offtake level::

    ng_error[ldz, day] ~ a[ldz] + b[day] + β·(stock_z[ldz] × severity_z[ldz, day]) + ε

LDZ fixed effects absorb every time-invariant difference between zones —
including the *level* of any stock variable, which over a two-year window is
collinear with the zone effect and carries no information at all. Day fixed
effects absorb everything national: the weather itself, demand shocks,
holidays, the incumbent's own model revisions. **The interaction is the only
place the hypothesis is identified.** Inference clusters by LDZ with a wild
cluster restricted bootstrap over 13 clusters.

Stock features come from **17,337,624 dwellings** — the EPC register cut at
2023-11-30 and deduplicated to latest-certificate-per-address as of that date,
joined to LDZ by full postcode.

### The placebo, run first

Before any real feature, a randomised per-zone score was pushed through the
identical pipeline 200 times:

| | |
|---|---|
| Rejection rate at nominal 5% | **0.060** |
| p-value distribution | approximately uniform (median 0.54) |
| Mean placebo \|β\| | 17.3% of the MDE |
| Placebo estimates reaching the MDE | **0 of 200** |

**PASS.** The pipeline returns nothing when nothing is there, so a null below
is a real null rather than a broken estimator.

### Result: null, and interpretably so

| Feature | Role | β (mscm/day) | β ÷ MDE | Wild-bootstrap p |
|---|---|---|---|---|
| **`mean_sap`** | **primary** | **+0.0242** | **0.29×** | **0.248** |
| `share_solid_wall` | secondary | +0.0371 | 0.44× | 0.019 |
| `mean_floor_area` | secondary | −0.0262 | 0.31× | 0.027 |
| `share_wall_eff_poor` | secondary | +0.0272 | 0.32× | 0.121 |
| `share_mains_gas` | secondary | +0.0177 | 0.21× | 0.327 |
| `share_pre_1930` | secondary | −0.0002 | 0.00× | 0.986 |
| `mean_sap`, no LDZ FE | ⚠️ sensitivity | +0.0224 | 0.27× | 0.333 |
| `mean_sap`, no day FE | ⚠️ sensitivity | +0.0241 | 0.29× | 0.316 |

Secondary features are judged against a Bonferroni threshold of 0.05/5 =
**0.010**. Nothing clears it. **No estimate anywhere in the table reaches the
minimum detectable effect** — the largest is 0.44× MDE.

**The naive inference would have got this wrong.** The primary feature's
conventional cluster-robust t-statistic is **+2.19** — "significant at 5%" by
the usual rule. The wild cluster bootstrap returns **p = 0.248**. With 13
clusters the asymptotic standard error is badly biased down, exactly as the
literature says, and this is the difference between reporting a finding and
reporting a null.

### Three diagnostics that make the null more than a shrug

**1. The six stock features carry about two dimensions, not six.** Across the
12 covered zones the correlation matrix has eigenvalues (2.87, 1.94, 0.77,
0.31, 0.07, 0.04): the **first two principal components explain 80.3%** of the
variation, the first three 93.1%. Six features on twelve units is far less
information than it looks.

**2. The signs are internally inconsistent.** `mean_sap` (higher = *better*
stock) and `share_solid_wall` (higher = *worse* fabric) should push in opposite
directions if either is picking up real building physics. Both coefficients are
**positive**, and the two features correlate **+0.36 across zones** — North
Thames has simultaneously the highest mean SAP (67.4) *and* the highest
solid-wall share (49.8%). They are indexing the same zone, not opposing
mechanisms.

**3. No estimate survives dropping one zone.** Leave-one-out on the largest
coefficient (`share_solid_wall`, β = +0.0371): dropping **NT more than doubles
it** to +0.0789; dropping **SE nearly halves it** to +0.0190. With 12
identifying units, a single zone moves the answer by a factor of two.

Taken together: the cross-section is too thin and too collinear to support the
hypothesis at this resolution, and the estimates that look largest are the
least stable.

### The Scotland gap, carried not hidden

The MHCLG EPC register is England & Wales only, so the SC zone receives 478
dwellings — border postcodes, not coverage. Per your decision, **SC is kept in
the panel and flagged**: it retains its LDZ fixed effect and contributes to the
day fixed effects, but its standardised stock features are **null, not zero**,
so the interaction is identified off the other 12 zones. Imputing "average"
stock for a zone with 478 observed dwellings would have been a fabrication
sitting directly on the regressor of interest.

## Recommendation on the Phase 2 kill criterion

**Do not proceed to Phase 2 stock construction. Close Project A's bottom-up
signal ambition and write it up as a negative result — but keep the gas
residual finding, which is the genuinely interesting part.**

### Why

The Phase A3 kill criterion asks whether the bottom-up model's information adds
explanatory power to the published forecast error, in any pre-specified regime.
Phase 1b has now tested the closest available proxy for that, on the primary
target, with the power calculation done in advance, and:

1. **The pre-specified primary interaction is null** — 0.29× MDE, p = 0.248 —
   and so are all five secondary features against a Bonferroni threshold. No
   estimate anywhere reached the minimum detectable effect.
2. **The null is interpretable, not merely underpowered-and-shrugged-at.** The
   MDE was computed before any estimate was seen, the placebo passed at 0.060
   against nominal 0.05, and 0 of 200 placebo draws reached the MDE.
3. **The cross-section cannot support a stronger test.** Twelve identifying
   zones, six stock features with ~2 effective dimensions, internally
   inconsistent coefficient signs, and leave-one-out instability of 2× on the
   largest estimate. This is not a sample-size problem that more data fixes —
   GB has 13 LDZs, and that is the whole population.
4. **A finer geography would not rescue it.** The natural next step would be
   sub-LDZ, but National Gas publishes demand and forecasts at LDZ level only;
   there is no finer published outturn to score against. The panel width is set
   by the data, not by effort.

Building the full bottom-up stock model — Phase A1's 3–4 weeks of archetype
construction, U-values, heat-loss coefficients and reweighting — would produce a
richer version of `mean_sap`. The test that variable would face is the one just
run, on the same 12 zones, with the same MDE. There is no reason to expect a
different answer, and `docs/research_plan.md` is explicit that this is when to
stop rather than tune.

### What to write up, and why it is worth writing

This is a **two-target negative result with a positive diagnostic finding in
the middle**, which is a better portfolio piece than either half alone:

- **Electricity (Phase 1):** the operational incumbent's error is flat across
  the temperature distribution (r = −0.013). Most of the gap between a standard
  weather regression and NESO is embedded renewables, which no stock model can
  see.
- **Gas (Phase 1b):** the incumbent's error is *not* flat — 3.8× worse on the
  coldest decile. Something heat-shaped is genuinely unforecast, and this is a
  real, reportable observation about operational gas forecasting.
- **But the unforecast component is not organised along cross-sectional
  building-stock lines** at the resolution GB's published data permits, and the
  reason is a measurement-resolution ceiling rather than an absence of physics.

That last sentence is the contribution. It is a quantified statement about
**when EPC-derived stock data can and cannot add value to operational demand
forecasting**, with a pre-computed MDE, a passing placebo, and diagnostics
showing exactly which constraint binds. `CLAUDE.md` §5 anticipates precisely
this outcome and calls it the deliverable.

### The kill criterion, formally

> **A3 fires.** The bottom-up model's information — proxied by six EPC-derived
> LDZ stock characteristics — adds no statistically significant explanatory
> power to the published National Gas D−1 LDZ forecast error, in the two-way
> fixed effects specification with wild cluster bootstrap inference, in the
> pre-specified cold-severity regime. Primary β = 0.29 × MDE (p = 0.248); no
> secondary feature clears Bonferroni; no estimate reaches the MDE of
> 0.0838 mscm/day.
>
> **Do not proceed to Phase A4.** A P&L built on an information source just
> shown to be uninformative is noise mining.

### If you want one more thing before closing

Two cheap options, in priority order. Both are new trials and must be logged
first.

1. **The seasonal tension (~1 day).** The incumbent's advantage over the
   baseline is *largest in summer* (2.50×) and *smallest in winter* (1.23×),
   while its error gradient is steepest on cold days. Decomposing the error by
   season *and* CWV decile jointly would say whether the cold-day signal is a
   winter phenomenon or a shoulder-season one. It does not change the kill
   decision but it sharpens the write-up's central observation.
2. **South East (~half a day).** Both forecasts are ~2× worse there than in
   comparably-sized zones, and SE is one of the two zones whose removal moves
   the largest coefficient most. If that is a data artefact it should be known
   before the null is published.

Neither is a route to rescuing the signal, and neither should be run in that
spirit.

## Limitations

- **The core test is only powered for large effects** (MDE 19.1% of mean
  absolute incumbent error). An effect smaller than that is invisible here, and
  the null should be read as "no large effect", not "no effect". This is the
  binding constraint and it does not improve with effort: GB has 13 LDZs and
  that is the whole population, not a sample.
- **Twelve identifying zones, six correlated features.** The first two
  principal components carry 80.3% of the cross-sectional variation, the signs
  are internally inconsistent, and the largest estimate moves 2× on dropping a
  single zone. The cross-section is thin in a way no estimator fixes.
- **EPC coverage is selected, not a census.** Certificates are triggered by
  sale, new build or let, so 17.3 M dwellings is roughly 70% of the E&W stock
  and over-represents recently-transacted and rented property. No reweighting
  to ONS dwelling counts was applied — Phase A1 would have done that, and its
  absence is a real limitation on the stock features rather than a rounding
  issue.
- **21% of dwellings were assigned to an LDZ by outcode, not full postcode**,
  because the Xoserve list is May 2017 and newer postcodes are absent. Outcode
  fallback is only used where the outcode maps unambiguously to one zone, and
  ambiguous ones are left unmatched, but the residual misassignment is not
  zero.
- **13 clusters.** All inference clusters by LDZ; asymptotic cluster-robust
  standard errors are unreliable at this count and are reported only alongside
  wild cluster bootstrap p-values. `tests/test_twoway.py` verifies the
  bootstrap is calibrated (rejection rate ≤ 0.15 at nominal 0.05 over 40
  replications; measured 0.033 in development) and that naive cluster-t
  over-rejects more.
- **The evaluation window was chosen, not forced**, unlike Phase 1's. The rule
  (24 months training) was pre-specified and logged before scoring, but it is a
  discretionary choice and should be counted as such.
- **The oracle carries a train/serve mismatch** (fitted on forecast CWV, served
  outturn CWV). Read as "weather-forecast error is indistinguishable from
  zero", not as a precise figure.
- **The HDD comparator is national, not per-LDZ**, so the 3.9× CWV advantage
  mixes variable construction with spatial resolution and cannot be decomposed
  without LDZ polygons.
- **LDZ offtake is not domestic heat demand either.** It is domestic *plus*
  small commercial load leaving the NTS. Much closer than transmission-metered
  electricity, but still not the thing the bottom-up model would predict.
- **Publication-timestamp timezone unresolved.** Handled by making the gate
  date-based, which is robust, but the exact hour a D−1 forecast became
  available is not established.
- **The portal endpoint is not the vendor's documented API.** It is the
  inventoried source and serves the same public data, but the documented REST
  catalogue is behind registration and was not used.

## What did not work

- The inventory's nominated gas endpoint (SOAP MIPI) — dead, replaced.
- The portal's default `latestFlag=Y` for the day-ahead forecast — a severe
  leak, rejected before scoring.
- The Phase 1 winter-vs-summer trick for resolving a publication timezone —
  inapplicable here; the gate was redesigned to not need it.
- The two annual harmonics that improved Phase 1 by 23% make the gas baseline
  marginally *worse* (0.690 vs 0.681). Reported, not relabelled.
- A national HDD as a substitute for the per-LDZ CWV — 3.9× worse, and a
  concrete demonstration that the GB-aggregate framing was the wrong one.
- **The core hypothesis itself.** Six EPC-derived stock characteristics,
  interacted with cold severity in a two-way fixed effects panel, explain none
  of the incumbent's forecast error. Pre-specified, placebo-validated,
  power-calculated in advance, and null.
- **Naive cluster-robust inference**, which would have reported the primary
  result as significant (t = +2.19) where the wild cluster bootstrap gives
  p = 0.248. Kept in the output as a labelled contrast, because it is the
  single most instructive number in the table.
- The obvious 23 M-row dedupe (sort, take last per key) — OOM-killed the
  process twice before being restructured as descending-year anti-joins.
- Reading the 88 GB EPC archive with `zipfile`'s native 4 KB reads over HTTP
  Range — ~75,000 requests per year, effectively never finishing. An 8 MB
  buffer took it to 90 MB/s.

---

## Reproducing

```bash
make setup && python scripts/run_phase1b.py
```

Cold cache: ~2 minutes for the gas side (13 series-years per request in ~3 s).
The EPC stock layer additionally needs `EPC_API_BEARER_TOKEN` in the gitignored
`.env` and takes ~5 minutes to stream, slim and dedupe 23 M certificates. Warm
cache: seconds. Every cached artefact in `data/raw/` carries a sidecar JSON
with the request bodies, retrieval timestamp, licence, vintage, publication-lag
statement and payload SHA-256. **No credential ever appears in a URL, a
sidecar, a log line or a committed file.**

Outputs: `reports/tables/phase1b_*.csv` (including `phase1b_core_test.csv` and
`phase1b_placebo.csv`), `reports/tables/phase1b_power.json`,
`reports/figures/phase1b_*.png`.

Sources added to `docs/data_inventory.md` in this phase: the National Gas
portal `POST /api/find-gas-data` endpoint and its publication-gating trap (§4),
the EPC bearer-token bulk API and its 93-column lowercase schema (§1), and the
Xoserve Postcode Exit Zone List as a new §12.

---

## Attribution

Contains National Gas Transmission data, accessed via the Gas Data Portal under
its published terms.
Contains Xoserve Postcode Exit Zone data, published for the GB gas Distribution
Network Operators.
Contains Energy Performance of Buildings data © Crown copyright, licensed under
the Open Government Licence v3.0 (address and postcode fields excepted).
Contains NESO data, © National Energy System Operator.
Contains public sector information licensed under the Open Government Licence v3.0.
Contains OS data © Crown copyright and database right 2026.
Contains National Statistics data © Crown copyright and database right 2026.
Weather data by Open-Meteo.com, licensed CC BY 4.0.
Generated using Copernicus Climate Change Service information 2026.
