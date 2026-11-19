"""Phase C1 pipeline: build the vintage panel and run the efficiency tests.

Pre-specified in ``reports/decision_log.md`` rows 43-45. Development sample
2021-12-01 -> 2026-08-07 (row 40). Headline target: the D+6 reconciled actual
(row 43); D+1 first-published actual as sensitivity.

Order of work, as the plan requires: baselines (B1-B3) and the MDE are
computed before the primary estimate; :func:`run_c1` returns them all, and the
runner script writes the MDE before printing any estimate.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Final

import numpy as np
import pandas as pd

from heat_nowcast.analysis.efficiency import (
    cold_regime_test,
    information_test,
    mincer_zarnowitz,
    nordhaus_chain,
    panel_revision_test,
    revision_regression,
    simulate_mde,
    walk_forward_corrected,
)
from heat_nowcast.data.gas import (
    GAS_HISTORY_START,
    LDZ_CODES,
    load_ldz_demand_actual,
    load_ldz_publication_history,
)
from heat_nowcast.evaluation.metrics import diebold_mariano
from heat_nowcast.evaluation.splits import ExpandingWindowSplitter
from heat_nowcast.features.vintages import (
    PRIMARY_SLOT,
    SLOT_ORDER,
    aggregate_gb,
    build_vintage_panel,
    latest_known_error,
)
from heat_nowcast.models.gas_baseline import walk_forward_predict_gas
from heat_nowcast.pipelines.phase1b import EVALUATION_START, run_phase1b

#: Development sample end (decision log row 40).
DEVELOPMENT_END: Final[dt.date] = dt.date(2026, 8, 7)
#: Kill-criterion forecast: 12-month burn-in, scored from here (row 45).
CORRECTED_SCORE_START: Final[pd.Timestamp] = pd.Timestamp("2022-12-01")
#: B3 embargo: D+6 actuals publish on D+6..D+8, so 9 days keeps the last
#: training actual published before the first test issue.
B3_EMBARGO: Final[pd.Timedelta] = pd.Timedelta(days=9)

TARGETS: Final[dict[str, str]] = {"d6": "actual_d6", "d1": "actual_d1"}
HEADLINE_TARGET: Final[str] = "d6"


def gate_cwv_before_issue(
    cwv_history: pd.DataFrame, issue: pd.DataFrame
) -> pd.DataFrame:
    """Latest CWV forecast per (gas day, LDZ) published strictly before ``issue``.

    The CWV forecast is republished through D-1 (08:15, 12:15, 15:15, 23:15).
    The "last on D-1" gate used in Phase 1b picks 23:15, which is *after* the
    16:15 demand forecast being tested; using it as issue-time information
    would leak. Here each row is gated on the demand forecast's own issue time.

    Parameters
    ----------
    cwv_history :
        All CWV forecast publications (``gas_day``, ``ldz``, ``value``,
        ``generated_at``).
    issue :
        ``gas_day``, ``ldz``, ``issue_at`` -- the D-1 16:15 issue time.
    """
    merged = cwv_history.merge(issue, on=["gas_day", "ldz"], how="inner")
    merged = merged.loc[merged["generated_at"] < merged["issue_at"]]
    merged = merged.sort_values(["gas_day", "ldz", "generated_at"])
    latest = merged.drop_duplicates(["gas_day", "ldz"], keep="last")
    return latest.rename(columns={"value": "cwv_fc", "generated_at": "cwv_issued"})[
        ["gas_day", "ldz", "cwv_fc", "cwv_issued"]
    ]


@dataclass
class C1Inputs:
    """The LDZ and GB vintage panels, with audit counts."""

    ldz: pd.DataFrame
    gb: pd.DataFrame
    audit: dict[str, float] = field(default_factory=dict)


def build_c1_inputs(
    *, end: dt.date = DEVELOPMENT_END, vintage: str = "2026-08-14"
) -> C1Inputs:
    """Assemble the LDZ x day vintage panel and its GB daily aggregate."""
    pubs = load_ldz_publication_history(
        "demand_forecast", start=GAS_HISTORY_START, end=end, vintage=vintage
    )
    wide, audit = build_vintage_panel(pubs)

    actual_frames = []
    for run, name in (("d_plus_1", "d1"), ("d_plus_6", "d6")):
        frame = load_ldz_demand_actual(end=end, vintage_run=run, vintage=vintage)
        actual_frames.append(
            frame.rename(
                columns={
                    "demand_mscm": f"actual_{name}",
                    "published_at": f"actual_{name}_published",
                }
            )[["gas_day", "ldz", f"actual_{name}", f"actual_{name}_published"]]
        )
    ldz = wide.merge(actual_frames[0], on=["gas_day", "ldz"], how="left").merge(
        actual_frames[1], on=["gas_day", "ldz"], how="left"
    )

    cwv_history = load_ldz_publication_history(
        "cwv_forecast_d_minus_1", start=GAS_HISTORY_START, end=end, vintage=vintage
    )
    issue = ldz[["gas_day", "ldz", f"issued_{PRIMARY_SLOT}"]].rename(
        columns={f"issued_{PRIMARY_SLOT}": "issue_at"}
    )
    ldz = ldz.merge(
        gate_cwv_before_issue(cwv_history, issue.dropna()),
        on=["gas_day", "ldz"],
        how="left",
    )
    ldz = ldz.loc[ldz["gas_day"] <= pd.Timestamp(end)].reset_index(drop=True)

    slot_cols = [f"f_{slot}" for slot in SLOT_ORDER]
    gb = aggregate_gb(
        ldz,
        sum_columns=[*slot_cols, "actual_d1", "actual_d6"],
        max_columns=[
            f"issued_{PRIMARY_SLOT}",
            "actual_d1_published",
            "actual_d6_published",
            "cwv_issued",
        ],
        mean_columns=["cwv_fc"],
        n_zones=len(LDZ_CODES),
    )
    gb = gb.rename(columns={f"issued_{PRIMARY_SLOT}": "issue_at"})
    gb = gb.set_index("gas_day").asfreq("D").rename_axis("gas_day").reset_index()
    # Day-before CWV forecast, itself gated on its own D-2 16:15 issue: both
    # terms of the difference are public at D-1 16:15.
    gb["d_cwv_fc"] = gb["cwv_fc"] - gb["cwv_fc"].shift(1)
    gb["is_weekend"] = (gb["gas_day"].dt.dayofweek >= 5).astype("float64")
    known = latest_known_error(
        gb,
        forecast_column=f"f_{PRIMARY_SLOT}",
        actual_column="actual_d1",
        actual_published_column="actual_d1_published",
        issue_column="issue_at",
    )
    gb[["e_known", "e_known_lag_days"]] = known.to_numpy()

    audit_out: dict[str, float] = {k: float(v) for k, v in audit.items()}
    audit_out["gb_days"] = float(len(gb))
    audit_out["gb_days_primary_complete"] = float(
        gb[[f"f_{PRIMARY_SLOT}", "f_dm1_1315", "actual_d6"]].notna().all(axis=1).sum()
    )
    audit_out["cwv_issued_after_issue_rows"] = float(
        (ldz["cwv_issued"] >= ldz[f"issued_{PRIMARY_SLOT}"]).sum()
    )
    audit_out["e_known_lag_share_gt2"] = float((gb["e_known_lag_days"] > 2).mean())
    return C1Inputs(ldz=ldz, gb=gb, audit=audit_out)


def b3_cwv_baseline_gb(end: dt.date = DEVELOPMENT_END) -> pd.DataFrame:
    """B3: the Phase 1b CWV+calendar walk-forward, re-targeted to D+6, GB sum.

    Uses the Phase 1b CWV gate (last publication on D-1, in practice 23:15),
    i.e. a weather forecast ~7 hours later than the incumbent's 16:15 issue.
    That favours the baseline, which still has to be disclosed.
    """
    result = run_phase1b(end=end, include_national_hdd=False)
    panel = result.panel.copy()
    splitter = ExpandingWindowSplitter(
        initial_train_end=pd.Timestamp(EVALUATION_START, tz="UTC") - B3_EMBARGO,
        test_span=pd.DateOffset(months=1),
        embargo=B3_EMBARGO,
    )
    panel["b3"], _ = walk_forward_predict_gas(
        panel,
        splitter,
        target_column="demand_mscm_d6",
        fit_weather_column="cwv_forecast",
        predict_weather_column="cwv_forecast",
    )
    gb = aggregate_gb(panel, sum_columns=["b3"], n_zones=len(LDZ_CODES))
    holidays = panel[["gas_day", "is_holiday_any"]]
    return gb.merge(
        holidays.groupby("gas_day", as_index=False)["is_holiday_any"].max(),
        on="gas_day",
        how="left",
    )


def score_gb(
    gb: pd.DataFrame, columns: dict[str, str], target: str, start: pd.Timestamp
) -> pd.DataFrame:
    """MAE, RMSE, bias, MAPE on identical GB rows for each named forecast."""
    rows = gb.loc[gb["gas_day"] >= start].dropna(subset=[target, *columns.values()])
    out = []
    for label, column in columns.items():
        error = rows[column] - rows[target]
        out.append(
            {
                "model": label,
                "target": target,
                "window_start": str(rows["gas_day"].min().date()),
                "window_end": str(rows["gas_day"].max().date()),
                "n_days": len(rows),
                "mae": float(error.abs().mean()),
                "rmse": float(np.sqrt((error**2).mean())),
                "bias": float(error.mean()),
                "mape_pct": float((error.abs() / rows[target]).mean() * 100.0),
            }
        )
    return pd.DataFrame(out)


@dataclass
class C1Result:
    """Every C1 table, in the order they were computed."""

    inputs: C1Inputs
    baselines: pd.DataFrame
    mde_curve: pd.DataFrame
    mde: float
    primary: dict[str, dict[str, float]]
    secondary: pd.DataFrame
    nordhaus_pairs: pd.DataFrame
    corrected_folds: pd.DataFrame
    kill_forecast: pd.DataFrame


def run_c1(*, n_sims: int = 500, seed: int = 20261117) -> C1Result:
    """Run C1 end to end: baselines, MDE, primary, secondary, kill forecast."""
    inputs = build_c1_inputs()
    gb = inputs.gb
    b3 = b3_cwv_baseline_gb()
    gb = gb.merge(b3[["gas_day", "b3", "is_holiday_any"]], on="gas_day", how="left")
    gb = gb.rename(columns={"is_holiday_any": "is_holiday"})
    gb["is_holiday"] = gb["is_holiday"].astype("float64")
    inputs.gb = gb

    # --- 1. kill-criterion forecast (needed for the baseline table) -------
    corrected: dict[str, pd.Series] = {}
    folds: list[pd.DataFrame] = []
    for name, target in TARGETS.items():
        fit = walk_forward_corrected(
            gb,
            target,
            target_published=f"{target}_published",
            issue_column="issue_at",
            score_start=CORRECTED_SCORE_START,
        )
        corrected[name] = fit.forecast
        folds.append(fit.folds.assign(target=name))
        gb[f"f_star_{name}"] = fit.forecast.to_numpy()

    # --- 2. baselines, on identical rows ---------------------------------
    baselines = []
    for name, target in TARGETS.items():
        baselines.append(
            score_gb(
                gb,
                {
                    "B1 raw incumbent D-1 16:15": f"f_{PRIMARY_SLOT}",
                    "B3 CWV+calendar walk-forward": "b3",
                    "f* corrected (kill criterion)": f"f_star_{name}",
                },
                target,
                pd.Timestamp(EVALUATION_START),
            ).assign(target_vintage=name)
        )
    baseline_table = pd.concat(baselines, ignore_index=True)

    # --- 3. MDE before any estimate --------------------------------------
    curve, mde = simulate_mde(gb, TARGETS[HEADLINE_TARGET], n_sims=n_sims, seed=seed)

    # --- 4. primary (headline D+6) and its D+1 sensitivity ----------------
    primary = {
        name: revision_regression(gb, target) for name, target in TARGETS.items()
    }

    # --- 5. secondary, headline target only -------------------------------
    target = TARGETS[HEADLINE_TARGET]
    secondary_rows: list[dict[str, object]] = []
    for index, slot in enumerate(SLOT_ORDER, start=1):
        mz = mincer_zarnowitz(gb, slot, target)
        secondary_rows.append(
            {
                "test": f"S{index} Mincer-Zarnowitz {slot}",
                "p_value": mz["p_value"],
                "estimate": mz["b"],
                "detail": f"a={mz['a']:.3f}, b={mz['b']:.4f}, "
                f"chi2={mz['wald_chi2']:.2f}, n={mz['n']:.0f}",
            }
        )
    chain, pairs = nordhaus_chain(gb, target)
    secondary_rows.append(
        {
            "test": "S9 Nordhaus revision chain",
            "p_value": chain["p_value"],
            "estimate": chain["slope"],
            "detail": f"se_day={chain['se_cluster_day']:.4f}, "
            f"rows={chain['n_rows']:.0f}",
        }
    )
    info = information_test(gb, target)
    secondary_rows.append(
        {
            "test": "S10 issue-time information (joint)",
            "p_value": info["p_value"],
            "estimate": info["wald_chi2"],
            "detail": ", ".join(
                f"{k.removeprefix('coef_')}={v:.4f}"
                for k, v in info.items()
                if k.startswith("coef_")
            )
            + f", n={info['n']:.0f}",
        }
    )
    cold = cold_regime_test(gb, target)
    secondary_rows.append(
        {
            "test": "S11 cold regime mean error",
            "p_value": cold["p_value"],
            "estimate": cold["mean_error_cold"],
            "detail": f"se={cold['se_cold']:.3f}, "
            f"cwv<={cold['cwv_threshold']:.2f}, n={cold['n_cold_days']:.0f}, "
            f"mean actual={cold['mean_actual_cold']:.1f}",
        }
    )
    panel = panel_revision_test(inputs.ldz, target)
    secondary_rows.append(
        {
            "test": "S12 panel primary, Driscoll-Kraay",
            "p_value": panel["p_value"],
            "estimate": panel["beta"],
            "detail": f"se={panel['se_driscoll_kraay']:.4f}, n={panel['n']:.0f}",
        }
    )
    secondary = pd.DataFrame(secondary_rows)
    secondary["bonferroni_alpha"] = 0.05 / len(secondary)
    secondary["reject"] = secondary["p_value"] < secondary["bonferroni_alpha"]

    # --- 6. kill-criterion comparison: f* vs raw, DM on absolute loss -----
    kill_rows = []
    for name, target in TARGETS.items():
        rows = gb.loc[gb["gas_day"] >= CORRECTED_SCORE_START].dropna(
            subset=[target, f"f_{PRIMARY_SLOT}", f"f_star_{name}"]
        )
        raw_error = rows[f"f_{PRIMARY_SLOT}"] - rows[target]
        new_error = rows[f"f_star_{name}"] - rows[target]
        dm = diebold_mariano(raw_error, new_error, power=1, max_lag=7)
        kill_rows.append(
            {
                "target_vintage": name,
                "window_start": str(rows["gas_day"].min().date()),
                "window_end": str(rows["gas_day"].max().date()),
                "n_days": len(rows),
                "mae_raw": float(raw_error.abs().mean()),
                "mae_corrected": float(new_error.abs().mean()),
                "dm_statistic": dm["statistic"],
                "dm_p_value": dm["p_value"],
            }
        )

    return C1Result(
        inputs=inputs,
        baselines=baseline_table,
        mde_curve=curve,
        mde=mde,
        primary=primary,
        secondary=secondary,
        nordhaus_pairs=pairs,
        corrected_folds=pd.concat(folds, ignore_index=True),
        kill_forecast=pd.DataFrame(kill_rows),
    )
