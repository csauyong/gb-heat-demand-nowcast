"""Run Paper 1's pre-registered analysis in stages.

Usage::

    python scripts/run_paper1.py audit       # sample counts only
    python scripts/run_paper1.py baselines   # named baselines (§4)
    python scripts/run_paper1.py mde         # MDEs (§6), before any estimate
    python scripts/run_paper1.py estimate    # H1 and the secondary family

Each stage writes ``reports/tables/paper1_<stage>*``. The MDE stage must be run
and logged in ``reports/decision_log.md`` before the estimate stage
(pre-registration §6). Logic lives in :mod:`heat_nowcast.pipelines.paper1`.
"""

from __future__ import annotations

import json
import sys

import pandas as pd

from heat_nowcast.paths import TABLES_DIR, ensure_dirs
from heat_nowcast.pipelines import paper1


def main(stage: str) -> None:
    """Run one stage and write its tables."""
    ensure_dirs()
    pd.set_option("display.width", 200)
    panel = paper1.build_panel()
    if stage == "audit":
        counts = paper1.audit(panel)
        weights = pd.DataFrame(panel.attrs["cwv_weights"])
        weights.to_csv(TABLES_DIR / "paper1_cwv_weights.csv", index=False)
        (TABLES_DIR / "paper1_audit.json").write_text(json.dumps(counts, indent=2))
        print(json.dumps(counts, indent=2))
    elif stage == "baselines":
        result = paper1.run_baselines(panel)
        out = {"h1_martingale": result.h1_martingale, "h1_weather": result.h1_weather}
        (TABLES_DIR / "paper1_baselines_h1.json").write_text(json.dumps(out, indent=2))
        result.nts_scores.to_csv(TABLES_DIR / "paper1_baselines_nts.csv", index=False)
        print(json.dumps(out, indent=2))
        print(result.nts_scores.round(3).to_string(index=False))
    elif stage == "mde":
        rows = []
        for test, mde in paper1.run_mdes(panel).items():
            mde.curve.assign(test=test).to_csv(
                TABLES_DIR / f"paper1_mde_curve_{test}.csv", index=False
            )
            for alpha, value in mde.mde.items():
                rows.append(
                    {
                        "test": test,
                        "alpha": alpha,
                        "mde": value,
                        "size_at_zero": float(mde.curve.iloc[0][f"power_{alpha:.4f}"]),
                        "unit_se": mde.unit_se,
                        "n": mde.n,
                        "block_rows": mde.block_rows,
                    }
                )
        table = pd.DataFrame(rows)
        table.to_csv(TABLES_DIR / "paper1_mde.csv", index=False)
        print(table.to_string(index=False))
    elif stage == "estimate":
        table, detail = paper1.run_estimates(panel)
        table.to_csv(TABLES_DIR / "paper1_estimates.csv", index=False)
        (TABLES_DIR / "paper1_estimates_detail.json").write_text(
            json.dumps(detail, indent=2, default=float)
        )
        print(table.to_string(index=False))
        print(json.dumps(detail, indent=2, default=float))
    else:
        msg = f"unknown stage {stage!r}"
        raise SystemExit(msg)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "audit")
