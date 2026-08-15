"""Two-way fixed effects with wild cluster bootstrap inference.

The estimator the Phase 1b core test needs, separated from the test itself so
it can be exercised on simulated panels (for power) and on the real one (for
estimates) with identical code.

Why two-way fixed effects, specifically
---------------------------------------
The regression of interest is::

    ng_forecast_error[ldz, day] ~ a[ldz] + b[day] + beta * (stock[ldz] x severity[day]) + e

* **LDZ fixed effects** absorb *all* time-invariant differences between zones:
  size, baseline stock composition, network characteristics, the incumbent's
  per-zone calibration. Over a 2-3 year window the building stock is
  essentially time-invariant, so the *level* of any stock variable is
  collinear with the LDZ effect and carries no information.
* **Day fixed effects** absorb everything common to the whole country on a
  given day: national weather, national demand shocks, the incumbent's
  national model revisions, holidays, supply events.

What survives both is the **interaction**. That is the only place the
hypothesis lives: the claim is not "zones with older housing use more gas"
(absorbed by LDZ effects) nor "cold days are harder to forecast" (absorbed by
day effects), but "the incumbent's error responds *differently* to cold in
zones with different stock". Anything less than both sets of fixed effects
answers a weaker question and must be reported as a sensitivity, never as the
headline.

Why wild cluster bootstrap
--------------------------
Errors are correlated within an LDZ over time, so inference must cluster by
LDZ. But there are **13 clusters**. Cluster-robust asymptotics assume the
number of clusters grows; at 13 the standard errors are biased down and
t-tests over-reject badly -- a null can be rejected at nominal 5% with true
size well above 15%. The wild cluster restricted bootstrap (Cameron, Gelbach
and Miller) is the standard remedy and is what this module uses. Rademacher
weights give 2^13 = 8,192 distinct draws, comfortably more than the bootstrap
replications used.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import numpy as np
import pandas as pd

DEFAULT_BOOTSTRAP_DRAWS: Final[int] = 999


@dataclass(frozen=True)
class TwoWayFEResult:
    """Estimate and inference for one two-way fixed effects regression.

    Attributes
    ----------
    coefficients :
        Point estimates for the regressors of interest, in input order.
    names :
        Regressor names.
    cluster_se :
        Conventional cluster-robust standard errors. **Reported for
        comparison only** -- with 13 clusters they are not reliable, and the
        bootstrap p-value is the one to read.
    t_stats :
        Coefficient divided by ``cluster_se``.
    wild_p_values :
        Wild cluster restricted bootstrap p-values, one per regressor.
    n_obs, n_clusters, n_units, n_periods :
        Panel dimensions actually used.
    residual_sd :
        Standard deviation of the within-transformed residual.
    """

    coefficients: np.ndarray
    names: list[str]
    cluster_se: np.ndarray
    t_stats: np.ndarray
    wild_p_values: np.ndarray
    n_obs: int
    n_clusters: int
    n_units: int
    n_periods: int
    residual_sd: float


def demean_two_way(
    values: np.ndarray,
    unit_index: np.ndarray,
    period_index: np.ndarray,
    *,
    tolerance: float = 1e-10,
    max_iterations: int = 200,
) -> np.ndarray:
    """Remove unit and period means by alternating projections.

    Equivalent to including a full set of unit and period dummies, but without
    building the dummy matrix. Iterated because with an unbalanced panel the
    two projections do not commute; on a balanced panel it converges in one
    pass.

    Parameters
    ----------
    values :
        Column vector or matrix; each column is demeaned independently.
    unit_index, period_index :
        Integer codes identifying the unit (LDZ) and period (day) of each row.
    tolerance :
        Convergence threshold on the maximum absolute change.
    max_iterations :
        Safety cap.

    Returns
    -------
    numpy.ndarray
        The within-transformed values, same shape as ``values``.
    """
    matrix = np.asarray(values, dtype="float64")
    single_column = matrix.ndim == 1
    if single_column:
        matrix = matrix.reshape(-1, 1)
    result = matrix.copy()

    n_units = int(unit_index.max()) + 1
    n_periods = int(period_index.max()) + 1
    unit_counts = np.bincount(unit_index, minlength=n_units).astype("float64")
    period_counts = np.bincount(period_index, minlength=n_periods).astype("float64")

    for _ in range(max_iterations):
        previous = result.copy()
        for column in range(result.shape[1]):
            unit_sums = np.bincount(
                unit_index, weights=result[:, column], minlength=n_units
            )
            result[:, column] -= (unit_sums / unit_counts)[unit_index]
            period_sums = np.bincount(
                period_index, weights=result[:, column], minlength=n_periods
            )
            result[:, column] -= (period_sums / period_counts)[period_index]
        if np.max(np.abs(result - previous)) < tolerance:
            break

    return result.ravel() if single_column else result


def _cluster_robust_vcov(
    design: np.ndarray,
    residuals: np.ndarray,
    cluster_index: np.ndarray,
    xtx_inv: np.ndarray,
) -> np.ndarray:
    """Cluster-robust sandwich variance, clustering on ``cluster_index``."""
    n_clusters = int(cluster_index.max()) + 1
    meat = np.zeros((design.shape[1], design.shape[1]))
    for cluster in range(n_clusters):
        mask = cluster_index == cluster
        if not mask.any():
            continue
        score = design[mask].T @ residuals[mask]
        meat += np.outer(score, score)
    sandwich: np.ndarray = xtx_inv @ meat @ xtx_inv
    return sandwich


def fit_two_way_fe(
    frame: pd.DataFrame,
    *,
    outcome: str,
    regressors: list[str],
    unit_column: str,
    period_column: str,
    bootstrap_draws: int = DEFAULT_BOOTSTRAP_DRAWS,
    seed: int = 20260815,
    include_unit_fe: bool = True,
    include_period_fe: bool = True,
) -> TwoWayFEResult:
    """Fit a two-way fixed effects regression with wild cluster bootstrap p-values.

    Parameters
    ----------
    frame :
        Panel with one row per (unit, period).
    outcome :
        Dependent variable. For the Phase 1b core test this is the **published
        forecast error**, not the demand level.
    regressors :
        Regressors of interest -- the stock x weather-severity interactions.
    unit_column, period_column :
        Columns identifying the LDZ and the gas day.
    bootstrap_draws :
        Wild cluster bootstrap replications.
    seed :
        Explicit seed; every stochastic routine in this repo takes one.
    include_unit_fe, include_period_fe :
        Both default ``True`` and both should stay that way for the headline.
        They exist so a sensitivity that drops one can be produced *and
        labelled* -- dropping either answers a weaker question (see the module
        docstring).

    Returns
    -------
    TwoWayFEResult
    """
    working = frame.dropna(subset=[outcome, *regressors, unit_column, period_column])
    if len(working) == 0:
        msg = "no complete rows for the requested regression"
        raise ValueError(msg)

    unit_index = pd.factorize(working[unit_column], sort=True)[0]
    period_index = pd.factorize(working[period_column], sort=True)[0]

    outcome_values = working[outcome].to_numpy(dtype="float64")
    design = working[regressors].to_numpy(dtype="float64")

    if include_unit_fe or include_period_fe:
        # When only one set is wanted, project on that one alone by pointing
        # the other index at a single group.
        unit_for_demean = unit_index if include_unit_fe else np.zeros_like(unit_index)
        period_for_demean = (
            period_index if include_period_fe else np.zeros_like(period_index)
        )
        outcome_values = demean_two_way(
            outcome_values, unit_for_demean, period_for_demean
        )
        design = demean_two_way(design, unit_for_demean, period_for_demean)

    xtx = design.T @ design
    xtx_inv = np.linalg.pinv(xtx)
    coefficients = xtx_inv @ (design.T @ outcome_values)
    residuals = outcome_values - design @ coefficients

    cluster_index = unit_index
    n_clusters = int(cluster_index.max()) + 1
    vcov = _cluster_robust_vcov(design, residuals, cluster_index, xtx_inv)
    # Small-sample correction, as in Stata's default.
    n_obs, n_params = design.shape
    correction = (n_clusters / (n_clusters - 1.0)) * (
        (n_obs - 1.0) / max(n_obs - n_params, 1)
    )
    vcov *= correction
    cluster_se = np.sqrt(np.maximum(np.diag(vcov), 0.0))
    t_stats = np.divide(
        coefficients,
        cluster_se,
        out=np.full_like(coefficients, np.nan),
        where=cluster_se > 0,
    )

    wild_p_values = _wild_cluster_bootstrap(
        design=design,
        outcome=outcome_values,
        cluster_index=cluster_index,
        xtx_inv=xtx_inv,
        observed_t=t_stats,
        draws=bootstrap_draws,
        seed=seed,
    )

    return TwoWayFEResult(
        coefficients=coefficients,
        names=list(regressors),
        cluster_se=cluster_se,
        t_stats=t_stats,
        wild_p_values=wild_p_values,
        n_obs=int(n_obs),
        n_clusters=n_clusters,
        n_units=len(np.unique(unit_index)),
        n_periods=len(np.unique(period_index)),
        residual_sd=float(residuals.std(ddof=1)),
    )


def _wild_cluster_bootstrap(
    *,
    design: np.ndarray,
    outcome: np.ndarray,
    cluster_index: np.ndarray,
    xtx_inv: np.ndarray,
    observed_t: np.ndarray,
    draws: int,
    seed: int,
) -> np.ndarray:
    """Wild cluster **restricted** bootstrap p-values, one per regressor.

    For each regressor in turn the null is imposed -- the model is re-estimated
    with that regressor excluded -- and the restricted residuals are perturbed
    by cluster-level Rademacher weights. The bootstrap t-distribution is then
    compared against the observed t. Imposing the null is what makes the
    procedure accurate with few clusters; the unrestricted version is markedly
    worse at 13.
    """
    rng = np.random.default_rng(seed)
    n_regressors = design.shape[1]
    n_clusters = int(cluster_index.max()) + 1
    p_values = np.full(n_regressors, np.nan)

    # Per-cluster blocks, reused across every draw. Nothing about a Rademacher
    # flip touches the data itself -- only the sign in front of each cluster's
    # score -- so the whole bootstrap reduces to k-dimensional algebra on
    # precomputed blocks. Mathematically identical to rebuilding the synthetic
    # outcome each draw, and fast enough to sit inside a power simulation.
    cluster_rows = [np.flatnonzero(cluster_index == c) for c in range(n_clusters)]
    xtx_blocks = np.stack([design[rows].T @ design[rows] for rows in cluster_rows])

    for target in range(n_regressors):
        keep = [j for j in range(n_regressors) if j != target]
        if keep:
            restricted_design = design[:, keep]
            restricted_xtx_inv = np.linalg.pinv(restricted_design.T @ restricted_design)
            restricted_beta = restricted_xtx_inv @ (restricted_design.T @ outcome)
            restricted_fit = restricted_design @ restricted_beta
        else:
            restricted_fit = np.zeros_like(outcome)
        restricted_residuals = outcome - restricted_fit

        fit_scores = np.stack(
            [design[rows].T @ restricted_fit[rows] for rows in cluster_rows]
        )
        residual_scores = np.stack(
            [design[rows].T @ restricted_residuals[rows] for rows in cluster_rows]
        )
        base_xty = fit_scores.sum(axis=0)

        weights = rng.choice(np.array([-1.0, 1.0]), size=(draws, n_clusters))
        bootstrap_t = np.full(draws, np.nan)
        for draw in range(draws):
            weight = weights[draw]
            xty_star = base_xty + weight @ residual_scores
            beta_star = xtx_inv @ xty_star
            scores = (
                fit_scores + weight[:, None] * residual_scores - xtx_blocks @ beta_star
            )
            meat = scores.T @ scores
            vcov_star = xtx_inv @ meat @ xtx_inv
            variance = vcov_star[target, target]
            if variance > 0:
                bootstrap_t[draw] = beta_star[target] / np.sqrt(variance)

        finite = bootstrap_t[np.isfinite(bootstrap_t)]
        if len(finite) == 0 or not np.isfinite(observed_t[target]):
            continue
        exceedances = int(np.sum(np.abs(finite) >= abs(observed_t[target])))
        p_values[target] = (exceedances + 1.0) / (len(finite) + 1.0)

    return p_values
