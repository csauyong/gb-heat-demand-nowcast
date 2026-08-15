"""Degree-day and population-weighting tests.

These are pure-function tests. Nothing here touches the network, so they run
in CI and they run fast.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from heat_nowcast.features.weather import (
    UK_HDD_BASE_C,
    build_population_weights,
    degree_deficit,
    heating_degree_days,
    population_weighted_temperature,
)


def hourly_frame(
    values: list[float],
    start: str = "2024-01-01T00:00:00Z",
    column: str = "temp_c_forecast",
) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "time_utc": pd.date_range(start, periods=len(values), freq="h", tz="UTC"),
            column: values,
        }
    )


# --------------------------------------------------------------------------
# base temperature
# --------------------------------------------------------------------------


def test_uk_base_is_15_5():
    assert UK_HDD_BASE_C == 15.5


def test_base_temperature_is_a_parameter_not_a_constant():
    """The whole point of exposing base_c: changing it must change the answer."""
    frame = hourly_frame([10.0] * 24)
    at_default = heating_degree_days(frame, value_column="temp_c_forecast")
    at_18 = heating_degree_days(frame, value_column="temp_c_forecast", base_c=18.0)
    at_5 = heating_degree_days(frame, value_column="temp_c_forecast", base_c=5.0)

    assert at_default["hdd"].iloc[0] == pytest.approx(5.5)
    assert at_18["hdd"].iloc[0] == pytest.approx(8.0)
    assert at_5["hdd"].iloc[0] == pytest.approx(0.0)


# --------------------------------------------------------------------------
# heating_degree_days
# --------------------------------------------------------------------------


def test_hdd_is_base_minus_daily_mean():
    frame = hourly_frame([15.5 - 3.0] * 24)
    result = heating_degree_days(frame, value_column="temp_c_forecast")
    assert len(result) == 1
    assert result["mean_temp_c"].iloc[0] == pytest.approx(12.5)
    assert result["hdd"].iloc[0] == pytest.approx(3.0)


def test_hdd_is_never_negative():
    """Warm days contribute zero, not a cooling credit."""
    frame = hourly_frame([25.0] * 24)
    result = heating_degree_days(frame, value_column="temp_c_forecast")
    assert result["hdd"].iloc[0] == 0.0


def test_hdd_uses_the_mean_then_truncates_not_the_other_way_round():
    """max(0, base - mean(T)) != mean(max(0, base - T)).

    A day swinging either side of the base is the case that separates the two
    definitions. Getting this backwards would inflate HDD on every shoulder-
    season day, which is precisely where a heating model's errors live.
    """
    values = [5.5] * 12 + [25.5] * 12  # mean 15.5 exactly
    frame = hourly_frame(values)
    result = heating_degree_days(frame, value_column="temp_c_forecast")

    assert result["mean_temp_c"].iloc[0] == pytest.approx(15.5)
    assert result["hdd"].iloc[0] == pytest.approx(0.0)

    # The instantaneous definition gives a very different number.
    deficit = degree_deficit(pd.Series(values))
    assert float(np.mean(deficit)) == pytest.approx(5.0)


def test_hdd_groups_by_local_day_not_utc_day():
    """In BST, local midnight is 23:00 UTC the day before.

    An hour placed in the wrong day misaligns HDD against a demand calendar
    that is defined on London dates.
    """
    # 2024-07-01 00:30 BST == 2024-06-30 23:30 UTC.
    frame = pd.DataFrame(
        {
            "time_utc": pd.to_datetime(
                ["2024-06-30T23:00:00Z", "2024-06-30T22:00:00Z"], utc=True
            ),
            "temp_c_forecast": [10.0, 10.0],
        }
    )
    result = heating_degree_days(frame, value_column="temp_c_forecast", min_hours=1)
    assert set(result["settlement_date"].astype(str)) == {
        "2024-06-30",
        "2024-07-01",
    }


def test_hdd_drops_partial_days():
    frame = hourly_frame([10.0] * 5)
    result = heating_degree_days(frame, value_column="temp_c_forecast")
    assert len(result) == 0


def test_hdd_keeps_clock_change_days():
    """23- and 25-hour days are legitimate and must not be discarded."""
    spring = pd.DataFrame(
        {
            "time_utc": pd.date_range(
                "2024-03-31T00:00:00Z", periods=23, freq="h", tz="UTC"
            ),
            "temp_c_forecast": [8.0] * 23,
        }
    )
    result = heating_degree_days(spring, value_column="temp_c_forecast")
    assert len(result) == 1
    assert int(result["n_hours"].iloc[0]) == 23


def test_hdd_requires_timezone_aware_input():
    frame = pd.DataFrame(
        {
            "time_utc": pd.date_range("2024-01-01", periods=24, freq="h"),
            "temp_c_forecast": [10.0] * 24,
        }
    )
    with pytest.raises(ValueError, match="timezone-aware"):
        heating_degree_days(frame, value_column="temp_c_forecast")


def test_degree_deficit_matches_hdd_on_a_flat_day():
    """With constant temperature the two definitions must agree."""
    frame = hourly_frame([9.5] * 24)
    daily = heating_degree_days(frame, value_column="temp_c_forecast")
    assert daily["hdd"].iloc[0] == pytest.approx(float(degree_deficit(9.5)))


def test_degree_deficit_handles_scalars_arrays_and_series():
    assert degree_deficit(20.0) == 0.0
    assert degree_deficit(10.5) == pytest.approx(5.0)
    np.testing.assert_allclose(
        degree_deficit(np.array([20.0, 10.5])), np.array([0.0, 5.0])
    )
    pd.testing.assert_series_equal(
        degree_deficit(pd.Series([20.0, 10.5])),
        pd.Series([0.0, 5.0]),
    )


# --------------------------------------------------------------------------
# population weighting
# --------------------------------------------------------------------------


def two_cluster_points() -> pd.DataFrame:
    """Two well-separated population clusters, 3:1 by population."""
    return pd.DataFrame(
        {
            "latitude": [51.5, 51.6, 55.9, 55.95],
            "longitude": [-0.1, -0.2, -3.2, -3.25],
            "population": [3000.0, 3000.0, 1000.0, 1000.0],
        }
    )


def test_weights_sum_to_one():
    weights = build_population_weights(two_cluster_points(), population_coverage=1.0)
    assert weights["weight"].sum() == pytest.approx(1.0)


def test_weights_are_proportional_to_population():
    weights = build_population_weights(two_cluster_points(), population_coverage=1.0)
    assert len(weights) == 2
    ordered = weights.sort_values("weight", ascending=False)
    assert ordered["weight"].iloc[0] == pytest.approx(0.75)
    assert ordered["weight"].iloc[1] == pytest.approx(0.25)


def test_cell_location_is_the_population_weighted_centroid():
    points = pd.DataFrame(
        {
            "latitude": [51.0, 51.0],
            "longitude": [-0.4, -0.2],
            "population": [3000.0, 1000.0],
        }
    )
    weights = build_population_weights(points, population_coverage=1.0)
    assert len(weights) == 1
    # (3*-0.4 + 1*-0.2)/4 = -0.35, not the midpoint -0.3.
    assert weights["longitude"].iloc[0] == pytest.approx(-0.35)


def test_population_coverage_drops_the_tail_and_renormalises():
    points = pd.DataFrame(
        {
            "latitude": [51.0, 55.0, 58.0],
            "longitude": [-0.1, -3.0, -5.0],
            "population": [9000.0, 900.0, 1.0],
        }
    )
    weights = build_population_weights(points, population_coverage=0.9)
    assert len(weights) < 3
    assert weights["weight"].sum() == pytest.approx(1.0)


def test_population_weighted_temperature_is_a_weighted_mean():
    weights = pd.DataFrame(
        {
            "point_id": ["a", "b"],
            "latitude": [51.5, 55.9],
            "longitude": [-0.1, -3.2],
            "population": [3000.0, 1000.0],
            "weight": [0.75, 0.25],
        }
    )
    stamp = pd.Timestamp("2024-01-01T00:00:00Z")
    temperatures = pd.DataFrame(
        {
            "time_utc": [stamp, stamp],
            "point_id": ["a", "b"],
            "temp_c_forecast": [10.0, 2.0],
        }
    )
    result = population_weighted_temperature(
        temperatures, weights, value_column="temp_c_forecast"
    )
    assert result["temp_c_forecast"].iloc[0] == pytest.approx(0.75 * 10.0 + 0.25 * 2.0)


def test_population_weighted_temperature_rejects_a_partial_grid():
    """A missing cell must raise, not quietly reweight the national mean."""
    weights = pd.DataFrame(
        {
            "point_id": ["a", "b"],
            "latitude": [51.5, 55.9],
            "longitude": [-0.1, -3.2],
            "population": [3000.0, 1000.0],
            "weight": [0.75, 0.25],
        }
    )
    stamp = pd.Timestamp("2024-01-01T00:00:00Z")
    temperatures = pd.DataFrame(
        {
            "time_utc": [stamp],
            "point_id": ["a"],
            "temp_c_forecast": [10.0],
        }
    )
    with pytest.raises(ValueError, match="missing weather cells"):
        population_weighted_temperature(
            temperatures, weights, value_column="temp_c_forecast"
        )


def test_realised_column_name_survives_the_weighting_step():
    """A `_realised` suffix must not be laundered away mid-pipeline."""
    weights = pd.DataFrame(
        {
            "point_id": ["a"],
            "latitude": [51.5],
            "longitude": [-0.1],
            "population": [1.0],
            "weight": [1.0],
        }
    )
    temperatures = pd.DataFrame(
        {
            "time_utc": [pd.Timestamp("2024-01-01T00:00:00Z")],
            "point_id": ["a"],
            "temp_c_realised": [4.0],
        }
    )
    result = population_weighted_temperature(
        temperatures, weights, value_column="temp_c_realised"
    )
    assert "temp_c_realised" in result.columns


def test_build_population_weights_rejects_bad_input():
    with pytest.raises(ValueError, match="missing columns"):
        build_population_weights(pd.DataFrame({"latitude": [1.0]}))
    with pytest.raises(ValueError, match="population_coverage"):
        build_population_weights(two_cluster_points(), population_coverage=0.0)
