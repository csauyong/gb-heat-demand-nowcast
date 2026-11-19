"""Blind coverage probe: dates and counts only, never values."""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from heat_nowcast.data import lseg_prices
from heat_nowcast.data.lseg_prices import coverage_from_frame, probe_history_coverage

SENTINEL = 987.654321


def fake_history(start: str, periods: int) -> pd.DataFrame:
    index = pd.bdate_range(start, periods=periods)
    values = np.full(periods, SENTINEL)
    values[3] = np.nan
    return pd.DataFrame({"TRDPRC_1": values}, index=index)


def test_report_never_carries_a_value() -> None:
    report = coverage_from_frame("X", fake_history("2021-11-01", 300))
    assert str(SENTINEL) not in repr(report)
    assert report.non_null == {"TRDPRC_1": 299}
    assert report.covers_development_sample
    assert report.missing_weekdays_from_required_start == 0


def test_late_start_is_flagged() -> None:
    report = coverage_from_frame("X", fake_history("2023-06-26", 100))
    assert report.first_date == dt.date(2023, 6, 26)
    assert not report.covers_development_sample


def test_access_failure_is_reported_not_raised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def denied(ric: str, start: dt.date, end: dt.date) -> pd.DataFrame:
        raise PermissionError("user does not have permission")

    monkeypatch.setattr(lseg_prices, "_get_history", denied)
    report = probe_history_coverage("X")
    assert report.rows == 0
    assert report.error is not None
    assert "permission" in report.error
