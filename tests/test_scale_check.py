"""Phase C0 scale-check tests on a synthetic panel with a known answer."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from heat_nowcast.analysis.scale_check import (
    assign_cwv_decile,
    decile_table,
    gb_daily_aggregate,
    hac_mean_by_group,
    row23_reconciliation,
    scale_check,
)

ZONES = ["EA", "NW", "SC"]


def proportional_error_panel(
    days: int = 1000, rel_error: float = 0.05, seed: int = 20261117
) -> pd.DataFrame:
    """Demand falls with CWV; the forecast error is a fixed share of demand.

    By construction MAE rises steeply into the cold tail while MAPE is flat --
    exactly the scale artefact C0 is meant to expose.
    """
    rng = np.random.default_rng(seed)
    gas_days = pd.date_range("2023-12-01", periods=days, freq="D")
    cwv = 10.0 + 8.0 * np.sin(2 * np.pi * np.arange(days) / 365.25)
    rows = []
    for k, zone in enumerate(ZONES):
        zone_cwv = cwv + rng.normal(0.0, 0.5, days)
        actual = (30.0 - 1.5 * zone_cwv) * (1.0 + 0.2 * k)
        sign = rng.choice([-1.0, 1.0], days)
        forecast = actual * (1.0 + sign * rel_error)
        rows.append(
            pd.DataFrame(
                {
                    "gas_day": gas_days,
                    "ldz": zone,
                    "demand_mscm_d1": actual,
                    "ng_forecast_mscm": forecast,
                    "gas_baseline_cwv": actual,
                    "cwv_forecast": zone_cwv,
                }
            )
        )
    return pd.concat(rows, ignore_index=True)


def test_decile_one_is_coldest() -> None:
    cwv = pd.Series(np.arange(100, dtype=float))
    deciles = assign_cwv_decile(cwv)
    assert deciles.iloc[0] == 1
    assert deciles.iloc[-1] == 10
    assert deciles.value_counts().eq(10).all()


def test_proportional_error_gives_mae_gradient_but_flat_mape() -> None:
    table = decile_table(gb_daily_aggregate(proportional_error_panel()))
    cold, warm = table.iloc[0], table.iloc[-1]
    assert cold["mae"] / warm["mae"] > 2.0
    # Zone errors partly cancel in the GB sum, so the level is below 5%, but
    # it must be the same in the cold and warm tails.
    assert cold["mape_pct"] == pytest.approx(warm["mape_pct"], rel=0.25)
    assert cold["mae_scaled_pct"] == pytest.approx(warm["mae_scaled_pct"], rel=0.25)


def test_hac_means_equal_group_means() -> None:
    rng = np.random.default_rng(1)
    group = pd.Series(np.repeat([1, 2, 3], 200))
    error = pd.Series(rng.normal(0.0, 1.0, 600) + group.to_numpy() * 0.5)
    table = hac_mean_by_group(error, group)
    expected = error.groupby(group).mean()
    np.testing.assert_allclose(table["mean_error"], expected.to_numpy())
    assert (table["ci_low"] < table["mean_error"]).all()
    assert (table["ci_high"] > table["mean_error"]).all()


def test_gb_aggregate_drops_incomplete_days() -> None:
    panel = proportional_error_panel(days=30)
    panel = panel.drop(index=panel.index[(panel["ldz"] == "SC")][:5])
    assert len(gb_daily_aggregate(panel)) == 25


def test_scale_check_has_gb_and_every_zone() -> None:
    table = scale_check(proportional_error_panel(days=400))
    assert set(table["level"]) == {"GB", *ZONES}
    assert table.groupby("level").size().eq(10).all()


def test_row23_reconciliation_separates_level_from_relative_error() -> None:
    result = row23_reconciliation(proportional_error_panel())
    assert result["mae_ratio_cold_over_warm"] > 2.0
    assert result["mape_ratio_cold_over_warm"] < result["mae_ratio_cold_over_warm"]
