"""Phase 1b core test: does stock heterogeneity explain the incumbent's error.

The question, stated precisely
------------------------------
Phase 1b's baseline comparison established that National Gas's published D-1
LDZ forecast has a **heat-shaped residual**: its error is 3.8x larger on the
coldest decile of days than the warmest, where the electricity incumbent's was
flat. That says something heat-related is systematically unforecast. It does
**not** say that dwelling-stock heterogeneity is what explains it.

This module asks that. Outcome is the **published forecast error**, not the
offtake level::

    ng_error[ldz, day] ~ a[ldz] + b[day] + beta * (stock_z[ldz] x severity_z[ldz, day]) + e

Why the interaction is the only place the hypothesis lives
----------------------------------------------------------
* **LDZ fixed effects** absorb every time-invariant difference between zones,
  including the *level* of any stock variable. Over a two-year window the
  building stock is effectively constant, so ``stock_z`` alone is collinear
  with the zone effect and carries no information whatsoever.
* **Day fixed effects** absorb everything national on a given day: the weather
  itself, national demand shocks, holidays, the incumbent's own model changes.

So the claim under test is not "zones with older housing use more gas"
(absorbed) nor "cold days are harder to forecast" (absorbed), but "**the
incumbent's error responds differently to cold in zones with different
stock**". Dropping either set of fixed effects answers a weaker question and is
reported as a sensitivity, never as the headline.

Discipline
----------
* The **placebo runs first** -- a randomised per-zone score through the
  identical pipeline, to confirm it returns nothing when nothing is there,
  before any real feature is used and before anyone is invested in a result.
* **One primary feature**, pre-specified: ``mean_sap``. It is the composite of
  fabric and heating efficiency and the closest single summary to what a
  bottom-up stock model would output. The other five features are secondary,
  reported together with a Bonferroni-adjusted threshold, and the count goes in
  the decision log.
* **Inference is the wild cluster bootstrap over 13 clusters.** Conventional
  cluster-robust standard errors are reported alongside but are not the number
  to read -- at 13 clusters they over-reject badly.
* The **MDE is known in advance** (0.0838 mscm/day, 19.1% of the incumbent's
  mean absolute error), so a null here is interpretable rather than merely
  stated.

Scotland
--------
SC is kept in the panel and flagged. It retains its LDZ fixed effect and
contributes to the day fixed effects, but its stock features are null, so it
drops out of the interaction term and the test is identified off the 12 zones
with EPC coverage. This is the recorded decision; the alternative -- imputing
"average" stock for a zone with 478 observed dwellings -- would be a fabrication
sitting directly on the regressor of interest.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import numpy as np
import pandas as pd

from heat_nowcast.analysis.twoway import TwoWayFEResult, fit_two_way_fe

#: Pre-specified primary stock feature. One test, declared before running.
PRIMARY_FEATURE: Final[str] = "mean_sap"

#: Secondary features, reported with a Bonferroni threshold over their count.
SECONDARY_FEATURES: Final[tuple[str, ...]] = (
    "share_solid_wall",
    "share_wall_eff_poor",
    "share_pre_1930",
    "mean_floor_area",
    "share_mains_gas",
)


@dataclass
class InteractionResult:
    """One stock x severity interaction estimate, with its context."""

    feature: str
    role: str
    estimate: float
    cluster_se: float
    t_stat: float
    wild_p_value: float
    n_obs: int
    n_clusters: int
    n_zones_identifying: int
    mde: float
    detectable: bool


def build_interaction_panel(
    panel: pd.DataFrame,
    stock: pd.DataFrame,
    *,
    forecast_column: str = "ng_forecast_mscm",
    outturn_column: str = "demand_mscm_d1",
    severity_source: str = "cwv_forecast",
) -> pd.DataFrame:
    """Join stock features onto the LDZ x gas-day panel and build severity.

    Parameters
    ----------
    panel :
        The Phase 1b LDZ x gas-day panel.
    stock :
        Per-LDZ stock features, standardised, from
        :func:`heat_nowcast.features.stock_ldz.standardise_stock_features`.
    forecast_column, outturn_column :
        Columns forming the outcome, ``forecast - outturn``.
    severity_source :
        Weather column to build cold severity from. **Must be the forecast
        CWV** for any result reported as point-in-time; the outturn CWV is a
        diagnostic only.

    Returns
    -------
    pandas.DataFrame
        Panel with ``ng_error``, ``cold_severity_z`` and one
        ``<feature>_x_severity`` column per standardised stock feature.
    """
    merged = panel.merge(stock, on="ldz", how="left", suffixes=("", "_stock"))
    merged["ng_error"] = merged[forecast_column] - merged[outturn_column]

    # Cold severity: negated CWV so that larger means colder, standardised
    # across the whole panel so the coefficient reads per SD of severity.
    severity = -merged[severity_source].astype("float64")
    merged["cold_severity_z"] = (severity - severity.mean()) / severity.std(ddof=0)

    for feature in (PRIMARY_FEATURE, *SECONDARY_FEATURES):
        column = f"{feature}_z"
        if column not in merged.columns:
            msg = f"standardised stock feature {column!r} missing from stock frame"
            raise ValueError(msg)
        merged[f"{feature}_x_severity"] = merged[column] * merged["cold_severity_z"]
    return merged


def run_interaction_test(
    panel: pd.DataFrame,
    *,
    feature: str,
    role: str,
    mde: float,
    bootstrap_draws: int = 999,
    seed: int = 20260815,
    include_unit_fe: bool = True,
    include_period_fe: bool = True,
) -> tuple[InteractionResult, TwoWayFEResult]:
    """Estimate one stock x severity interaction with two-way FE.

    Rows where the interaction is null -- Scotland, which has no stock
    features -- drop out of the regressor but their zone still contributes to
    the fixed effects through the other columns, which is the intended
    behaviour.
    """
    regressor = f"{feature}_x_severity"
    usable = panel.dropna(subset=["ng_error", regressor, "ldz", "gas_day"])
    fit = fit_two_way_fe(
        usable,
        outcome="ng_error",
        regressors=[regressor],
        unit_column="ldz",
        period_column="gas_day",
        bootstrap_draws=bootstrap_draws,
        seed=seed,
        include_unit_fe=include_unit_fe,
        include_period_fe=include_period_fe,
    )
    result = InteractionResult(
        feature=feature,
        role=role,
        estimate=float(fit.coefficients[0]),
        cluster_se=float(fit.cluster_se[0]),
        t_stat=float(fit.t_stats[0]),
        wild_p_value=float(fit.wild_p_values[0]),
        n_obs=fit.n_obs,
        n_clusters=fit.n_clusters,
        n_zones_identifying=int(usable["ldz"].nunique()),
        mde=mde,
        detectable=bool(abs(float(fit.coefficients[0])) >= mde),
    )
    return result, fit


def run_placebo(
    panel: pd.DataFrame,
    *,
    mde: float,
    replications: int = 200,
    bootstrap_draws: int = 199,
    seed: int = 20260815,
) -> pd.DataFrame:
    """Run the full pipeline on randomised per-zone scores.

    This is run **before** any real stock feature. It answers a question no
    amount of care in the estimator can answer by itself: does this pipeline,
    on this panel, return nothing when there is nothing to find? If the placebo
    rejection rate is materially above the nominal size, every subsequent
    p-value is suspect and the real result should not be believed either way.

    Returns
    -------
    pandas.DataFrame
        One row per replication with the estimate and bootstrap p-value.
    """
    rng = np.random.default_rng(seed)
    zones = sorted(panel["ldz"].dropna().unique())
    records: list[dict[str, float]] = []

    for replication in range(replications):
        scores = rng.normal(size=len(zones))
        scores = (scores - scores.mean()) / scores.std(ddof=0)
        mapping = dict(zip(zones, scores, strict=True))
        trial = panel.copy()
        trial["placebo_x_severity"] = (
            trial["ldz"].map(mapping) * trial["cold_severity_z"]
        )
        usable = trial.dropna(subset=["ng_error", "placebo_x_severity"])
        fit = fit_two_way_fe(
            usable,
            outcome="ng_error",
            regressors=["placebo_x_severity"],
            unit_column="ldz",
            period_column="gas_day",
            bootstrap_draws=bootstrap_draws,
            seed=int(rng.integers(0, 2**31 - 1)),
        )
        records.append(
            {
                "replication": float(replication),
                "estimate": float(fit.coefficients[0]),
                "wild_p_value": float(fit.wild_p_values[0]),
                "abs_estimate_over_mde": abs(float(fit.coefficients[0])) / mde,
            }
        )
    return pd.DataFrame(records)


def bonferroni_threshold(n_secondary: int, alpha: float = 0.05) -> float:
    """Bonferroni-adjusted threshold for the secondary features.

    Crude, and deliberately so: with six correlated stock measures a sharper
    correction would need their dependence structure, and the honest cost of
    looking at six things is easier to defend than an estimated one.
    """
    return alpha / max(n_secondary, 1)
