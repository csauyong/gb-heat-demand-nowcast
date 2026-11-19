"""Paper 1 data layer: portal clock, gas-day start, price embargo, parsing."""

from __future__ import annotations

import datetime as dt
from typing import Any

import pandas as pd
import pytest

from heat_nowcast.data import gas
from heat_nowcast.data.nts_market import (
    PriceEmbargoError,
    check_price_embargo,
    first_publication,
)
from heat_nowcast.timeutils import gas_day_start_utc, portal_local_to_utc


def test_portal_clock_is_uk_local_in_summer_and_winter() -> None:
    stamps = pd.Series(pd.to_datetime(["2024-01-15 13:10", "2024-07-15 13:10"]))
    utc = portal_local_to_utc(stamps)
    assert utc.iloc[0] == pd.Timestamp("2024-01-15 13:10", tz="UTC")
    assert utc.iloc[1] == pd.Timestamp("2024-07-15 12:10", tz="UTC")


def test_clock_change_edge_cases_resolve_to_the_later_instant() -> None:
    stamps = pd.Series(
        pd.to_datetime(["2022-10-30 01:30", "2022-03-27 01:30"])
    )  # ambiguous (autumn), non-existent (spring)
    utc = portal_local_to_utc(stamps)
    assert utc.iloc[0] == pd.Timestamp("2022-10-30 01:30", tz="UTC")  # read as GMT
    assert utc.iloc[1] == pd.Timestamp("2022-03-27 01:00", tz="UTC")  # 02:00 BST


def test_gas_day_starts_at_05_local() -> None:
    starts = gas_day_start_utc(pd.Series(pd.to_datetime(["2024-01-15", "2024-07-15"])))
    assert starts.iloc[0] == pd.Timestamp("2024-01-15 05:00", tz="UTC")
    assert starts.iloc[1] == pd.Timestamp("2024-07-15 04:00", tz="UTC")


def test_price_embargo_allows_a_probe_and_blocks_a_full_pull() -> None:
    start = dt.date(2021, 12, 1)
    check_price_embargo(start, dt.date(2021, 12, 7), preregistration_row=None)
    with pytest.raises(PriceEmbargoError):
        check_price_embargo(start, dt.date(2026, 8, 7), preregistration_row=None)
    check_price_embargo(start, dt.date(2026, 8, 7), preregistration_row=99)


def test_first_publication_keeps_the_earliest_value() -> None:
    frame = pd.DataFrame(
        {
            "gas_day": pd.to_datetime(["2024-01-15"] * 3),
            "value": [3.0, 1.0, 2.0],
            "generated_at": pd.to_datetime(
                ["2024-01-18 11:41", "2024-01-16 11:41", "2024-01-17 11:41"]
            ),
        }
    )
    first = first_publication(frame)
    assert len(first) == 1
    assert first.loc[0, "value"] == 1.0


def test_fetch_publication_object_parses_portal_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_post(body: dict[str, Any]) -> list[dict[str, Any]]:
        assert body["latestFlag"] == "N"
        return [
            {
                "value": "308",
                "applicableAt": "02/12/2021 13:10:00",
                "applicableFor": "03/12/2021",
                "generatedTimeStamp": "02/12/2021 13:10:00",
                "itemName": "Demand Forecast, NTS",
                "UnitOfMeasure": "mscm",
            }
        ]

    monkeypatch.setattr(gas, "_post", fake_post)
    frame, urls = gas.fetch_publication_object(
        "PUBOB623", dt.date(2021, 12, 1), dt.date(2021, 12, 7), all_publications=True
    )
    assert len(urls) == 1
    assert frame.loc[0, "gas_day"] == pd.Timestamp("2021-12-03")
    assert frame.loc[0, "generated_at"] == pd.Timestamp("2021-12-02 13:10")
    assert frame.loc[0, "value"] == 308.0
