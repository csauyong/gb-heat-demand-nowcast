"""Forecast error metrics and grouped scoring.

Sign convention throughout: ``error = forecast - actual``. A positive bias
therefore means the forecast runs **high**. This is stated because the
opposite convention is equally common and a silent sign flip would invert
every conclusion about whether a forecast over- or under-predicts cold
weather.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from heat_nowcast.evaluation.splits import effective_sample_size


def error_metrics(
    actual: pd.Series,
    forecast: pd.Series,
    *,
    with_effective_n: bool = True,
) -> dict[str, float]:
    """Compute MAE, RMSE, bias and MAPE for one forecast series.

    Parameters
    ----------
    actual, forecast :
        Aligned series. Rows where either is missing are dropped pairwise.
    with_effective_n :
        Also report the autocorrelation-corrected effective sample size. This
        is the number that should be used for any standard error, not ``n``
        (`CLAUDE.md` §3).

    Returns
    -------
    dict
        ``n``, ``mae``, ``rmse``, ``bias``, ``mape_pct`` and, optionally,
        ``n_effective``. All-NaN input yields NaN metrics rather than raising,
        so a season with no data does not abort a whole table.
    """
    frame = pd.DataFrame({"actual": actual.to_numpy(), "forecast": forecast.to_numpy()})
    frame = frame.dropna()
    if len(frame) == 0:
        empty = {
            "n": 0.0,
            "mae": float("nan"),
            "rmse": float("nan"),
            "bias": float("nan"),
            "mape_pct": float("nan"),
        }
        if with_effective_n:
            empty["n_effective"] = 0.0
        return empty

    error = frame["forecast"] - frame["actual"]
    metrics = {
        "n": float(len(frame)),
        "mae": float(error.abs().mean()),
        "rmse": float(np.sqrt((error**2).mean())),
        "bias": float(error.mean()),
        "mape_pct": float(
            (error.abs() / frame["actual"].abs().replace(0.0, np.nan)).mean() * 100.0
        ),
    }
    if with_effective_n:
        metrics["n_effective"] = float(effective_sample_size(error))
    return metrics


def score_by_group(
    frame: pd.DataFrame,
    *,
    actual_column: str,
    forecast_columns: dict[str, str],
    group_columns: list[str] | None = None,
) -> pd.DataFrame:
    """Score several forecasts on identical rows, optionally split by group.

    Both forecasts are scored on exactly the same rows: rows missing *any*
    forecast are dropped for *all* of them. Without that, a forecast with
    patchier coverage would be scored on an easier subset, and the comparison
    would be meaningless (`CLAUDE.md` §4 -- identical data, identical
    windows).

    Parameters
    ----------
    frame :
        Frame containing the actuals, the forecasts and any grouping columns.
    actual_column :
        Column holding the realised value.
    forecast_columns :
        Mapping of display label to column name, e.g.
        ``{"NESO day-ahead": "neso_da_forecast_mw"}``.
    group_columns :
        Columns to break the table out by. ``None`` gives one overall row.

    Returns
    -------
    pandas.DataFrame
        Long results table with the group columns, ``model``, and the metric
        columns from :func:`error_metrics`.
    """
    needed = [actual_column, *forecast_columns.values()]
    complete = frame.dropna(subset=needed).copy()

    def score_block(block: pd.DataFrame) -> pd.DataFrame:
        rows = [
            {"model": label, **error_metrics(block[actual_column], block[column])}
            for label, column in forecast_columns.items()
        ]
        return pd.DataFrame(rows)

    if not group_columns:
        result = score_block(complete)
        result.insert(0, "group", "all")
        return result

    blocks: list[pd.DataFrame] = []
    for keys, block in complete.groupby(group_columns, dropna=False, sort=True):
        scored = score_block(block)
        key_tuple = keys if isinstance(keys, tuple) else (keys,)
        for position, column in enumerate(group_columns):
            scored.insert(position, column, str(key_tuple[position]))
        blocks.append(scored)
    return pd.concat(blocks, ignore_index=True)


def skill_score(
    reference_metric: float,
    candidate_metric: float,
) -> float:
    """Fractional improvement of a candidate over a reference, as a percentage.

    Positive means the candidate is better (lower error). Returns NaN if the
    reference is zero or missing.
    """
    if not np.isfinite(reference_metric) or reference_metric == 0.0:
        return float("nan")
    return float((reference_metric - candidate_metric) / reference_metric * 100.0)


def diebold_mariano(
    error_a: pd.Series,
    error_b: pd.Series,
    *,
    power: int = 2,
    max_lag: int = 48,
) -> dict[str, float]:
    """Diebold-Mariano test of equal predictive accuracy, HAC-corrected.

    Tests the null that two forecasts have equal expected loss. The long-run
    variance of the loss differential is estimated with a Newey-West kernel,
    because the differential of two half-hourly demand forecasts is heavily
    autocorrelated and an i.i.d. variance would produce a wildly overstated
    statistic.

    Parameters
    ----------
    error_a, error_b :
        Forecast errors (``forecast - actual``) for the two models, aligned
        and in time order. A positive statistic means model **a** has the
        larger loss, i.e. model b is better.
    power :
        Loss exponent. 2 for squared error, 1 for absolute error.
    max_lag :
        Newey-West truncation lag. 48 is one day of half-hourly data.

    Returns
    -------
    dict
        ``statistic``, ``p_value`` (two-sided, normal approximation),
        ``mean_loss_differential`` and ``n``.

    Notes
    -----
    With roughly two heating seasons of data the effective sample is small and
    this test has correspondingly low power. A non-rejection here is not
    evidence of equality; the minimum detectable effect should be reported
    alongside it (`docs/research_plan.md`, kill criterion A2).
    """
    from scipy import stats

    paired = pd.DataFrame({"a": error_a.to_numpy(), "b": error_b.to_numpy()}).dropna()
    n_obs = len(paired)
    if n_obs < 10:
        return {
            "statistic": float("nan"),
            "p_value": float("nan"),
            "mean_loss_differential": float("nan"),
            "n": float(n_obs),
        }

    differential = (paired["a"].abs() ** power - paired["b"].abs() ** power).to_numpy(
        dtype="float64"
    )
    mean_differential = float(differential.mean())
    centred = differential - mean_differential

    long_run_variance = float(np.dot(centred, centred) / n_obs)
    truncation = min(max_lag, n_obs - 1)
    for lag in range(1, truncation + 1):
        weight = 1.0 - lag / (truncation + 1.0)
        covariance = float(np.dot(centred[:-lag], centred[lag:]) / n_obs)
        long_run_variance += 2.0 * weight * covariance

    if long_run_variance <= 0.0:
        return {
            "statistic": float("nan"),
            "p_value": float("nan"),
            "mean_loss_differential": mean_differential,
            "n": float(n_obs),
        }

    statistic = mean_differential / np.sqrt(long_run_variance / n_obs)
    p_value = float(2.0 * (1.0 - stats.norm.cdf(abs(statistic))))
    return {
        "statistic": float(statistic),
        "p_value": p_value,
        "mean_loss_differential": mean_differential,
        "n": float(n_obs),
    }
