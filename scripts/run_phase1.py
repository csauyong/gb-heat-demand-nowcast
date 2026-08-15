"""Run the Phase 1 comparison and write its tables and figures.

Usage::

    python scripts/run_phase1.py

Analysis logic lives in ``src/heat_nowcast/pipelines/phase1.py``; this script
only invokes it and renders the output (`CLAUDE.md` §7).
"""

from __future__ import annotations

import json

import pandas as pd

from heat_nowcast.paths import FIGURES_DIR, TABLES_DIR, ensure_dirs
from heat_nowcast.pipelines.phase1 import run_phase1
from heat_nowcast.reporting.figures import (
    plot_error_by_period,
    plot_error_by_season,
    plot_residual_scatter,
)


def main() -> None:
    """Run the pipeline, write tables to CSV and figures to PNG."""
    ensure_dirs()
    pd.set_option("display.width", 200)

    result = run_phase1()

    tables = {
        "phase1_overall": result.overall,
        "phase1_by_season": result.by_season,
        "phase1_by_day_type": result.by_day_type,
        "phase1_by_season_and_day_type": result.by_season_and_day_type,
        "phase1_folds": result.folds,
        "phase1_weather_grid": result.weights,
    }
    for name, table in tables.items():
        table.to_csv(TABLES_DIR / f"{name}.csv", index=False)

    (TABLES_DIR / "phase1_diagnostics.json").write_text(
        json.dumps(result.diagnostics, indent=2, default=str) + "\n",
        encoding="utf-8",
    )

    plot_error_by_season(result, FIGURES_DIR / "phase1_error_by_season.png")
    plot_error_by_period(result, FIGURES_DIR / "phase1_error_by_period.png")
    plot_residual_scatter(result, FIGURES_DIR / "phase1_residual_scatter.png")

    print("\n=== OVERALL ===")
    print(result.overall.to_string(index=False))
    print("\n=== BY SEASON ===")
    print(result.by_season.to_string(index=False))
    print("\n=== BY DAY TYPE ===")
    print(result.by_day_type.to_string(index=False))
    print("\n=== DIAGNOSTICS ===")
    print(json.dumps(result.diagnostics, indent=2, default=str))


if __name__ == "__main__":
    main()
