"""C1 efficiency-test tests on synthetic vintage series with a known answer."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from heat_nowcast.analysis.efficiency import (
    mincer_zarnowitz,
    nordhaus_chain,
    revision_regression,
    simulate_mde,
    walk_forward_corrected,
)
from heat_nowcast.features.vintages import SLOT_ORDER


def synthetic_daily(
    days: int = 1500, overshoot: float = 0.0, bias: float = 0.0, seed: int = 7
) -> pd.DataFrame:
    """Vintages that absorb news ``u1`` at 16:15 on D-1.

    With ``overshoot = 0`` the 16:15 forecast is efficient: its error ``u2`` is
    independent of its revision ``-u1``. With ``overshoot = k`` the revision is
    ``-(1 + k) u1`` and the error ``u2 - k u1``, so the primary slope is
    ``k / (1 + k)``.
    """
    rng = np.random.default_rng(seed)
    gas_day = pd.date_range("2021-12-01", periods=days, freq="D")
    actual = 100.0 + 30.0 * np.sin(2 * np.pi * np.arange(days) / 365.25)
    u1, u2 = rng.normal(0, 2.0, days), rng.normal(0, 2.0, days)
    frame = pd.DataFrame({"gas_day": gas_day, "actual": actual})
    frame["f_dm1_1315"] = actual + u1 + u2 + bias
    frame["f_dm1_1615"] = actual + u2 - overshoot * u1 + bias
    noise = u2.copy()
    for slot in SLOT_ORDER[2:]:
        noise = 0.6 * noise + rng.normal(0, 0.2, days)
        frame[f"f_{slot}"] = actual + noise
    frame["issue"] = gas_day - pd.Timedelta(days=1) + pd.Timedelta(hours=16, minutes=15)
    frame["published"] = gas_day + pd.Timedelta(days=6, hours=12)
    return frame


def test_efficient_forecast_has_zero_slope() -> None:
    result = revision_regression(synthetic_daily(), "actual")
    assert abs(result["beta"]) < 3 * result["se"]


def test_overshooting_revisions_give_the_known_slope() -> None:
    result = revision_regression(synthetic_daily(overshoot=0.5), "actual")
    assert result["beta"] == pytest.approx(0.5 / 1.5, abs=0.05)
    assert result["p_value"] < 0.001


def test_mincer_zarnowitz_accepts_unbiased_and_rejects_biased() -> None:
    unbiased = mincer_zarnowitz(synthetic_daily(), "dm1_1615", "actual")
    biased = mincer_zarnowitz(synthetic_daily(bias=3.0), "dm1_1615", "actual")
    assert unbiased["b"] == pytest.approx(1.0, abs=0.05)
    assert biased["p_value"] < 0.001


def test_nordhaus_table_covers_six_pairs() -> None:
    summary, table = nordhaus_chain(synthetic_daily(), "actual")
    assert len(table) == 6
    assert summary["n_days"] == 1500
    assert (table["b2_mae_zero_revision"] > 0).all()


def test_mde_curve_has_size_near_nominal_and_rises() -> None:
    curve, mde = simulate_mde(synthetic_daily(days=800), "actual", n_sims=200, seed=3)
    assert float(curve["rejection_rate"].iloc[0]) < 0.12
    assert curve["rejection_rate"].iloc[-1] > 0.95
    assert np.isfinite(mde) and mde > 0


def test_corrected_forecast_never_trains_on_unpublished_actuals() -> None:
    daily = synthetic_daily(bias=2.0)
    result = walk_forward_corrected(
        daily,
        "actual",
        target_published="published",
        issue_column="issue",
        score_start=pd.Timestamp("2022-12-01"),
    )
    folds = result.folds
    assert len(folds) > 0
    # Last training day's actual (published D+6 12:00) precedes the first issue.
    published_last = folds["last_train_day"] + pd.Timedelta(days=6, hours=12)
    assert (published_last < folds["first_issue"]).all()
    assert result.forecast[daily["gas_day"] < pd.Timestamp("2022-12-01")].isna().all()


def test_corrected_forecast_removes_a_constant_bias() -> None:
    daily = synthetic_daily(bias=2.0)
    result = walk_forward_corrected(
        daily,
        "actual",
        target_published="published",
        issue_column="issue",
        score_start=pd.Timestamp("2022-12-01"),
    )
    scored = result.forecast.notna()
    raw_mae = (
        (daily.loc[scored, "f_dm1_1615"] - daily.loc[scored, "actual"]).abs().mean()
    )
    new_mae = (result.forecast[scored] - daily.loc[scored, "actual"]).abs().mean()
    assert new_mae < raw_mae
