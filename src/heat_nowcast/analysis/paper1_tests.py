"""Estimators for Paper 1's pre-registered tests (``docs/paper1_preregistration.md``).

Implementation choices are fixed in ``reports/decision_log.md`` row 56. This
module holds estimators only; which sample and which variables each test uses
is decided in :mod:`heat_nowcast.pipelines.paper1`.

* :func:`hac_ols` -- OLS with Newey-West HAC (7 lags by default).
* :func:`simulate_mde_ols` -- minimum detectable effect by block bootstrap of
  the null-model residual (procedure as C1, generalised).
* :func:`median_mz` -- median Mincer-Zarnowitz (H2) with a moving-block
  bootstrap covariance.
* :func:`ekt_gmm` -- Elliott, Komunjer & Timmermann (2005) GMM for the
  asymmetry of a lin-lin loss (H3).
* :func:`holm` -- Holm step-down decisions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats
from statsmodels.regression.quantile_regression import QuantReg

from heat_nowcast.evaluation.splits import effective_sample_size

HAC_LAGS: Final[int] = 7
ALPHA: Final[float] = 0.05
MDE_POWER: Final[float] = 0.80
SEED: Final[int] = 20261117
BLOCK_DAYS: Final[int] = 14
DEFAULT_MULTIPLES: Final[tuple[float, ...]] = (
    0.0,
    0.5,
    1.0,
    1.5,
    2.0,
    2.5,
    3.0,
    3.5,
    4.0,
    5.0,
    6.0,
    8.0,
)


@dataclass(frozen=True)
class HacFit:
    """One HAC regression, reduced to what the tables report."""

    params: dict[str, float]
    se: dict[str, float]
    p_values: dict[str, float]
    n: int
    n_effective: float
    r_squared: float


def hac_ols(y: pd.Series, design: pd.DataFrame, *, lags: int = HAC_LAGS) -> HacFit:
    """OLS with Newey-West HAC covariance; rows with any NaN are dropped.

    ``design`` must already contain the constant if one is wanted. Lags count
    rows of the estimation sample (decision log row 56, item 8).
    """
    frame = pd.concat([y.rename("_y"), design], axis=1).dropna()
    fit = sm.OLS(frame["_y"], frame.drop(columns="_y")).fit(
        cov_type="HAC", cov_kwds={"maxlags": lags}
    )
    return HacFit(
        params={k: float(v) for k, v in fit.params.items()},
        se={k: float(v) for k, v in fit.bse.items()},
        p_values={k: float(v) for k, v in fit.pvalues.items()},
        n=int(fit.nobs),
        n_effective=effective_sample_size(pd.Series(fit.resid), max_lag=30),
        r_squared=float(fit.rsquared),
    )


def block_length_rows(gas_days: pd.Series, block_days: int = BLOCK_DAYS) -> int:
    """Rows spanning ``block_days`` calendar days on a gappy sample (row 56, 9)."""
    days = pd.to_datetime(gas_days)
    span = (days.max() - days.min()).days + 1
    return max(1, round(block_days * len(days) / span))


def circular_block_index(
    n_obs: int, block_rows: int, rng: np.random.Generator
) -> np.ndarray:
    """Row index for one circular moving-block bootstrap draw."""
    n_blocks = int(np.ceil(n_obs / block_rows))
    starts = rng.integers(0, n_obs, n_blocks)
    index = (starts[:, None] + np.arange(block_rows)[None, :]).ravel() % n_obs
    out: np.ndarray = index[:n_obs]
    return out


def _interpolate_mde(curve: pd.DataFrame, column: str) -> float:
    above = curve.index[curve[column] >= MDE_POWER]
    if len(above) == 0:
        return float("nan")
    upper = int(above[0])
    effects = curve["effect"].to_numpy(dtype="float64")
    if upper == 0:
        return float(effects[0])
    rates = curve[column].to_numpy(dtype="float64")
    weight = (MDE_POWER - rates[upper - 1]) / (rates[upper] - rates[upper - 1])
    return float(effects[upper - 1] + weight * (effects[upper] - effects[upper - 1]))


@dataclass(frozen=True)
class MdeResult:
    """Power curve and MDE at each requested alpha."""

    curve: pd.DataFrame
    mde: dict[float, float]
    unit_se: float
    n: int
    block_rows: int


def simulate_mde_ols(
    y: pd.Series,
    null_design: pd.DataFrame,
    tested: pd.Series,
    gas_days: pd.Series,
    *,
    alphas: tuple[float, ...] = (ALPHA,),
    n_sims: int = 500,
    multiples: tuple[float, ...] = DEFAULT_MULTIPLES,
    seed: int = SEED,
    lags: int = HAC_LAGS,
) -> MdeResult:
    """MDE of one coefficient in a HAC regression, by simulation.

    The residual of ``y`` on ``null_design`` (the model *without* the tested
    term) is block-resampled independently of ``tested``; ``effect * tested``
    is added and the full model re-fitted. The estimate on the real data is
    never computed. Effects are on a grid of multiples of the tested term's
    HAC SE from one null draw.
    """
    frame = pd.concat(
        [
            y.rename("_y"),
            null_design,
            tested.rename("_x"),
            pd.to_datetime(gas_days).rename("_d"),
        ],
        axis=1,
    ).dropna()
    null_x = frame[list(null_design.columns)].to_numpy(dtype="float64")
    residual = (
        sm.OLS(frame["_y"].to_numpy(dtype="float64"), null_x).fit().resid.astype(float)
    )
    x = frame["_x"].to_numpy(dtype="float64")
    full = np.column_stack([null_x, x])
    n_obs = len(frame)
    block_rows = block_length_rows(frame["_d"])
    rng = np.random.default_rng(seed)

    def p_and_se(outcome: np.ndarray) -> tuple[float, float]:
        fit = sm.OLS(outcome, full).fit(cov_type="HAC", cov_kwds={"maxlags": lags})
        return float(np.asarray(fit.pvalues)[-1]), float(np.asarray(fit.bse)[-1])

    def draw() -> np.ndarray:
        resampled: np.ndarray = residual[circular_block_index(n_obs, block_rows, rng)]
        return resampled

    _, unit_se = p_and_se(draw())
    rows = []
    for multiple in multiples:
        effect = multiple * unit_se
        p_values = np.array([p_and_se(draw() + effect * x)[0] for _ in range(n_sims)])
        row: dict[str, float] = {"multiple": multiple, "effect": effect}
        for alpha in alphas:
            row[f"power_{alpha:.4f}"] = float((p_values < alpha).mean())
        rows.append(row)
    curve = pd.DataFrame(rows)
    mde = {alpha: _interpolate_mde(curve, f"power_{alpha:.4f}") for alpha in alphas}
    return MdeResult(
        curve=curve, mde=mde, unit_se=unit_se, n=n_obs, block_rows=block_rows
    )


# --------------------------------------------------------------------------
# H2: median Mincer-Zarnowitz
# --------------------------------------------------------------------------


def _median_fit(actual: np.ndarray, forecast: np.ndarray) -> np.ndarray:
    design = np.column_stack([np.ones_like(forecast), forecast])
    params: np.ndarray = np.asarray(
        QuantReg(actual, design).fit(q=0.5, max_iter=5000).params
    )
    return params


def block_bootstrap_cov(
    actual: np.ndarray,
    forecast: np.ndarray,
    *,
    draws: int = 999,
    block_rows: int = BLOCK_DAYS,
    seed: int = SEED,
) -> np.ndarray:
    """Covariance of (a, b) from a circular moving-block bootstrap of pairs."""
    rng = np.random.default_rng(seed)
    n_obs = len(actual)
    estimates = np.empty((draws, 2))
    for k in range(draws):
        index = circular_block_index(n_obs, block_rows, rng)
        estimates[k] = _median_fit(actual[index], forecast[index])
    cov: np.ndarray = np.cov(estimates, rowvar=False)
    return cov


def joint_wald(params: np.ndarray, cov: np.ndarray) -> tuple[float, float]:
    """Wald test of (a, b) = (0, 1), chi-squared with 2 df."""
    diff = params - np.array([0.0, 1.0])
    statistic = float(diff @ np.linalg.solve(cov, diff))
    return statistic, float(stats.chi2.sf(statistic, df=2))


def median_mz(
    actual: pd.Series,
    forecast: pd.Series,
    *,
    draws: int = 999,
    block_rows: int = BLOCK_DAYS,
    seed: int = SEED,
) -> dict[str, float]:
    """H2: quantile regression (tau = 0.5) of actual on 1, forecast; joint test.

    Rows must be in time order on a (near-)contiguous daily calendar.
    """
    frame = pd.concat([actual.rename("a"), forecast.rename("f")], axis=1).dropna()
    a_values = frame["a"].to_numpy(dtype="float64")
    f_values = frame["f"].to_numpy(dtype="float64")
    params = _median_fit(a_values, f_values)
    cov = block_bootstrap_cov(
        a_values, f_values, draws=draws, block_rows=block_rows, seed=seed
    )
    statistic, p_value = joint_wald(params, cov)
    median_error = float(np.median(f_values - a_values))
    return {
        "a": float(params[0]),
        "b": float(params[1]),
        "a_se": float(np.sqrt(cov[0, 0])),
        "b_se": float(np.sqrt(cov[1, 1])),
        "wald_chi2": statistic,
        "p_value": p_value,
        "median_error_f_minus_a": median_error,
        "n": float(len(frame)),
    }


def simulate_mde_median_mz(
    actual: pd.Series,
    forecast: pd.Series,
    *,
    alphas: tuple[float, ...] = (ALPHA,),
    n_sims: int = 500,
    cov_draws: int = 199,
    multiples: tuple[float, ...] = DEFAULT_MULTIPLES,
    block_rows: int = BLOCK_DAYS,
    seed: int = SEED,
) -> MdeResult:
    """MDE for H2, in mscm/d of median bias.

    Null outcome: ``F + u*``, with ``u*`` the block-resampled residual
    ``A - F`` centred at its median (so the null holds exactly). The effect is
    a shift ``c`` of the median of A. Inside the simulation the joint Wald test
    uses one block-bootstrap covariance computed on a null draw, held fixed
    (a constant shift does not change it); see the MDE decision-log row.
    """
    frame = pd.concat([actual.rename("a"), forecast.rename("f")], axis=1).dropna()
    f_values = frame["f"].to_numpy(dtype="float64")
    residual = frame["a"].to_numpy(dtype="float64") - f_values
    residual = residual - np.median(residual)
    n_obs = len(frame)
    rng = np.random.default_rng(seed)

    def null_draw() -> np.ndarray:
        drawn: np.ndarray = (
            f_values + residual[circular_block_index(n_obs, block_rows, rng)]
        )
        return drawn

    cov = block_bootstrap_cov(
        null_draw(), f_values, draws=cov_draws, block_rows=block_rows, seed=seed + 1
    )
    point = np.array([1.0, float(f_values.mean())])
    unit_se = float(np.sqrt(point @ cov @ point))
    rows = []
    for multiple in multiples:
        effect = multiple * unit_se
        p_values = np.array(
            [
                joint_wald(_median_fit(null_draw() + effect, f_values), cov)[1]
                for _ in range(n_sims)
            ]
        )
        row: dict[str, float] = {"multiple": multiple, "effect": effect}
        for alpha in alphas:
            row[f"power_{alpha:.4f}"] = float((p_values < alpha).mean())
        rows.append(row)
    curve = pd.DataFrame(rows)
    mde = {alpha: _interpolate_mde(curve, f"power_{alpha:.4f}") for alpha in alphas}
    return MdeResult(
        curve=curve, mde=mde, unit_se=unit_se, n=n_obs, block_rows=block_rows
    )


# --------------------------------------------------------------------------
# H3: EKT GMM
# --------------------------------------------------------------------------


def _newey_west(moments: np.ndarray, lags: int) -> np.ndarray:
    n_obs = moments.shape[0]
    centred = moments - moments.mean(axis=0)
    s: np.ndarray = centred.T @ centred / n_obs
    for lag in range(1, lags + 1):
        weight = 1.0 - lag / (lags + 1.0)
        gamma = centred[lag:].T @ centred[:-lag] / n_obs
        s = s + weight * (gamma + gamma.T)
    return s


def ekt_gmm(
    error_ekt: pd.Series,
    instruments: pd.DataFrame,
    *,
    lags: int = HAC_LAGS,
    max_iter: int = 100,
    tol: float = 1e-10,
) -> dict[str, float]:
    """EKT (2005) GMM estimate of the lin-lin asymmetry alpha, p = 1.

    Loss ``L(e) = [alpha + (1 - 2 alpha) 1(e < 0)] |e|`` with ``e = y - f``
    (EKT sign). Moments ``v_t (1(e_t < 0) - alpha)``; ``alpha > 0.5`` means
    under-forecasts are weighted more. ``S`` is Newey-West (decision log
    row 56, item 13); iterated from the identity.

    Returns
    -------
    dict
        ``alpha``, ``se``, ``ci_low``, ``ci_high``, ``j_stat``, ``j_df``,
        ``j_p_value``, ``z_alpha_half`` (test of alpha = 0.5), ``n``.
    """
    frame = pd.concat([error_ekt.rename("_e"), instruments], axis=1).dropna()
    e = frame["_e"].to_numpy(dtype="float64")
    v = frame[list(instruments.columns)].to_numpy(dtype="float64")
    n_obs, d = v.shape
    negative = (e < 0).astype(float)
    v_bar = v.mean(axis=0)
    w_bar = (v * negative[:, None]).mean(axis=0)
    s_inv = np.eye(d)
    alpha = 0.5
    for _ in range(max_iter):
        new_alpha = float((v_bar @ s_inv @ w_bar) / (v_bar @ s_inv @ v_bar))
        moments = v * (negative - new_alpha)[:, None]
        s_inv = np.linalg.inv(_newey_west(moments, lags))
        converged = abs(new_alpha - alpha) < tol
        alpha = new_alpha
        if converged:
            break
    g_bar = w_bar - alpha * v_bar
    j_stat = float(n_obs * g_bar @ s_inv @ g_bar)
    se = float(np.sqrt(1.0 / (n_obs * (v_bar @ s_inv @ v_bar))))
    z = stats.norm.ppf(0.975)
    return {
        "alpha": alpha,
        "se": se,
        "ci_low": alpha - z * se,
        "ci_high": alpha + z * se,
        "j_stat": j_stat,
        "j_df": float(d - 1),
        "j_p_value": float(stats.chi2.sf(j_stat, df=d - 1)),
        "z_alpha_half": (alpha - 0.5) / se,
        "p_alpha_half": float(2 * stats.norm.sf(abs((alpha - 0.5) / se))),
        "n": float(n_obs),
    }


# --------------------------------------------------------------------------
# Multiple testing
# --------------------------------------------------------------------------


def holm(p_values: dict[str, float], alpha: float = ALPHA) -> dict[str, bool]:
    """Holm step-down: reject decisions at family-wise level ``alpha``."""
    ordered = sorted(p_values.items(), key=lambda item: item[1])
    m = len(ordered)
    decisions: dict[str, bool] = {}
    still_rejecting = True
    for rank, (name, p_value) in enumerate(ordered):
        still_rejecting = still_rejecting and p_value <= alpha / (m - rank)
        decisions[name] = still_rejecting
    return decisions


def holm_with_pending(
    p_values: dict[str, float], pending: str, alpha: float = ALPHA
) -> dict[str, str]:
    """Holm decisions that hold whatever the pending test's p-value turns out.

    Each known test gets ``"reject"`` or ``"retain"`` if the decision is the
    same with the pending p-value at 0 and at 1, else ``"depends"``.
    """
    low = holm({**p_values, pending: 0.0}, alpha)
    high = holm({**p_values, pending: 1.0}, alpha)
    out = {}
    for name in p_values:
        if low[name] == high[name]:
            out[name] = "reject" if low[name] else "retain"
        else:
            out[name] = "depends"
    return out
