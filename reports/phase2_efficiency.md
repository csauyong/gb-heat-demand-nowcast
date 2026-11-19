# Phase C1 — Is National Gas's day-ahead LDZ demand forecast weakly efficient?

**Date:** 2026-11-17
**Scope:** Option 1, Phase C1 of `docs/research_plan_v2.md`. Pre-specified in
`reports/decision_log.md` rows 43–46 before any estimate; results in row 47.
**Kill criterion C1 fired.** Phase C2 (prices) is not run.

---

## The result, stated plainly

**The forecast's revisions are efficient. Its level is not.**

- **Primary test — null.** The error of the last D−1 publication (16:15) does
  not depend on the 13:15 → 16:15 revision: slope **−0.044** (HAC SE 0.125,
  p = 0.72), which is **0.17 × the minimum detectable effect** (0.254). The
  test was powered: its simulated size is 0.046, and a slope of 0.25 would be
  found 80% of the time.
- **Kill-criterion forecast — fails.** Adding a walk-forward intercept and
  revision correction to the raw 16:15 forecast makes it slightly *worse*:
  MAE 3.985 vs 3.965 mscm/day over 1,320 days, Diebold–Mariano p = 0.77.
- **But the forecast is biased.** Mincer–Zarnowitz rejects unbiasedness at
  every one of the eight vintages (p ≤ 8 × 10⁻¹¹). The 16:15 error is
  predictable from information public at 16:15 (joint χ²₅ = 75.8,
  p = 6 × 10⁻¹⁵). On the coldest tenth of days it over-forecasts by
  **+2.17 mscm/day**, about 1% of offtake.

**Why the bias cannot be exploited by the pre-specified correction.** It does
not stay still. Mean 16:15 error by Oct–Sep year (D+6 target, mscm/day; descriptive):

| Year | 2021/22* | 2022/23 | 2023/24 | 2024/25 | 2025/26* |
|---|---|---|---|---|---|
| Mean error | +0.82 | **+2.87** | +1.24 | +0.09 | −0.36 |
| MAE | 3.72 | 5.23 | 3.49 | 3.83 | 3.92 |

\* partial year (from 2021-12-01; to 2026-08-07).

The over-forecast peaked in the 2022/23 energy-price-shock year, when
households cut gas use in response to price rather than weather, and it has
decayed since. An expanding-window correction learns the crisis-year bias and
then over-corrects: on 2023-12 → 2026-08 its bias is −1.29 against the raw
forecast's +0.26. The price-shock explanation is a hypothesis; C1 did not test it.

**What can be claimed:** at D−1 the published LDZ forecast uses its own revision
news efficiently, and a simple statistical correction does not beat it out of
sample. **What cannot be claimed:** that the forecast is unbiased. The plan's
wording for this outcome, "weakly efficient at D−1", is too broad and is not
used.

---

## Design

| Item | Choice | Log row |
|---|---|---|
| Sample | 2021-12-01 → 2026-08-07 (development); 1,711 GB days, 1,680 complete for the primary test | 40, 46 |
| Target | **D+6 reconciled actual** (headline); D+1 first-published actual (sensitivity) | 43 |
| Unit | GB = sum of 13 LDZs, only where all 13 are present | 44 |
| Vintages | 8 canonical slots, D−1 13:15 → D+1 00:15; 1,625 non-canonical rows dropped | 44, 46 |
| Inference | Newey–West HAC, 7 lags; effective N ≈ 277 of 1,680 days | 44 |
| MDE | Block bootstrap of the real error, independent of the revision; 500 draws per grid point; computed before the estimate | 44 |

**Point-in-time handling.**
- The CWV regressor is gated to the last publication before each day's 16:15
  issue (median 1 h before). The Phase 1b gate would have used the 23:15
  publication, which comes after the 16:15 issue.
- The "last known error" regressor uses a D+1 actual only if it was published
  before the issue time. On 10.8% of days that means D−3 or earlier, because
  the D−2 actual published late.

**Disclosed side effect for Phase 1b (row 46).** The Phase 1b CWV baseline was
served the 23:15 CWV, about 7 h later than the incumbent's 16:15 issue. That
favours the baseline, so the Phase 1b conclusion (the incumbent wins) is
conservative. Phase 1b was not re-run.

---

## Baselines (GB, identical rows, 2023-12-01 → 2026-08-07, 971 days)

| Model | Target | MAE | RMSE | Bias | MAPE |
|---|---|---|---|---|---|
| B1 raw incumbent, D−1 16:15 | D+6 | **3.72** | 5.16 | +0.26 | 3.27% |
| f* corrected (kill criterion) | D+6 | 4.03 | 5.30 | −1.29 | 3.84% |
| B3 CWV + calendar walk-forward | D+6 | 7.11 | 8.61 | −5.88 | 7.76% |
| B1 raw incumbent | D+1 | 3.88 | 5.73 | +0.34 | 3.41% |
| f* corrected | D+1 | 4.12 | 5.81 | −1.11 | 3.87% |
| B3 CWV + calendar | D+1 | 7.20 | 8.97 | −5.79 | 7.84% |

B2 ("no further revision") is the zero forecast for each next revision; its
loss is the mean absolute revision, in the Nordhaus table below.

---

## Secondary tests (D+6 target; Bonferroni α = 0.05/12 = 0.0042)

| Test | Estimate | p | Reject |
|---|---|---|---|
| S1 MZ, D−1 13:15 | a = +0.93, b = 0.984 | 8e-11 | yes |
| S2 MZ, D−1 16:15 | a = +0.80, b = 0.985 | 4e-13 | yes |
| S3 MZ, D 00:15 | a = +0.59, b = 0.987 | 3e-12 | yes |
| S4 MZ, D 10:15 | a = +0.50, b = 0.987 | 5e-17 | yes |
| S5 MZ, D 13:15 | a = +0.24, b = 0.987 | 2e-26 | yes |
| S6 MZ, D 16:15 | a = +0.04, b = 0.989 | 4e-28 | yes |
| S7 MZ, D 21:15 | a = −0.41, b = 0.995 | 7e-19 | yes |
| S8 MZ, D+1 00:15 | a = −0.52, b = 0.996 | 3e-17 | yes |
| S9 Nordhaus chain (stacked, clustered by day) | slope −0.018 | 0.90 | no |
| S10 issue-time information (joint) | χ²₅ = 75.8 | 6e-15 | yes |
| S11 cold regime (CWV ≤ 4.00, 169 days) | +2.17 mscm/day | 1.5e-4 | yes |
| S12 panel primary, Driscoll–Kraay | β = +0.077 | 0.042 | no |

S10 coefficients: CWV −0.21, ΔCWV **+1.63**, weekend +0.31, holiday +0.34,
last known error +0.016. When tomorrow is forecast warmer than today, the
forecast runs high, i.e. it under-responds to a forecast change in weather.

**Caveat on S10 and S11.** Both were motivated by Phase C0, which used
2023-12 → 2026-08, 57% of this sample. Their rejections are not independent
confirmation, and they are the hypotheses to take to a confirmation sample.

Per-pair Nordhaus slopes (descriptive; B2 loss = mean |revision|, mscm/day):

| Pair | Slope | HAC p | B2 loss |
|---|---|---|---|
| D−1 16:15 → D 00:15 | +0.078 | 0.016 | 0.81 |
| D 00:15 → D 10:15 | +0.330 | 0.060 | 1.71 |
| D 10:15 → D 13:15 | −0.292 | 0.27 | 1.30 |
| D 13:15 → D 16:15 | +0.153 | 0.11 | 0.98 |
| D 16:15 → D 21:15 | +0.286 | <0.001 | 1.07 |
| D 21:15 → D+1 00:15 | +0.088 | <0.001 | 0.33 |

Revisions within gas day D are positively autocorrelated late in the day,
which suggests smoothing. Stacked across pairs, the slope is zero. These are
within-day vintages, not the day-ahead decision.

---

## What did not work

- The pre-specified revision/intercept correction (f*): worse than the raw
  forecast, because the bias is non-stationary.
- The cold-regime "forecast failure" from Phase 1b, already withdrawn in C0.
  What remains is ~1% bias, and the test is not independent of C0.
- C2 was not reached, so no price or tradeability claim is made in either
  direction.

## What would be needed to go further (not done; owner decision)

A **new**, disclosed-as-post-hoc hypothesis could be tested, for example: "the
16:15 forecast under-responds to ΔCWV" or "the forecast over-forecasts in the
cold". It would need to be frozen now and scored only on confirmation samples
1 (2026-08-08 onward) and 2 (winter 2026/27). It must not be refit or
re-tested on the development sample.

## Reproducing

```bash
python scripts/run_c1_efficiency.py
```

Warm cache: about a minute, with no network calls. Tables are in
`reports/tables/c1_*` (gitignored, regenerated by the script).
