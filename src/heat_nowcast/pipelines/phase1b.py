"""Phase 1b: the gas baseline against National Gas's published D-1 LDZ forecast.

What this pipeline answers
--------------------------
Phase 1 scored the *secondary* target and found the gap between a standard
weather regression and the operational forecast dominated by embedded
renewables and transmission metering -- neither of which exists on the gas
side. This pipeline runs the equivalent exercise on the **primary** target,
per ``docs/research_plan.md``: daily LDZ gas offtake, against National Gas's
own published D-1 LDZ demand forecast, at Local Distribution Zone level.

The LDZ panel is not incidental. At GB aggregate over a couple of years the
building stock is near-constant, so a bottom-up stock model collapses to a
rescaled degree-day term and the cross-sectional heterogeneity that EPC data
uniquely carries is integrated away. Thirteen zones observed daily is the
smallest panel in which that heterogeneity is identifiable at all.

Windows
-------
Gas history begins 2021-12-01 (probed; all five series empty at 2021-06 and
populated at 2021-12). The evaluation window is **pre-specified** as everything
from 2023-12-01, i.e. after 24 months of training -- two full years, enough to
identify the annual harmonics and the trend before any out-of-sample scoring.
Unlike Phase 1, where the window was forced by data availability, this is a
choice; it is stated here, made once, and not revisited.

Specifications
--------------
All pre-specified and recorded in ``reports/decision_log.md`` **before** the
evaluation window was scored:

1. ``gas_baseline_cwv`` -- per-LDZ OLS on forecast CWV + day-of-week + holiday
   + Christmas period + trend + 2 annual harmonics. **Headline.**
2. ``gas_baseline_no_harmonics`` -- as (1) with no harmonics. Sensitivity.
3. ``gas_seasonal_naive`` -- lag-7-day persistence per LDZ. Floor.
4. ``gas_baseline_national_hdd`` -- as (1) with Phase 1's GB population-weighted
   forecast HDD replacing the per-LDZ CWV. Reported because the Phase 1b brief
   requires HDD and CWV both to be shown; note it runs on the shorter window
   where point-in-time forecast HDD exists (from 2024-02-04).
5. ``gas_oracle_cwv_realised`` -- as (1) served the **actual** CWV.
   ``REALISED-WEATHER-DIAGNOSTIC``. Upper bound only, never a headline.

The competitor throughout is National Gas's published forecast, gated to the
last publication dated on D-1 (:class:`heat_nowcast.data.gas.ForecastGate`).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Final

import numpy as np
import pandas as pd

from heat_nowcast.data.calendar_uk import (
    christmas_period_flag,
    holiday_flags,
    load_uk_bank_holidays,
    uk_season,
)
from heat_nowcast.data.gas import (
    GAS_HISTORY_START,
    LDZ_CODES,
    MSCM_PER_DAY_TO_MW,
    ForecastGate,
    load_ldz_cwv,
    load_ldz_demand_actual,
    load_ldz_demand_forecast,
)
from heat_nowcast.evaluation.metrics import error_metrics, score_by_group
from heat_nowcast.evaluation.splits import ExpandingWindowSplitter
from heat_nowcast.models.gas_baseline import (
    seasonal_naive_gas,
    walk_forward_predict_gas,
)

#: Pre-specified: evaluation starts after 24 months of training history.
EVALUATION_START: Final[dt.date] = dt.date(2023, 12, 1)

REFIT_CADENCE: Final[pd.DateOffset] = pd.DateOffset(months=1)

#: Inherited from Phase 1 for comparability. Only ~2 days would be strictly
#: needed here -- the outturn publishes at D+1 and the CWV forecast at D-1,
#: with no ERA5 dependency to clear -- so this is conservative, not binding.
EMBARGO: Final[pd.Timedelta] = pd.Timedelta(days=7)

#: Gas day runs 05:00-05:00 UTC (`CLAUDE.md` §2.3).
GAS_DAY_START_HOUR: Final[int] = 5

#: The Scotland LDZ keeps Scottish bank holidays; the rest keep England & Wales.
#: 2 January and the differing late-summer holiday are real demand events.
SCOTLAND_LDZ: Final[str] = "SC"

FORECAST_COLUMNS: Final[dict[str, str]] = {
    "National Gas D-1": "ng_forecast_mscm",
    "CWV+calendar baseline": "gas_baseline_cwv",
    "CWV+calendar, no harmonics": "gas_baseline_no_harmonics",
    "Seasonal naive (lag 7d)": "gas_seasonal_naive",
}

ORACLE_COLUMN: Final[str] = "gas_oracle_cwv_realised"
NATIONAL_HDD_COLUMN: Final[str] = "gas_baseline_national_hdd"


@dataclass
class Phase1bResult:
    """Everything the Phase 1b report needs, plus the audit trail."""

    panel: pd.DataFrame
    folds: pd.DataFrame
    overall: pd.DataFrame
    by_ldz: pd.DataFrame
    by_season: pd.DataFrame
    by_day_type: pd.DataFrame
    by_season_and_day_type: pd.DataFrame
    diagnostics: dict[str, object]


def _gas_day_start_utc(gas_day: pd.Series) -> pd.Series:
    """Return the UTC instant each gas day begins (05:00 UTC on D).

    Used as the panel's time index so that the walk-forward splitter cuts on
    the moment the gas day actually opens, not on a naive midnight that belongs
    to the electricity convention.
    """
    days = pd.DatetimeIndex(pd.Series(gas_day).to_numpy()).normalize()
    return pd.Series(days.tz_localize("UTC") + pd.Timedelta(hours=GAS_DAY_START_HOUR))


def build_gas_panel(
    *,
    start: dt.date = GAS_HISTORY_START,
    end: dt.date | None = None,
    gate: ForecastGate = ForecastGate.LAST_ON_D_MINUS_1,
    vintage: str = "2026-08-14",
) -> pd.DataFrame:
    """Assemble the LDZ x gas-day panel.

    Joins the outturn (D+1 first publication), the reconciled outturn (D+6),
    National Gas's gated D-1 forecast, the forecast CWV (legal) and the actual
    CWV (diagnostic), plus calendar features.
    """
    actual = load_ldz_demand_actual(
        start=start, end=end, vintage_run="d_plus_1", vintage=vintage
    ).rename(
        columns={
            "demand_mscm": "demand_mscm_d1",
            "published_at": "outturn_published_at",
        }
    )
    reconciled = load_ldz_demand_actual(
        start=start, end=end, vintage_run="d_plus_6", vintage=vintage
    ).rename(columns={"demand_mscm": "demand_mscm_d6"})[
        ["gas_day", "ldz", "demand_mscm_d6"]
    ]
    forecast = load_ldz_demand_forecast(
        start=start, end=end, gate=gate, vintage=vintage
    )
    cwv_forecast = load_ldz_cwv(
        kind="forecast_d_minus_1", start=start, end=end, gate=gate, vintage=vintage
    )
    # REALISED-WEATHER-DIAGNOSTIC: outturn CWV, published D+1. Column keeps its
    # `_realised` suffix all the way through (`CLAUDE.md` §2.1).
    cwv_actual = load_ldz_cwv(kind="actual", start=start, end=end, vintage=vintage)

    panel = (
        actual.merge(reconciled, on=["gas_day", "ldz"], how="left")
        .merge(forecast, on=["gas_day", "ldz"], how="left")
        .merge(cwv_forecast, on=["gas_day", "ldz"], how="left")
        .merge(cwv_actual, on=["gas_day", "ldz"], how="left")
    )

    holidays = load_uk_bank_holidays(vintage=vintage)
    flags = holiday_flags(panel["gas_day"], holidays)
    is_scotland = (panel["ldz"] == SCOTLAND_LDZ).to_numpy()
    panel["is_holiday_any"] = np.where(
        is_scotland,
        flags["is_holiday_scotland"].to_numpy(),
        flags["is_holiday_ew"].to_numpy(),
    )
    panel["is_christmas_period"] = christmas_period_flag(panel["gas_day"]).to_numpy()
    panel["season"] = uk_season(panel["gas_day"]).to_numpy()

    day_of_week = pd.DatetimeIndex(panel["gas_day"]).dayofweek.to_numpy()
    panel["day_type"] = np.where(
        panel["is_holiday_any"].to_numpy(),
        "holiday",
        np.where(
            day_of_week == 5,
            "saturday",
            np.where(day_of_week == 6, "sunday", "weekday"),
        ),
    )
    panel["gas_day_utc"] = _gas_day_start_utc(panel["gas_day"]).to_numpy()
    return panel.sort_values(["gas_day", "ldz"]).reset_index(drop=True)


def attach_national_hdd(
    panel: pd.DataFrame, *, vintage: str = "2026-08-14"
) -> pd.DataFrame:
    """Attach Phase 1's GB population-weighted forecast HDD to every LDZ row.

    The Phase 1b brief requires HDD to be reported alongside CWV rather than
    silently replaced by it. This is the honest version of that comparison
    available today: a **national** HDD, identical across zones, because
    per-LDZ HDD needs LDZ boundary polygons that are not in
    ``docs/data_inventory.md``.

    Its limitation is exactly the point of the comparison. A national HDD
    cannot distinguish a cold day in Scotland from a cold day in the South
    West, whereas the CWV is published per zone. If the CWV baseline beats the
    national-HDD baseline, that difference *is* the value of spatial weather
    resolution, measured rather than asserted.

    Also note the shorter window: point-in-time forecast HDD only exists from
    2024-02-04 (`reports/phase1_findings.md`), so rows before then get NaN and
    drop out of any comparison that includes this column.
    """
    from heat_nowcast.pipelines.phase1 import build_hdd_series, build_weather_grid

    weights = build_weather_grid(vintage=vintage)
    hdd = build_hdd_series(
        weights,
        start=dt.date(2021, 4, 1),
        end=dt.date.fromisoformat(str(panel["gas_day"].max().date())),
        vintage=vintage,
    )[["settlement_date", "hdd_forecast"]].rename(
        columns={"settlement_date": "gas_day", "hdd_forecast": "national_hdd_forecast"}
    )
    return panel.merge(hdd, on="gas_day", how="left")


def run_phase1b(
    *,
    start: dt.date = GAS_HISTORY_START,
    end: dt.date | None = None,
    evaluation_start: dt.date = EVALUATION_START,
    gate: ForecastGate = ForecastGate.LAST_ON_D_MINUS_1,
    vintage: str = "2026-08-14",
    include_national_hdd: bool = True,
) -> Phase1bResult:
    """Run the Phase 1b baseline comparison and return every table the report needs."""
    panel = build_gas_panel(start=start, end=end, gate=gate, vintage=vintage)
    if include_national_hdd:
        panel = attach_national_hdd(panel, vintage=vintage)

    splitter = ExpandingWindowSplitter(
        initial_train_end=pd.Timestamp(evaluation_start, tz="UTC") - EMBARGO,
        test_span=REFIT_CADENCE,
        embargo=EMBARGO,
    )

    panel["gas_baseline_cwv"], folds = walk_forward_predict_gas(
        panel,
        splitter,
        target_column="demand_mscm_d1",
        fit_weather_column="cwv_forecast",
        predict_weather_column="cwv_forecast",
        annual_harmonics=2,
    )
    panel["gas_baseline_no_harmonics"], _ = walk_forward_predict_gas(
        panel,
        splitter,
        target_column="demand_mscm_d1",
        fit_weather_column="cwv_forecast",
        predict_weather_column="cwv_forecast",
        annual_harmonics=0,
    )
    # REALISED-WEATHER-DIAGNOSTIC: served the outturn CWV instead of the D-1
    # forecast. Upper bound only; never reported as a headline.
    panel[ORACLE_COLUMN], _ = walk_forward_predict_gas(
        panel,
        splitter,
        target_column="demand_mscm_d1",
        fit_weather_column="cwv_forecast",
        predict_weather_column="cwv_actual_realised",
        annual_harmonics=2,
    )
    panel["gas_seasonal_naive"] = seasonal_naive_gas(
        panel, target_column="demand_mscm_d1"
    )
    if include_national_hdd:
        panel[NATIONAL_HDD_COLUMN], _ = walk_forward_predict_gas(
            panel,
            splitter,
            target_column="demand_mscm_d1",
            fit_weather_column="national_hdd_forecast",
            predict_weather_column="national_hdd_forecast",
            annual_harmonics=2,
        )

    scored = panel[
        (panel["gas_day"] >= pd.Timestamp(evaluation_start))
        & panel["demand_mscm_d1"].notna()
        & panel["ng_forecast_mscm"].notna()
        & panel["gas_baseline_cwv"].notna()
    ].reset_index(drop=True)

    all_columns = {**FORECAST_COLUMNS, "Oracle (REALISED CWV)": ORACLE_COLUMN}

    overall = score_by_group(
        scored, actual_column="demand_mscm_d1", forecast_columns=all_columns
    )
    by_ldz = score_by_group(
        scored,
        actual_column="demand_mscm_d1",
        forecast_columns=all_columns,
        group_columns=["ldz"],
    )
    by_season = score_by_group(
        scored,
        actual_column="demand_mscm_d1",
        forecast_columns=all_columns,
        group_columns=["season"],
    )
    by_day_type = score_by_group(
        scored,
        actual_column="demand_mscm_d1",
        forecast_columns=all_columns,
        group_columns=["day_type"],
    )
    by_both = score_by_group(
        scored,
        actual_column="demand_mscm_d1",
        forecast_columns=all_columns,
        group_columns=["season", "day_type"],
    )

    diagnostics = _build_diagnostics(
        panel, scored, all_columns, evaluation_start, include_national_hdd
    )

    return Phase1bResult(
        panel=panel,
        folds=folds,
        overall=overall,
        by_ldz=by_ldz,
        by_season=by_season,
        by_day_type=by_day_type,
        by_season_and_day_type=by_both,
        diagnostics=diagnostics,
    )


def _build_diagnostics(
    panel: pd.DataFrame,
    scored: pd.DataFrame,
    all_columns: dict[str, str],
    evaluation_start: dt.date,
    include_national_hdd: bool,
) -> dict[str, object]:
    """Assemble the Phase 1b analogue of the Phase 1 error decomposition."""
    complete = scored.dropna(subset=list(all_columns.values()))
    ng_error = complete["ng_forecast_mscm"] - complete["demand_mscm_d1"]
    base_error = complete["gas_baseline_cwv"] - complete["demand_mscm_d1"]
    oracle_error = complete[ORACLE_COLUMN] - complete["demand_mscm_d1"]

    base_mae = float(base_error.abs().mean())
    ng_mae = float(ng_error.abs().mean())
    oracle_mae = float(oracle_error.abs().mean())
    gap = base_mae - ng_mae

    diagnostics: dict[str, object] = {
        "evaluation_start": str(evaluation_start),
        "evaluation_end": str(scored["gas_day"].max().date()),
        "history_start": str(panel["gas_day"].min().date()),
        "n_scored_rows": len(complete),
        "n_gas_days": int(complete["gas_day"].nunique()),
        "n_ldz": int(complete["ldz"].nunique()),
        "mean_offtake_mscm": float(complete["demand_mscm_d1"].mean()),
        "mean_offtake_mw_equiv": float(
            complete["demand_mscm_d1"].mean() * MSCM_PER_DAY_TO_MW
        ),
        "mscm_per_day_to_mw": MSCM_PER_DAY_TO_MW,
        "gap_baseline_minus_ng_mae_mscm": gap,
        "weather_forecast_error_cost_mscm": base_mae - oracle_mae,
        "weather_forecast_error_share_of_gap": (
            (base_mae - oracle_mae) / gap if gap else float("nan")
        ),
        "constant_bias_cost_mscm": base_mae
        - float((base_error - base_error.mean()).abs().mean()),
        "error_correlation_baseline_ng": float(np.corrcoef(base_error, ng_error)[0, 1]),
        "cwv_forecast_vs_actual_corr": float(
            complete["cwv_forecast"].corr(complete["cwv_actual_realised"])
        ),
        "cwv_forecast_vs_actual_mae": float(
            (complete["cwv_forecast"] - complete["cwv_actual_realised"]).abs().mean()
        ),
    }

    # --- the Phase A3 question, asked directly of the incumbent's residual ---
    per_day = complete.groupby("gas_day", as_index=False).agg(
        ng_error=("ng_forecast_mscm", "size")
    )
    del per_day
    daily = (
        complete.assign(ng_error=ng_error.to_numpy(), cwv=complete["cwv_forecast"])
        .groupby("gas_day", as_index=False)
        .agg(ng_error=("ng_error", "mean"), cwv=("cwv", "mean"))
        .dropna()
    )
    diagnostics["ng_error_vs_cwv_corr_daily"] = float(
        np.corrcoef(daily["cwv"], daily["ng_error"])[0, 1]
    )
    cold = daily.loc[daily["cwv"] <= daily["cwv"].quantile(0.10)]
    diagnostics["ng_coldest_decile"] = {
        "n_days": len(cold),
        "mae_mscm": float(cold["ng_error"].abs().mean()),
        "mean_error_mscm": float(cold["ng_error"].mean()),
        "all_days_mae_mscm": float(daily["ng_error"].abs().mean()),
    }

    # --- vintage: D+1 first publication vs D+6 reconciled (`CLAUDE.md` §2.2) ---
    vintage_pair = panel.dropna(subset=["demand_mscm_d1", "demand_mscm_d6"])
    if len(vintage_pair) > 0:
        revision = vintage_pair["demand_mscm_d6"] - vintage_pair["demand_mscm_d1"]
        diagnostics["restatement_d1_to_d6"] = {
            "n": len(vintage_pair),
            "mean_revision_mscm": float(revision.mean()),
            "mean_abs_revision_mscm": float(revision.abs().mean()),
            "revision_as_pct_of_mean_offtake": float(
                revision.abs().mean() / vintage_pair["demand_mscm_d1"].mean() * 100.0
            ),
            "share_exactly_equal": float((revision.abs() < 1e-9).mean()),
        }

    if include_national_hdd:
        hdd_rows = scored.dropna(
            subset=[NATIONAL_HDD_COLUMN, "gas_baseline_cwv", "ng_forecast_mscm"]
        )
        if len(hdd_rows) > 0:
            diagnostics["national_hdd_comparison"] = {
                "n": len(hdd_rows),
                "window_start": str(hdd_rows["gas_day"].min().date()),
                "cwv_mae": float(
                    (hdd_rows["gas_baseline_cwv"] - hdd_rows["demand_mscm_d1"])
                    .abs()
                    .mean()
                ),
                "national_hdd_mae": float(
                    (hdd_rows[NATIONAL_HDD_COLUMN] - hdd_rows["demand_mscm_d1"])
                    .abs()
                    .mean()
                ),
                "ng_mae": float(
                    (hdd_rows["ng_forecast_mscm"] - hdd_rows["demand_mscm_d1"])
                    .abs()
                    .mean()
                ),
            }

    # --- per-LDZ share of the panel, so the reader can weight the by-LDZ table ---
    diagnostics["ldz_mean_offtake_mscm"] = {
        str(ldz): float(complete.loc[complete["ldz"] == ldz, "demand_mscm_d1"].mean())
        for ldz in LDZ_CODES
        if (complete["ldz"] == ldz).any()
    }
    diagnostics["ng_overall"] = error_metrics(
        complete["demand_mscm_d1"], complete["ng_forecast_mscm"]
    )
    return diagnostics
