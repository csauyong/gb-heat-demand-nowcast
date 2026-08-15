"""Two-way fixed effects and wild cluster bootstrap tests.

The bootstrap is the load-bearing piece of Phase 1b inference: with 13
clusters, conventional cluster-robust t-tests over-reject badly, so a null
result is only credible if the bootstrap is calibrated. These tests check that
directly rather than assuming it.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from heat_nowcast.analysis.twoway import (
    TwoWayFEResult,
    demean_two_way,
    fit_two_way_fe,
)

N_UNITS = 13
N_PERIODS = 300


def panel(
    *,
    true_effect: float = 0.0,
    noise_sd: float = 1.0,
    seed: int = 20260815,
    unit_fe_sd: float = 3.0,
    period_fe_sd: float = 2.0,
) -> pd.DataFrame:
    """Balanced LDZ-like panel with a time-invariant stock score.

    The stock score is constant within a unit, exactly as a real building-stock
    metric is over a two-year window -- which is why only its interaction with
    a time-varying severity is identified.
    """
    rng = np.random.default_rng(seed)
    units = np.repeat(np.arange(N_UNITS), N_PERIODS)
    periods = np.tile(np.arange(N_PERIODS), N_UNITS)

    stock = rng.normal(size=N_UNITS)
    stock = (stock - stock.mean()) / stock.std()
    severity = rng.normal(size=N_PERIODS)

    frame = pd.DataFrame(
        {
            "ldz": [f"L{u:02d}" for u in units],
            "gas_day": periods,
            "stock": stock[units],
            "severity": severity[periods],
        }
    )
    frame["interaction"] = frame["stock"] * frame["severity"]
    frame["y"] = (
        rng.normal(0.0, unit_fe_sd, N_UNITS)[units]
        + rng.normal(0.0, period_fe_sd, N_PERIODS)[periods]
        + true_effect * frame["interaction"]
        + rng.normal(0.0, noise_sd, len(frame))
    )
    return frame


def fit(frame: pd.DataFrame, **kwargs: object) -> TwoWayFEResult:
    defaults: dict[str, object] = {
        "outcome": "y",
        "regressors": ["interaction"],
        "unit_column": "ldz",
        "period_column": "gas_day",
        "bootstrap_draws": 399,
        "seed": 7,
    }
    defaults.update(kwargs)
    return fit_two_way_fe(frame, **defaults)  # type: ignore[arg-type]  # kwargs heterogeneous


# --------------------------------------------------------------------------
# the within transformation
# --------------------------------------------------------------------------


def test_demeaning_annihilates_pure_fixed_effects():
    """Anything that is unit effect plus period effect must demean to zero."""
    rng = np.random.default_rng(1)
    units = np.repeat(np.arange(N_UNITS), N_PERIODS)
    periods = np.tile(np.arange(N_PERIODS), N_UNITS)
    values = rng.normal(size=N_UNITS)[units] + rng.normal(size=N_PERIODS)[periods]

    residual = demean_two_way(values, units, periods)
    assert np.max(np.abs(residual)) < 1e-9


def test_demeaning_leaves_an_interaction_intact():
    """The regressor of interest must survive both projections."""
    rng = np.random.default_rng(2)
    units = np.repeat(np.arange(N_UNITS), N_PERIODS)
    periods = np.tile(np.arange(N_PERIODS), N_UNITS)
    stock = rng.normal(size=N_UNITS)[units]
    severity = rng.normal(size=N_PERIODS)[periods]

    residual = demean_two_way(stock * severity, units, periods)
    assert residual.std() > 0.5


def test_demeaning_removes_a_time_invariant_regressor_entirely():
    """Stock *levels* are absorbed by unit effects -- this is why we need the
    interaction, and the test states it rather than leaving it implicit."""
    rng = np.random.default_rng(3)
    units = np.repeat(np.arange(N_UNITS), N_PERIODS)
    periods = np.tile(np.arange(N_PERIODS), N_UNITS)
    stock_level = rng.normal(size=N_UNITS)[units]

    residual = demean_two_way(stock_level, units, periods)
    assert np.max(np.abs(residual)) < 1e-9


# --------------------------------------------------------------------------
# estimation
# --------------------------------------------------------------------------


def test_recovers_a_known_interaction_effect():
    result = fit(panel(true_effect=0.35))
    assert result.coefficients[0] == pytest.approx(0.35, abs=0.05)
    assert result.wild_p_values[0] < 0.05


def test_reports_panel_dimensions():
    result = fit(panel())
    assert result.n_clusters == N_UNITS
    assert result.n_units == N_UNITS
    assert result.n_periods == N_PERIODS
    assert result.n_obs == N_UNITS * N_PERIODS


def test_zero_effect_is_not_rejected():
    result = fit(panel(true_effect=0.0, seed=11))
    assert result.wild_p_values[0] > 0.05


def test_empty_input_raises():
    frame = panel().iloc[:0]
    with pytest.raises(ValueError, match="no complete rows"):
        fit(frame)


# --------------------------------------------------------------------------
# inference calibration -- the point of the module
# --------------------------------------------------------------------------


def test_wild_bootstrap_is_calibrated_under_the_null():
    """Rejection rate at nominal 5% must not exceed it materially.

    With 13 clusters this is exactly where naive cluster-robust inference
    fails, so it is checked rather than assumed. The restricted wild bootstrap
    is expected to be slightly conservative; over-rejection is the failure that
    matters and the assertion is one-sided in that direction.
    """
    p_values = [
        fit(
            panel(true_effect=0.0, seed=100 + replication), bootstrap_draws=199
        ).wild_p_values[0]
        for replication in range(40)
    ]
    rejection_rate = float(np.mean(np.array(p_values) <= 0.05))
    assert rejection_rate <= 0.15, (
        f"wild cluster bootstrap over-rejects: {rejection_rate:.3f} at nominal 0.05"
    )


def test_naive_cluster_t_over_rejects_more_than_the_bootstrap():
    """Demonstrates why the bootstrap is needed, on this exact panel shape.

    If this ever stops holding, the 13-cluster caveat in the report should be
    revisited -- but it is the well-documented behaviour and the report leans
    on it.
    """
    naive_rejections = 0
    bootstrap_rejections = 0
    for replication in range(40):
        result = fit(
            panel(true_effect=0.0, seed=200 + replication), bootstrap_draws=199
        )
        if abs(result.t_stats[0]) > 1.96:
            naive_rejections += 1
        if result.wild_p_values[0] <= 0.05:
            bootstrap_rejections += 1
    assert naive_rejections >= bootstrap_rejections


def test_bootstrap_p_values_are_deterministic_given_a_seed():
    """Every stochastic routine takes an explicit seed (`CLAUDE.md` §7)."""
    frame = panel(true_effect=0.2)
    first = fit(frame, seed=42).wild_p_values[0]
    second = fit(frame, seed=42).wild_p_values[0]
    assert first == second


def test_different_seeds_give_similar_p_values():
    frame = panel(true_effect=0.0, seed=5)
    values = [
        fit(frame, seed=seed, bootstrap_draws=399).wild_p_values[0]
        for seed in (1, 2, 3)
    ]
    assert max(values) - min(values) < 0.15


# --------------------------------------------------------------------------
# fixed-effect sensitivities must be labelled, never headline
# --------------------------------------------------------------------------


def test_dropping_period_fe_changes_the_estimate_when_a_day_shock_exists():
    """Without day effects a national shock contaminates the interaction.

    This is why the module insists both sets of fixed effects stay in for the
    headline: dropping either answers a weaker question.
    """
    frame = panel(true_effect=0.0, period_fe_sd=8.0, seed=21)
    # Make the national shock correlate with severity, as a cold snap would.
    frame["y"] = frame["y"] + 3.0 * frame["severity"]

    with_both = fit(frame)
    without_period = fit(frame, include_period_fe=False)
    assert abs(without_period.coefficients[0]) >= abs(with_both.coefficients[0])


def test_dropping_unit_fe_leaves_unit_level_variation_in_the_residual():
    frame = panel(true_effect=0.0, unit_fe_sd=10.0, seed=22)
    with_both = fit(frame)
    without_unit = fit(frame, include_unit_fe=False)
    assert without_unit.residual_sd > with_both.residual_sd
