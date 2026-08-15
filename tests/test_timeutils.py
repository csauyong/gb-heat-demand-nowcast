"""Settlement-period arithmetic, including the 46- and 50-period days."""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from heat_nowcast.timeutils import (
    gas_day,
    settlement_period_to_utc,
    settlement_periods_in_day,
)


def test_normal_day_has_48_periods():
    assert settlement_periods_in_day(dt.date(2024, 1, 15)) == 48


def test_spring_forward_day_has_46_periods():
    """GMT -> BST, 2024-03-31. A 23-hour day."""
    assert settlement_periods_in_day(dt.date(2024, 3, 31)) == 46


def test_autumn_day_has_50_periods():
    """BST -> GMT, 2024-10-27. A 25-hour day."""
    assert settlement_periods_in_day(dt.date(2024, 10, 27)) == 50


def test_period_end_in_winter_is_utc_aligned():
    result = settlement_period_to_utc(
        pd.Series([pd.Timestamp("2024-01-15")]), pd.Series([1])
    )
    assert result.iloc[0] == pd.Timestamp("2024-01-15T00:30:00Z")


def test_period_end_in_summer_accounts_for_bst():
    """Local midnight in BST is 23:00 UTC the previous day."""
    result = settlement_period_to_utc(
        pd.Series([pd.Timestamp("2024-07-15")]), pd.Series([1])
    )
    assert result.iloc[0] == pd.Timestamp("2024-07-14T23:30:00Z")


def test_spring_forward_last_period_ends_at_local_midnight():
    """SP46 on the 23-hour day must land on the next local midnight.

    2024-03-31 begins in GMT, so local midnight is 00:00 UTC. The clocks go
    forward at 01:00 GMT, so the 46 periods span 23 hours and SP46 ends at
    23:00 UTC, which is 2024-04-01 00:00 BST.
    """
    result = settlement_period_to_utc(
        pd.Series([pd.Timestamp("2024-03-31")]), pd.Series([46])
    )
    assert result.iloc[0] == pd.Timestamp("2024-03-31T23:00:00Z")
    assert result.iloc[0].tz_convert("Europe/London") == pd.Timestamp(
        "2024-04-01T00:00:00+0100"
    )


def test_autumn_last_period_ends_at_local_midnight():
    """SP50 on the 25-hour day must land on the next local midnight."""
    result = settlement_period_to_utc(
        pd.Series([pd.Timestamp("2024-10-27")]), pd.Series([50])
    )
    assert result.iloc[0] == pd.Timestamp("2024-10-28T00:00:00Z")


def test_periods_are_strictly_increasing_across_a_clock_change():
    """The autumn day repeats a local hour; UTC instants must not repeat."""
    date = pd.Series([pd.Timestamp("2024-10-27")] * 50)
    periods = pd.Series(range(1, 51))
    result = settlement_period_to_utc(date, periods)
    assert result.is_monotonic_increasing
    assert result.nunique() == 50


def test_a_full_year_of_periods_is_unique():
    """End-to-end guard against DST double-counting or gaps."""
    rows: list[tuple[pd.Timestamp, int]] = []
    day = dt.date(2024, 1, 1)
    while day < dt.date(2025, 1, 1):
        count = settlement_periods_in_day(day)
        rows.extend((pd.Timestamp(day), period) for period in range(1, count + 1))
        day += dt.timedelta(days=1)

    frame = pd.DataFrame(rows, columns=["settlement_date", "settlement_period"])
    stamps = settlement_period_to_utc(
        frame["settlement_date"], frame["settlement_period"]
    )
    assert stamps.nunique() == len(stamps)
    assert stamps.is_monotonic_increasing
    # 366 days in 2024, minus one hour in spring, plus one in autumn.
    assert len(stamps) == 366 * 48


def test_invalid_settlement_period_rejected():
    with pytest.raises(ValueError, match=r"\[1, 50\]"):
        settlement_period_to_utc(
            pd.Series([pd.Timestamp("2024-01-15")]), pd.Series([0])
        )
    with pytest.raises(ValueError, match=r"\[1, 50\]"):
        settlement_period_to_utc(
            pd.Series([pd.Timestamp("2024-01-15")]), pd.Series([51])
        )


def test_gas_day_boundary_is_05_00_utc():
    """Gas day is 05:00-05:00 UTC and is not the electricity day."""
    stamps = pd.Series(
        pd.to_datetime(
            [
                "2024-01-15T04:59:00Z",
                "2024-01-15T05:00:00Z",
                "2024-01-15T23:00:00Z",
                "2024-01-16T04:59:00Z",
            ],
            utc=True,
        )
    )
    days = gas_day(stamps)
    assert list(days.astype(str)) == [
        "2024-01-14",
        "2024-01-15",
        "2024-01-15",
        "2024-01-15",
    ]


def test_gas_day_requires_timezone_aware_input():
    with pytest.raises(ValueError, match="timezone-aware"):
        gas_day(pd.Series(pd.to_datetime(["2024-01-15T05:00:00"])))
