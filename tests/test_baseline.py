"""Baseline model tests, built on a synthetic panel with a known answer."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from heat_nowcast.evaluation.splits import ExpandingWindowSplitter
from heat_nowcast.models.baseline import (
    HddCalendarBaseline,
    seasonal_naive_forecast,
    walk_forward_predict,
)

TRUE_INTERCEPT = 25_000.0
TRUE_HDD_SLOPE = 900.0


def synthetic_panel(days: int = 900, seed: int = 20260814) -> pd.DataFrame:
    """A panel whose demand is an exact linear function of HDD and calendar.

    Forecast HDD is realised HDD plus noise, mimicking the real train/serve
    setup: the model is fitted on the clean regressor and served the noisy one.
    """
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2022-01-01", periods=days, freq="D")
    periods = np.arange(1, 49)

    frame = pd.DataFrame(
        {
            "settlement_date": np.repeat(dates, len(periods)),
            "settlement_period": np.tile(periods, len(dates)),
        }
    )
    frame["settlement_datetime"] = pd.DatetimeIndex(
        frame["settlement_date"]
    ).tz_localize("UTC") + pd.to_timedelta(frame["settlement_period"] * 30, unit="m")

    day_of_year = pd.DatetimeIndex(frame["settlement_date"]).dayofyear.to_numpy()
    seasonal = 8.0 * np.cos(2 * np.pi * day_of_year / 365.25)
    frame["hdd_realised"] = np.clip(6.0 + seasonal, 0.0, None)
    frame["hdd_forecast"] = np.clip(
        frame["hdd_realised"] + rng.normal(0.0, 0.5, len(frame)), 0.0, None
    )

    frame["is_holiday_any"] = False
    frame["is_christmas_period"] = False
    day_of_week = pd.DatetimeIndex(frame["settlement_date"]).dayofweek.to_numpy()
    frame["demand_mw"] = (
        TRUE_INTERCEPT
        + TRUE_HDD_SLOPE * frame["hdd_realised"]
        - 1_500.0 * (day_of_week >= 5)
        + 40.0 * frame["settlement_period"]
    )
    return frame


def test_fit_recovers_known_coefficients():
    panel = synthetic_panel()
    model = HddCalendarBaseline(annual_harmonics=0).fit(
        panel, target_column="demand_mw", hdd_column="hdd_realised"
    )
    hdd_position = model.feature_names_.index("hdd")
    slopes = [coef[hdd_position] for coef in model.coefficients_.values()]
    assert np.allclose(slopes, TRUE_HDD_SLOPE, atol=1.0)


def test_fits_one_model_per_settlement_period():
    panel = synthetic_panel(days=200)
    model = HddCalendarBaseline().fit(
        panel, target_column="demand_mw", hdd_column="hdd_realised"
    )
    assert len(model.coefficients_) == 48


def test_periods_49_and_50_fold_onto_period_48():
    """The 50-period autumn day must not get its own five-point regression."""
    panel = synthetic_panel(days=200)
    model = HddCalendarBaseline().fit(
        panel, target_column="demand_mw", hdd_column="hdd_realised"
    )
    clock_change = panel.iloc[:2].copy()
    clock_change["settlement_period"] = [49, 50]
    predictions = model.predict(clock_change, hdd_column="hdd_realised")
    assert predictions.notna().all()


def test_predict_uses_the_column_it_is_given():
    """Forecast and realised HDD must produce different predictions.

    If they did not, the column would not be reaching the design matrix and
    the point-in-time distinction would be cosmetic.
    """
    panel = synthetic_panel(days=300)
    model = HddCalendarBaseline().fit(
        panel, target_column="demand_mw", hdd_column="hdd_realised"
    )
    on_forecast = model.predict(panel, hdd_column="hdd_forecast")
    on_realised = model.predict(panel, hdd_column="hdd_realised")
    assert not np.allclose(on_forecast.to_numpy(), on_realised.to_numpy())


def test_oracle_beats_the_forecast_driven_run():
    """Realised weather must be the upper bound, never the headline.

    Guards the interpretation of the oracle row: if a forecast-driven run ever
    beat the oracle on the same model, something is wrong with the wiring.
    """
    panel = synthetic_panel(days=400)
    model = HddCalendarBaseline().fit(
        panel, target_column="demand_mw", hdd_column="hdd_realised"
    )
    forecast_error = (
        (model.predict(panel, hdd_column="hdd_forecast") - panel["demand_mw"])
        .abs()
        .mean()
    )
    oracle_error = (
        (model.predict(panel, hdd_column="hdd_realised") - panel["demand_mw"])
        .abs()
        .mean()
    )
    assert oracle_error < forecast_error


def test_predict_before_fit_raises():
    with pytest.raises(RuntimeError, match="not fitted"):
        HddCalendarBaseline().predict(
            synthetic_panel(days=5), hdd_column="hdd_realised"
        )


def test_missing_hdd_yields_nan_not_a_silent_fallback():
    panel = synthetic_panel(days=200)
    model = HddCalendarBaseline().fit(
        panel, target_column="demand_mw", hdd_column="hdd_realised"
    )
    gapped = panel.iloc[:10].copy()
    gapped.loc[gapped.index[:5], "hdd_forecast"] = np.nan
    predictions = model.predict(gapped, hdd_column="hdd_forecast")
    assert predictions.iloc[:5].isna().all()
    assert predictions.iloc[5:].notna().all()


@pytest.mark.pointintime
def test_walk_forward_leaves_the_initial_training_period_unpredicted():
    """Rows before the first test window must have no prediction at all.

    An in-sample prediction leaking into the scored series would flatter the
    baseline exactly where it has seen the answer.
    """
    panel = synthetic_panel(days=900)
    splitter = ExpandingWindowSplitter(
        initial_train_end=pd.Timestamp("2023-01-01", tz="UTC"),
        test_span=pd.DateOffset(months=1),
        embargo=pd.Timedelta(days=7),
    )
    predictions, folds = walk_forward_predict(
        panel,
        splitter,
        target_column="demand_mw",
        fit_hdd_column="hdd_realised",
        predict_hdd_column="hdd_forecast",
    )
    first_test_start = folds["test_start"].min()
    before = panel["settlement_datetime"] < first_test_start
    assert predictions[before.to_numpy()].isna().all()
    assert predictions[~before.to_numpy()].notna().any()


@pytest.mark.pointintime
def test_walk_forward_scores_each_row_at_most_once():
    panel = synthetic_panel(days=900)
    splitter = ExpandingWindowSplitter(
        initial_train_end=pd.Timestamp("2023-01-01", tz="UTC"),
        test_span=pd.DateOffset(months=1),
    )
    seen: set[int] = set()
    for fold in splitter.split(panel["settlement_datetime"]):
        overlap = seen & set(fold.test_index.tolist())
        assert not overlap
        seen.update(fold.test_index.tolist())


def test_walk_forward_training_sets_only_grow():
    panel = synthetic_panel(days=900)
    splitter = ExpandingWindowSplitter(
        initial_train_end=pd.Timestamp("2023-01-01", tz="UTC"),
        test_span=pd.DateOffset(months=1),
    )
    _, folds = walk_forward_predict(
        panel,
        splitter,
        target_column="demand_mw",
        fit_hdd_column="hdd_realised",
        predict_hdd_column="hdd_forecast",
    )
    assert folds["train_rows"].is_monotonic_increasing
    assert (folds["test_start"] > folds["train_end"]).all()


def test_seasonal_naive_uses_the_same_period_a_week_earlier():
    panel = synthetic_panel(days=60)
    naive = seasonal_naive_forecast(panel, target_column="demand_mw")
    week_ahead = 7 * 48
    np.testing.assert_allclose(
        naive.iloc[week_ahead : week_ahead + 48].to_numpy(),
        panel["demand_mw"].iloc[:48].to_numpy(),
    )
    assert naive.iloc[:week_ahead].isna().all()
