"""Paper 1 features, baselines and estimators (decision log row 56)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from heat_nowcast.analysis.paper1_tests import (
    block_length_rows,
    ekt_gmm,
    hac_ols,
    holm,
    holm_with_pending,
    median_mz,
    simulate_mde_ols,
)
from heat_nowcast.features.paper1 import (
    CUTOFF_DM1_1615,
    cwv_weights_by_gas_year,
    gated_ldz_values,
    gb_weighted_cwv,
    label_nts_slots,
    latest_known_actual,
    product_rule,
)
from heat_nowcast.pipelines.paper1 import walk_forward_b3_nts

DAY = pd.Timestamp("2024-01-10")


def test_nts_slots_nearest_within_tolerance() -> None:
    pubs = pd.DataFrame(
        {
            "gas_day": [DAY] * 4,
            "value": [1.0, 2.0, 3.0, 4.0],
            "generated_at": [
                DAY - pd.Timedelta(hours=10, minutes=50),  # D-1 13:10 exactly
                DAY - pd.Timedelta(hours=10, minutes=40),  # 13:20, farther
                DAY - pd.Timedelta(hours=7, minutes=43),  # 16:17 -> 16:15 slot
                DAY + pd.Timedelta(hours=3),  # D 03:00, no slot
            ],
        }
    )
    wide = label_nts_slots(pubs)
    assert wide.loc[0, "f_dm1_1310"] == 1.0
    assert wide.loc[0, "f_dm1_1615"] == 3.0
    assert wide.attrs["rows_dropped"] == 1


def test_cwv_gate_is_strict() -> None:
    cutoff = DAY + CUTOFF_DM1_1615
    history = pd.DataFrame(
        {
            "gas_day": [DAY] * 3,
            "ldz": ["EA"] * 3,
            "value": [1.0, 2.0, 3.0],
            "generated_at": [
                cutoff - pd.Timedelta(hours=4),
                cutoff - pd.Timedelta(hours=1),
                cutoff,  # stamped at the cut-off: not yet known
            ],
        }
    )
    gated = gated_ldz_values(history, CUTOFF_DM1_1615)
    assert gated["value"].tolist() == [2.0]


def test_weights_use_only_previously_published_actuals() -> None:
    ldz = ("A", "B")
    days = pd.date_range("2022-10-01", "2023-09-30", freq="D")
    rows = []
    for day in days:
        late = day >= pd.Timestamp("2023-09-28")
        for code, value in (("A", 3.0), ("B", 1.0)):
            published = day + pd.Timedelta(days=6)
            rows.append(
                {
                    "gas_day": day,
                    "ldz": code,
                    # Late-September actuals publish in October: must be ignored.
                    "actual": 1000.0 if (late and code == "B") else value,
                    "published_at": published,
                }
            )
    weights = cwv_weights_by_gas_year(pd.DataFrame(rows), [2022, 2023], ldz)
    first = weights.loc[weights["gas_year"] == 2022]
    assert (first["weight"] == 0.5).all() and (first["basis_days"] == 0).all()
    second = weights.loc[weights["gas_year"] == 2023].set_index("ldz")["weight"]
    assert second["A"] == pytest.approx(0.75)


def test_weighted_cwv_needs_every_zone() -> None:
    weights = pd.DataFrame(
        {"gas_year": [2023, 2023], "ldz": ["A", "B"], "weight": [0.75, 0.25]}
    )
    gated = pd.DataFrame(
        {
            "gas_day": [DAY, DAY, DAY + pd.Timedelta(days=1)],
            "ldz": ["A", "B", "A"],
            "value": [4.0, 8.0, 4.0],
        }
    )
    cwv = gb_weighted_cwv(gated, weights, n_zones=2)
    assert cwv[DAY] == pytest.approx(5.0)
    assert np.isnan(cwv[DAY + pd.Timedelta(days=1)])


def test_product_rule() -> None:
    # Delivery days Tue 2024-05-07 .. Mon 2024-05-13; 2024-05-06 is a holiday.
    delivery = pd.Series(pd.date_range("2024-05-07", "2024-05-13", freq="D"))
    trades = pd.Series(pd.date_range("2024-05-06", "2024-05-12", freq="D"))
    holidays = pd.Series(pd.to_datetime(["2024-05-06"]))
    keep = product_rule(delivery, trades, holidays).tolist()
    # Tue (trade Mon=holiday) no; Wed, Thu, Fri yes; Sat (Fri trade) no;
    # Sun, Mon (weekend trade) no.
    assert keep == [False, True, True, True, False, False, False]


def test_no_change_uses_only_published_actuals() -> None:
    days = pd.date_range("2024-01-01", periods=4, freq="D")
    daily = pd.DataFrame(
        {
            "gas_day": days,
            "actual": [10.0, 20.0, 30.0, 40.0],
            "published": days + pd.Timedelta(days=1, hours=12),
            "issue": days - pd.Timedelta(hours=11),  # D-1 13:00
        }
    )
    known = latest_known_actual(
        daily,
        actual_column="actual",
        actual_published_column="published",
        issue_column="issue",
    )
    # D-1's actual publishes at D 12:00 > D-1 13:00, so D-2 is the latest known.
    assert np.isnan(known.iloc[1])
    assert known.iloc[2] == 10.0 and known.iloc[3] == 20.0


def test_b3_nts_never_trains_on_unpublished_actuals() -> None:
    days = pd.date_range("2021-12-01", "2023-01-31", freq="D")
    rng = np.random.default_rng(0)
    panel = pd.DataFrame(
        {
            "gas_day": days,
            "cwv_1310": rng.normal(10, 4, len(days)),
            "dow": days.dayofweek,
            "holiday_ew": 0.0,
            "issued_n_1310": days - pd.Timedelta(hours=11),
            "an_d6_published": days + pd.Timedelta(days=6, hours=12),
        }
    )
    panel["an_d6"] = 300 - 8 * panel["cwv_1310"] + rng.normal(0, 1, len(days))
    # Poison every actual unpublished at the December fold's first issue
    # (2022-11-30 13:00): D+6 12:00 publication admits days up to 2022-11-24.
    poison = panel["gas_day"] >= pd.Timestamp("2022-11-25")
    panel.loc[poison, "an_d6"] = 1e6
    forecast = walk_forward_b3_nts(panel)
    december = panel["gas_day"].between("2022-12-01", "2022-12-31")
    assert forecast[december].abs().max() < 1000


def test_mde_size_and_power() -> None:
    rng = np.random.default_rng(1)
    n = 400
    days = pd.Series(pd.date_range("2023-01-01", periods=n, freq="D"))
    x = pd.Series(rng.normal(size=n))
    y = pd.Series(rng.normal(size=n))
    design = pd.DataFrame({"const": np.ones(n)})
    result = simulate_mde_ols(
        y, design, x, days, n_sims=100, multiples=(0.0, 2.0, 4.0), seed=3
    )
    power = result.curve["power_0.0500"].tolist()
    assert power[0] < 0.15
    assert power[2] > 0.9
    assert 0 < result.mde[0.05] < 4 * result.unit_se


def test_block_length_scales_to_calendar() -> None:
    days = pd.Series(pd.date_range("2024-01-01", periods=140, freq="D"))
    assert block_length_rows(days) == 14
    assert block_length_rows(days.iloc[::2]) == 7


def test_median_mz_unbiased_forecast() -> None:
    rng = np.random.default_rng(2)
    f = pd.Series(rng.normal(250, 50, 600))
    a = f + pd.Series(rng.standard_t(4, 600) * 5)
    result = median_mz(a, f, draws=99)
    assert result["b"] == pytest.approx(1.0, abs=0.05)
    assert result["p_value"] > 0.01


def test_ekt_symmetric_and_asymmetric() -> None:
    rng = np.random.default_rng(4)
    n = 2000
    z = pd.DataFrame({"const": np.ones(n), "z": rng.normal(size=n)})
    symmetric = ekt_gmm(pd.Series(rng.normal(size=n)), z)
    assert symmetric["ci_low"] < 0.5 < symmetric["ci_high"]
    # Forecast set low: e = y - f mostly positive. The forecast is then a low
    # quantile, i.e. over-forecasts (weight 1 - alpha) are the costly side and
    # alpha is below one half (alpha ~ P(e < 0) ~ 0.31).
    shifted = ekt_gmm(pd.Series(rng.normal(size=n) + 0.5), z)
    assert shifted["alpha"] == pytest.approx(0.31, abs=0.03)
    # Forecast set high -> alpha above one half.
    high = ekt_gmm(pd.Series(rng.normal(size=n) - 0.5), z)
    assert high["alpha"] > 0.6
    assert shifted["j_df"] == 1.0


def test_holm() -> None:
    decisions = holm({"a": 0.001, "b": 0.02, "c": 0.04})
    assert decisions == {"a": True, "b": True, "c": True}
    assert holm({"a": 0.001, "b": 0.03, "c": 0.04}) == {
        "a": True,
        "b": False,
        "c": False,
    }
    pending = holm_with_pending({"a": 0.001, "b": 0.5}, pending="x")
    assert pending == {"a": "reject", "b": "retain"}
    borderline = holm_with_pending({"a": 0.02, "b": 0.5}, pending="x")
    assert borderline["a"] == "depends"


def test_hac_ols_reports_effective_n() -> None:
    rng = np.random.default_rng(5)
    x = pd.Series(rng.normal(size=300))
    y = 2 * x + pd.Series(rng.normal(size=300))
    fit = hac_ols(y, pd.DataFrame({"const": 1.0, "x": x}))
    assert fit.params["x"] == pytest.approx(2.0, abs=0.2)
    assert 0 < fit.n_effective <= 300


def test_nts_outturn_rule() -> None:
    from heat_nowcast.pipelines.paper1 import D1_EARLIEST, nts_outturn

    day = pd.Timestamp("2023-01-10")
    pubs = pd.DataFrame(
        {
            "gas_day": [day] * 3 + [day + pd.Timedelta(days=1)],
            "value": [0.1, 259.2, 259.3, 5810.0],
            "generated_at": [
                day + pd.Timedelta(days=1, hours=10),  # partial accrual
                day + pd.Timedelta(days=1, hours=12, minutes=20),
                day + pd.Timedelta(days=2),
                day + pd.Timedelta(days=2, hours=12, minutes=20),
            ],
        }
    )
    out = nts_outturn(pubs, earliest=D1_EARLIEST).set_index("gas_day")["value"]
    assert out[day] == 259.2
    assert np.isnan(out[day + pd.Timedelta(days=1)])
