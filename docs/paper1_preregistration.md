# Paper 1 — Pre-registration

**Title (working):** *Do gas prices know what the system operator knows?
Forecast revisions, an incentive-defined loss and the NBP in Great Britain.*

**Status: FINAL TEXT, 2026-11-19.** Owner decisions D1–D5 approved
2026-11-18 and D6–D7 approved 2026-11-19. Gate G0 passed (decision log rows
52–53). It binds from the freeze commit and OSF upload (§11).
Until then, price data stays embargoed in code
(`heat_nowcast.data.nts_market.PRICE_PREREGISTRATION_ROW is None`).

**What has and has not been seen (as of this draft):**

| Data | Seen? |
|---|---|
| LDZ forecast publications, LDZ actuals, CWV | **Yes**, 2021-12-01 → 2026-08-07: C0, C1 (decision log rows 39–47) |
| NTS forecast publications, NTS actuals | **Pulled, structure only** (row 49). No error, bias or revision statistic computed. |
| SAP, SMP | **One probe week** (2021-12-01 → 07), schema and timestamps only; no values inspected |
| NBP day-ahead price | **Values not seen**, apart from the disclosure below. Chosen series: EEX `PNX-NBPEOD-DA` (D6). Only **dates, row counts and field names** were read, by a blind probe that discards values in-function (rows 52–53). **Disclosure:** during the entitlement check on 2026-11-19 the Workspace overview **displayed the latest quote (18-Nov-2026) and a small recent price chart for a few seconds**. The chart window overlaps CONF. Nothing was recorded, joined to demand data or analysed. |
| Other price series | Marex Spectron `GA2NB`: dates and counts only (row 53) |
| Anything after 2026-08-07 | **Not analysed.** LDZ data to 2026-11-09 is on disk, untouched. |

Consequences:
- Every price hypothesis (H1, H4, H5) and the NTS rationality hypotheses (H2,
  H3) are **genuinely pre-registered**.
- H6, H7 and H3b were suggested by development data and are scored **only on
  the confirmation sample**.

---

## 1. Samples

| Name | Gas days | Use |
|---|---|---|
| Development (DEV) | 2021-12-01 → 2026-08-07 | Estimation of H2, H3 (no prices) |
| Development, price tests (DEV-P) | **2023-03-20** → 2026-08-07 | Estimation of H1, H1-orth, H1-tight, H4, H5. Starts at the first date of the EEX EOD series (D6); the 2022 shock year is **not** in the price tests. |
| Confirmation (CONF) | 2026-08-08 → 2027-03-31 | Re-estimation of H1 and H2 on CONF alone; the only sample for H3b, H6, H7 |

- No observation from CONF enters any DEV estimate.
- CONF is scored once, after 2027-04-08, when its D+6 actuals have published.
- **Exclusions**, fixed now and counted in the paper: a gas day is dropped from
  a test if any variable that test needs is missing. Nothing is imputed.
- **Day-ahead product rule** (H1, H4, H5):
  - An EEX row is dated by its **trade date** t. On the latest row, dated
    2026-11-18, LSEG shows contract "19Nov26", so the row describes delivery
    t + 1.
  - Keep gas day D = t + 1 only if t is Monday–Thursday and **neither t nor
    D is an England & Wales bank holiday**.
  - Friday trade dates (which may price Saturday or Monday) and days next to
    a holiday are excluded, whatever EEX's weekend convention turns out to
    be. The count is reported.

## 2. Variables

**Time:**
- **Clock:** portal timestamps are UK local; all comparisons are in UTC via
  `timeutils.portal_local_to_utc`.
- **Gas day:** 05:00–05:00 UK local (row 49).

**Publications** (slot rule, row 49): each publication takes the nearest
canonical slot within ±30 min; anything else is dropped.

| Symbol | Definition |
|---|---|
| `F^N_s` | NTS demand forecast for D at slot s ∈ {D−1 13:10, D−1 16:15, D 00:15, D 10:15, D 13:10, D 16:15, D 21:10, D+1 00:15}, mscm/d |
| `F^L_s` | Sum over the 13 LDZs of the LDZ forecast at the matching LDZ slot (13:15 for 13:10). NaN unless all 13 zones are present. |
| `A^N`, `A^L` | Outturn: **first publication of the D+6 actual** (headline); first publication of the D+1 actual (sensitivity) |
| `e^N_s = F^N_s − A^N` | Error, forecast minus actual (C1 convention); CG convention reported alongside |
| `R^L(s₁→s₂) = F^L_{s₂} − F^L_{s₁}` | LDZ revision between slots |
| `P^DA_D` | EEX NBP Day Ahead EOD index `PNX-NBPEOD-DA`, field `TRDPRC_1`, on trade date D−1, p/therm, converted to p/kWh (1 therm = 29.3071 kWh) |
| `T_c` | Start of the EEX EOD window: **17:15 CE(S)T = 16:15 UK** on D−1 (window 16:15–16:30 UK). Under D7 a publication stamped at or after 16:15 UK counts as post-close. |
| `SAP_D` | First-published SAP for gas day D, p/kWh |
| `S_D(h)` | Hourly within-day SAP path for D at hour h (`applicable_at`), first publication. A **cumulative** average (§8). |
| `CWV^fc_t` | GB composite weather variable forecast for D: LDZ CWV forecasts weighted by each LDZ's share of D+6 demand **in the previous complete gas year** (known at the time), using the latest CWV publication before t |
| `pre` / `post` | A publication is *pre-close* if its UTC time < `T_c` on D−1, otherwise *post-close*. Under D7 the only pre-close LDZ slot is D−1 13:15. |
| `R_post` | `R^L(D−1 13:15 → D+1 00:15)`: all LDZ revisions published from the window's start until OCM trading for D ends, including the D−1 16:15 publication |
| `R_late` | `R^L(D−1 16:15 → D+1 00:15)`: revisions published **after the window ends** (used in H5) |
| `ΔCWV_post` | `CWV^fc` at the last CWV publication before D starts (D−1 23:15) minus `CWV^fc` at the last before `T_c` (D−1 15:15) |
| `cold_D` | 1 if GB mean `CWV^fc` at D−1 16:15 ≤ **4.00** (bottom decile of DEV, fixed from C1); else 0 |

**Why LDZ revisions, not NTS, are the price regressor.**
- NTS total demand includes gas burnt in power stations, which responds to the
  gas price within the day. An NTS revision can therefore be *caused* by the
  price it is meant to explain.
- LDZ (mostly heating) demand does not respond to within-day prices, so LDZ
  revisions are the exogenous measure of demand news.
- NTS revisions are a labelled robustness check only.

## 3. Primary hypothesis

**H1 — Post-close operator news moves the within-day price.**

```
SAP_D − P^DA_D = a + β_post·R_post + γ·ΔCWV_post + Σ month-of-year + u
```

Sample DEV-P, product rule §1.

- **H0: β_post = 0**, two-sided, α = 0.05. The expected sign is β_post > 0.
- Newey–West HAC, 7 lags (as C1). Effective N reported.
- **Interpretation, fixed now:**
  - β_post > 0 → operator news after the close is priced; report the price
    impact in p/kWh per mscm/d.
  - β_post = 0 with power (§6) → news is not priced beyond public weather
    news.
- **Attenuation, declared in advance** (Halova, Kurov & Kucher 2014):
  - `R_post` measures the operator's update, not the market's surprise;
  - measurement error biases β_post towards zero;
  - so a null rules out effects above the MDE, not every effect.

## 4. Secondary hypotheses (one family of six, Holm at 0.05)

Price tests on DEV-P; H2 and H3 on DEV. H1-pre is dropped under D7: with
only the 13:15 publication before the close, it has no revision to test. The
16:15-as-pre-close version is robustness check 8.

| ID | Specification | H0 |
|---|---|---|
| **H1-orth** | H1 with `R_post` replaced by its residual from regressing `R_post` on `ΔCWV_post` and month-of-year (DEV-P) | coefficient = 0 |
| **H1-tight** | H1 plus `R_post × cold_D` | interaction = 0 |
| **H2** | Median Mincer–Zarnowitz: quantile regression at τ = 0.5 of `A^N` on `1, F^N_{D−1 13:10}` | a = 0 and b = 1 jointly. Moving-block bootstrap SE (14-day blocks, 999 draws, seed 20261117). |
| **H3** | EKT GMM with lin-lin loss (p = 1) on `e^N_{D−1 13:10}`; instruments {1, `e^N_known`, `CWV^fc` at 13:10}; `e^N_known` is the latest NTS error whose actual was published before 13:10 on D−1 (C1 gate) | Rationality given the estimated α (J-test). α also reported with a CI, and its distance from 0.5 (symmetric absolute loss, which the incentive implies). |
| **H4** | `e^N_{D−1 13:10} = a + δ·ΔP^DA_D + θ·R^L(13:15→16:15) + γ·ΔCWV(12:15→15:15) + u`, where `ΔP^DA_D = P^DA_D − P^DA_{D−1}` (EOD indices on consecutive trade dates; both days must pass the product rule) | δ = 0 (the price holds no demand information beyond the operator's forecast and its own later revision) |
| **H5** | `R_late = a + κ·ΔP^DA_D + γ·ΔCWV_post + u`. `R_late` contains only revisions published after the window closes at 16:30; the first is D 00:15. | κ = 0 (the market does not anticipate the operator's later revisions) |

Inference for H1-*, H4 and H5: HAC with 7 lags.

**Named baselines** (implemented and tested before any H-test runs):

| For | Baseline |
|---|---|
| H1 | (i) martingale: `E[SAP_D − P^DA_D] = 0`; (ii) weather-news only: H1 without the R terms |
| H2, H3 | Raw operator forecast; no-change; CWV + calendar walk-forward (C1's B3, re-targeted to NTS) |
| H4 | Thomas, Massol & Sévi (2022) specification re-estimated on GB DEV, as the published-method comparator |

## 5. Confirmation hypotheses (CONF only; one family, Holm at 0.05)

| ID | Specification | H0 | Origin |
|---|---|---|---|
| **H1-C** | H1, re-estimated on CONF | β_post = 0 | replication of the primary |
| **H2-C** | H2 on CONF | a = 0, b = 1 | replication |
| **H3b** | H3 with α allowed to differ when `cold_D = 1` (Patton & Timmermann 2007) | α_cold = α_other | post-hoc (C0/C1) |
| **H6** | GB LDZ `e^L_{D−1 16:15} = a + c·ΔCWV^fc + controls` (C1's S10 regressors) | c ≤ 0, one-sided; DEV estimate +1.63 | post-hoc (C1 S10) |
| **H7** | Mean `e^L_{D−1 16:15}` on `cold_D = 1` days | ≤ 0, one-sided; DEV +2.17 | post-hoc (C1 S11) |

The CONF MDE for each test is computed (§6) and published **before** it is
scored. CONF is short and mostly one winter, so the MDEs will be large. A CONF
null is reported as "not confirmed at this power", not as a refutation.

## 6. Power

- **Procedure:** as C1.
  - Moving-block bootstrap (14-day blocks) of the outcome residual from the
    regression *without* the tested term, drawn independently of that term.
  - Inject effect = multiple × (pre-chosen unit), with 500 draws per grid
    point and seed 20261117.
  - MDE = smallest effect rejected in 80% of draws at the test's α.
- **Timing:** computed **after** the price data is unlocked and **before** any
  hypothesis coefficient is estimated. The MDE uses the outcome's variance,
  not the effect. Results are logged in a decision-log row before estimation.
- **Units:** H1 per 1 mscm/d of `R_post`; H4 and H5 per 1 p/kWh of
  `ΔP^DA`; H2 per 1 mscm/d of median bias.

## 7. Robustness (pre-listed; never headline; not tests)

1. D+1 instead of D+6 outturn.
2. NTS instead of LDZ revisions in H1 (endogeneity caveat, §2).
3. GMT months only (November–March).
4. Excluding 2022-10-01 → 2023-03-31 (affects H2, H3; DEV-P already starts
   2023-03-20).
5. Excluding supply-shock days: gas days with a National Gas Margins Notice
   or Gas Deficit Warning in force. The definition is fixed here; the list is
   compiled from National Gas's notice archive using **notice dates only**,
   before any price coefficient is estimated. If it can't be compiled, this
   check is dropped and the drop is reported.
6. Outcome winsorised at the 1st/99th DEV-P percentiles.
7. HAC lags 3 and 14.
8. **D7 alternative:** the 16:15 publication counted as pre-close. H1 becomes
   `… + β_post·R^L(16:15→D+1 00:15) + β_pre·R^L(13:15→16:15) …`, with β_pre
   reported.
9. **Longer price sample:** H1 on 2021-12-01 → 2026-08-07, using Marex
   Spectron `GA2NB` before 2023-03-20 and EEX after, with a source dummy.
   GA2NB's window definition is uncertain (row 53), so this is labelled
   accordingly.

## 8. Fallback if G0 fails (no licensed day-ahead price) — **not triggered**

G0 passed on 2026-11-19 (row 53), so this section does not run. It is kept as
written to show it was fixed before the outcome of G0 was known.

- H1, H1-*, H4, H5 and H1-C are **not run**.
- The primary becomes **H1-SAP** (within-day impounding):
  - For each within-day LDZ publication k ∈ {D 10:15, D 13:15, D 16:15}:
    `ΔS_k = S_D(h_k + 3) − S_D(h_k − 1)`, with h_k the hour of k.
  - Pooled regression `ΔS_k = a_k + β·R^L_k + γ·R^L_{k+1} + u`, errors
    clustered by gas day.
  - **H0: β = 0.** γ is a placebo: a *later* revision should not explain an
    earlier price move.
- `S_D(h)` is a cumulative average, so ΔS understates the marginal price
  change, by more the later the hour. Signs and tests are valid; magnitudes
  are lower bounds and are reported as such.
- H2, H3 and the confirmation family are unaffected.
- The fallback is chosen **by gate G0**, recorded in the decision log, not by
  results.

## 9. Exploratory (labelled exploratory in the paper; no tests)

- Bai–Perron break dates in the monthly mean of `e^N_{D−1 13:10}` and
  `e^L_{D−1 16:15}`.
- Bias half-life after Q4 2022.
- Monthly bias on the lagged Ofgem price cap. Use **announcement** dates, not
  effective dates.
- Weather-adjusted demand fall following Ruhnau et al. (2023).
- Optional: the NESO electricity day-ahead forecast as a second forecaster.

## 10. Deviations

- Any change after the freeze gets a dated decision-log row with its reason
  **before** the affected result is computed, and is listed in the paper's
  appendix.
- A result is never re-run under a changed specification without that row.
- Trial count for any multiple-testing statement = rows in the decision log
  from the freeze onward.

## 11. Freeze procedure

1. ~~Owner resolves the open decisions below and approves the text.~~ Done
   2026-11-19.
2. ~~The day-ahead price provider's methodology note is in hand.~~ Done: EEX
   publishes the EOD window, 17:15–17:30 CE(S)T. Product rule in §1.
3. Commit this file. The commit hash is the frozen version.
4. **Owner** uploads it to OSF (it is the owner's account and a public act)
   and records the OSF link.
5. Append the freeze row to `reports/decision_log.md` with hash and link.
6. In the same commit as row 5, set `PRICE_PREREGISTRATION_ROW` to that row
   number. Only then pull prices.

## Owner decisions — **D1–D7 all approved as drafted** (D1–D5 2026-11-18, row 51; D6–D7 2026-11-19, row 54)

| # | Decision | Approved |
|---|---|---|
| D1 | Adopt literature proposals (i)–(v) of row 50 as written here (CG convention, H3b, H1-orth, H1-tight, Thomas et al. baseline) | Adopt all |
| D2 | **LDZ revisions as the H1 regressor**, NTS as robustness (endogeneity argument, §2). New in this draft; not in the plan. | Adopt |
| D3 | Day-level H1 primary, with the within-day SAP version only as fallback | Adopt; the cumulative SAP path is too weak a measure for a primary when a day-ahead price exists |
| D4 | D+6 outturn as headline for NTS too (consistent with C1). The incentive's outturn vintage is unknown. | Adopt; revisit only if the licence says otherwise *before* the freeze |
| D5 | Cold threshold fixed at CWV ≤ 4.00 from DEV, not re-computed on CONF | Adopt |

**Decisions from the series search (2026-11-19, rows 52–53), approved 2026-11-19:**

| # | Decision | Approved |
|---|---|---|
| D6 | **Revised after the blind probe (row 53).** Day-ahead series = EEX NBP EOD `PNX-NBPEOD-DA` (window 16:15–16:30 UK; entitled; complete). It starts **2023-03-20**, so the **price tests (H1, H1-\*, H4, H5) use DEV-P = 2023-03-20 → 2026-08-07** (about 850 trading days); H2, H3 keep the full DEV. Marex Spectron `GA2NB` (history ≤2015, but thinning badly: ~half of 2026 missing) is used only as a labelled robustness extension of H1 back to 2021-12-01, never in CONF. §8 fallback not needed. | Adopt. Costs: the price tests miss the 2022 shock year; the paper says so. |
| D7 | Classification of the LDZ D−1 16:15 publication: with the EEX window opening at 16:15, call it **post-close** in the primary H1 (it cannot be impounded at the window's first minute), with pre-close as robustness. `R_pre` is then always zero, so **H1-pre has no variation and is dropped** from the secondary family. | Adopt post-close. Alternative: keep H1-pre with 16:15 as pre-close, at the cost of a contestable timing assumption. |
