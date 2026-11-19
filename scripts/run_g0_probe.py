"""Gate G0: blind history check of candidate NBP day-ahead series.

Prints and writes coverage only (dates, row counts, field names, non-null
counts). No price value is fetched into anything that outlives the probe
(decision log row 52; ``heat_nowcast.data.lseg_prices``).

Needs LSEG Workspace running and ``LSEG_APP_KEY`` set (in ``.env``).
"""

from __future__ import annotations

from dataclasses import asdict

import pandas as pd

from heat_nowcast.data.lseg_prices import CANDIDATE_SERIES, probe_history_coverage
from heat_nowcast.paths import TABLES_DIR


def main() -> None:
    """Probe every candidate and write ``reports/tables/g0_coverage.csv``."""
    rows = []
    for ric in CANDIDATE_SERIES:
        report = asdict(probe_history_coverage(ric))
        rows.append(report)
        print(report)
    TABLES_DIR.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(TABLES_DIR / "g0_coverage.csv", index=False)


if __name__ == "__main__":
    main()
