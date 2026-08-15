"""Phase 1 figures. Matplotlib only."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from heat_nowcast.pipelines.phase1 import Phase1Result

SEASON_ORDER = ["winter", "spring", "summer", "autumn"]
DAY_TYPE_ORDER = ["weekday", "saturday", "sunday", "holiday"]

#: Series driven by realised weather. Drawn dashed and labelled, so an oracle
#: line can never be mistaken for a forecast line in a figure.
ORACLE_LABEL = "Oracle (REALISED weather)"


class _Style(NamedTuple):
    """Drawing style for one series. Oracle series are visually distinct."""

    linestyle: str
    alpha: float
    hatch: str


def _style_for(model: str) -> _Style:
    """Return the drawing style for a model, marking oracle series apart."""
    if model == ORACLE_LABEL:
        return _Style(linestyle="--", alpha=0.75, hatch="//")
    return _Style(linestyle="-", alpha=1.0, hatch="")


def plot_error_by_season(result: Phase1Result, path: Path) -> Path:
    """Draw a grouped bar chart of MAE by season, one bar per model."""
    table = result.by_season.copy()
    models = list(table["model"].unique())
    seasons = [s for s in SEASON_ORDER if s in set(table["season"])]

    figure, axis = plt.subplots(figsize=(10, 5.5))
    width = 0.8 / max(len(models), 1)
    positions = np.arange(len(seasons))

    for offset, model in enumerate(models):
        values = [
            float(
                table.loc[
                    (table["season"] == season) & (table["model"] == model), "mae"
                ].iloc[0]
            )
            for season in seasons
        ]
        bar_style = _style_for(model)
        axis.bar(
            positions + offset * width,
            values,
            width=width,
            label=model,
            hatch=bar_style.hatch,
            alpha=bar_style.alpha,
            edgecolor="black",
            linewidth=0.4,
        )

    axis.set_xticks(positions + width * (len(models) - 1) / 2)
    axis.set_xticklabels(seasons)
    axis.set_ylabel("MAE (MW)")
    axis.set_title(
        "Day-ahead national demand forecast error by season\n"
        f"{result.diagnostics['evaluation_start']} to "
        f"{result.diagnostics['evaluation_end']}, "
        "out-of-sample walk-forward"
    )
    axis.legend(fontsize=8, ncols=2)
    axis.grid(axis="y", alpha=0.3)
    figure.text(
        0.01,
        0.01,
        "Hatched bar is driven by REALISED (ERA5) weather -- an upper bound, "
        "not a forecast. All other bars are point-in-time.",
        fontsize=7,
        style="italic",
    )
    figure.tight_layout(rect=(0, 0.04, 1, 1))
    figure.savefig(path, dpi=150)
    plt.close(figure)
    return path


def plot_error_by_period(result: Phase1Result, path: Path) -> Path:
    """MAE by settlement period -- where in the day each forecast struggles."""
    from heat_nowcast.pipelines.phase1 import FORECAST_COLUMNS, ORACLE_COLUMN

    scored = result.panel.dropna(
        subset=[
            "demand_outturn_mw",
            *FORECAST_COLUMNS.values(),
            ORACLE_COLUMN,
        ]
    )
    figure, axis = plt.subplots(figsize=(10, 5.5))

    for label, column in {
        **FORECAST_COLUMNS,
        ORACLE_LABEL: ORACLE_COLUMN,
    }.items():
        error = (scored[column] - scored["demand_outturn_mw"]).abs()
        by_period = error.groupby(scored["settlement_period"]).mean()
        style = _style_for(label)
        axis.plot(
            by_period.index,
            by_period.to_numpy(),
            label=label,
            linestyle=style.linestyle,
            alpha=style.alpha,
            linewidth=1.6,
        )

    axis.set_xlabel("Settlement period (1 = 00:00-00:30 London)")
    axis.set_ylabel("MAE (MW)")
    axis.set_title(
        "Forecast error by time of day\n"
        f"{result.diagnostics['evaluation_start']} to "
        f"{result.diagnostics['evaluation_end']}"
    )
    axis.legend(fontsize=8)
    axis.grid(alpha=0.3)
    figure.text(
        0.01,
        0.01,
        "Dashed line is driven by REALISED (ERA5) weather -- diagnostic upper "
        "bound only.",
        fontsize=7,
        style="italic",
    )
    figure.tight_layout(rect=(0, 0.04, 1, 1))
    figure.savefig(path, dpi=150)
    plt.close(figure)
    return path


def plot_residual_scatter(result: Phase1Result, path: Path) -> Path:
    """NESO's error against the baseline's error, and against HDD.

    The left panel is the Phase A3 question in one picture: if the two errors
    are uncorrelated, the baseline knows something NESO does not.
    """
    scored = result.panel.dropna(
        subset=["demand_outturn_mw", "neso_da_forecast_mw", "baseline_hdd_calendar"]
    )
    neso_error = scored["neso_da_forecast_mw"] - scored["demand_outturn_mw"]
    baseline_error = scored["baseline_hdd_calendar"] - scored["demand_outturn_mw"]

    figure, axes = plt.subplots(1, 2, figsize=(12, 5.5))

    axes[0].scatter(neso_error, baseline_error, s=2, alpha=0.15)
    axes[0].axhline(0.0, linewidth=0.8, color="black")
    axes[0].axvline(0.0, linewidth=0.8, color="black")
    correlation = float(np.corrcoef(neso_error, baseline_error)[0, 1])
    axes[0].set_xlabel("NESO day-ahead error (MW)")
    axes[0].set_ylabel("HDD+calendar baseline error (MW)")
    axes[0].set_title(f"Errors move together (r = {correlation:.2f})")
    axes[0].grid(alpha=0.3)

    daily = (
        pd.DataFrame(
            {
                "settlement_date": scored["settlement_date"],
                "hdd_forecast": scored["hdd_forecast"],
                "neso_error": neso_error,
            }
        )
        .groupby("settlement_date", as_index=False)
        .agg(hdd_forecast=("hdd_forecast", "first"), neso_error=("neso_error", "mean"))
    )
    axes[1].scatter(daily["hdd_forecast"], daily["neso_error"], s=8, alpha=0.5)
    axes[1].axhline(0.0, linewidth=0.8, color="black")
    axes[1].set_xlabel("Forecast HDD (base 15.5 degC)")
    axes[1].set_ylabel("NESO daily mean error (MW)")
    axes[1].set_title("Is NESO's error predictable from heating demand?")
    axes[1].grid(alpha=0.3)

    figure.suptitle(
        "Phase 1 residual diagnostics -- both panels use point-in-time "
        "forecast weather",
        fontsize=11,
    )
    figure.tight_layout()
    figure.savefig(path, dpi=150)
    plt.close(figure)
    return path
