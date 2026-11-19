"""Paper 1, phase P0: pull NTS demand series and audit their structure.

Structure only -- publication slots, counts, coverage, publication lags. No
forecast error, bias or price value is computed here: those are pre-registered
tests (``docs/paper1_plan.md`` §5) and must not be looked at before the freeze.
Prices are pulled for one probe week only (the embargo in
:mod:`heat_nowcast.data.nts_market` enforces this).

Writes ``reports/tables/p0_*.csv`` and prints a summary.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd

from heat_nowcast.data.nts_market import (
    NTS_DEMAND_OBJECTS,
    SYSTEM_PRICE_OBJECTS,
    load_nts_publication_history,
    load_system_price,
)
from heat_nowcast.paths import TABLES_DIR

TABLES = TABLES_DIR
END = dt.date(2026, 11, 9)
PROBE = (dt.date(2021, 12, 1), dt.date(2021, 12, 7))


def slot_table(frame: pd.DataFrame) -> pd.DataFrame:
    """Count publications by (day offset from gas day, portal clock HH:MM)."""
    offset = (frame["generated_at"].dt.normalize() - frame["gas_day"]).dt.days
    clock = frame["generated_at"].dt.strftime("%H:%M")
    counts = (
        pd.DataFrame({"offset_days": offset, "clock": clock})
        .value_counts()
        .rename("publications")
        .reset_index()
        .sort_values(["offset_days", "clock"])
    )
    return counts.reset_index(drop=True)


def coverage_by_gas_year(frame: pd.DataFrame) -> pd.DataFrame:
    """Days with at least one publication, and publications per day, by Oct-Sep year."""
    day = frame["gas_day"]
    year = day.dt.year.where(day.dt.month < 10, day.dt.year + 1)
    per_day = frame.groupby("gas_day").size()
    per_day_year = year.groupby(frame["gas_day"]).first()
    return pd.DataFrame(
        {
            "days_present": per_day.groupby(per_day_year).size(),
            "pubs_per_day_median": per_day.groupby(per_day_year).median(),
            "pubs_per_day_min": per_day.groupby(per_day_year).min(),
        }
    ).rename_axis("gas_year_ending")


def main() -> None:
    """Pull the NTS series, probe one price week, write the audit tables."""
    TABLES.mkdir(parents=True, exist_ok=True)
    summary: list[dict[str, object]] = []
    for series in NTS_DEMAND_OBJECTS:
        frame = load_nts_publication_history(series, end=END)
        calendar = pd.date_range(frame["gas_day"].min(), END, freq="D")
        missing = calendar.difference(pd.DatetimeIndex(frame["gas_day"].unique()))
        slots = slot_table(frame)
        slots.to_csv(TABLES / f"p0_slots_{series}.csv", index=False)
        coverage_by_gas_year(frame).to_csv(TABLES / f"p0_coverage_{series}.csv")
        summary.append(
            {
                "series": series,
                "object_id": NTS_DEMAND_OBJECTS[series],
                "rows": len(frame),
                "first_gas_day": frame["gas_day"].min().date(),
                "last_gas_day": frame["gas_day"].max().date(),
                "missing_days": len(missing),
                "distinct_slots": len(slots),
                "units": ",".join(sorted(frame["unit"].astype(str).unique())),
            }
        )
        print(f"\n== {series}: {len(frame)} rows, {len(missing)} missing days")
        print(slots.head(14).to_string(index=False))

    for series in SYSTEM_PRICE_OBJECTS:
        frame = load_system_price(series, start=PROBE[0], end=PROBE[1])
        # Structure only: publication times and hour coverage. No values.
        lag = frame["generated_at"] - frame["gas_day"]
        summary.append(
            {
                "series": series,
                "object_id": SYSTEM_PRICE_OBJECTS[series],
                "rows": len(frame),
                "first_gas_day": frame["gas_day"].min().date(),
                "last_gas_day": frame["gas_day"].max().date(),
                "missing_days": 7 - frame["gas_day"].nunique(),
                "distinct_slots": int(frame["applicable_at"].dt.hour.nunique()),
                "units": ",".join(sorted(frame["unit"].astype(str).unique())),
                "first_publication_lag": str(lag.min()),
            }
        )

    table = pd.DataFrame(summary)
    table.to_csv(TABLES / "p0_summary.csv", index=False)
    print("\n" + table.to_string(index=False))


if __name__ == "__main__":
    main()
