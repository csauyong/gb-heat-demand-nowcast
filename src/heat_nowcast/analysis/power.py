"""Minimum detectable effect for the Phase 1b core test, by simulation.

Why this module exists
----------------------
Phase 1 reported a null (NESO's error was uncorrelated with HDD) without a
minimum detectable effect, and flagged that as a limitation of its own
write-up. An underpowered null is not evidence of absence, and a null reported
without an MDE is uninterpretable: the reader cannot tell whether the effect is
absent or merely invisible at this sample size.

So the MDE is computed **first**, on the real panel, and reported **above** the
estimates. If the MDE turns out to be larger than any effect the bottom-up
hypothesis would plausibly produce, then the core test cannot answer the
question and that is the finding -- no amount of estimation fixes it.

Method
------
The simulation reuses the actual data rather than a parametric fiction:

1. Take the real LDZ x day panel of published National Gas forecast errors.
2. Within-transform it (LDZ and day fixed effects), giving the residual the
   core test would actually work with -- real variance, real within-LDZ
   autocorrelation, real cross-sectional imbalance.
3. Construct the interaction regressor exactly as the core test would:
   a time-invariant, standardised per-LDZ stock score crossed with a
   day-varying weather-severity measure. The stock score is *simulated*
   (standard normal across the 13 zones, fixed within zone), because the real
   one needs EPC data; standardising it means the resulting MDE is expressed
   **per standard deviation of the stock variable**, which is the scale-free
   form and does not depend on which stock metric is eventually used.
4. For a grid of true effect sizes, add ``beta * interaction`` to a resampled
   residual, re-estimate with two-way FE, and test with the wild cluster
   bootstrap over 13 clusters.
5. Report the smallest ``beta`` reaching the target power.

Residuals are resampled **by cluster** (whole LDZ time series at a time), which
preserves within-zone serial correlation. Resampling row-by-row would destroy
it and would understate the MDE -- flattering the design in exactly the
direction that matters.

Units
-----
The MDE is reported three ways: in mscm/day (the native unit), in MW-equivalent
(comparable with the Phase 1 electricity figures), and as a share of the mean
absolute published forecast error (the honest relative scale -- an effect
smaller than a few percent of the incumbent's own error is not going to support
anything downstream).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

import numpy as np
import pandas as pd

from heat_nowcast.analysis.twoway import demean_two_way, fit_two_way_fe
from heat_nowcast.data.gas import MSCM_PER_DAY_TO_MW

DEFAULT_TARGET_POWER: Final[float] = 0.80
DEFAULT_ALPHA: Final[float] = 0.05


@dataclass
class PowerResult:
    """Simulation-based power curve and the resulting MDE.

    Attributes
    ----------
    effect_grid :
        True effect sizes tested, in mscm/day per SD of the stock score per
        unit of weather severity.
    power :
        Estimated power at each grid point.
    mde :
        Smallest effect reaching ``target_power``; NaN if the grid never does.
    mde_mw_equivalent :
        ``mde`` converted to average MW, for comparability with Phase 1.
    mde_share_of_mean_abs_error :
        ``mde`` as a fraction of the mean absolute published forecast error.
    """

    effect_grid: np.ndarray
    power: np.ndarray
    mde: float
    mde_mw_equivalent: float
    mde_share_of_mean_abs_error: float
    target_power: float
    alpha: float
    n_obs: int
    n_clusters: int
    n_periods: int
    residual_sd: float
    mean_abs_error: float
    interaction_sd: float
    simulations: int
    bootstrap_draws: int
    seed: int
    detail: dict[str, object] = field(default_factory=dict)


def build_interaction(
    panel: pd.DataFrame,
    *,
    unit_column: str,
    severity_column: str,
    seed: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Build a simulated, standardised stock x severity interaction.

    Returns
    -------
    interaction : numpy.ndarray
        The regressor of interest.
    stock_score : numpy.ndarray
        The per-row stock score, kept so callers can confirm it is genuinely
        time-invariant within an LDZ.

    Notes
    -----
    The stock score is standard normal **across the 13 zones** and constant
    within a zone -- which is what a real stock metric looks like over a
    two-year window, and is precisely why an LDZ fixed effect absorbs its level
    and only the interaction is identified.
    """
    rng = np.random.default_rng(seed)
    units = pd.factorize(panel[unit_column], sort=True)[0]
    n_units = int(units.max()) + 1

    per_unit = rng.normal(size=n_units)
    per_unit = (per_unit - per_unit.mean()) / per_unit.std(ddof=0)
    stock_score = per_unit[units]

    severity = panel[severity_column].to_numpy(dtype="float64")
    severity = (severity - np.nanmean(severity)) / np.nanstd(severity)

    return stock_score * severity, stock_score


def simulate_mde(
    panel: pd.DataFrame,
    *,
    outcome: str,
    unit_column: str,
    period_column: str,
    severity_column: str,
    effect_grid: np.ndarray | None = None,
    simulations: int = 200,
    bootstrap_draws: int = 199,
    target_power: float = DEFAULT_TARGET_POWER,
    alpha: float = DEFAULT_ALPHA,
    seed: int = 20260815,
) -> PowerResult:
    """Estimate the MDE for the stock x severity interaction on the real panel.

    Parameters
    ----------
    panel :
        The real LDZ x gas-day panel.
    outcome :
        The published forecast error column.
    unit_column, period_column, severity_column :
        LDZ, gas day, and the weather-severity measure to interact with.
    effect_grid :
        True effect sizes to test, in mscm/day. Defaults to a grid spanning
        0 to 0.5 SD of the within-transformed residual.
    simulations :
        Simulation replications per grid point.
    bootstrap_draws :
        Wild cluster bootstrap draws inside each simulation. Kept modest
        because the outer loop already dominates; the p-value only needs to be
        accurate near ``alpha``.
    target_power :
        Power the MDE is defined at.
    alpha :
        Test size.
    seed :
        Explicit seed.

    Returns
    -------
    PowerResult
    """
    working = panel.dropna(
        subset=[outcome, unit_column, period_column, severity_column]
    ).reset_index(drop=True)

    units = pd.factorize(working[unit_column], sort=True)[0]
    periods = pd.factorize(working[period_column], sort=True)[0]

    interaction, stock_score = build_interaction(
        working, unit_column=unit_column, severity_column=severity_column, seed=seed
    )
    working = working.assign(_interaction=interaction, _stock=stock_score)

    residual = demean_two_way(
        working[outcome].to_numpy(dtype="float64"), units, periods
    )
    residual_sd = float(residual.std(ddof=1))
    mean_abs_error = float(np.abs(working[outcome].to_numpy()).mean())
    interaction_sd = float(np.std(interaction))

    if effect_grid is None:
        effect_grid = residual_sd * np.array(
            [0.0, 0.005, 0.01, 0.02, 0.03, 0.05, 0.075, 0.10, 0.15, 0.20, 0.30, 0.50]
        )

    rng = np.random.default_rng(seed + 1)
    n_clusters = int(units.max()) + 1
    cluster_rows = [np.flatnonzero(units == c) for c in range(n_clusters)]

    power = np.zeros(len(effect_grid))
    for grid_position, effect in enumerate(effect_grid):
        rejections = 0
        for _replication in range(simulations):
            # Resample residuals by whole cluster, preserving within-LDZ serial
            # correlation. Row-wise resampling would destroy it and understate
            # the MDE.
            chosen = rng.integers(0, n_clusters, size=n_clusters)
            synthetic = np.empty_like(residual)
            for target_cluster, source_cluster in enumerate(chosen):
                target_rows = cluster_rows[target_cluster]
                source_rows = cluster_rows[source_cluster]
                if len(source_rows) >= len(target_rows):
                    synthetic[target_rows] = residual[source_rows[: len(target_rows)]]
                else:
                    reps = int(np.ceil(len(target_rows) / len(source_rows)))
                    tiled = np.tile(residual[source_rows], reps)
                    synthetic[target_rows] = tiled[: len(target_rows)]

            simulated = synthetic + effect * interaction
            trial = working.assign(_y=simulated)
            result = fit_two_way_fe(
                trial,
                outcome="_y",
                regressors=["_interaction"],
                unit_column=unit_column,
                period_column=period_column,
                bootstrap_draws=bootstrap_draws,
                seed=int(rng.integers(0, 2**31 - 1)),
            )
            if (
                np.isfinite(result.wild_p_values[0])
                and result.wild_p_values[0] <= alpha
            ):
                rejections += 1
        power[grid_position] = rejections / simulations

    reached = np.flatnonzero(power >= target_power)
    mde = float(effect_grid[reached[0]]) if len(reached) else float("nan")

    return PowerResult(
        effect_grid=effect_grid,
        power=power,
        mde=mde,
        mde_mw_equivalent=mde * MSCM_PER_DAY_TO_MW,
        mde_share_of_mean_abs_error=(
            mde / mean_abs_error if mean_abs_error else float("nan")
        ),
        target_power=target_power,
        alpha=alpha,
        n_obs=len(working),
        n_clusters=n_clusters,
        n_periods=len(np.unique(periods)),
        residual_sd=residual_sd,
        mean_abs_error=mean_abs_error,
        interaction_sd=interaction_sd,
        simulations=simulations,
        bootstrap_draws=bootstrap_draws,
        seed=seed,
        detail={
            "size_at_zero_effect": float(power[0]) if effect_grid[0] == 0 else None,
            "residual_sd_units": "mscm/day",
        },
    )
