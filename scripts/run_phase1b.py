"""Run the Phase 1b gas comparison and the core-test power analysis.

Usage::

    python scripts/run_phase1b.py

Analysis logic lives in ``src/heat_nowcast/`` (`CLAUDE.md` §7); this script
invokes it and renders the output.
"""

from __future__ import annotations

import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from heat_nowcast.analysis.power import simulate_mde
from heat_nowcast.paths import FIGURES_DIR, TABLES_DIR, ensure_dirs
from heat_nowcast.pipelines.phase1b import (
    EVALUATION_START,
    Phase1bResult,
    run_phase1b,
)

ORACLE_LABEL = "Oracle (REALISED CWV)"


def scored_panel(result: Phase1bResult) -> pd.DataFrame:
    """Rows that entered the comparison, with error columns attached."""
    panel = result.panel
    scored = panel[
        (panel["gas_day"] >= pd.Timestamp(EVALUATION_START))
        & panel["demand_mscm_d1"].notna()
        & panel["ng_forecast_mscm"].notna()
        & panel["gas_baseline_cwv"].notna()
    ].copy()
    scored["ng_error"] = scored["ng_forecast_mscm"] - scored["demand_mscm_d1"]
    scored["baseline_error"] = scored["gas_baseline_cwv"] - scored["demand_mscm_d1"]
    return scored


def plot_mae_by_ldz(result: Phase1bResult) -> None:
    """Draw grouped bars of MAE per Local Distribution Zone."""
    table = result.by_ldz.pivot_table(index="ldz", columns="model", values="mae")
    order = [
        "National Gas D-1",
        "CWV+calendar baseline",
        "Seasonal naive (lag 7d)",
        ORACLE_LABEL,
    ]
    figure, axis = plt.subplots(figsize=(11, 5.5))
    positions = np.arange(len(table))
    width = 0.8 / len(order)
    for offset, model in enumerate(order):
        is_oracle = model == ORACLE_LABEL
        axis.bar(
            positions + offset * width,
            table[model].to_numpy(),
            width=width,
            label=model,
            edgecolor="black",
            linewidth=0.4,
            hatch="//" if is_oracle else "",
            alpha=0.75 if is_oracle else 1.0,
        )
    axis.set_xticks(positions + width * (len(order) - 1) / 2)
    axis.set_xticklabels(table.index)
    axis.set_ylabel("MAE (mscm/day)")
    axis.set_xlabel("Local Distribution Zone")
    axis.set_title(
        "Daily LDZ gas offtake forecast error, "
        f"{result.diagnostics['evaluation_start']} to "
        f"{result.diagnostics['evaluation_end']}\nout-of-sample walk-forward"
    )
    axis.legend(fontsize=8)
    axis.grid(axis="y", alpha=0.3)
    figure.text(
        0.01,
        0.01,
        "Hatched bar driven by REALISED (outturn) CWV -- diagnostic upper "
        "bound, not a forecast.",
        fontsize=7,
        style="italic",
    )
    figure.tight_layout(rect=(0, 0.04, 1, 1))
    figure.savefig(FIGURES_DIR / "phase1b_mae_by_ldz.png", dpi=150)
    plt.close(figure)


def plot_incumbent_error_vs_weather(result: Phase1bResult) -> None:
    """Plot the Phase A3 question, asked of the gas incumbent's residual."""
    scored = scored_panel(result)
    daily = scored.groupby("gas_day", as_index=False).agg(
        ng_error=("ng_error", "mean"), cwv=("cwv_forecast", "mean")
    )

    figure, axes = plt.subplots(1, 2, figsize=(12, 5))
    axes[0].scatter(daily["cwv"], daily["ng_error"], s=9, alpha=0.5)
    axes[0].axhline(0.0, linewidth=0.8, color="black")
    correlation = float(np.corrcoef(daily["cwv"], daily["ng_error"])[0, 1])
    coldest = daily["cwv"].quantile(0.10)
    axes[0].axvline(coldest, linestyle="--", color="tab:red", linewidth=1)
    axes[0].set_xlabel("Forecast CWV (lower = colder)")
    axes[0].set_ylabel("National Gas daily mean error (mscm/day)")
    axes[0].set_title(f"Gas: incumbent error vs weather (r = {correlation:.3f})")
    axes[0].grid(alpha=0.3)

    daily["decile"] = pd.qcut(daily["cwv"], 10, labels=False)
    by_decile = daily.groupby("decile").agg(
        mae=("ng_error", lambda values: values.abs().mean())
    )
    axes[1].bar(by_decile.index, by_decile["mae"], edgecolor="black", linewidth=0.4)
    axes[1].set_xlabel("CWV decile (0 = coldest)")
    axes[1].set_ylabel("National Gas MAE (mscm/day)")
    axes[1].set_title("Incumbent error IS worse in cold weather")
    axes[1].grid(axis="y", alpha=0.3)

    figure.suptitle(
        "Phase 1b: is there a heat signal in the incumbent's residual? "
        "(contrast with Phase 1 electricity)",
        fontsize=11,
    )
    figure.tight_layout()
    figure.savefig(FIGURES_DIR / "phase1b_ng_error_vs_cwv.png", dpi=150)
    plt.close(figure)


def plot_power_curve(power: dict[str, object]) -> None:
    """Power curve and the resulting MDE for the core test."""
    figure, axis = plt.subplots(figsize=(9, 5))
    axis.plot(power["effect_grid"], power["power"], marker="o", linewidth=1.6)
    axis.axhline(0.8, linestyle="--", color="tab:red", linewidth=1)
    axis.axvline(power["mde"], linestyle="--", color="tab:red", linewidth=1)
    axis.annotate(
        f"MDE = {power['mde']:.4f} mscm/day\n"
        f"({power['mde_mw']:.0f} MW-equiv, "
        f"{power['mde_share']:.0%} of mean |NG error|)",
        xy=(power["mde"], 0.8),
        xytext=(power["mde"] * 1.15, 0.45),
        fontsize=9,
        arrowprops={"arrowstyle": "->", "color": "tab:red"},
    )
    axis.set_xlabel(
        "True interaction effect "
        "(mscm/day per SD of stock score per SD of cold severity)"
    )
    axis.set_ylabel("Power")
    axis.set_ylim(0.0, 1.02)
    axis.grid(alpha=0.3)
    axis.set_title(
        f"Phase 1b core test: power on the real 13 x {power['n_periods']} panel\n"
        "wild cluster bootstrap, 13 clusters, alpha=0.05"
    )
    figure.tight_layout()
    figure.savefig(FIGURES_DIR / "phase1b_power_curve.png", dpi=150)
    plt.close(figure)


def main() -> None:
    """Run the pipeline and the power analysis, and write every output."""
    ensure_dirs()
    pd.set_option("display.width", 220)

    result = run_phase1b()
    tables = {
        "phase1b_overall": result.overall,
        "phase1b_by_ldz": result.by_ldz,
        "phase1b_by_season": result.by_season,
        "phase1b_by_day_type": result.by_day_type,
        "phase1b_by_season_and_day_type": result.by_season_and_day_type,
        "phase1b_folds": result.folds,
    }
    for name, table in tables.items():
        table.to_csv(TABLES_DIR / f"{name}.csv", index=False)
    (TABLES_DIR / "phase1b_diagnostics.json").write_text(
        json.dumps(result.diagnostics, indent=2, default=str) + "\n",
        encoding="utf-8",
    )

    # Power first: the MDE is reported above the estimates so that whatever the
    # core test returns is interpretable (`reports/phase1b_findings.md`).
    scored = scored_panel(result)
    scored["cold_severity"] = -scored["cwv_forecast"]
    mde = simulate_mde(
        scored,
        outcome="ng_error",
        unit_column="ldz",
        period_column="gas_day",
        severity_column="cold_severity",
    )
    power_payload: dict[str, object] = {
        "effect_grid": mde.effect_grid.tolist(),
        "power": mde.power.tolist(),
        "mde": mde.mde,
        "mde_mw": mde.mde_mw_equivalent,
        "mde_share": mde.mde_share_of_mean_abs_error,
        "residual_sd": mde.residual_sd,
        "mean_abs_error": mde.mean_abs_error,
        "n_obs": mde.n_obs,
        "n_clusters": mde.n_clusters,
        "n_periods": mde.n_periods,
        "simulations": mde.simulations,
        "bootstrap_draws": mde.bootstrap_draws,
        "size_at_zero": mde.detail.get("size_at_zero_effect"),
        "seed": mde.seed,
    }
    (TABLES_DIR / "phase1b_power.json").write_text(
        json.dumps(power_payload, indent=2) + "\n", encoding="utf-8"
    )

    plot_mae_by_ldz(result)
    plot_incumbent_error_vs_weather(result)
    plot_power_curve(power_payload)

    print("\n=== MDE (reported before the estimates) ===")
    print(
        f"  {mde.mde:.4f} mscm/day = {mde.mde_mw_equivalent:.1f} MW-equivalent "
        f"= {mde.mde_share_of_mean_abs_error:.1%} of mean |NG error| "
        f"at {mde.target_power:.0%} power, alpha={mde.alpha}"
    )
    print("\n=== OVERALL ===")
    print(result.overall.to_string(index=False))
    print("\n=== BY LDZ ===")
    print(
        result.by_ldz.pivot_table(index="ldz", columns="model", values="mae").round(3)
    )
    print("\n=== DIAGNOSTICS ===")
    print(json.dumps(result.diagnostics, indent=2, default=str))


if __name__ == "__main__":
    main()
