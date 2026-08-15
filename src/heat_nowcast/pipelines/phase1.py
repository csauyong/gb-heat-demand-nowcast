"""Phase 1: assemble the panel, run the baseline, score it against NESO.

What this pipeline does and does not claim
------------------------------------------
It answers one question: **how far is a standard HDD-plus-calendar regression
from NESO's published day-ahead national demand forecast?** That gap is the
headroom any bottom-up stock model has to work with. If it is small, the
published forecast already impounds most of what a temperature-driven model
can know, and Phase A3's kill criterion is in play before the stock model is
ever built.

It does **not** model domestic heat demand. NESO's National Demand is
transmission-metered and is not a heat series (``docs/data_inventory.md``
§2.1). Phase 1 is deliberately a comparison of *forecasts of the same
published quantity*, which is the only comparison that can be made on
identical rows against an identical truth.

Windows
-------
``EVALUATION_START`` is set by data availability, not by choice, which is the
cleanest justification a test period can have. Point-in-time forecast weather
at a fixed day-ahead lead begins 2024-02-04 (see
:mod:`heat_nowcast.data.weather`), so that is where out-of-sample scoring can
begin. Training history runs from 2021-04-01, where NESO's forecast
performance file starts.

Specifications
--------------
Three, all pre-specified before the evaluation window was scored, and all
recorded in ``reports/decision_log.md``:

1. ``baseline_hdd_calendar`` -- HDD + day-of-week + holiday + Christmas
   period + trend + 2 annual harmonics. The headline.
2. ``baseline_no_harmonics`` -- specification 1 without the harmonics, i.e.
   exactly the four terms in the Phase 1 brief. Sensitivity.
3. ``seasonal_naive`` -- last week, same settlement period. The floor.

Plus one diagnostic run, never a headline:

4. ``baseline_oracle_realised`` -- specification 1 served **realised** ERA5
   HDD instead of forecast HDD. REALISED-WEATHER-DIAGNOSTIC. It exists to
   split the baseline's error into model error and weather-forecast error.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Final

import numpy as np
import pandas as pd

from heat_nowcast.data.calendar_uk import (
    christmas_period_flag,
    day_type,
    holiday_flags,
    load_uk_bank_holidays,
    uk_season,
)
from heat_nowcast.data.neso import (
    load_neso_day_ahead_forecast_performance,
    load_neso_historic_demand,
)
from heat_nowcast.data.ons_geography import load_gb_population_points
from heat_nowcast.data.weather import (
    PREVIOUS_RUNS_ARCHIVE_START,
    load_forecast_temperature,
    load_realised_temperature,
)
from heat_nowcast.evaluation.metrics import diebold_mariano, score_by_group
from heat_nowcast.evaluation.splits import ExpandingWindowSplitter
from heat_nowcast.features.weather import (
    UK_HDD_BASE_C,
    build_population_weights,
    heating_degree_days,
    population_weighted_temperature,
)
from heat_nowcast.models.baseline import seasonal_naive_forecast, walk_forward_predict

#: Training history starts where NESO's forecast performance file starts.
TRAINING_START: Final[dt.date] = dt.date(2021, 4, 1)

#: Out-of-sample scoring starts where point-in-time forecast weather starts.
#: Chosen once, by data availability, and not revisited (`CLAUDE.md` §3).
EVALUATION_START: Final[dt.date] = PREVIOUS_RUNS_ARCHIVE_START

#: Refit cadence and test-window width.
REFIT_CADENCE: Final[pd.DateOffset] = pd.DateOffset(months=1)

#: Covers NESO's ~1-day outturn lag and ERA5's ~5-day preliminary lag.
EMBARGO: Final[pd.Timedelta] = pd.Timedelta(days=7)

FORECAST_COLUMNS: Final[dict[str, str]] = {
    "NESO day-ahead": "neso_da_forecast_mw",
    "HDD+calendar baseline": "baseline_hdd_calendar",
    "HDD+calendar, no harmonics": "baseline_no_harmonics",
    "Seasonal naive (lag 7d)": "seasonal_naive",
}

#: Kept apart from FORECAST_COLUMNS so an oracle number cannot reach a
#: headline table by accident (`CLAUDE.md` §2.1).
ORACLE_COLUMN: Final[str] = "baseline_oracle_realised"


@dataclass
class Phase1Result:
    """Everything a report needs, and the audit trail behind it."""

    panel: pd.DataFrame
    weights: pd.DataFrame
    folds: pd.DataFrame
    overall: pd.DataFrame
    by_season: pd.DataFrame
    by_day_type: pd.DataFrame
    by_season_and_day_type: pd.DataFrame
    diagnostics: dict[str, object]


def build_weather_grid(
    *,
    vintage: str = "2026-08-14",
    grid_lat_deg: float = 0.75,
    grid_lon_deg: float = 1.5,
    population_coverage: float = 0.995,
) -> pd.DataFrame:
    """Build the population-weighted weather grid from LSOA-level points."""
    points = load_gb_population_points(vintage=vintage)
    return build_population_weights(
        points,
        grid_lat_deg=grid_lat_deg,
        grid_lon_deg=grid_lon_deg,
        population_coverage=population_coverage,
    )


def build_hdd_series(
    weights: pd.DataFrame,
    *,
    start: dt.date,
    end: dt.date,
    base_c: float = UK_HDD_BASE_C,
    lead_days: int = 1,
    vintage: str = "2026-08-14",
) -> pd.DataFrame:
    """Build daily forecast and realised HDD for GB.

    Returns one row per settlement date with ``hdd_forecast`` (point-in-time
    legal) and ``hdd_realised`` (REALISED-WEATHER-DIAGNOSTIC). The two are
    kept in one frame *and named distinctly* so downstream code has to choose
    explicitly which one it consumes.
    """
    forecast_start = max(start, PREVIOUS_RUNS_ARCHIVE_START)
    forecast_long = load_forecast_temperature(
        weights, forecast_start, end, lead_days=lead_days, vintage=vintage
    )
    forecast_national = population_weighted_temperature(
        forecast_long, weights, value_column="temp_c_forecast"
    )
    forecast_hdd = heating_degree_days(
        forecast_national, value_column="temp_c_forecast", base_c=base_c
    ).rename(
        columns={
            "hdd": "hdd_forecast",
            "mean_temp_c": "mean_temp_c_forecast",
            "n_hours": "n_hours_forecast",
        }
    )

    # REALISED-WEATHER-DIAGNOSTIC: ERA5 reanalysis, not knowable at prediction
    # time. Used here to (a) train the baseline, which is legal because the
    # walk-forward embargo exceeds ERA5's ~5-day publication lag, and (b) drive
    # the oracle run, which is reported only as an upper bound.
    realised_long = load_realised_temperature(weights, start, end, vintage=vintage)
    realised_national = population_weighted_temperature(
        realised_long, weights, value_column="temp_c_realised"
    )
    realised_hdd = heating_degree_days(
        realised_national, value_column="temp_c_realised", base_c=base_c
    ).rename(
        columns={
            "hdd": "hdd_realised",
            "mean_temp_c": "mean_temp_c_realised",
            "n_hours": "n_hours_realised",
        }
    )

    return realised_hdd.merge(forecast_hdd, on="settlement_date", how="left")


def build_panel(
    hdd: pd.DataFrame,
    *,
    vintage: str = "2026-08-14",
) -> pd.DataFrame:
    """Join NESO demand, the published forecast, HDD and calendar features."""
    performance = load_neso_day_ahead_forecast_performance(vintage=vintage)
    historic = load_neso_historic_demand(vintage=vintage)
    holidays = load_uk_bank_holidays(vintage=vintage)

    panel = performance.merge(
        historic[["settlement_datetime", "nd_mw", "tsd_mw"]],
        on="settlement_datetime",
        how="left",
    ).merge(hdd, on="settlement_date", how="left")

    flags = holiday_flags(panel["settlement_date"], holidays)
    panel["is_holiday_any"] = flags["is_holiday_any"].to_numpy()
    panel["is_christmas_period"] = christmas_period_flag(
        panel["settlement_date"]
    ).to_numpy()
    panel["season"] = uk_season(panel["settlement_date"]).to_numpy()
    panel["day_type"] = day_type(panel["settlement_date"], holidays).to_numpy()

    return panel.sort_values("settlement_datetime").reset_index(drop=True)


def run_phase1(
    *,
    base_c: float = UK_HDD_BASE_C,
    lead_days: int = 1,
    vintage: str = "2026-08-14",
    end: dt.date | None = None,
    grid_lat_deg: float = 0.75,
    grid_lon_deg: float = 1.5,
) -> Phase1Result:
    """Run the whole Phase 1 comparison and return every table the report needs.

    Parameters
    ----------
    base_c :
        HDD base temperature. Defaults to the UK convention.
    lead_days :
        Forecast lead for the point-in-time weather. 1 matches NESO's
        day-ahead horizon; 2 is the strictly-safe sensitivity.
    vintage :
        Vintage label passed to every loader.
    end :
        Last settlement date to consider. Defaults to two days before today,
        which clears NESO's outturn publication lag.
    grid_lat_deg, grid_lon_deg :
        Weather grid resolution.

    Returns
    -------
    Phase1Result
        Panel, weights, fold summary, and the scored tables.
    """
    # UTC, not local: `date.today()` reads the machine's timezone, which
    # would make the evaluation window depend on where the run happened.
    end = end or (dt.datetime.now(tz=dt.UTC).date() - dt.timedelta(days=2))

    weights = build_weather_grid(
        vintage=vintage,
        grid_lat_deg=grid_lat_deg,
        grid_lon_deg=grid_lon_deg,
    )
    hdd = build_hdd_series(
        weights,
        start=TRAINING_START,
        end=end,
        base_c=base_c,
        lead_days=lead_days,
        vintage=vintage,
    )
    panel = build_panel(hdd, vintage=vintage)
    panel = panel[panel["settlement_date"] <= pd.Timestamp(end)].reset_index(drop=True)

    splitter = ExpandingWindowSplitter(
        initial_train_end=pd.Timestamp(EVALUATION_START, tz="UTC") - EMBARGO,
        test_span=REFIT_CADENCE,
        embargo=EMBARGO,
    )

    panel["baseline_hdd_calendar"], folds = walk_forward_predict(
        panel,
        splitter,
        target_column="demand_outturn_mw",
        fit_hdd_column="hdd_realised",
        predict_hdd_column="hdd_forecast",
        annual_harmonics=2,
    )
    panel["baseline_no_harmonics"], _ = walk_forward_predict(
        panel,
        splitter,
        target_column="demand_outturn_mw",
        fit_hdd_column="hdd_realised",
        predict_hdd_column="hdd_forecast",
        annual_harmonics=0,
    )
    # REALISED-WEATHER-DIAGNOSTIC: served realised ERA5 HDD instead of the
    # archived forecast. Upper bound only; never reported as a headline.
    panel[ORACLE_COLUMN], _ = walk_forward_predict(
        panel,
        splitter,
        target_column="demand_outturn_mw",
        fit_hdd_column="hdd_realised",
        predict_hdd_column="hdd_realised",
        annual_harmonics=2,
    )
    panel["seasonal_naive"] = seasonal_naive_forecast(
        panel, target_column="demand_outturn_mw"
    )

    scored = panel[
        (panel["settlement_datetime"] >= pd.Timestamp(EVALUATION_START, tz="UTC"))
        & panel["demand_outturn_mw"].notna()
        & panel["neso_da_forecast_mw"].notna()
        & panel["baseline_hdd_calendar"].notna()
    ].reset_index(drop=True)

    all_columns = {**FORECAST_COLUMNS, "Oracle (REALISED weather)": ORACLE_COLUMN}

    overall = score_by_group(
        scored, actual_column="demand_outturn_mw", forecast_columns=all_columns
    )
    by_season = score_by_group(
        scored,
        actual_column="demand_outturn_mw",
        forecast_columns=all_columns,
        group_columns=["season"],
    )
    by_day_type = score_by_group(
        scored,
        actual_column="demand_outturn_mw",
        forecast_columns=all_columns,
        group_columns=["day_type"],
    )
    by_both = score_by_group(
        scored,
        actual_column="demand_outturn_mw",
        forecast_columns=all_columns,
        group_columns=["season", "day_type"],
    )

    complete = scored.dropna(subset=list(all_columns.values()))
    neso_error = complete["neso_da_forecast_mw"] - complete["demand_outturn_mw"]
    baseline_error = complete["baseline_hdd_calendar"] - complete["demand_outturn_mw"]
    oracle_error = complete[ORACLE_COLUMN] - complete["demand_outturn_mw"]

    diagnostics: dict[str, object] = {
        "evaluation_start": str(EVALUATION_START),
        "evaluation_end": str(end),
        "training_start": str(TRAINING_START),
        "base_c": base_c,
        "lead_days": lead_days,
        "grid_cells": len(weights),
        "grid_lat_deg": grid_lat_deg,
        "grid_lon_deg": grid_lon_deg,
        "n_scored_rows": len(complete),
        "n_scored_days": int(complete["settlement_date"].nunique()),
        "dm_baseline_vs_neso": diebold_mariano(baseline_error, neso_error),
        "dm_oracle_vs_neso": diebold_mariano(oracle_error, neso_error),
        "error_correlation_baseline_neso": float(
            np.corrcoef(baseline_error, neso_error)[0, 1]
        ),
        "neso_long_window": _neso_long_window_metrics(panel),
        "nd_vs_outturn_reconciliation": _reconcile_outturn(panel),
    }

    return Phase1Result(
        panel=panel,
        weights=weights,
        folds=folds,
        overall=overall,
        by_season=by_season,
        by_day_type=by_day_type,
        by_season_and_day_type=by_both,
        diagnostics=diagnostics,
    )


def _neso_long_window_metrics(panel: pd.DataFrame) -> dict[str, object]:
    """NESO's own error over its full published history, for context.

    The baseline cannot be scored here -- point-in-time forecast weather does
    not exist before 2024-02-04 -- so this is context, not a comparison.
    """
    from heat_nowcast.evaluation.metrics import error_metrics

    complete = panel.dropna(subset=["neso_da_forecast_mw", "demand_outturn_mw"])
    metrics: dict[str, object] = dict(
        error_metrics(complete["demand_outturn_mw"], complete["neso_da_forecast_mw"])
    )
    return {
        **metrics,
        "first_date": str(complete["settlement_date"].min().date()),
        "last_date": str(complete["settlement_date"].max().date()),
    }


def _reconcile_outturn(panel: pd.DataFrame) -> dict[str, float]:
    """Compare NESO's scoring outturn against its historic-demand ND series.

    These are two separately published views of the same quantity. Quantifying
    the gap is the honest way to state what "outturn" means here, rather than
    assuming the two files agree.
    """
    complete = panel.dropna(subset=["demand_outturn_mw", "nd_mw"])
    if len(complete) == 0:
        return {"n": 0.0}
    difference = complete["demand_outturn_mw"] - complete["nd_mw"]
    return {
        "n": float(len(complete)),
        "mean_difference_mw": float(difference.mean()),
        "mean_abs_difference_mw": float(difference.abs().mean()),
        "share_within_1_mw": float((difference.abs() <= 1.0).mean()),
        "max_abs_difference_mw": float(difference.abs().max()),
    }
