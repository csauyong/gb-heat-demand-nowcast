"""Run Phase C0: the incumbent's error by forecast-CWV decile, four ways.

Usage::

    python scripts/run_c0_scale_check.py

Pre-specified in ``reports/decision_log.md`` row 41. Rebuilds the Phase 1b
panel from the warm cache on the Phase 1b evaluation window (2023-12-01 ->
2026-08-06, the same 12,714 rows as row 16) and writes
``reports/tables/c0_scale_check.csv`` and ``reports/tables/c0_reconciliation.json``.
Analysis logic lives in :mod:`heat_nowcast.analysis.scale_check`.
"""

from __future__ import annotations

import datetime as dt
import json

import pandas as pd

from heat_nowcast.analysis.scale_check import row23_reconciliation, scale_check
from heat_nowcast.paths import TABLES_DIR, ensure_dirs
from heat_nowcast.pipelines.phase1b import EVALUATION_START, run_phase1b

#: Last gas day of the row-16 baseline comparison (12,714 rows).
WINDOW_END = dt.date(2026, 8, 6)


def main() -> None:
    """Build the panel, run C0 and write its tables."""
    ensure_dirs()
    result = run_phase1b(end=WINDOW_END, include_national_hdd=False)
    panel = result.panel
    scored = panel[
        (panel["gas_day"] >= pd.Timestamp(EVALUATION_START))
        & (panel["gas_day"] <= pd.Timestamp(WINDOW_END))
        & panel["demand_mscm_d1"].notna()
        & panel["ng_forecast_mscm"].notna()
        & panel["gas_baseline_cwv"].notna()
    ].copy()
    print(
        f"C0 window {scored['gas_day'].min().date()} -> "
        f"{scored['gas_day'].max().date()}: {len(scored)} rows, "
        f"{scored['gas_day'].nunique()} gas days"
    )

    table = scale_check(scored)
    table.to_csv(TABLES_DIR / "c0_scale_check.csv", index=False)
    reconciliation = row23_reconciliation(scored)
    (TABLES_DIR / "c0_reconciliation.json").write_text(
        json.dumps(reconciliation, indent=2)
    )

    with pd.option_context("display.width", 200, "display.max_columns", 20):
        print(table.loc[table["level"] == "GB"].round(3).to_string(index=False))
    print(json.dumps(reconciliation, indent=2))


if __name__ == "__main__":
    main()
