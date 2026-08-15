# Research plan

Phased plan for both projects. Every phase has an explicit **kill criterion**:
the result that means *stop and write up what you found*, rather than tune.

## Why kill criteria are written down first

The failure mode for a portfolio project built alongside a thesis is not
producing a bad result. It is producing an *endless* one — a project that
absorbs eighteen months because every disappointing number invites one more
specification. A kill criterion fired is not a failure; it is the project
returning its answer early and freeing the time.

Two rules make them binding:

1. **A kill criterion is evaluated once, on pre-specified data, and the verdict
   is recorded in `reports/decision_log.md` with the date.** Re-running a kill
   test after changing the model is a new test and counts toward the
   multiple-comparisons budget.
2. **"Killed" means the phase stops and the finding is written up.** It does
   not mean the project is deleted. A killed Project A at Phase 3 still yields
   a complete, honest piece of work — arguably a better one than a marginal
   pass. See `CLAUDE.md` §5.

**Time budget.** Thesis submission is April 2027. These projects must not
threaten it. Suggested allocation: Project A ~12 weeks of effective part-time
work, Project B ~8 weeks, running roughly in parallel with A first. Project B
is deliberately the lighter lift and the safer deliverable — it produces a
publishable artefact even in the fully null case, because a well-diagnosed null
with placebo evidence *is* the result. If time compresses, protect B and
truncate A at whatever phase it has reached.

**Order of attack.** Do Phase A0 and B0 before committing to either. They are
cheap and they are the phases most likely to kill a project before you have
invested in it.

---

# Project A — GB domestic heat demand nowcast

**Research question.** Does a bottom-up, stock-based model of GB domestic heat
demand contain information about realised GB electricity and gas demand not
already present in the published NESO day-ahead forecast; and if so, does it
survive costs?

**Structural note before starting.** The single hardest problem in this project
is not modelling — it is that **domestic heat demand is not directly
observed**. NESO's ND/TSD are transmission-metered and net of embedded
generation. Gas LDZ offtakes are much closer to domestic heat but mix in small
commercial load. The project must be honest about what it is validating
against, and the choice of validation target should be made in Phase A1 and
then fixed. Do not drift between targets when results disappoint — that is
specification search wearing a lab coat.

**Recommendation:** make the **gas LDZ offtake series the primary validation
target**, not electricity demand. ~85% of GB homes heat with gas, so the
signal-to-noise ratio is far better, and the incumbent baseline (National Gas's
published Composite Weather Variable) is a well-defined comparator. Electricity
becomes the secondary target where heat pumps and resistive heating matter.
This is a stronger project than the electricity-first version and it is not
obvious until you look at where the domestic heat signal actually lives.

---

### Phase A0 — Feasibility and data reconnaissance (1–2 weeks)

Cheapest phase, highest kill value. Do not skip it.

**Do:**
- Pull one year each of: EPC bulk extract, NESO historic demand, NESO historic
  day-ahead forecasts, National Gas LDZ offtakes, Open-Meteo historical
  *forecast* archive, ONS LSOA dwelling counts.
- Confirm the Open-Meteo historical forecast archive actually covers GB at
  usable resolution back to 2021, with the variables needed (2m temperature,
  wind speed, solar radiation, humidity).
- Compute EPC coverage by LSOA against ONS dwelling counts. Map it. Look at
  the spatial pattern of the gaps.
- Reproduce NESO's published day-ahead forecast error distribution from their
  own performance dataset. Know the number you are trying to beat before you
  build anything.
- Write down, in one page, exactly what series you will validate against and
  why.

**Kill criterion A0.**
> **Kill if the Open-Meteo historical forecast archive does not provide GB
> coverage back to at least 2021-22 winter with the required variables, and no
> free substitute archive of point-in-time forecasts can be found.**
>
> Without point-in-time forecast weather there is no legitimate trading-signal
> project — only a realised-weather diagnostic exercise, which is not what this
> project claims to be. Do not proceed on realised weather with a promise to
> fix it later. That promise is never kept and the whole result set becomes
> unusable.
>
> **Also kill if** EPC coverage is below ~35% of dwellings in more than a
> quarter of LSOAs *and* the coverage gap correlates strongly with observable
> stock characteristics (tenure, build age, deprivation) — at that point the
> reweighting step carries more uncertainty than the signal it supports, and
> the bottom-up model is dominated by an unverifiable assumption.
>
> **Fallback if killed on coverage:** reframe as an England-and-Wales,
> high-coverage-LSOA study with explicit external-validity limits. Still a
> good project. Not a GB nowcast.

**Deliverable:** `reports/00_feasibility.md` + coverage map.

---

### Phase A1 — Stock construction and the bottom-up physical model (3–4 weeks)

**Do:**
- Deduplicate EPC to latest-certificate-per-address as-of a stated date.
- Aggregate to LSOA: dwelling counts by archetype (built form × wall type ×
  insulation level × heating fuel × floor area band).
- Reweight to ONS dwelling counts. **Test the reweighting**: hold out LSOAs
  with high coverage, degrade them to the coverage level of low-coverage LSOAs,
  and check the reweighting recovers the truth.
- Build the physical heat-loss model: fabric U-values → heat loss coefficient
  per archetype → LSOA-level heat demand as a function of external temperature,
  with heating system efficiency and a behavioural response (setpoint,
  heating hours, occupancy).
- Aggregate LSOA → GB using the fixed spatial weighting scheme (see
  `docs/data_inventory.md` §5.4 — scheme estimated on HadUK-Grid climatology,
  values fed from forecast weather).
- **Build the baselines now, not later:** HDD-plus-calendar regression, and the
  National Gas CWV-based comparator.

**Kill criterion A1.**
> **Kill if the bottom-up model, driven by *realised* weather (the generous
> case), cannot match the HDD-plus-calendar baseline on the validation target
> — say, within 10% on RMSE over a full heating season.**
>
> This is the oracle test and it is deliberately generous. If the physical
> model cannot beat a two-variable regression when handed perfect weather, the
> stock detail is adding noise, not information, and no amount of ML on top
> will rescue it. The realistic forecast-driven case can only be worse.
>
> **This is the most likely kill point in the project,** and it is worth
> knowing that in advance rather than being surprised. Bottom-up building
> physics models are notoriously poor at aggregate prediction — the prebound
> and rebound effects mean actual consumption deviates from modelled
> consumption by 30%+ systematically, and the deviation is behavioural, not
> fabric-driven. If A1 kills, **the write-up is genuinely interesting**: it is
> a quantified statement about the aggregate performance gap in GB housing
> stock models, which is a live question in the energy literature and is
> directly adjacent to the thesis.

**Deliverable:** `reports/01_stock_model.md`, LSOA archetype table,
reweighting validation.

---

### Phase A2 — Point-in-time nowcast (2 weeks)

Switch from realised to **forecast** weather. Everything from here is
point-in-time legal.

**Do:**
- Rebuild the demand estimate from archived forecast weather at the correct
  vintage for each target timestamp.
- Establish the walk-forward evaluation harness: expanding window, refit
  cadence stated, embargo at the split boundary.
- Decompose error: model error vs weather-forecast error, using the A1 oracle
  run as the reference.
- Report against both baselines on identical splits.

**Kill criterion A2.**
> **Kill if the forecast-driven model's skill over the HDD-plus-calendar
> baseline is not statistically distinguishable from zero on out-of-sample
> walk-forward evaluation (Diebold-Mariano, accounting for autocorrelation and
> for the small effective sample — ~5 winters).**
>
> Note the honesty requirement in the test: with ~5 heating seasons the
> effective sample is small and the test will have low power. State the minimum
> detectable effect. If the test cannot detect a 10% RMSE improvement at
> reasonable power, say so — an underpowered null is not evidence of absence,
> and pretending otherwise in either direction is the error to avoid.

**Deliverable:** `reports/02_nowcast.md` with the error decomposition.

---

### Phase A3 — Incremental information over the published forecast (2–3 weeks)

**This is the scientific core of the project.** Even if Phase A4 never happens,
a clean answer here is a complete piece of work.

**Do:**
- Regress the NESO day-ahead forecast error on the bottom-up model's
  information: encompassing regression, forecast combination weights, Granger-
  style tests on the residual.
- Condition on regime: cold snaps, shoulder season, holidays, wind-driven
  embedded generation errors. **Incremental information is far more likely to
  exist in the tails than on average**, and an average-case null with a
  cold-snap signal is an interesting result, not a failed one. Pre-specify the
  regimes before looking.
- Test the gas side (LDZ offtakes vs National Gas D+1 forecast) and the
  electricity side separately.

**Kill criterion A3.**
> **Kill the trading strand if the bottom-up model's information adds no
> statistically significant explanatory power to the published forecast error
> — i.e. its forecast-combination weight is not distinguishable from zero, and
> the encompassing regression cannot reject that the published forecast
> encompasses the bottom-up model — in any pre-specified regime.**
>
> **If this fires, the project is finished and it is finished successfully.**
> Write up: "the published operational forecast already impounds building-stock
> heterogeneity; a bottom-up EPC-based model adds no incremental information at
> GB aggregate level, including in cold-snap regimes." That is a clean,
> defensible, negative finding about operational forecast efficiency, it is
> directly relevant to the roles you are targeting, and it demonstrates exactly
> the discipline a research desk wants to see. **Do not proceed to Phase A4 to
> salvage it.** A P&L built on an information source you have just shown to be
> uninformative is noise mining, and a competent interviewer will identify it
> as such in about ninety seconds.

**Deliverable:** `reports/03_incremental_information.md` — **the headline
deliverable of Project A regardless of sign.**

---

### Phase A4 — Tradeability (3 weeks) — *only if A3 passes*

**Do:**
- Map the residual signal to a tradeable instrument: GB day-ahead power
  (Elexon MID / N2EX reference), or NBP within-day / day-ahead gas. **Not the
  forward curve** — that data is commercial (`docs/data_inventory.md` §10).
- Define the decision timestamp precisely: when the NESO forecast publishes,
  when the weather forecast run lands, when the market closes for the relevant
  auction. The signal must be knowable before the tradeable moment.
- Build the cost model *first*: spread, commission, slippage, position size vs
  typical volume, capacity.
- Backtest with walk-forward parameter selection. Report break-even cost level
  as the headline statistic.
- Deflate the Sharpe ratio for the number of specifications in the decision
  log.

**Kill criterion A4.**
> **Kill if the strategy's break-even transaction cost is below a realistic
> round-trip cost for the instrument, or if the deflated Sharpe ratio's
> confidence interval includes zero.**
>
> Report the break-even cost either way — "profitable up to £X/MWh round trip
> against a realistic £Y" is an informative and honest result in both
> directions, and it is a far better thing to put in front of a desk than a
> point-estimate Sharpe.

**Deliverable:** `reports/04_tradeability.md` with cost sensitivity surface.

---

### Phase A5 — Write-up (1–2 weeks)

Whatever phase the project reached. `reports/final_report.md` + README with:
research question, method, headline result **including negative results**, what
did not work, and the decision log as an appendix.

---

# Project B — Causal event studies on UK energy-policy shocks

**Research question.** Do UK energy-efficiency and heating-policy
announcements produce measurable abnormal returns in exposed equities; and does
an SC/SDiD design recover effects that the standard market-model event study
misses or spuriously reports?

**Structural note.** This project has a **guaranteed deliverable** and that is
its main virtue as portfolio insurance. Even if every effect is null, the
methodological comparison — market model vs SC vs SDiD, with placebo and
pre-trend diagnostics on the same events — is itself the contribution. Frame it
that way from the start rather than as a hunt for significant effects, and the
incentive to p-hack disappears.

**The real risk here is not null results. It is confounding.** UK energy policy
announcements cluster with Budgets, Spending Reviews, and general political
events that move housebuilders for entirely unrelated reasons (interest rates,
planning reform, stamp duty). An announcement made *inside a Budget* is
essentially uninterpretable for a firm-level event study. This must be handled
in Phase B1, not discovered in Phase B3.

---

### Phase B0 — Event dictionary and identification audit (1–2 weeks)

Do this before writing any estimator. It determines whether the project is
viable.

**Do:**
- Build `docs/events.yaml` from GOV.UK, Hansard, Ofgem, DESNZ. Each entry:
  date, time (London) where knowable, source URL, scheduled vs unscheduled,
  directional expectation (positive/negative for which sector), and a
  **confounding note**: what else happened that day.
- Classify every event: (a) clean and unscheduled; (b) clean but anticipated;
  (c) confounded (Budget day, MPC day, major macro release, general election
  period); (d) leaked/pre-trailed.
- Reconstruct FTSE 350 membership as of each event date for the donor pool.
- Count how many events fall in class (a).

**Kill criterion B0.**
> **Kill if fewer than ~8–10 events survive as class (a) or (b) — clean, dated,
> directionally unambiguous, not confounded by a same-day macro or fiscal
> event.**
>
> Synthetic control on a handful of events with contaminated dates produces
> confident-looking nonsense. If the clean event count is too low, **the
> fallback is a single-event deep dive** — most likely the September 2023
> policy rollback, which was unscheduled, sharply directional, and had clearly
> exposed names. A rigorous SC/SDiD analysis of one well-chosen event with
> exhaustive placebo and robustness work is a *better* portfolio piece than a
> thin panel of ten muddy ones. Take that fallback without regret.

**Deliverable:** `docs/events.yaml` + `reports/00_event_audit.md` with the
classification table.

---

### Phase B1 — Baseline market-model event study (1 week)

Baseline first, per `CLAUDE.md` §4.

**Do:**
- OLS market model on a stated pre-event estimation window; CAR/CAAR over
  several event windows (−1,+1), (0,+1), (0,+5), (0,+20).
- Standard inference plus a bootstrap, and cross-sectional dependence
  correction — **events shared across firms mean returns are correlated in
  event time**, and naive t-tests over-reject badly. This is the single most
  common error in published event studies.
- Full results table, before touching SC or SDiD.

**Kill criterion B1.**
> No kill — this phase always completes and is always reported. It is the
> comparator. **But:** if the market-model results are already clean, strong,
> and robust to the dependence correction, note that the bar for SC/SDiD to
> add value is correspondingly high, and adjust expectations for Phase B3.

**Deliverable:** `reports/01_market_model.md`.

---

### Phase B2 — Pre-trend and donor-pool diagnostics (1–2 weeks)

**Do:**
- For each treated firm and event, assess pre-treatment fit achievable from the
  donor pool: pre-period RMSPE, and whether a convex combination of donors can
  track the treated unit at all.
- Donor pool construction: same-market non-exposed firms, sector-matched
  international comparators (Kingspan, Rockwool for insulation; European
  housebuilders), with exposure screening so donors are genuinely untreated.
- Pre-trend tests: is there differential drift before the event?

**Kill criterion B2.**
> **Kill the SC strand if pre-treatment RMSPE is not materially better than
> the market model's pre-event residual standard deviation for the majority of
> treated units** — i.e. the donor pool cannot construct a credible
> counterfactual.
>
> SC's whole claim is a better counterfactual than a factor model. If the
> synthetic unit does not track the treated unit pre-event, the post-event
> "effect" is fit failure, not treatment. **This is a real and reportable
> finding**: "for UK housebuilders, the available donor pool cannot construct a
> synthetic control with acceptable pre-treatment fit, because the sector's
> exposure to UK rates and planning policy is not spanned by any untreated
> combination." That is a substantive statement about when SC is and is not
> applicable, and it directly answers the project's stated research question.
> Proceed to SDiD, which is more robust to imperfect pre-fit, and report the
> SC failure.

**Deliverable:** `reports/02_diagnostics.md` with pre-fit plots.

---

### Phase B3 — SC and SDiD estimation (2 weeks)

**Do:**
- Synthetic control per treated unit per event; SDiD on the panel.
- Inference: in-space placebos (permute treatment across donors), in-time
  placebos (fake event dates in the pre-period), leave-one-out donor
  sensitivity, and the placebo-based p-value from the RMSPE ratio distribution.
- Compare against the Phase B1 market-model results event by event. Where they
  disagree, diagnose *why* before deciding which to believe.

**Kill criterion B3.**
> **Kill further estimator development if the SC/SDiD estimates are not
> distinguishable from the placebo distribution for the large majority of
> events** — specifically if the treated unit's RMSPE ratio does not fall in
> the tail of the placebo distribution.
>
> **This is a legitimate terminal finding and the project reports it as the
> headline:** "UK energy-efficiency policy announcements do not produce
> detectable abnormal returns in exposed equities beyond what the market model
> already captures; the additional structure of SC/SDiD does not change the
> conclusion; effects reported in the naive market model at conventional
> significance do not survive placebo inference." Combined with the Phase B2
> diagnostics this is a genuinely useful methodological paper and demonstrates
> exactly the skepticism the target roles hire for. **Do not add estimators
> until something turns significant.**

**Deliverable:** `reports/03_causal_estimates.md`.

---

### Phase B4 — Heterogeneity and mechanism (1–2 weeks) — *only if B3 passes*

**Do:**
- Cross-sectional heterogeneity in effect size: is it explained by measurable
  exposure (revenue share from retrofit, UK revenue concentration, product mix)?
- EconML / causal forest for treatment-effect heterogeneity if the sample
  supports it — **it probably does not**, and saying so is better than
  producing an underpowered heterogeneity analysis.
- Persistence: does the effect decay, persist, or reverse?

**Kill criterion B4.**
> **Kill if effect heterogeneity is uncorrelated with any ex-ante exposure
> measure.** An "effect" that does not scale with exposure is not a policy
> effect — it is a common shock or a data artefact, and finding that it does
> not scale is an important robustness failure that should be reported rather
> than omitted.

**Deliverable:** `reports/04_heterogeneity.md`.

---

### Phase B5 — Write-up (1 week)

`reports/final_report.md`: the methodological comparison is the headline,
whatever the signs. Include the "what did not work" section and the decision
log.

---

## Cross-project checkpoints

Review at each of these and be willing to stop:

| Checkpoint | Question | Action if no |
|---|---|---|
| End A0 / B0 | Is the data actually there, point-in-time? | Stop or reframe. Do not proceed on a promise |
| End A1 / B2 | Does the method have anything to work with? | Write up the diagnostic finding and stop |
| End A3 / B3 | Is there a real effect after honest inference? | **Write up the null. This is the deliverable** |
| End A4 / B4 | Does it survive costs / exposure scaling? | Report break-even and stop |
| Any time | Is this threatening April 2027 submission? | Truncate at current phase and write up |

**Final reminder.** Both projects are designed so that the null result is
publishable and the write-up is the deliverable. If you find yourself
reluctant to fire a kill criterion, that reluctance is the signal that the
criterion is doing its job.
