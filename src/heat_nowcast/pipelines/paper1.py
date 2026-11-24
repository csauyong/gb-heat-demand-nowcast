"""Paper 1 pipeline: panel, baselines, MDEs and the pre-registered estimates.

Pre-registration: ``docs/paper1_preregistration.md`` (frozen at commit
``8770eab``, OSF https://osf.io/zdytk/, decision log row 55). Implementation
choices and deviations: decision log row 56. H4 and its point-in-time
Thomas-Massol-Sevi baseline: decision log row 60.

The stages are separate functions so the runner can write and log the MDEs
**before** any hypothesis coefficient is computed (pre-registration §6):

1. :func:`build_panel` -- one row per gas day, DEV (2021-12-01 -> 2026-08-07).
2. :func:`audit` -- sample counts only.
3. :func:`run_baselines` -- the named baselines (§4).
4. :func:`run_mdes` -- MDEs (§6).
5. :func:`run_estimates` -- H1, H1-orth, H1-tight, H2, H3, H5; Holm.
6. :func:`run_h4_baseline`, :func:`run_h4_mde`, :func:`run_h4` -- H4 (row 60).
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from typing import Final

import numpy as np
import pandas as pd
import statsmodels.api as sm

from heat_nowcast.analysis.paper1_tests import (
    ALPHA,
    BLOCK_DAYS,
    HAC_LAGS,
    SEED,
    MdeResult,
    ekt_gmm,
    hac_ols,
    holm,
    holm_with_pending,
    median_mz,
    simulate_mde_median_mz,
    simulate_mde_ols,
)
from heat_nowcast.data.calendar_uk import load_uk_bank_holidays
from heat_nowcast.data.gas import (
    GAS_HISTORY_START,
    LDZ_CODES,
    load_ldz_demand_actual,
    load_ldz_publication_history,
)
from heat_nowcast.data.lseg_prices import (
    load_gb_power_day_ahead_peak,
    load_nbp_day_ahead,
)
from heat_nowcast.data.nts_market import (
    first_publication,
    load_nts_publication_history,
    load_system_price,
)
from heat_nowcast.features.paper1 import (
    CUTOFF_D_0500,
    CUTOFF_DM1_1310,
    CUTOFF_DM1_1615,
    classify_row_dating,
    cwv_weights_by_gas_year,
    gas_year,
    gated_ldz_values,
    gb_weighted_cwv,
    label_nts_slots,
    latest_known_actual,
    product_rule,
)
from heat_nowcast.features.vintages import latest_known_error
from heat_nowcast.pipelines.c1 import build_c1_inputs

DEV_START: Final[dt.date] = GAS_HISTORY_START
DEV_END: Final[dt.date] = dt.date(2026, 8, 7)
DEVP_START: Final[dt.date] = dt.date(2023, 3, 20)
COLD_THRESHOLD: Final[float] = 4.00
#: Scoring window of the H2/H3 forecast baselines (12-month burn-in, as C1).
BASELINE_SCORE_START: Final[pd.Timestamp] = pd.Timestamp("2022-12-01")
#: Secondary family size (pre-registration §4) and its first Holm threshold.
SECONDARY_SIZE: Final[int] = 6
SECONDARY_ALPHAS: Final[tuple[float, ...]] = (ALPHA / SECONDARY_SIZE, ALPHA)


# --------------------------------------------------------------------------
# 1. Panel
# --------------------------------------------------------------------------


#: Plausible range of GB NTS daily demand, mscm/d (decision log row 57).
NTS_PLAUSIBLE: Final[tuple[float, float]] = (50.0, 600.0)
#: The D+1 actual counts from its scheduled 12:00 D+1 publication (row 57).
D1_EARLIEST: Final[pd.Timedelta] = pd.Timedelta(days=1, hours=12)


def nts_outturn(publications: pd.DataFrame, *, earliest: pd.Timedelta) -> pd.DataFrame:
    """First NTS actual published at or after ``gas_day + earliest``, if plausible.

    Implausible values (outside :data:`NTS_PLAUSIBLE`) become NaN; nothing is
    replaced by a later restatement (decision log row 57).
    """
    eligible = publications.loc[
        publications["generated_at"] >= publications["gas_day"] + earliest
    ]
    frame = first_publication(eligible)[["gas_day", "value", "generated_at"]].copy()
    low, high = NTS_PLAUSIBLE
    frame["value"] = frame["value"].where(frame["value"].between(low, high))
    return frame


def _first_pub_actual(series: str, end: dt.date) -> pd.DataFrame:
    earliest = D1_EARLIEST if series == "demand_actual_d_plus_1" else pd.Timedelta(0)
    return nts_outturn(load_nts_publication_history(series, end=end), earliest=earliest)


def build_panel(end: dt.date = DEV_END) -> pd.DataFrame:
    """One row per DEV gas day with every variable of pre-registration §2."""
    days = pd.DataFrame({"gas_day": pd.date_range(DEV_START, end, freq="D")})

    # LDZ revision panel (C1's vintage panel, GB sums over 13 zones).
    ldz = build_c1_inputs(end=end).gb
    ldz = ldz[["gas_day", "f_dm1_1315", "f_dm1_1615", "f_dp1_0015"]]
    panel = days.merge(ldz, on="gas_day", how="left")
    panel["r_post"] = panel["f_dp1_0015"] - panel["f_dm1_1315"]
    panel["r_late"] = panel["f_dp1_0015"] - panel["f_dm1_1615"]
    panel["r_1315_1615"] = panel["f_dm1_1615"] - panel["f_dm1_1315"]

    # NTS forecast at D-1 13:10 and outturn vintages (first publication).
    nts_end = max(end, dt.date(2026, 11, 9))  # cached window; trimmed below
    nts = label_nts_slots(load_nts_publication_history("demand_forecast", end=nts_end))
    nts_dropped = int(nts.attrs["rows_dropped"])
    nts = nts[["gas_day", "f_dm1_1310", "issued_dm1_1310", "f_dm1_1615"]].rename(
        columns={
            "f_dm1_1310": "fn_1310",
            "issued_dm1_1310": "issued_n_1310",
            "f_dm1_1615": "fn_1615",
        }
    )
    panel = panel.merge(nts, on="gas_day", how="left")
    for series, name in (
        ("demand_actual_d_plus_6", "an_d6"),
        ("demand_actual_d_plus_1", "an_d1"),
    ):
        actual = _first_pub_actual(series, nts_end).rename(
            columns={"value": name, "generated_at": f"{name}_published"}
        )
        panel = panel.merge(actual, on="gas_day", how="left")
    known = latest_known_error(
        panel,
        forecast_column="fn_1310",
        actual_column="an_d1",
        actual_published_column="an_d1_published",
        issue_column="issued_n_1310",
    )
    panel["en_known"] = known["e_known"].to_numpy()
    panel["no_change"] = latest_known_actual(
        panel,
        actual_column="an_d1",
        actual_published_column="an_d1_published",
        issue_column="issued_n_1310",
    ).to_numpy()

    # CWV forecasts, gated, GB-weighted with weights known at the time.
    cwv = load_ldz_publication_history("cwv_forecast_d_minus_1", end=end)
    d6 = load_ldz_demand_actual(end=end, vintage_run="d_plus_6").rename(
        columns={"demand_mscm": "actual"}
    )
    years = sorted(gas_year(days["gas_day"]).unique().tolist())
    weights = cwv_weights_by_gas_year(d6, years, LDZ_CODES)
    equal = weights.assign(weight=1.0 / len(LDZ_CODES))
    for name, offset in (
        ("cwv_1310", CUTOFF_DM1_1310),
        ("cwv_tc", CUTOFF_DM1_1615),
        ("cwv_d0500", CUTOFF_D_0500),
    ):
        gated = gated_ldz_values(cwv, offset)
        panel = panel.merge(
            gb_weighted_cwv(gated, weights).rename(name),
            left_on="gas_day",
            right_index=True,
            how="left",
        )
        if name == "cwv_tc":
            panel = panel.merge(
                gb_weighted_cwv(gated, equal).rename("cwv_tc_unweighted"),
                left_on="gas_day",
                right_index=True,
                how="left",
            )
    panel["dcwv_post"] = panel["cwv_d0500"] - panel["cwv_tc"]
    panel["dcwv_1215_1515"] = panel["cwv_tc"] - panel["cwv_1310"]
    panel["cold"] = (panel["cwv_tc"] <= COLD_THRESHOLD).astype(float)
    panel["cold"] = panel["cold"].where(panel["cwv_tc"].notna())

    # Calendar.
    holidays = load_uk_bank_holidays()
    holidays_ew = holidays.loc[holidays["division"] == "england-and-wales", "date"]
    ew = set(pd.to_datetime(holidays_ew).dt.normalize())
    panel["holiday_ew"] = panel["gas_day"].isin(ew).astype(float)
    panel["month"] = panel["gas_day"].dt.month
    panel["dow"] = panel["gas_day"].dt.dayofweek

    # Prices (DEV-P only; nothing after DEV_END is pulled).
    eex = load_nbp_day_ahead(DEVP_START, end - dt.timedelta(days=1))
    eex = eex.assign(gas_day=eex["trade_date"] + pd.Timedelta(days=1))
    panel = panel.merge(
        eex[["gas_day", "trade_date", "delivery_date", "price_p_kwh"]].rename(
            columns={"price_p_kwh": "p_da"}
        ),
        on="gas_day",
        how="left",
    )
    sap = first_publication(load_system_price("sap_day", start=DEVP_START, end=end))
    panel = panel.merge(
        sap[["gas_day", "value"]].rename(columns={"value": "sap"}),
        on="gas_day",
        how="left",
    )
    in_devp = panel["gas_day"] >= pd.Timestamp(DEVP_START)
    # The row must actually deliver on D = t + 1 (FUT_BASIS; row 59).
    delivers_next_day = panel["delivery_date"] == panel["gas_day"]
    panel["pr"] = (
        product_rule(panel["gas_day"], eex["trade_date"], holidays_ew)
        & in_devp
        & delivers_next_day
    )
    panel["pr_both"] = panel["pr"] & panel["pr"].shift(1, fill_value=False)
    panel["y"] = (panel["sap"] - panel["p_da"]).where(panel["pr"])
    panel["dp_da"] = (panel["p_da"] - panel["p_da"].shift(1)).where(panel["pr_both"])

    # GB day-ahead power peakload for the H4 baseline (row 60). Rows are
    # auction-dated by row 60's weekday rule, so delivery = row date + 1.
    power = load_gb_power_day_ahead_peak(
        DEVP_START - dt.timedelta(days=5), end - dt.timedelta(days=1)
    )
    dating = classify_row_dating(power["row_date"], power["price_gbp_mwh"])
    if dating != "auction":
        msg = f"EPEX row dating is {dating!r}, not 'auction' (row 60): stop"
        raise RuntimeError(msg)
    power = power.assign(gas_day=power["row_date"] + pd.Timedelta(days=1))
    panel = panel.merge(
        power[["gas_day", "price_gbp_mwh"]].rename(
            columns={"price_gbp_mwh": "pe_peak"}
        ),
        on="gas_day",
        how="left",
    )
    panel.attrs["cwv_weights"] = weights.to_dict("records")
    panel.attrs["nts_rows_dropped"] = nts_dropped
    return panel


def month_dummies(gas_days: pd.Series) -> pd.DataFrame:
    """Month-of-year dummies, January as the base."""
    months = pd.to_datetime(gas_days).dt.month
    return pd.DataFrame(
        {f"m{m:02d}": (months == m).astype(float) for m in range(2, 13)},
        index=gas_days.index,
    )


def _with_const(frame: pd.DataFrame) -> pd.DataFrame:
    out: pd.DataFrame = sm.add_constant(frame, has_constant="add")
    return out


# --------------------------------------------------------------------------
# 2. Audit (counts only)
# --------------------------------------------------------------------------


def audit(panel: pd.DataFrame) -> dict[str, float]:
    """Sample counts per test; no outcome statistic."""
    devp = panel.loc[panel["gas_day"] >= pd.Timestamp(DEVP_START)]
    trade = devp["gas_day"] - pd.Timedelta(days=1)
    h1 = devp.loc[devp["pr"]].dropna(subset=["y", "r_post", "dcwv_post"])
    h5 = devp.loc[devp["pr_both"]].dropna(subset=["r_late", "dp_da", "dcwv_post"])
    dev = panel.dropna(subset=["fn_1310", "an_d6"])
    weights = pd.DataFrame(panel.attrs.get("cwv_weights", []))
    out: dict[str, float] = {
        "devp_gas_days": float(len(devp)),
        "devp_trade_mon_thu": float((trade.dt.dayofweek <= 3).sum()),
        "devp_with_eex_row": float(devp["p_da"].notna().sum()),
        "eex_rows_not_delivering_next_day": float(
            (
                devp["delivery_date"].notna()
                & (devp["delivery_date"] != devp["gas_day"])
            ).sum()
        ),
        "devp_with_sap": float(devp["sap"].notna().sum()),
        "product_rule_days": float(devp["pr"].sum()),
        "product_rule_both_days": float(devp["pr_both"].sum()),
        "h1_complete_cases": float(len(h1)),
        "h1_tight_complete_cases": float(len(h1.dropna(subset=["cold"]))),
        "h5_complete_cases": float(len(h5)),
        "h2_complete_cases": float(len(dev)),
        "h3_complete_cases": float(len(dev.dropna(subset=["en_known", "cwv_1310"]))),
        "nts_slot_rows_dropped_all_years": float(
            panel.attrs.get("nts_rows_dropped", np.nan)
        ),
        "cold_share_devp_weighted": float((devp["cwv_tc"] <= COLD_THRESHOLD).mean()),
        "cold_share_devp_unweighted": float(
            (devp["cwv_tc_unweighted"] <= COLD_THRESHOLD).mean()
        ),
        "cold_share_dev_weighted": float((panel["cwv_tc"] <= COLD_THRESHOLD).mean()),
        "cold_share_dev_unweighted": float(
            (panel["cwv_tc_unweighted"] <= COLD_THRESHOLD).mean()
        ),
        "cold_days_in_h1": float(h1["cold"].sum()),
    }
    if not weights.empty:
        out["weights_equal_gas_years"] = float(
            weights.loc[weights["basis_days"] == 0, "gas_year"].nunique()
        )
    return out


# --------------------------------------------------------------------------
# 3. Baselines
# --------------------------------------------------------------------------


def walk_forward_b3_nts(panel: pd.DataFrame) -> pd.Series:
    """B3-NTS: OLS of the D+6 NTS actual on CWV and calendar, refit monthly.

    A training row is admitted only if its D+6 actual was first published
    before the fold's first 13:10 issue (decision log row 56, item 17).
    """
    frame = panel.reset_index(drop=True)
    design = pd.concat(
        [
            frame[["cwv_1310"]],
            (frame["cwv_1310"] ** 2).rename("cwv_1310_sq"),
            pd.get_dummies(frame["dow"], prefix="dow", drop_first=True, dtype=float),
            frame[["holiday_ew"]],
            month_dummies(frame["gas_day"]),
        ],
        axis=1,
    )
    design = _with_const(design)
    forecast = pd.Series(np.nan, index=frame.index)
    months = pd.date_range(BASELINE_SCORE_START, frame["gas_day"].max(), freq="MS")
    for fold_start in months:
        fold_end = fold_start + pd.DateOffset(months=1)
        test = frame.index[
            (frame["gas_day"] >= fold_start) & (frame["gas_day"] < fold_end)
        ]
        first_issue = frame.loc[test, "issued_n_1310"].min()
        if pd.isna(first_issue):
            continue
        train = frame.index[
            (frame["gas_day"] < fold_start) & (frame["an_d6_published"] < first_issue)
        ]
        rows = pd.concat([frame.loc[train, "an_d6"], design.loc[train]], axis=1)
        rows = rows.dropna()
        coef, *_ = np.linalg.lstsq(
            rows.drop(columns="an_d6").to_numpy(dtype=float),
            rows["an_d6"].to_numpy(dtype=float),
            rcond=None,
        )
        x_test = design.loc[test].to_numpy(dtype=float)
        forecast.loc[test] = x_test @ coef
    return forecast


def score(frame: pd.DataFrame, forecasts: dict[str, str], target: str) -> pd.DataFrame:
    """MAE, RMSE, mean and median error (forecast - actual) on identical rows."""
    rows = frame.dropna(subset=[target, *forecasts.values()])
    out = []
    for label, column in forecasts.items():
        error = rows[column] - rows[target]
        out.append(
            {
                "forecast": label,
                "window_start": str(rows["gas_day"].min().date()),
                "window_end": str(rows["gas_day"].max().date()),
                "n_days": len(rows),
                "mae": float(error.abs().mean()),
                "rmse": float(np.sqrt((error**2).mean())),
                "mean_error": float(error.mean()),
                "median_error": float(error.median()),
            }
        )
    return pd.DataFrame(out)


@dataclass
class Baselines:
    """Every named baseline, computed before any hypothesis test."""

    h1_martingale: dict[str, float]
    h1_weather: dict[str, float]
    nts_scores: pd.DataFrame


def run_baselines(panel: pd.DataFrame) -> Baselines:
    """H1 (i) martingale and (ii) weather-news only; H2/H3 forecast baselines."""
    h1 = panel.loc[panel["pr"]].dropna(subset=["y", "r_post", "dcwv_post"])
    martingale = hac_ols(h1["y"], pd.DataFrame({"const": 1.0}, index=h1.index))
    weather = hac_ols(
        h1["y"],
        _with_const(
            pd.concat([h1[["dcwv_post"]], month_dummies(h1["gas_day"])], axis=1)
        ),
    )
    dev = panel.copy()
    dev["b3_nts"] = walk_forward_b3_nts(dev)
    scored = dev.loc[dev["gas_day"] >= BASELINE_SCORE_START]
    nts_scores = score(
        scored,
        {
            "raw NTS D-1 13:10": "fn_1310",
            "no-change (latest published D+1 actual)": "no_change",
            "B3-NTS CWV+calendar walk-forward": "b3_nts",
        },
        "an_d6",
    )
    return Baselines(
        h1_martingale={
            "mean_sap_minus_pda": martingale.params["const"],
            "se_hac": martingale.se["const"],
            "p_value": martingale.p_values["const"],
            "n": float(martingale.n),
            "n_effective": martingale.n_effective,
        },
        h1_weather={
            "gamma_dcwv_post": weather.params["dcwv_post"],
            "se_hac": weather.se["dcwv_post"],
            "p_value": weather.p_values["dcwv_post"],
            "r_squared": weather.r_squared,
            "n": float(weather.n),
        },
        nts_scores=nts_scores,
    )


# --------------------------------------------------------------------------
# 4. MDEs (no hypothesis coefficient is computed here)
# --------------------------------------------------------------------------


def _h1_controls(frame: pd.DataFrame) -> pd.DataFrame:
    return _with_const(
        pd.concat([frame[["dcwv_post"]], month_dummies(frame["gas_day"])], axis=1)
    )


def orthogonalised_r_post(panel: pd.DataFrame) -> pd.Series:
    """H1-orth regressor: R_post net of dCWV_post and month FE, on all DEV-P days."""
    devp = panel.loc[panel["gas_day"] >= pd.Timestamp(DEVP_START)].dropna(
        subset=["r_post", "dcwv_post"]
    )
    fit = sm.OLS(devp["r_post"], _h1_controls(devp)).fit()
    return pd.Series(fit.resid, index=devp.index).reindex(panel.index)


def run_mdes(panel: pd.DataFrame, *, n_sims: int = 500) -> dict[str, MdeResult]:
    """MDE for H1, H1-orth, H1-tight, H5 and H2 (H3 has no unit; H4 held)."""
    panel = panel.assign(r_orth=orthogonalised_r_post(panel))
    h1 = panel.loc[panel["pr"]].dropna(subset=["y", "r_post", "dcwv_post"])
    tight = h1.dropna(subset=["cold"])
    h5 = panel.loc[panel["pr_both"]].dropna(subset=["r_late", "dp_da", "dcwv_post"])
    dev = panel.dropna(subset=["fn_1310", "an_d6"])
    return {
        "H1": simulate_mde_ols(
            h1["y"], _h1_controls(h1), h1["r_post"], h1["gas_day"], n_sims=n_sims
        ),
        "H1-orth": simulate_mde_ols(
            h1["y"],
            _h1_controls(h1),
            h1["r_orth"],
            h1["gas_day"],
            alphas=SECONDARY_ALPHAS,
            n_sims=n_sims,
        ),
        "H1-tight": simulate_mde_ols(
            tight["y"],
            pd.concat([_h1_controls(tight), tight[["r_post"]]], axis=1),
            tight["r_post"] * tight["cold"],
            tight["gas_day"],
            alphas=SECONDARY_ALPHAS,
            n_sims=n_sims,
        ),
        "H5": simulate_mde_ols(
            h5["r_late"],
            _with_const(h5[["dcwv_post"]]),
            h5["dp_da"],
            h5["gas_day"],
            alphas=SECONDARY_ALPHAS,
            n_sims=n_sims,
        ),
        "H2": simulate_mde_median_mz(
            dev["an_d6"], dev["fn_1310"], alphas=SECONDARY_ALPHAS, n_sims=n_sims
        ),
    }


# --------------------------------------------------------------------------
# 5. Estimates
# --------------------------------------------------------------------------


def _coef_row(
    test: str,
    fit_params: dict[str, float],
    fit_se: dict[str, float],
    fit_p: dict[str, float],
    term: str,
    n: int,
    n_eff: float,
) -> dict[str, object]:
    return {
        "test": test,
        "term": term,
        "estimate": fit_params[term],
        "se": fit_se[term],
        "p_value": fit_p[term],
        "n": n,
        "n_effective": n_eff,
    }


def run_estimates(panel: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, object]]:
    """H1 (primary) and the five runnable secondary tests; Holm with H4 pending."""
    panel = panel.assign(r_orth=orthogonalised_r_post(panel))
    h1 = panel.loc[panel["pr"]].dropna(subset=["y", "r_post", "dcwv_post"])
    rows: list[dict[str, object]] = []

    fit = hac_ols(h1["y"], pd.concat([_h1_controls(h1), h1[["r_post"]]], axis=1))
    rows.append(
        _coef_row(
            "H1", fit.params, fit.se, fit.p_values, "r_post", fit.n, fit.n_effective
        )
    )
    rows.append(
        _coef_row(
            "H1", fit.params, fit.se, fit.p_values, "dcwv_post", fit.n, fit.n_effective
        )
    )

    orth = hac_ols(h1["y"], pd.concat([_h1_controls(h1), h1[["r_orth"]]], axis=1))
    rows.append(
        _coef_row(
            "H1-orth",
            orth.params,
            orth.se,
            orth.p_values,
            "r_orth",
            orth.n,
            orth.n_effective,
        )
    )

    tight_rows = h1.dropna(subset=["cold"]).assign(
        r_post_x_cold=lambda f: f["r_post"] * f["cold"]
    )
    tight = hac_ols(
        tight_rows["y"],
        pd.concat(
            [_h1_controls(tight_rows), tight_rows[["r_post", "r_post_x_cold"]]], axis=1
        ),
    )
    rows.append(
        _coef_row(
            "H1-tight",
            tight.params,
            tight.se,
            tight.p_values,
            "r_post_x_cold",
            tight.n,
            tight.n_effective,
        )
    )

    h5_rows = panel.loc[panel["pr_both"]].dropna(
        subset=["r_late", "dp_da", "dcwv_post"]
    )
    h5 = hac_ols(h5_rows["r_late"], _with_const(h5_rows[["dp_da", "dcwv_post"]]))
    rows.append(
        _coef_row("H5", h5.params, h5.se, h5.p_values, "dp_da", h5.n, h5.n_effective)
    )

    dev = panel.dropna(subset=["fn_1310", "an_d6"])
    h2 = median_mz(dev["an_d6"], dev["fn_1310"], block_rows=BLOCK_DAYS, seed=SEED)
    rows.append(
        {
            "test": "H2",
            "term": "a=0,b=1 (joint)",
            "estimate": h2["median_error_f_minus_a"],
            "se": float("nan"),
            "p_value": h2["p_value"],
            "n": int(h2["n"]),
            "n_effective": float("nan"),
        }
    )

    h3_rows = dev.dropna(subset=["en_known", "cwv_1310"])
    h3 = ekt_gmm(
        h3_rows["an_d6"] - h3_rows["fn_1310"],
        _with_const(h3_rows[["en_known", "cwv_1310"]]),
    )
    rows.append(
        {
            "test": "H3",
            "term": "J (rationality given alpha)",
            "estimate": h3["alpha"],
            "se": h3["se"],
            "p_value": h3["j_p_value"],
            "n": int(h3["n"]),
            "n_effective": float("nan"),
        }
    )
    table = pd.DataFrame(rows)

    secondary = {
        str(row["test"]): float(str(row["p_value"]))
        for row in rows
        if row["test"] in {"H1-orth", "H1-tight", "H2", "H3", "H5"}
    }
    holm_decisions = holm_with_pending(secondary, pending="H4")
    table["holm_family_decision"] = table["test"].map(holm_decisions)
    detail: dict[str, object] = {"h2": h2, "h3": h3, "h1_r2": fit.r_squared}
    return table, detail


# --------------------------------------------------------------------------
# 6. Leak check and pre-listed robustness for H1 (never headline)
# --------------------------------------------------------------------------


def h1_robustness(panel: pd.DataFrame) -> pd.DataFrame:
    """Pre-registered robustness checks 6 (winsorised) and 7 (HAC lags 3, 14)."""
    h1 = panel.loc[panel["pr"]].dropna(subset=["y", "r_post", "dcwv_post"])
    design = pd.concat([_h1_controls(h1), h1[["r_post"]]], axis=1)
    rows = []
    low, high = h1["y"].quantile([0.01, 0.99])
    variants = {
        "R6 outcome winsorised 1/99 (DEV-P)": (h1["y"].clip(low, high), 7),
        "R7 HAC lags 3": (h1["y"], 3),
        "R7 HAC lags 14": (h1["y"], 14),
    }
    for label, (outcome, lags) in variants.items():
        fit = hac_ols(outcome, design, lags=lags)
        rows.append(
            {
                "check": label,
                "beta_post": fit.params["r_post"],
                "se": fit.se["r_post"],
                "p_value": fit.p_values["r_post"],
                "n": fit.n,
            }
        )
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# 7. H4 and its point-in-time Thomas-Massol-Sevi baseline (row 60)
# --------------------------------------------------------------------------

#: The day-ahead window closes at D-1 16:30 (portal clock): the TMS issue time.
TMS_ISSUE: Final[pd.Timedelta] = pd.Timedelta(hours=-7, minutes=-30)
#: First scored month after the 12-month burn-in from DEV-P's start.
TMS_SCORE_START: Final[pd.Timestamp] = pd.Timestamp("2024-04-01")
TMS_PRICE_TERMS: Final[tuple[str, ...]] = ("ln_s_lag", "ln_p_lag", "dln_s", "dln_p")
H4_CONTROLS: Final[list[str]] = ["r_1315_1615", "dcwv_1215_1515"]


def tms_frame(panel: pd.DataFrame) -> pd.DataFrame:
    """Variables of B-TMS-PIT (row 60), aligned to the contiguous calendar panel.

    Demand regressors are the NTS D+1 actual of D-2 and D-3, admitted only if
    first published strictly before D-1 16:30; otherwise NaN. Prices are in
    GBP/MWh; a non-positive power price leaves the log spark ratio missing.
    """
    frame = panel.reset_index(drop=True)
    issue = frame["gas_day"] + TMS_ISSUE

    def known_log_q(lag: int) -> pd.Series:
        demand = frame["an_d1"].shift(lag)
        published = frame["an_d1_published"].shift(lag)
        out: pd.Series = np.log(demand.where(published < issue))
        return out

    lq2, lq3 = known_log_q(2), known_log_q(3)
    gas = frame["p_da"] * 10.0  # p/kWh -> GBP/MWh
    power = frame["pe_peak"].where(frame["pe_peak"] > 0)
    ln_p = pd.Series(np.log(gas), index=frame.index)
    ln_s = pd.Series(np.log(power / gas), index=frame.index)
    months = month_dummies(frame["gas_day"])
    out = pd.DataFrame(
        {
            "gas_day": frame["gas_day"],
            "an_d6": frame["an_d6"],
            "an_d6_published": frame["an_d6_published"],
            "issued_tms": issue,
            "fn_1310": frame["fn_1310"],
            "fn_1615": frame["fn_1615"],
            "lq2": lq2,
            "y_tms": np.log(frame["an_d6"]) - lq2,
            "ln_s_lag": ln_s.shift(1),
            "ln_p_lag": ln_p.shift(1),
            "dlq_lag": lq2 - lq3,
            "dln_s": ln_s - ln_s.shift(1),
            "dln_p": ln_p - ln_p.shift(1),
        }
    )
    out = pd.concat([out, months, (months - months.shift(1)).add_prefix("d_")], axis=1)
    out["tms_sample"] = frame["pr_both"].astype(bool)
    out["pe_nonpositive"] = frame["pe_peak"] <= 0
    return out


def tms_columns(frame: pd.DataFrame, *, with_prices: bool) -> list[str]:
    """Regressors of B-TMS-PIT (or its no-price variant), without the constant."""
    months = [c for c in frame.columns if re.fullmatch(r"(d_)?m\d\d", str(c))]
    core = ["lq2", "dlq_lag"]
    prices = list(TMS_PRICE_TERMS) if with_prices else []
    return [*core, *prices, *months]


def walk_forward_tms(frame: pd.DataFrame, *, with_prices: bool) -> pd.Series:
    """Monthly expanding walk-forward forecast of A^N in levels (row 60, 5b).

    A training row is admitted only if its D+6 actual was first published
    before the fold's first D-1 16:30 issue. Forecast = exp(fitted log level).
    """
    design = _with_const(frame[tms_columns(frame, with_prices=with_prices)])
    usable = frame["tms_sample"] & design.notna().all(axis=1)
    forecast = pd.Series(np.nan, index=frame.index)
    for fold_start in pd.date_range(TMS_SCORE_START, frame["gas_day"].max(), freq="MS"):
        fold_end = fold_start + pd.DateOffset(months=1)
        in_fold = (frame["gas_day"] >= fold_start) & (frame["gas_day"] < fold_end)
        test = frame.index[usable & in_fold]
        if len(test) == 0:
            continue
        first_issue = frame.loc[test, "issued_tms"].min()
        train = frame.index[
            usable
            & (frame["gas_day"] < fold_start)
            & (frame["an_d6_published"] < first_issue)
            & frame["y_tms"].notna()
        ]
        coef, *_ = np.linalg.lstsq(
            design.loc[train].to_numpy(dtype=float),
            frame.loc[train, "y_tms"].to_numpy(dtype=float),
            rcond=None,
        )
        fitted = design.loc[test].to_numpy(dtype=float) @ coef
        forecast.loc[test] = np.exp(fitted + frame.loc[test, "lq2"].to_numpy())
    return forecast


def tms_in_sample(frame: pd.DataFrame) -> dict[str, float]:
    """Re-estimate B-TMS-PIT on DEV-P, HAC 7 (row 60, 5a). Not a family test."""
    rows = frame.loc[frame["tms_sample"]]
    design = _with_const(rows[tms_columns(rows, with_prices=True)])
    data = pd.concat([rows["y_tms"], design], axis=1).dropna()
    x = data.drop(columns="y_tms")
    x = x.loc[:, (x != 0).any()]  # month-change dummies never switched on
    fit = sm.OLS(data["y_tms"], x).fit(cov_type="HAC", cov_kwds={"maxlags": HAC_LAGS})
    wald = fit.wald_test(
        ", ".join(f"{term} = 0" for term in TMS_PRICE_TERMS), scalar=True
    )
    cov = fit.cov_params()
    rho = float(fit.params["lq2"])
    out: dict[str, float] = {
        "n": float(fit.nobs),
        "r_squared": float(fit.rsquared),
        "rho": rho,
        "rho_se": float(fit.bse["lq2"]),
        "wald_price_terms_stat": float(wald.statistic),
        "wald_price_terms_p": float(wald.pvalue),
    }
    for term in TMS_PRICE_TERMS:
        out[f"{term}"] = float(fit.params[term])
        out[f"{term}_se"] = float(fit.bse[term])
        out[f"{term}_p"] = float(fit.pvalues[term])
    for term in ("ln_s_lag", "ln_p_lag"):
        theta = float(fit.params[term])
        grad = np.zeros(len(fit.params))
        names = list(fit.params.index)
        grad[names.index(term)] = -1.0 / rho
        grad[names.index("lq2")] = theta / rho**2
        out[f"long_run_{term}"] = -theta / rho
        out[f"long_run_{term}_se"] = float(np.sqrt(grad @ cov.to_numpy() @ grad))
    return out


def diebold_mariano(errors_a: pd.Series, errors_b: pd.Series) -> dict[str, float]:
    """DM test on squared-error loss, HAC 7: d = e_a^2 - e_b^2 (negative = a better)."""
    loss = (errors_a**2 - errors_b**2).rename("d")
    fit = hac_ols(loss, pd.DataFrame({"const": 1.0}, index=loss.index))
    return {
        "mean_loss_diff": fit.params["const"],
        "se_hac": fit.se["const"],
        "p_value": fit.p_values["const"],
        "n": float(fit.n),
    }


def run_h4_baseline(panel: pd.DataFrame) -> dict[str, object]:
    """B-TMS-PIT: in-sample re-estimation and walk-forward comparison (row 60)."""
    frame = tms_frame(panel)
    frame["tms"] = walk_forward_tms(frame, with_prices=True)
    frame["tms_noprice"] = walk_forward_tms(frame, with_prices=False)
    scored = frame.loc[frame["tms_sample"] & (frame["gas_day"] >= TMS_SCORE_START)]
    forecasts = {
        "B-TMS-PIT (16:30)": "tms",
        "B-TMS-PIT-noprice (16:30)": "tms_noprice",
        "raw NTS D-1 13:10": "fn_1310",
        "raw NTS D-1 16:15": "fn_1615",
    }
    scores = score(scored, forecasts, "an_d6")
    common = scored.dropna(subset=["an_d6", *forecasts.values()])
    error = {k: common[k] - common["an_d6"] for k in forecasts.values()}
    dm = {
        "tms_vs_nts_1310": diebold_mariano(error["tms"], error["fn_1310"]),
        "tms_vs_nts_1615": diebold_mariano(error["tms"], error["fn_1615"]),
        "tms_vs_noprice": diebold_mariano(error["tms"], error["tms_noprice"]),
    }
    sample = frame.loc[frame["tms_sample"]]
    counts = {
        "h4_sample_days": float(len(sample)),
        "dropped_pe_nonpositive": float(
            (sample["pe_nonpositive"] | sample["pe_nonpositive"].shift(1)).sum()
        ),
        "dropped_lq2_not_public": float(sample["lq2"].isna().sum()),
        "in_sample_complete": float(
            len(sample.dropna(subset=["y_tms", *tms_columns(sample, with_prices=True)]))
        ),
    }
    return {
        "in_sample": tms_in_sample(frame),
        "scores": scores,
        "diebold_mariano": dm,
        "counts": counts,
    }


def h4_rows(panel: pd.DataFrame) -> pd.DataFrame:
    """H4 estimation rows: D and D-1 pass the product rule; e^N = F - A."""
    rows = panel.loc[panel["pr_both"]].assign(e_n=lambda f: f["fn_1310"] - f["an_d6"])
    return rows.dropna(subset=["e_n", "dp_da", *H4_CONTROLS])


def run_h4_mde(panel: pd.DataFrame, *, n_sims: int = 500) -> MdeResult:
    """MDE for H4 per 1 p/kWh of dP^DA (pre-registration §6), before estimation."""
    rows = h4_rows(panel)
    return simulate_mde_ols(
        rows["e_n"],
        _with_const(rows[H4_CONTROLS]),
        rows["dp_da"],
        rows["gas_day"],
        alphas=SECONDARY_ALPHAS,
        n_sims=n_sims,
    )


def run_h4(
    panel: pd.DataFrame, other_secondary: dict[str, float]
) -> tuple[pd.DataFrame, dict[str, bool]]:
    """Estimate H4 once and settle Holm over the six secondary tests."""
    rows = h4_rows(panel)
    fit = hac_ols(rows["e_n"], _with_const(rows[["dp_da", *H4_CONTROLS]]))
    table = pd.DataFrame(
        [
            _coef_row(
                "H4", fit.params, fit.se, fit.p_values, term, fit.n, fit.n_effective
            )
            for term in ("dp_da", *H4_CONTROLS)
        ]
    )
    family = {**other_secondary, "H4": fit.p_values["dp_da"]}
    if len(family) != SECONDARY_SIZE:
        msg = f"secondary family has {len(family)} tests, expected {SECONDARY_SIZE}"
        raise ValueError(msg)
    return table, holm(family)
