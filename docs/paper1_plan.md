# Paper 1 plan — Operator gas demand forecasts, their revisions, and NBP prices

**Date:** 2026-11-17. **Status:** plan only; no price data has been accessed.
**Builds on:** Option 1 / Phase C1 (`reports/phase2_efficiency.md`, decision log
rows 38–47). C1's kill criterion fired, so C2 as written in
`docs/research_plan_v2.md` is **not** revived here. The price questions below
are new hypotheses, logged as post-C1, and do not depend on the operator's
error being predictable.

## P0 status (2026-11-17, decision log row 49)

| Item | Status |
|---|---|
| NTS forecast, every publication | **Done.** On disk, 2021-12-01 → 2026-11-09, no missing days. The incentivised D−1 forecast is the **13:10** portal slot (published "at 13:00"). |
| NTS actuals D+1, D+6 | **Done.** D+1 is republished ~5× on D+1, so the first-knowable value must be gated. |
| SAP / SMP | **Loaders done and tested; one probe week only.** Embargo lifted at the freeze (row 55, OSF https://osf.io/zdytk/). SAP and EEX DA pulled for DEV-P; DEV estimates in decision log row 59. H4 (point-in-time TMS baseline, demand lagged to D−2) in rows 60–62: null; the secondary family rejects nothing. |
| Hourly within-day SAP path | **New finding:** `PUBOB47`. It allows an intraday version of H1 around the 10:15 / 13:10 / 16:15 publications. Caveat: it is a *cumulative* within-day average without volumes, so hourly marginal prices can't be recovered exactly. Decide day-level vs hourly H1 **at the freeze**, not after. |
| Timestamp timezone | **Resolved: UK local.** §4.1 is no longer a risk. |
| Gas-day definition | **05:00 UK local**, not 05:00 UTC. `CLAUDE.md` §2.3 needs an owner amendment; Phase 1b is affected by 1 h on BST days (disclosed, not re-run). |
| Incentive loss | **Absolute error**, annual weighted average (licence SpC 5.6 Part C). The weights are not yet found. H2–H3 run p = 1 as primary and p = 2 as a check. |
| History before 2021-12 | **None on the portal.** C's pre-shock baseline is only Dec 2021 – Feb 2022, when prices were already high. C stays exploratory. |
| **NBP day-ahead price (G0)** | **Open: owner action.** Library request below. |
| Literature review | **First pass done** (`docs/paper1_literature.md`, row 50). Six design proposals await the freeze. Full-text reading and forward-citation checks are still open. |

**Library request (to send):**

> I need a daily NBP (UK natural gas) **day-ahead** price series for academic
> research, 1 Dec 2021 to the present: ideally the ICIS Heren NBP day-ahead
> index, or the ICE Endex NBP day-ahead settlement. Bid and offer would also
> help. Is it available through LSEG Datastream / Workspace, Bloomberg or
> another subscription the library holds? I also need the methodology note
> giving the assessment window (time of day), and the weekend and
> bank-holiday product conventions.

---

## 0. Venue

| Venue | Role | Why |
|---|---|---|
| **The Energy Journal** | **Primary** | The closest prior paper (Thomas, Massol & Sévi 2022, EJ 43(5)) is here. A GB follow-up with publication-by-publication forecasts and an incentive-defined loss function is a natural sequel. EJ wants the economics of energy, which the regulation and price angles supply. |
| Energy Economics | Fallback | Same paper, if EJ declines. |
| International Journal of Forecasting | Only if §1 contribution A becomes the main result | IJF would publish "rationality under a regulator-defined loss" as a method-plus-evidence paper, but not the price leg alone. |
| ICAIF | Not targeted | No AI/ML contribution; not found in CORE. |

**EJ practicalities:**
- single-anonymised review by two referees;
- $150 submission fee, waived if an author is an IAEE member, so join as a student first;
- preprints allowed, so post the working paper first and give its DOI on submission.

---

## 1. What the paper claims

Each contribution is designed so that **either outcome is publishable**. That
is the main defence against a desk reject for "null result".

**A. Rationality under the loss the regulator actually imposes.**
- National Gas is financially incentivised on the accuracy of its D−1 NTS
  demand forecast, published at 13:00. The RIIO-2 target was 8.35 mcm/day; a
  later scheme is listed at 6.79 mcm/day, adjustable for wind.
- If the incentive scores absolute error, the rational forecast is the
  conditional *median*, not the mean. C1's Mincer–Zarnowitz rejections (a mean
  test) may then say nothing about irrationality.
- Most rationality papers must guess the loss function (Elliott, Komunjer and
  Timmermann 2005, 2008). Here it is written in a licence.
- *Outcomes:* rational at the median under the incentive → the bias is the
  incentive's design, which is a regulatory finding. Not rational → a stronger
  finding.
- The incentivised publication (13:00 NTS) versus the non-incentivised ones
  (LDZ, within-day) gives a within-forecaster contrast.

**B. Does the market know what the operator knows, and when?** This is the GB
counterpart to Thomas et al., with what they lacked: every publication of the
forecast, timestamped.
- **Primary (B1):** do operator revisions published *after* the day-ahead
  price is set move the within-day price (SAP), while revisions published
  *before* it do not?
- The second half is the semi-strong efficiency test, with a built-in placebo.
- *Outcomes:*
  - post-close revisions priced and pre-close revisions not → efficient
    market, plus a price-impact estimate;
  - pre-close revisions priced → the day-ahead price under-reacts to public
    information;
  - nothing priced → operator revisions carry no price-relevant news beyond
    weather forecasts.

**C. How fast did the operator learn the 2022/23 demand response?**
- C1 found the forecast's bias peaked at +2.87 mscm/day in 2022/23 and decayed
  by 2025.
- Weather-adjusted household gas demand fell about 13–18% that winter (OBR;
  Warwick CAGE WP 727). A bias of about 2–3% of demand implies the forecaster
  absorbed most of the drop quickly. That is unverified and is what C measures.
- *Estimand:* the half-life of the bias after the shock, and whether
  publicly known retail prices (the Ofgem price cap and the Energy Price
  Guarantee) predict it.
- C was suggested by C1 data, so it is **labelled exploratory** in the paper.
  Its confirmatory element is the frozen tests in §5.

---

## 2. What is already known, and what that constrains

| Fact | Consequence |
|---|---|
| C1: revisions efficient (β = −0.044, 95% CI ≈ [−0.29, 0.20]); corrected forecast does not beat the raw one | Reported as is. Not re-estimated with new specifications on the development sample. |
| C1: issue-time information predicts the error (ΔCWV, cold days), but this was motivated by C0 | **Confirmation-sample only** (§5, H6–H7). |
| **No price data has been touched** | The price hypotheses can be genuinely pre-registered. This is the paper's biggest credibility asset; freeze before the first price pull. |
| Development sample ends 2026-08-07; confirmation 1 runs from 2026-08-08 and confirmation 2 is winter 2026/27 | Development results go in the working paper; the confirmation sample goes in the submission. |

---

## 3. Data

| Series | Source | On disk? | Knowable at | Audit task |
|---|---|---|---|---|
| LDZ forecast, 8 publications × 13 zones | National Gas portal | yes, from 2021-12-01 | each `generatedTimeStamp` | none |
| LDZ actuals, D+1 and D+6 | National Gas portal | yes | per-row `published_at` | none |
| CWV forecast and actual | National Gas portal | yes | per publication | none |
| **NTS total demand forecast, all publications, including the 13:00 D−1 incentivised one** | National Gas portal | **no** | each publication | Find the PUBOB ids; confirm every publication is served with `latestFlag=N`; check when history starts. Prices clear on *total* demand (LDZ plus power, industry, exports, storage), so this, not LDZ, is the price-relevant forecast. |
| NTS actual demand (vintages) | National Gas portal | no | per publication | same |
| **SAP** (system average price, gas day D) | National Gas portal; ONS dataset | no | after gas day D ends | Free. Volume-weighted average of OCM trades for D. |
| SMP buy/sell (cash-out prices) | National Gas portal | no | after D | Free. Robustness and imbalance-cost framing. |
| **NBP day-ahead price** | **institutional: LSEG Datastream or Bloomberg (ICIS Heren / ICE Endex)** | no | the assessment window on D−1 | **Gate G0.** Ofgem's series is monthly only. Document the assessment window *in London time*, plus the weekend/holiday product convention. |
| Ofgem price cap, EPG levels | Ofgem | no | announcement dates | For C. Use announcement date, not effective date. |
| Incentive scheme documents | National Gas, Ofgem RIGs | no | scheme dates | Exact formula (absolute or squared error, deadband, which publication, which outturn vintage). Determines the loss function in A. |

**Gate G0** (end of P0): if no daily day-ahead NBP price with a documented
assessment time covering 2021-12 → 2026-08 can be licensed, drop B. The paper
becomes A + C and the target moves to IJF or Energy Economics. Record the
outcome in the decision log.

---

## 4. Point-in-time and timing (stricter than C1)

1. **The publication-timestamp timezone is no longer moot.** C1 compared only
   timestamps from the portal's own clock. B compares them with a price
   assessed on the London clock.
   - Resolve it using the documented 13:00 London publication time of the
     incentivised forecast against its portal timestamp in BST months.
   - If it can't be resolved, run every timing-sensitive test on **GMT months
     only**, when London = UTC, and say so.
2. **Gas-day definition.** `CLAUDE.md` says 05:00–05:00 UTC. Check this against
   the UNC transportation principal document, which may define it in UK local
   time. If it does, conversion code across the repo is affected.
3. **Before or after the close.**
   - Each publication is classified once, before estimation, as before or after
     the day-ahead assessment window.
   - The 13:15 D−1 publication precedes any plausible close. Whether 16:15
     does depends on the assessment methodology.
   - Classification rules go in the decision log.
4. **SAP for D is knowable only after D ends.** It is an outcome, never a
   regressor.
5. **Day-ahead weekend and holiday products** cover several gas days. Either
   map them correctly or exclude them, decided before estimation.
6. Weather news: the public weather-forecast change between publications (the
   CWV forecast gated to before each publication, as in C1) is a control.

---

## 5. Hypotheses to freeze (decision log + OSF, before the first price pull)

> **Superseded by `docs/paper1_preregistration.md` (draft, 2026-11-17).**
> The draft refines this section: LDZ revisions as the H1 regressor, H1-orth,
> H1-tight, H3b, a confirmation family, a pre-specified fallback for G0, and
> the freeze procedure. The list below is kept as the original plan.

**Primary (one test):**
- **H1 (B1):**
  `SAP_D − P^DA_{D−1} = a + β_post · R_post + β_pre · R_pre + γ · ΔCWVfc_post + u`
  - `R_post` is the NTS forecast revision from the last pre-close publication
    to the last publication before D starts.
  - `R_pre` is the D−1 revision before the close.
  - Headline: H0 β_post = 0. Joint test: β_pre = 0.
  - HAC standard errors (Newey–West), with the lag set before estimation.
  - MDE by block bootstrap, computed before estimation, exactly as in C1.

**Secondary (Holm-corrected as one family):**
- **H2 (A):** quantile Mincer–Zarnowitz at τ = 0.5 on the incentivised 13:00
  NTS forecast, against the outturn the incentive scores.
  - Contrast: the LDZ 13:15 and 16:15 publications.
  - The τ = 0.5 analogue of C1's test, on a different forecast.
- **H3 (A):** Elliott–Komunjer–Timmermann (EKT) GMM estimate of the asymmetry
  parameter α, for absolute-error (p = 1) and squared-error (p = 2) loss.
  - Instruments: constant, last known error, CWV forecast.
  - Rationality test given α; α by gas year.
- **H4 (B, Thomas et al. reversed):** do day-ahead price changes before the
  close predict the incentivised forecast's error? An encompassing test:
  Harvey–Leybourne–Newbold.
- **H5 (B):** does the day-ahead price change predict the operator's *later*
  revisions? That is, does the market anticipate the operator?
- **H6 (confirmation only):** the 16:15 LDZ error loads positively on ΔCWV
  (C1, S10). Scored on 2026-08-08 → 2027-03-31 only.
- **H7 (confirmation only):** cold-regime over-forecast (C1, S11), same
  sample.

**Exploratory (labelled as such):**
- C: break dates in monthly bias (Bai–Perron), bias half-life, and bias on
  lagged price-cap level.
- NESO electricity day-ahead forecast as a second forecaster facing the same
  shock. Optional; include only if A and B are complete.

**Confirmation sample:** H1, H2, H6 and H7 are also scored on
2026-08-08 → 2027-03-31, with every estimated parameter frozen.
- Compute the MDE for that sample first and publish it with the
  pre-registration.
- One winter may detect only large effects; say so beforehand.

---

## 6. Baselines (implemented first, with tests)

| Test | Named baseline |
|---|---|
| Forecast accuracy | B1 raw operator; B2 no-change; B3 CWV + calendar walk-forward (exists) |
| H1 price change | **Martingale:** E[SAP_D − P^DA] = 0. **Weather-news only:** the same regression with `ΔCWVfc_post` alone. Revisions must add beyond public weather news; otherwise the operator is just relaying the weather. |
| H4 | Operator forecast alone, versus forecast plus price |

---

## 7. Economic significance, and what is not claimed

- **Primary economic quantity:** price impact in p/therm per mscm of
  revision, and the implied imbalance-cost exposure using SMP.
- **No P&L.** A trading result needs bid–ask and execution data that GB
  open sources don't provide (`CLAUDE.md` §6).
- A trading section is added only if H4 or H5 shows information the market
  fails to price *and* spread data is licensed. It would then carry the full
  cost model and the break-even cost. Otherwise the paper says plainly that
  no tradeability claim is made.

---

## 8. What EJ referees will check

- An **institutional background** section covering OCM trading, SAP, cash-out,
  the publication schedule and the incentive formula. EJ referees expect it.
- Literature, with a proper review (25–40 references), including:
  - forecast rationality: Mincer–Zarnowitz 1969; Nordhaus 1987; EKT 2005,
    2008; Patton–Timmermann 2007;
  - Thomas, Massol & Sévi 2022;
  - forecast-news effects in electricity intraday markets;
  - NBP efficiency and weather news;
  - the 2022/23 GB demand response (OBR; Warwick CAGE).
- **Inference:** HAC standard errors, effective N stated, and the trial count
  from the decision log.
- **Robustness:**
  - D+1 vs D+6 outturn;
  - LDZ vs NTS;
  - GMT-only months;
  - excluding Oct 2022 – Mar 2023;
  - excluding supply-shock days (Norwegian outages, LNG), identified from
    public notices.
- **Pre-registration link** (OSF), timestamped before the first price pull.
- **Replication package:** code plus derived statistics. Licensed price data
  is not redistributed, only the script that reads it.

---

## 9. Phases

| Phase | Work | Exit |
|---|---|---|
| P0 data and institutions (≈1–2 wk) | NTS forecast vintages, SAP and SMP loaders, with docstrings per `CLAUDE.md` §7; library request for the day-ahead price; timezone and gas-day checks; incentive formula; literature review | **G0** recorded |
| P1 freeze (≈2–3 days) | Decision-log rows and OSF pre-registration; MDE for H1 on the development sample and the confirmation sample | Frozen before any price is loaded into analysis |
| P2 estimate, development sample (≈1–2 wk) | Baselines first, then H1–H5; exploratory C | Results in decision log |
| P3 working paper (≈2 wk) | SSRN or arXiv | Preprint DOI |
| P4 confirmation (after 2027-03-31) | Score the frozen tests; add the section | **Submit to EJ** |

The 2–3 weeks originally suggested covers P0–P2 only if the day-ahead price
arrives quickly. The library request is the long pole, so make it on day one.

---

## 10. Risks

| Risk | Effect | Mitigation |
|---|---|---|
| No licensed day-ahead NBP series | B drops | G0, then A + C to IJF or Energy Economics |
| NTS forecast history shorter than LDZ | Smaller A sample | Run A on LDZ as well; report both |
| Supply shocks dominate 2022 prices | Low power for H1 | MDE shown up front; supply-shock exclusion robustness |
| Timestamp timezone unresolved | Timing tests weaker | GMT months only |
| Incentive formula not public in full | Loss function in A uncertain | Run p = 1 and p = 2; report both |

---

## 11. Manuscript outline (EJ)

1. Introduction: the question, the three contributions, the headline numbers
2. Institutional background: GB gas balancing, OCM, SAP, cash-out, the
   forecast schedule, the incentive
3. Data and point-in-time construction
4. Method: incentive-loss rationality; the news-impounding regression; power
5. Results A (rationality), B (prices), C (crisis, exploratory)
6. Pre-registered confirmation sample
7. Robustness
8. Discussion: incentive design, market efficiency, limits
9. Conclusion

Appendices: decision-log trial count, every publication slot, the MDE curves,
and what did not work (C1's corrected forecast).
