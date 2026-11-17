"""Phase C0: test whether the incumbent's cold-weather error gradient is scale.

Why this exists
---------------
Phase 1b reported National Gas's D-1 LDZ forecast as "3.8x less accurate on
the coldest decile" (``reports/decision_log.md`` row 23). That compares mean
absolute errors in mscm/day, and offtake on a cold day is several times offtake
on a warm day, so an error that is a constant *percentage* of demand would
produce the same gradient. This module re-describes the same residuals by
decile of forecast CWV in four ways (row 41):

(a) MAE, mscm/day;
(b) MAPE, % of the actual;
(c) MAE divided by the mean walk-forward baseline prediction in the decile --
    a scale that does not divide by the outcome itself;
(d) signed mean error (``forecast - actual``) with a Newey-West HAC interval.

Nothing here is a new forecast. The inputs are residuals already scored in
Phase 1b, and the deciles are cut on **forecast** CWV, which was knowable at
issue time. It is descriptive and does not touch the confirmation samples.
"""

from __future__ import annotations

from typing import Final

import numpy as np
import pandas as pd
import statsmodels.api as sm

#: Newey-West truncation lag for daily series of ~1,000 gas days
#: (floor(4 * (T/100)^(2/9)) = 6 at T = 978; rounded up to a week).
HAC_LAGS: Final[int] = 7
N_DECILES: Final[int] = 10

ACTUAL: Final[str] = "demand_mscm_d1"
FORECAST: Final[str] = "ng_forecast_mscm"
BASELINE: Final[str] = "gas_baseline_cwv"
CWV: Final[str] = "cwv_forecast"


def gb_daily_aggregate(panel: pd.DataFrame) -> pd.DataFrame:
    """Sum the LDZ panel to one GB row per gas day.

    Only gas days with all zones present are kept, so a missing zone cannot
    masquerade as a warm day. The CWV is the unweighted mean across zones, the
    same definition row 23 used, so the deciles are comparable with it.

    Parameters
    ----------
    panel :
        LDZ x gas-day frame with ``gas_day``, ``ldz``, the actual, the
        incumbent forecast, the baseline prediction and forecast CWV.

    Returns
    -------
    pandas.DataFrame
        One row per gas day, sorted by ``gas_day``.
    """
    needed = ["gas_day", "ldz", ACTUAL, FORECAST, BASELINE, CWV]
    complete = panel[needed].dropna()
    n_zones = complete["ldz"].nunique()
    daily = complete.groupby("gas_day", as_index=False).agg(
        **{
            ACTUAL: (ACTUAL, "sum"),
            FORECAST: (FORECAST, "sum"),
            BASELINE: (BASELINE, "sum"),
            CWV: (CWV, "mean"),
            "n_zones": ("ldz", "size"),
        }
    )
    daily = daily.loc[daily["n_zones"] == n_zones].drop(columns="n_zones")
    return daily.sort_values("gas_day").reset_index(drop=True)


def assign_cwv_decile(cwv: pd.Series, n_bins: int = N_DECILES) -> pd.Series:
    """Label each row with its CWV decile, 1 = coldest (lowest CWV).

    CWV (composite weather variable) falls as weather gets colder, so decile 1
    is the cold tail.
    """
    labels = pd.qcut(cwv, q=n_bins, labels=False, duplicates="raise")
    return (labels + 1).astype(int)


def hac_mean_by_group(
    error: pd.Series,
    group: pd.Series,
    *,
    lags: int = HAC_LAGS,
) -> pd.DataFrame:
    """Mean of ``error`` within each group, with Newey-West HAC standard errors.

    Fits ``error ~ sum_g 1[group = g]`` with no constant over the series in its
    original (time) order, so each coefficient is a group mean and the HAC
    covariance accounts for serial correlation across neighbouring days,
    including days that fall in different groups.

    Parameters
    ----------
    error, group :
        Aligned series, already sorted by time.
    lags :
        Newey-West truncation lag.

    Returns
    -------
    pandas.DataFrame
        Indexed by group with ``mean_error``, ``hac_se``, ``ci_low``,
        ``ci_high`` (95%).
    """
    dummies = pd.get_dummies(group, prefix="g", dtype=float)
    fit = sm.OLS(error.to_numpy(dtype=float), dummies.to_numpy()).fit(
        cov_type="HAC", cov_kwds={"maxlags": lags}
    )
    params = np.asarray(fit.params, dtype=float)
    se = np.asarray(fit.bse, dtype=float)
    keys = [int(column.removeprefix("g_")) for column in dummies.columns]
    return pd.DataFrame(
        {
            "mean_error": params,
            "hac_se": se,
            "ci_low": params - 1.96 * se,
            "ci_high": params + 1.96 * se,
        },
        index=pd.Index(keys, name="cwv_decile"),
    )


def decile_table(series: pd.DataFrame, *, lags: int = HAC_LAGS) -> pd.DataFrame:
    """Score one daily series (GB or one LDZ) by forecast-CWV decile.

    Parameters
    ----------
    series :
        One row per gas day with the actual, incumbent forecast, baseline
        prediction and forecast CWV.
    lags :
        Newey-West truncation lag for the signed-error interval.

    Returns
    -------
    pandas.DataFrame
        One row per decile: CWV range, ``n_days``, mean actual, (a) ``mae``,
        (b) ``mape_pct``, (c) ``mae_scaled_pct`` and (d) ``mean_error`` with
        its HAC interval.
    """
    frame = series.sort_values("gas_day").reset_index(drop=True).copy()
    frame["cwv_decile"] = assign_cwv_decile(frame[CWV])
    error = frame[FORECAST] - frame[ACTUAL]
    frame["abs_error"] = error.abs()
    frame["ape_pct"] = frame["abs_error"] / frame[ACTUAL] * 100.0

    table = frame.groupby("cwv_decile").agg(
        cwv_min=(CWV, "min"),
        cwv_max=(CWV, "max"),
        n_days=(ACTUAL, "size"),
        mean_actual=(ACTUAL, "mean"),
        mean_baseline=(BASELINE, "mean"),
        mae=("abs_error", "mean"),
        mape_pct=("ape_pct", "mean"),
    )
    table["mae_scaled_pct"] = table["mae"] / table["mean_baseline"] * 100.0
    table = table.join(hac_mean_by_group(error, frame["cwv_decile"], lags=lags))
    return table.reset_index()


def scale_check(panel: pd.DataFrame, *, lags: int = HAC_LAGS) -> pd.DataFrame:
    """Run C0 at GB-aggregate level and for every LDZ.

    Returns
    -------
    pandas.DataFrame
        Long table with a ``level`` column (``"GB"`` or the LDZ code) followed
        by the :func:`decile_table` columns.
    """
    blocks = [decile_table(gb_daily_aggregate(panel), lags=lags).assign(level="GB")]
    needed = ["gas_day", ACTUAL, FORECAST, BASELINE, CWV]
    for ldz, zone in panel.groupby("ldz", sort=True):
        zone_series = zone[needed].dropna()
        blocks.append(decile_table(zone_series, lags=lags).assign(level=str(ldz)))
    table = pd.concat(blocks, ignore_index=True)
    return table[["level", *[c for c in table.columns if c != "level"]]]


def row23_reconciliation(panel: pd.DataFrame) -> dict[str, float]:
    """Recompute the Phase 1b "3.8x" figure exactly as row 23 defined it.

    Row 23 averaged the incumbent's error **across zones** per gas day (so
    zone errors of opposite sign cancel) and cut deciles on the zone-mean CWV.
    This reproduces that number and sets it beside the same ratio on two
    scale-free measures, so the correction note can say how much of the
    gradient survives.
    """
    needed = ["gas_day", ACTUAL, FORECAST, CWV]
    complete = panel[needed].dropna()
    daily = (
        complete.assign(error=complete[FORECAST] - complete[ACTUAL])
        .groupby("gas_day", as_index=False)
        .agg(error=("error", "mean"), cwv=(CWV, "mean"), actual=(ACTUAL, "mean"))
    )
    cold = daily.loc[daily["cwv"] <= daily["cwv"].quantile(0.10)]
    warm = daily.loc[daily["cwv"] >= daily["cwv"].quantile(0.90)]
    cold_mae = float(cold["error"].abs().mean())
    warm_mae = float(warm["error"].abs().mean())
    cold_rel = float((cold["error"].abs() / cold["actual"]).mean() * 100.0)
    warm_rel = float((warm["error"].abs() / warm["actual"]).mean() * 100.0)
    return {
        "n_days": float(len(daily)),
        "coldest_decile_mae_mscm": cold_mae,
        "warmest_decile_mae_mscm": warm_mae,
        "mae_ratio_cold_over_warm": cold_mae / warm_mae,
        "coldest_decile_mape_pct": cold_rel,
        "warmest_decile_mape_pct": warm_rel,
        "mape_ratio_cold_over_warm": cold_rel / warm_rel,
        "mean_offtake_ratio_cold_over_warm": float(
            cold["actual"].mean() / warm["actual"].mean()
        ),
    }
