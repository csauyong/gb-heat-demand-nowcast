"""Vintage-panel tests: slot labelling, no back-filling, and the known-error gate."""

from __future__ import annotations

import numpy as np
import pandas as pd

from heat_nowcast.features.vintages import (
    SLOT_ORDER,
    aggregate_gb,
    build_vintage_panel,
    label_slots,
    latest_known_error,
)


def publications_for(gas_day: str, ldz: str = "EA") -> pd.DataFrame:
    day = pd.Timestamp(gas_day)
    stamps = [
        day - pd.Timedelta(days=1) + pd.Timedelta(hours=13, minutes=15),
        day - pd.Timedelta(days=1) + pd.Timedelta(hours=16, minutes=15),
        day + pd.Timedelta(minutes=15),
        day + pd.Timedelta(hours=10, minutes=15),
        day + pd.Timedelta(hours=13, minutes=15),
        day + pd.Timedelta(hours=16, minutes=15),
        day + pd.Timedelta(hours=21, minutes=15),
        day + pd.Timedelta(days=1, minutes=15),
    ]
    return pd.DataFrame(
        {
            "gas_day": day,
            "ldz": ldz,
            "value": np.arange(1.0, 9.0),
            "generated_at": stamps,
        }
    )


def test_canonical_slots_are_labelled_in_order() -> None:
    labels = label_slots(publications_for("2024-01-10"))
    assert list(labels) == list(SLOT_ORDER)


def test_non_canonical_slot_is_dropped_not_relabelled() -> None:
    pubs = publications_for("2024-01-10")
    odd = pd.DataFrame(
        {
            "gas_day": [pd.Timestamp("2024-01-10")],
            "ldz": ["EA"],
            "value": [99.0],
            "generated_at": [pd.Timestamp("2024-01-09 21:15")],
        }
    )
    wide, audit = build_vintage_panel(pd.concat([pubs, odd], ignore_index=True))
    assert audit["rows_non_canonical"] == 1
    assert 99.0 not in wide.filter(like="f_").to_numpy()
    assert wide.loc[0, "f_dm1_1615"] == 2.0


def test_missing_slot_stays_missing() -> None:
    pubs = publications_for("2024-01-10")
    pubs = pubs.loc[pubs["generated_at"] != pd.Timestamp("2024-01-09 16:15")]
    wide, _ = build_vintage_panel(pubs)
    assert np.isnan(wide["f_dm1_1615"].to_numpy(dtype="float64")[0])
    assert wide.loc[0, "f_dm1_1315"] == 1.0


def test_duplicate_timestamp_keeps_last() -> None:
    pubs = publications_for("2024-01-10")
    repeat = pubs.iloc[[1]].assign(value=42.0)
    wide, audit = build_vintage_panel(pd.concat([pubs, repeat], ignore_index=True))
    assert audit["rows_duplicate_timestamp"] == 1
    assert wide.loc[0, "f_dm1_1615"] == 42.0


def test_gb_sum_is_nan_when_a_zone_is_missing() -> None:
    frame = pd.DataFrame(
        {
            "gas_day": pd.to_datetime(["2024-01-10"] * 3 + ["2024-01-11"] * 2),
            "ldz": ["A", "B", "C", "A", "B"],
            "x": [1.0, 2.0, 3.0, 1.0, 2.0],
        }
    )
    gb = aggregate_gb(frame, sum_columns=["x"], n_zones=3)
    assert gb.loc[0, "x"] == 6.0
    assert np.isnan(gb["x"].to_numpy(dtype="float64")[1])


def test_known_error_skips_an_actual_published_after_issue() -> None:
    """D-2's actual arrives late (on D), so at D-1 16:15 only D-3 is known."""
    days = pd.date_range("2024-01-01", periods=6, freq="D")
    issue = days - pd.Timedelta(days=1) + pd.Timedelta(hours=16, minutes=15)
    published = days + pd.Timedelta(days=1, hours=12)
    late = 3  # gas day 2024-01-04 publishes on D+2, not D+1
    published = published.where(
        np.arange(6) != late, days[late] + pd.Timedelta(days=2, hours=12)
    )
    daily = pd.DataFrame(
        {
            "gas_day": days,
            "f": [10.0, 20.0, 30.0, 40.0, 50.0, 60.0],
            "a": [9.0, 18.0, 27.0, 36.0, 45.0, 54.0],  # error = 1, 2, 3, ...
            "pub": published,
            "issue": issue,
        }
    )
    known = latest_known_error(
        daily,
        forecast_column="f",
        actual_column="a",
        actual_published_column="pub",
        issue_column="issue",
    )
    # Gas day 2024-01-06 (index 5): D-2 is index 3, published late on 01-06,
    # after the 01-05 16:15 issue -> falls back to D-3 (index 2, error 3).
    assert known.loc[5, "e_known"] == 3.0
    assert known.loc[5, "e_known_lag_days"] == 3.0
    # Gas day 2024-01-05 (index 4): D-2 is index 2, published 01-04 12:00 < issue.
    assert known.loc[4, "e_known"] == 3.0
    assert known.loc[4, "e_known_lag_days"] == 2.0
    # Never uses D-1, whose actual cannot exist at D-1 16:15.
    assert (known["e_known_lag_days"].dropna() >= 2).all()
