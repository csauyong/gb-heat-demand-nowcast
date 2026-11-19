"""Run Phase C1: weak-efficiency tests of National Gas's LDZ demand forecast.

Usage::

    python scripts/run_c1_efficiency.py

Pre-specified in ``reports/decision_log.md`` rows 43-46. Writes
``reports/tables/c1_*.csv`` / ``.json``. The MDE is written and printed
before any estimate. Analysis logic lives in :mod:`heat_nowcast.pipelines.c1`.
"""

from __future__ import annotations

import json

import pandas as pd

from heat_nowcast.paths import TABLES_DIR, ensure_dirs
from heat_nowcast.pipelines.c1 import run_c1


def main() -> None:
    """Run C1 and write every table."""
    ensure_dirs()
    result = run_c1()
    pd.set_option("display.width", 200)
    pd.set_option("display.max_columns", 20)
    pd.set_option("display.max_colwidth", 120)

    print("== audit ==")
    print(json.dumps(result.inputs.audit, indent=2))

    print("== MDE (computed before any estimate) ==")
    result.mde_curve.to_csv(TABLES_DIR / "c1_mde_curve.csv", index=False)
    print(result.mde_curve.round(4).to_string(index=False))
    print(f"MDE (80% power, alpha 0.05): {result.mde:.4f}")

    print("== baselines (identical GB rows) ==")
    result.baselines.to_csv(TABLES_DIR / "c1_baselines.csv", index=False)
    print(result.baselines.round(3).to_string(index=False))

    print("== primary ==")
    primary = {"mde": result.mde, **result.primary}
    (TABLES_DIR / "c1_primary.json").write_text(json.dumps(primary, indent=2))
    print(json.dumps(primary, indent=2))

    print("== secondary ==")
    result.secondary.to_csv(TABLES_DIR / "c1_secondary.csv", index=False)
    print(result.secondary.to_string(index=False))
    result.nordhaus_pairs.to_csv(TABLES_DIR / "c1_nordhaus_pairs.csv", index=False)
    print(result.nordhaus_pairs.round(4).to_string(index=False))

    print("== kill-criterion forecast ==")
    result.kill_forecast.to_csv(TABLES_DIR / "c1_kill_forecast.csv", index=False)
    result.corrected_folds.to_csv(TABLES_DIR / "c1_corrected_folds.csv", index=False)
    print(result.kill_forecast.round(4).to_string(index=False))


if __name__ == "__main__":
    main()
