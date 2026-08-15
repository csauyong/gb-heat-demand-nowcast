# CLAUDE.md — quant research portfolio

Governs both projects in this folder. Read this before touching either repo.
Where a project-level convention conflicts with this file, **this file wins**.

Owner: Chun Sang Au Yong. Context: final-year PhD (causal ML on UK housing
energy data, submitting April 2027). These two projects are portfolio work
targeting quant research and applied science roles. They are judged on
methodological honesty, not on headline numbers.

`lsoa-graph/` in this folder is a separate, unrelated project. Ignore it.

---

## 1. The two projects

### Project A — `gb-heat-demand-nowcast/`

**Purpose.** Build GB domestic heating demand from the bottom up out of the
building stock, rather than from the top down out of aggregate demand history.
LSOA-level EPC dwelling characteristics (fabric, heating system, floor area)
are combined with weather to produce a physically-grounded demand estimate,
aggregated to GB, and compared with what the system operator actually
publishes.

**Research question, stated precisely.**

> Does a bottom-up, stock-based model of GB domestic heat demand contain
> information about realised GB electricity and gas demand that is **not
> already present in the published NESO day-ahead demand forecast**; and if so,
> is that incremental information large enough, and available early enough, to
> support a tradeable signal in GB power or gas after realistic costs?

Note the structure. There are three separate claims, and they are tested in
order, and each one can fail on its own:

1. **Fit.** The bottom-up model tracks realised domestic heat demand.
2. **Incremental information.** Its residual against the published forecast is
   predictable — i.e. the published forecast is missing something the stock
   model knows. This is the interesting scientific claim and it is where the
   project's contribution actually lives.
3. **Tradeability.** That incremental information survives point-in-time
   constraints, transaction costs, and execution assumptions.

Claim 2 failing is a legitimate and publishable outcome: it says the published
forecast already impounds building-stock heterogeneity, which is itself a
finding about the sophistication of operational forecasting. Claim 3 failing
while claim 2 holds is the *most likely* outcome and must be written up as
such, not buried.

### Project B — `uk-energy-policy-event-study/`

**Purpose.** Apply modern causal panel methods — synthetic control (SC) and
synthetic difference-in-differences (SDiD) — to UK energy-efficiency and
heating policy announcements, and measure the effect on exposed equities:
housebuilders, insulation and building-materials manufacturers, utilities,
and residential landlords / REITs.

**Research question, stated precisely.**

> Do UK energy-efficiency and heating-policy announcements produce measurable,
> persistent abnormal returns in exposed equities; and does a synthetic-control
> / SDiD design — which constructs a weighted counterfactual from a donor pool
> and can be falsified with placebo and pre-trend diagnostics — recover effects
> that the standard market-model event study either misses or spuriously
> reports?

The comparison against the standard market-model event study is not a footnote.
It is the point. The deliverable is a statement about **when the extra
machinery earns its keep and when it does not**, backed by diagnostics.

---

## 2. Point-in-time discipline — the hard rule

**No feature, at any stage, in either project, may use information that was not
publicly available at the moment being predicted.** This is not a
best-practice suggestion. It is the rule that makes the difference between
portfolio work a quant desk takes seriously and portfolio work it discards on
sight. A single leaked feature invalidates every number downstream of it.

Concretely, this means:

### 2.1 Forecast weather, not realised weather

**Any nowcast that is evaluated as a trading signal must be driven by forecast
weather — the forecast that existed at the decision time — not by realised or
reanalysis weather.**

Realised weather (ERA5, HadUK-Grid) is not knowable at prediction time. A heat
demand model fed realised temperature will look excellent and will be
worthless. Use an archive of *what the forecast said at the time*: Open-Meteo's
Historical Forecast API (archived model runs from 2021 onward) is the free
route; see `docs/data_inventory.md`.

Realised weather has exactly two sanctioned uses:

- **Diagnostic decomposition** — separating the model's own error from weather
  forecast error, so you can say how much of the residual is your fault.
- **Upper-bound / oracle runs** — establishing the ceiling a perfect weather
  forecast would allow.

**Wherever realised weather is used, the code, the figure caption, and the
report text must say so explicitly.** Use the literal marker
`REALISED-WEATHER-DIAGNOSTIC` in a comment at the call site and name the
variable or column with a `_realised` suffix. Any table mixing forecast-driven
and realised-driven results must label the rows. No oracle number is ever
reported as a headline result.

### 2.2 Data vintage and restatement

Published energy data is restated. NESO historic demand, Elexon settlement
runs (II → SF → R1 → R2 → R3 → RF), and gas flows all revise after first
publication. Backtests must use the vintage available at the time, or, where
a vintage archive does not exist, must state that restatement contamination is
present and bound its likely size. Never silently use a final settlement run
in a backtest of a decision made at gate closure.

### 2.3 Publication lag is a feature property

Every feature has a timestamp at which it became knowable. That timestamp —
not the timestamp it describes — determines which prediction it may enter.
EPC stock data has a quarterly release lag; day-ahead forecasts appear at a
known time of day; gas data has its own gas-day convention (05:00–05:00 UTC,
which is *not* the electricity day). Getting the gas day wrong is a leak.

### 2.4 Corporate actions and survivorship (Project B)

Equity prices must be split- and dividend-adjusted using adjustment factors
knowable at the time. Donor pools must not be constructed from firms that
exist today — that is survivorship bias and it will flatter every synthetic
control. Build the donor pool from index membership as of the event date.

### 2.5 Event timing (Project B)

Announcement **time**, not just date, matters. If an announcement lands at
15:00 London, the event window opens intraday, and a close-to-close return on
the announcement day mixes pre- and post-announcement information. Record the
time where it is knowable and say so where it is not. Flag announcements that
were trailed or leaked in the press beforehand — the effective event date is
the leak, not the podium.

---

## 3. Splits and evaluation

**Time-ordered splits only.**

- No random shuffling. Ever.
- No k-fold cross-validation on time series. No `KFold`, no `ShuffleSplit`, no
  `train_test_split(shuffle=True)`. If you see one in this repo, it is a bug.
- Use **walk-forward** or **expanding-window** evaluation. Rolling-origin
  refits, out-of-sample forward in time, every time.
- **Embargo and purge** around the split boundary where the target or the
  features have overlapping horizons, so information does not bleed across the
  cut.
- The test period is chosen once and is not revisited. Hyperparameters are
  selected on an inner validation fold that is itself time-ordered and strictly
  earlier than the test period.
- Report the number of effective independent observations, not the number of
  half-hourly rows. Half-hourly demand data is enormously autocorrelated;
  50,000 rows is not 50,000 observations, and standard errors that assume it is
  are wrong.

For Project B, the analogue is: pre-treatment fit is never allowed to peek at
post-treatment outcomes, donor weights are fit on pre-period data only, and
the pre-period used for fitting is disclosed.

---

## 4. Named baselines — every model, every time

**No model result is ever reported on its own.** Every headline number is
reported alongside a named, pre-specified naive baseline, with the comparison
made on identical data, identical splits, and identical evaluation windows.

**Project A baselines (both are mandatory):**

1. **HDD-plus-calendar regression on national demand.** Heating degree days
   from a population-weighted national temperature, plus calendar effects
   (day of week, holiday, time of day, seasonality). This is the standard
   utility-industry approach and it is a *strong* baseline. Beating it is the
   minimum bar for the bottom-up model to be worth anything.
2. **The published NESO day-ahead demand forecast.** This is the real
   competitor. It is produced by people with more data than you, including
   commercial weather feeds and embedded generation telemetry. If the
   bottom-up model does not add information on top of this, say so.

**Project B baseline:**

1. **Standard market-model abnormal returns.** OLS market model estimated on a
   pre-event window, CAR/CAAR over event windows, with the conventional
   significance tests. Every SC/SDiD result is reported next to it. Where they
   disagree, the report must explain *why* — donor composition, pre-trend
   violation, confounding events — rather than asserting the fancier method is
   correct because it is fancier.

Baselines are implemented first, before the main model, and live in version
control as first-class code with their own tests. A baseline hacked together
at the end to lose gracefully is dishonest.

---

## 5. Negative results are kept

**If a result is negative, it is written up. It is not deleted, not quietly
dropped from the report, and not iterated on until it becomes positive.**

Specifically: **if the bottom-up model does not beat the published NESO
forecast, that finding is the deliverable.** A clean, well-diagnosed
demonstration that a physically-motivated bottom-up stock model does not add
information over an operational forecast — with the decomposition showing
*where* the information is already impounded — is a stronger portfolio piece
than a marginal positive result reached by trying forty specifications.

Rules that follow from this:

- Keep a running `reports/decision_log.md` in each project: every
  specification tried, the date, what it did, and whether it was kept. This is
  the multiple-comparisons audit trail. Deflated Sharpe ratios and multiple-
  testing corrections are computed against the *actual* number of trials, which
  requires having counted them.
- A specification is not abandoned because it produced an unwelcome number.
  It is abandoned because a pre-stated kill criterion fired
  (see `docs/research_plan.md`) or because it is wrong.
- The final report contains a "what did not work" section. It is not optional.
- Do not rerun the test period with new features. Once the test period is
  touched, it is contaminated, and any further use must be disclosed as such.

---

## 6. Execution realism — mandatory in any P&L

**No P&L figure, Sharpe ratio, or return series may be produced without an
explicit, documented cost model.** A gross-of-cost backtest is not a result and
is not shown, not even "for reference", not even in an appendix.

Every P&L must state and apply:

- **Transaction costs** — commission and exchange fees for the specific venue
  and contract.
- **Bid-ask spread** — crossed on entry and exit, at realistic width for the
  contract and time of day. GB power and gas contracts away from the front are
  not liquid; a front-month spread assumption applied to a seasonal contract is
  a fiction.
- **Slippage and market impact** — sized against a stated position size and a
  stated fraction of typical volume. State the capacity of the strategy.
- **Execution timing** — the exact time the signal is knowable and the exact
  time the order fills, with a realistic delay between them. Signals derived
  from a day-ahead forecast published at a known time cannot be traded before
  that time.
- **Margin, financing, and contract mechanics** — for futures, initial and
  variation margin; for spread positions, the correct leg conventions.
- **Sensitivity** — the cost assumption is varied, and the P&L is reported
  across a range. If the result survives only at the optimistic end, say so
  plainly. The break-even cost level is reported as a headline statistic: "this
  signal is profitable up to X per unit of cost" is far more credible than a
  single Sharpe number.

Any Sharpe or IR is reported with an uncertainty interval and a deflation for
the number of specifications tried.

---

## 7. Code style and engineering conventions

**Language and stack.** Python 3.11+. `pandas` and `polars` (polars preferred
for the large EPC and half-hourly panels; pandas where the ecosystem requires
it). `scikit-learn` for ML, `statsmodels` for inference and standard errors,
`EconML` for causal estimation. Project B additionally uses SC/SDiD
implementations — wrap whatever is used behind a project interface rather than
scattering library calls through notebooks.

**Typed function signatures are required.** Every function has annotated
parameters and an annotated return type. `from __future__ import annotations`
at the top of every module. `mypy` runs in `make lint` and its complaints are
fixed, not ignored. `# type: ignore` requires a comment explaining why.

**Every data-loading function documents its source URL and vintage.** The
docstring of any function that reads external data must state:

- the source URL it came from;
- the licence;
- the vintage — dataset version, release date, or download date;
- the publication lag, and therefore the earliest timestamp at which the
  returned values were knowable.

Example of the required shape:

```python
def load_neso_day_ahead_forecast(
    start: pd.Timestamp,
    end: pd.Timestamp,
    *,
    vintage: str = "2026-08-14",
) -> pl.DataFrame:
    """Load NESO published day-ahead national demand forecast.

    Source: https://www.neso.energy/data-portal/1-day-ahead-demand-forecast
    Licence: NESO Open Data Licence (see docs/data_inventory.md)
    Vintage: downloaded {vintage}; NESO CKAN resource id <id>
    Publication lag: published ~10:00 London on D-1 for delivery day D.
        Values are therefore knowable from D-1 10:00 London onward and must
        not be used for any prediction timestamped before that.

    Returns a frame with a UTC `settlement_datetime` index.
    """
```

**Other conventions.**

- All timestamps are timezone-aware UTC internally. Convert to Europe/London
  only at the display boundary. BST transitions create 46- and 50-settlement-
  period days in GB electricity data; code must handle both.
- Gas day (05:00–05:00 UTC) and electricity day are different. Never mix them
  without an explicit conversion function.
- `src/` is an installed package (`pip install -e .` via `make setup`).
  Notebooks import from it. **Analysis logic does not live in notebooks** —
  notebooks are for exploration and for rendering results, and any function
  that survives exploration moves into `src/` with a test.
- Deterministic: every stochastic routine takes an explicit `seed`.
- Long-running data pulls are cached to `data/raw/` with the vintage in the
  filename. `data/` is gitignored; the loader that regenerates it is not.
- `ruff` for lint and format. Line length 88.
- Commit messages describe the research decision, not just the diff.

---

## 8. Working agreements for Claude in this repo

- Do not write analysis code unless asked. Scaffolding, planning, and review
  are separate activities from implementation.
- When asked to implement a model, implement its baseline first.
- If a requested feature would breach point-in-time discipline, say so and stop
  rather than implementing it with a caveat.
- Never propose a random or k-fold split on this data.
- Never produce a P&L number without a cost model.
- When a result looks good, the first response is to look for the leak.
