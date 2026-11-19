"""Phase C1: weak-efficiency tests of National Gas's republished LDZ forecast.

Every test here is pre-specified in ``reports/decision_log.md`` rows 44-45,
written before any of them was computed. Sign convention as everywhere in
this repo: ``error = forecast - actual``, so a positive error is an
over-forecast, and ``revision = f_k - f_{k-1}``.

Weak efficiency (Nordhaus 1987; Mincer & Zarnowitz 1969) says a forecast's
error should be unpredictable from anything known when it was issued --
including its own latest revision. The primary test regresses the error of
the last D-1 vintage on the D-1 13:15 -> 16:15 revision: a slope of zero is
efficiency, a positive slope means revisions overshoot, a negative slope means
they are too timid.

Inference is HAC (Newey-West) on the contiguous daily GB series, because
daily gas-forecast errors are serially correlated and an i.i.d. standard
error would overstate every statistic (`CLAUDE.md` §3).
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
from typing import Final

import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.regression.linear_model import RegressionResultsWrapper

from heat_nowcast.evaluation.splits import effective_sample_size
from heat_nowcast.features.vintages import PRIMARY_SLOT, SLOT_ORDER

HAC_LAGS: Final[int] = 7
BLOCK_DAYS: Final[int] = 14
MDE_POWER: Final[float] = 0.80
ALPHA: Final[float] = 0.05


def _hac_fit(
    y: pd.Series, design: pd.DataFrame, lags: int = HAC_LAGS
) -> RegressionResultsWrapper:
    """OLS with Newey-West HAC covariance. Rows with any NaN are dropped."""
    frame = pd.concat([y.rename("_y"), design], axis=1).dropna()
    return sm.OLS(frame["_y"], frame.drop(columns="_y")).fit(
        cov_type="HAC", cov_kwds={"maxlags": lags}
    )


def _wald(
    fit: RegressionResultsWrapper, restrictions: np.ndarray, q: np.ndarray
) -> tuple[float, float]:
    """Chi-squared Wald statistic and p-value using the fit's own covariance."""
    test = fit.wald_test((restrictions, q), use_f=False, scalar=True)
    return float(test.statistic), float(test.pvalue)


def errors_and_revisions(daily: pd.DataFrame, target: str) -> pd.DataFrame:
    """Attach ``e_<slot>`` for every slot and ``r_<slot>`` for slots 2..8."""
    frame = daily.copy()
    for slot in SLOT_ORDER:
        frame[f"e_{slot}"] = frame[f"f_{slot}"] - frame[target]
    for previous, current in pairwise(SLOT_ORDER):
        frame[f"r_{current}"] = frame[f"f_{current}"] - frame[f"f_{previous}"]
    return frame


# --------------------------------------------------------------------------
# Primary test
# --------------------------------------------------------------------------


def revision_regression(
    daily: pd.DataFrame, target: str, *, lags: int = HAC_LAGS
) -> dict[str, float]:
    """Primary C1 test: ``e_{D-1 16:15} ~ 1 + r_{D-1 13:15 -> 16:15}``, HAC.

    Returns slope, HAC SE, two-sided p, intercept, ``n`` (gas days),
    ``n_effective`` (autocorrelation-corrected, from the residuals) and the
    standard deviation of the revision, so the slope can be read in mscm.
    """
    frame = errors_and_revisions(daily, target)
    revision = frame[f"r_{PRIMARY_SLOT}"]
    design = sm.add_constant(revision.rename("revision"))
    fit = _hac_fit(frame[f"e_{PRIMARY_SLOT}"], design, lags)
    return {
        "beta": float(fit.params["revision"]),
        "se": float(fit.bse["revision"]),
        "t": float(fit.tvalues["revision"]),
        "p_value": float(fit.pvalues["revision"]),
        "intercept": float(fit.params["const"]),
        "intercept_se": float(fit.bse["const"]),
        "n": float(fit.nobs),
        "n_effective": effective_sample_size(pd.Series(fit.resid), max_lag=30),
        "sd_revision": float(revision.dropna().std()),
        "share_zero_revision": float((revision.dropna().abs() < 1e-9).mean()),
    }


def simulate_mde(
    daily: pd.DataFrame,
    target: str,
    *,
    n_sims: int = 500,
    block_days: int = BLOCK_DAYS,
    multiples: tuple[float, ...] = (0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0),
    seed: int = 20261117,
    lags: int = HAC_LAGS,
) -> tuple[pd.DataFrame, float]:
    """Minimum detectable slope for the primary test, by simulation.

    The real GB error series is resampled with a circular block bootstrap
    (``block_days`` blocks) *independently of* the real revision series, so any
    true relation between them is destroyed while the error's own
    autocorrelation and distribution are kept. A known slope ``beta * r`` is
    added and the primary regression re-run. The estimate on the real data is
    never used.

    The grid is expressed in multiples of the HAC standard error from one null
    draw, so it scales itself without looking at the estimate.

    Returns
    -------
    curve : pandas.DataFrame
        ``beta``, ``multiple``, ``rejection_rate``. The ``beta = 0`` row is the
        empirical size of the test.
    mde : float
        Smallest ``|beta|`` with rejection rate >= 80%, linearly interpolated
        on the grid; NaN if the grid never reaches it.
    """
    frame = errors_and_revisions(daily, target)
    paired = frame[[f"e_{PRIMARY_SLOT}", f"r_{PRIMARY_SLOT}"]].dropna()
    error = paired.iloc[:, 0].to_numpy(dtype="float64")
    revision = paired.iloc[:, 1].to_numpy(dtype="float64")
    n_obs = len(error)
    design = sm.add_constant(revision)
    rng = np.random.default_rng(seed)

    def draw() -> np.ndarray:
        n_blocks = int(np.ceil(n_obs / block_days))
        starts = rng.integers(0, n_obs, n_blocks)
        index = (starts[:, None] + np.arange(block_days)[None, :]).ravel() % n_obs
        resampled: np.ndarray = error[index[:n_obs]]
        return resampled

    def slope_p(outcome: np.ndarray) -> tuple[float, float]:
        fit = sm.OLS(outcome, design).fit(cov_type="HAC", cov_kwds={"maxlags": lags})
        return float(np.asarray(fit.bse)[1]), float(np.asarray(fit.pvalues)[1])

    se0, _ = slope_p(draw())
    rows = []
    for multiple in multiples:
        beta = multiple * se0
        rejections = sum(
            slope_p(draw() + beta * revision)[1] < ALPHA for _ in range(n_sims)
        )
        rows.append(
            {"multiple": multiple, "beta": beta, "rejection_rate": rejections / n_sims}
        )
    curve = pd.DataFrame(rows)

    mde = float("nan")
    above = curve.index[curve["rejection_rate"] >= MDE_POWER]
    if len(above) > 0:
        upper = int(above[0])
        if upper == 0:
            mde = float(curve["beta"].iloc[0])
        else:
            rates = curve["rejection_rate"].to_numpy(dtype="float64")
            betas = curve["beta"].to_numpy(dtype="float64")
            weight = (MDE_POWER - rates[upper - 1]) / (rates[upper] - rates[upper - 1])
            mde = float(betas[upper - 1] + weight * (betas[upper] - betas[upper - 1]))
    return curve, mde


# --------------------------------------------------------------------------
# Secondary tests
# --------------------------------------------------------------------------


def mincer_zarnowitz(
    daily: pd.DataFrame, slot: str, target: str, *, lags: int = HAC_LAGS
) -> dict[str, float]:
    """Fit ``A ~ a + b * f_slot`` and Wald-test ``a = 0, b = 1`` jointly (HAC)."""
    design = sm.add_constant(daily[f"f_{slot}"].rename("forecast"))
    fit = _hac_fit(daily[target], design, lags)
    statistic, p_value = _wald(fit, np.eye(2), np.array([0.0, 1.0]))
    return {
        "a": float(fit.params["const"]),
        "b": float(fit.params["forecast"]),
        "b_se": float(fit.bse["forecast"]),
        "wald_chi2": statistic,
        "p_value": p_value,
        "n": float(fit.nobs),
    }


def nordhaus_chain(
    daily: pd.DataFrame, target: str
) -> tuple[dict[str, float], pd.DataFrame]:
    """Do within-day revisions predict the next revision? (S9).

    Stacks the six pairs ``(r_k, r_{k-1})`` for k = D 00:15 ... D+1 00:15 and
    fits ``r_k ~ 1 + r_{k-1}`` with errors clustered by gas day (the six pairs
    of one day share news). The per-pair table is descriptive and also carries
    baseline B2's loss: the mean absolute revision, which is the MAE of
    predicting every next revision to be zero.
    """
    frame = errors_and_revisions(daily, target)
    pairs = list(pairwise(SLOT_ORDER[1:]))
    stacked = []
    table = []
    for previous, current in pairs:
        block = pd.DataFrame(
            {
                "gas_day": frame["gas_day"],
                "r_now": frame[f"r_{current}"],
                "r_prev": frame[f"r_{previous}"],
            }
        ).dropna()
        stacked.append(block)
        fit = _hac_fit(block["r_now"], sm.add_constant(block["r_prev"]))
        table.append(
            {
                "pair": f"{previous}->{current}",
                "slope": float(fit.params["r_prev"]),
                "slope_se_hac": float(fit.bse["r_prev"]),
                "p_value": float(fit.pvalues["r_prev"]),
                "b2_mae_zero_revision": float(block["r_now"].abs().mean()),
                "n": float(fit.nobs),
            }
        )
    long = pd.concat(stacked, ignore_index=True)
    groups = pd.factorize(long["gas_day"])[0]
    fit = sm.OLS(long["r_now"], sm.add_constant(long["r_prev"])).fit(
        cov_type="cluster", cov_kwds={"groups": groups}
    )
    summary = {
        "slope": float(fit.params["r_prev"]),
        "se_cluster_day": float(fit.bse["r_prev"]),
        "p_value": float(fit.pvalues["r_prev"]),
        "n_rows": float(fit.nobs),
        "n_days": float(long["gas_day"].nunique()),
    }
    return summary, pd.DataFrame(table)


INFORMATION_REGRESSORS: Final[tuple[str, ...]] = (
    "cwv_fc",
    "d_cwv_fc",
    "is_weekend",
    "is_holiday",
    "e_known",
)


def information_test(
    daily: pd.DataFrame, target: str, *, lags: int = HAC_LAGS
) -> dict[str, float]:
    """Is the D-1 16:15 error predictable from issue-time information? (S10).

    ``daily`` must carry :data:`INFORMATION_REGRESSORS`, each knowable at the
    D-1 16:15 issue (built by the C1 pipeline; ``e_known`` is gated by
    :func:`heat_nowcast.features.vintages.latest_known_error`). Joint HAC Wald
    test that every slope is zero.
    """
    frame = errors_and_revisions(daily, target)
    design = sm.add_constant(
        frame[list(INFORMATION_REGRESSORS)].astype("float64"), has_constant="add"
    )
    fit = _hac_fit(frame[f"e_{PRIMARY_SLOT}"], design, lags)
    k = len(INFORMATION_REGRESSORS)
    restrictions = np.hstack([np.zeros((k, 1)), np.eye(k)])
    statistic, p_value = _wald(fit, restrictions, np.zeros(k))
    result: dict[str, float] = {
        "wald_chi2": statistic,
        "df": float(k),
        "p_value": p_value,
        "n": float(fit.nobs),
    }
    for name in INFORMATION_REGRESSORS:
        result[f"coef_{name}"] = float(fit.params[name])
        result[f"p_{name}"] = float(fit.pvalues[name])
    return result


def cold_regime_test(
    daily: pd.DataFrame,
    target: str,
    *,
    cwv_column: str = "cwv_fc",
    quantile: float = 0.10,
    lags: int = HAC_LAGS,
) -> dict[str, float]:
    """Mean D-1 16:15 error on the coldest forecast-CWV decile of days (S11).

    Fitted as ``e ~ 1[cold] + 1[not cold]`` (no constant) over the contiguous
    series, so the cold-day mean carries a HAC SE that respects serial
    correlation with neighbouring days. Threshold: the ``quantile`` of
    forecast CWV over the whole sample passed in (the development sample).
    """
    frame = errors_and_revisions(daily, target)
    threshold = float(frame[cwv_column].quantile(quantile))
    cold = (frame[cwv_column] <= threshold).astype("float64")
    cold = cold.where(frame[cwv_column].notna())
    design = pd.DataFrame({"cold": cold, "not_cold": 1.0 - cold})
    fit = _hac_fit(frame[f"e_{PRIMARY_SLOT}"], design, lags)
    mean_level = float(frame.loc[cold == 1.0, target].mean())
    return {
        "cwv_threshold": threshold,
        "mean_error_cold": float(fit.params["cold"]),
        "se_cold": float(fit.bse["cold"]),
        "p_value": float(fit.pvalues["cold"]),
        "mean_error_not_cold": float(fit.params["not_cold"]),
        "mean_actual_cold": mean_level,
        "n_cold_days": float((cold == 1.0).sum()),
    }


def panel_revision_test(
    ldz_frame: pd.DataFrame, target: str, *, lags: int = HAC_LAGS
) -> dict[str, float]:
    """Panel version of the primary test, LDZ x day, Driscoll-Kraay SE (S12).

    ``e_{ldz,D} ~ LDZ FE + beta * r_{ldz,D}``. Driscoll-Kraay (statsmodels
    ``hac-groupsum`` over gas days) allows arbitrary correlation across the 13
    zones on a day -- they share weather and one forecaster -- and serial
    correlation across days. Clustering by LDZ alone would not.
    """
    frame = errors_and_revisions(ldz_frame, target)
    frame = frame.dropna(subset=[f"e_{PRIMARY_SLOT}", f"r_{PRIMARY_SLOT}"])
    frame = frame.sort_values(["gas_day", "ldz"]).reset_index(drop=True)
    dummies = pd.get_dummies(frame["ldz"], prefix="ldz", dtype="float64")
    revision = frame[f"r_{PRIMARY_SLOT}"].rename("revision")
    design = pd.concat([revision, dummies], axis=1)
    time = pd.factorize(frame["gas_day"], sort=True)[0]
    fit = sm.OLS(frame[f"e_{PRIMARY_SLOT}"], design).fit(
        cov_type="hac-groupsum", cov_kwds={"time": time, "maxlags": lags}
    )
    return {
        "beta": float(fit.params["revision"]),
        "se_driscoll_kraay": float(fit.bse["revision"]),
        "p_value": float(fit.pvalues["revision"]),
        "n": float(fit.nobs),
        "n_days": float(frame["gas_day"].nunique()),
    }


# --------------------------------------------------------------------------
# Kill-criterion forecast
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class CorrectedForecast:
    """Walk-forward bias/revision-corrected forecast and its audit trail."""

    forecast: pd.Series
    folds: pd.DataFrame


def walk_forward_corrected(
    daily: pd.DataFrame,
    target: str,
    *,
    target_published: str,
    issue_column: str,
    score_start: pd.Timestamp,
    min_train_days: int = 180,
) -> CorrectedForecast:
    """``f* = f_{D-1 16:15} - (a + b * r)``, refit monthly on an expanding window.

    ``(a, b)`` come from OLS of the D-1 16:15 error on the D-1 revision. A
    training row is admitted only if its target actual was **published before
    the first issue time of the fold** -- a per-row gate rather than a fixed
    embargo, because D+6 actuals sometimes publish on D+7 or D+8 and a few were
    republished months later.

    Returns
    -------
    CorrectedForecast
        ``forecast`` aligned to ``daily`` (NaN before ``score_start``), and one
        audit row per fold.
    """
    frame = errors_and_revisions(daily, target).reset_index(drop=True)
    error_col, revision_col = f"e_{PRIMARY_SLOT}", f"r_{PRIMARY_SLOT}"
    corrected = pd.Series(np.nan, index=frame.index)
    records = []
    months = pd.date_range(
        score_start, frame["gas_day"].max(), freq="MS", inclusive="both"
    )
    if len(months) == 0 or months[0] != score_start:
        months = pd.DatetimeIndex([score_start, *months])
    for fold_start in months:
        fold_end = fold_start + pd.DateOffset(months=1)
        test = frame.index[
            (frame["gas_day"] >= fold_start) & (frame["gas_day"] < fold_end)
        ]
        if len(test) == 0:
            continue
        issue_times = frame.loc[test, issue_column].dropna()
        if issue_times.empty:
            continue
        first_issue = issue_times.min()
        train = frame.loc[
            (frame["gas_day"] < fold_start) & (frame[target_published] < first_issue)
        ].dropna(subset=[error_col, revision_col])
        if len(train) < min_train_days:
            continue
        fit = sm.OLS(train[error_col], sm.add_constant(train[revision_col])).fit()
        a, b = float(fit.params["const"]), float(fit.params[revision_col])
        rows = frame.loc[test]
        corrected.loc[test] = rows[f"f_{PRIMARY_SLOT}"] - (a + b * rows[revision_col])
        records.append(
            {
                "fold_start": fold_start,
                "first_issue": first_issue,
                "n_train": len(train),
                "last_train_day": train["gas_day"].max(),
                "a": a,
                "b": b,
            }
        )
    return CorrectedForecast(forecast=corrected, folds=pd.DataFrame(records))


def bonferroni_alpha(n_tests: int, alpha: float = ALPHA) -> float:
    """Per-test threshold for ``n_tests`` secondary tests."""
    return alpha / n_tests
