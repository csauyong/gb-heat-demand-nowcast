"""Vintage panel of National Gas's republished LDZ demand forecast (Phase C1).

The forecast for gas day D is republished at eight canonical times, from 13:15
on D-1 to 00:15 on D+1 (``reports/decision_log.md`` rows 14 and 44). C1 asks
whether those revisions are efficient, so it needs every vintage side by side:
``f[ldz, gas_day, slot]``.

Point-in-time rules applied here
--------------------------------
* A slot is identified from the publication's own ``generated_at`` relative to
  the gas day it describes, so a vintage can never be attributed to an earlier
  issue time than it actually had.
* Non-canonical publications (about 1.6% of rows: occasional 21:15 on D-1,
  xx:58 re-issues, 10:15 on D+1) are dropped and counted, never re-labelled
  into a neighbouring slot.
* The one feature built from *outturn* -- the incumbent's most recent known
  error -- is gated row by row on the actual's own ``published_at``, because
  about 8% of D+1 actuals publish on D+2, not D+1. Assuming "D-2 is always
  known at D-1" would leak on those days.

Timestamps are compared within the portal's own clock. Its timezone (London or
UTC) is unresolved; every comparison here is between two timestamps from that
same clock, so the ambiguity does not affect them.
"""

from __future__ import annotations

from typing import Final

import numpy as np
import pandas as pd

#: (day offset from gas day, clock time) -> slot label, in publication order.
CANONICAL_SLOTS: Final[dict[tuple[int, str], str]] = {
    (-1, "13:15"): "dm1_1315",
    (-1, "16:15"): "dm1_1615",
    (0, "00:15"): "d_0015",
    (0, "10:15"): "d_1015",
    (0, "13:15"): "d_1315",
    (0, "16:15"): "d_1615",
    (0, "21:15"): "d_2115",
    (1, "00:15"): "dp1_0015",
}
SLOT_ORDER: Final[tuple[str, ...]] = tuple(CANONICAL_SLOTS.values())

#: The headline day-ahead vintage and the one before it (decision log row 45).
PRIMARY_SLOT: Final[str] = "dm1_1615"
PRIOR_SLOT: Final[str] = "dm1_1315"

#: How far back to look for the most recent published actual.
MAX_KNOWN_ERROR_LAG_DAYS: Final[int] = 5


def label_slots(publications: pd.DataFrame) -> pd.Series:
    """Map each publication to its canonical slot label, or NA if non-canonical.

    Parameters
    ----------
    publications :
        Frame with naive ``gas_day`` and ``generated_at`` columns.
    """
    offset = (
        pd.DatetimeIndex(publications["generated_at"]).normalize()
        - pd.DatetimeIndex(publications["gas_day"]).normalize()
    ).days
    clock = pd.DatetimeIndex(publications["generated_at"]).strftime("%H:%M")
    labels = [
        CANONICAL_SLOTS.get((int(day), str(time)))
        for day, time in zip(offset, clock, strict=True)
    ]
    return pd.Series(labels, index=publications.index, dtype="object")


def build_vintage_panel(
    publications: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Pivot the publication history to one row per (gas day, LDZ).

    Parameters
    ----------
    publications :
        Long frame from
        :func:`heat_nowcast.data.gas.load_ldz_publication_history`.

    Returns
    -------
    wide : pandas.DataFrame
        ``gas_day``, ``ldz``, then ``f_<slot>`` (value) and ``issued_<slot>``
        (its ``generated_at``) for every slot in :data:`SLOT_ORDER`. A slot
        with no publication is NaN / NaT -- never filled from a neighbour.
    audit : dict
        Row counts: ``rows_in``, ``rows_non_canonical`` (dropped),
        ``rows_duplicate_timestamp`` (same slot published twice; last kept).
    """
    working = publications.copy()
    working["slot"] = label_slots(working)
    audit = {
        "rows_in": len(working),
        "rows_non_canonical": int(working["slot"].isna().sum()),
    }
    working = working.dropna(subset=["slot"])
    keys = ["gas_day", "ldz", "slot"]
    audit["rows_duplicate_timestamp"] = int(working.duplicated(keys).sum())
    working = working.sort_values([*keys, "generated_at"], kind="stable")
    working = working.drop_duplicates(keys, keep="last")

    values = working.pivot_table(
        index=["gas_day", "ldz"], columns="slot", values="value", aggfunc="first"
    )
    issued = working.pivot_table(
        index=["gas_day", "ldz"], columns="slot", values="generated_at", aggfunc="first"
    )
    values = values.reindex(columns=list(SLOT_ORDER)).add_prefix("f_")
    issued = issued.reindex(columns=list(SLOT_ORDER)).add_prefix("issued_")
    wide = values.join(issued).reset_index()
    wide.columns.name = None
    return wide.sort_values(["gas_day", "ldz"]).reset_index(drop=True), audit


def aggregate_gb(
    frame: pd.DataFrame,
    *,
    sum_columns: list[str],
    max_columns: list[str] | None = None,
    mean_columns: list[str] | None = None,
    n_zones: int = 13,
) -> pd.DataFrame:
    """Aggregate an LDZ x gas-day frame to GB, one row per gas day.

    A summed column is NaN for a gas day unless **all** ``n_zones`` zones are
    present for it, so a missing zone cannot read as a fall in demand.
    ``max_columns`` (timestamps) take the latest zone, which is the moment the
    GB total became fully knowable.
    """
    grouped = frame.groupby("gas_day", sort=True)
    out = pd.DataFrame(
        index=pd.Index(sorted(frame["gas_day"].unique()), name="gas_day")
    )
    for column in sum_columns:
        total = grouped[column].sum(min_count=1)
        count = grouped[column].count()
        out[column] = total.where(count == n_zones)
    for column in max_columns or []:
        latest = grouped[column].max()
        count = grouped[column].count()
        out[column] = latest.where(count == n_zones)
    for column in mean_columns or []:
        mean = grouped[column].mean()
        count = grouped[column].count()
        out[column] = mean.where(count == n_zones)
    return out.reset_index()


def latest_known_error(
    daily: pd.DataFrame,
    *,
    forecast_column: str,
    actual_column: str,
    actual_published_column: str,
    issue_column: str,
    max_lag_days: int = MAX_KNOWN_ERROR_LAG_DAYS,
) -> pd.DataFrame:
    """Return the error on the latest gas day whose actual was public at issue.

    For each gas day D, looks back over D-1 ... D-``max_lag_days`` and takes the
    most recent day d whose ``actual_published_column`` is strictly before D's
    ``issue_column``. Its error ``forecast - actual`` is the feature.

    Parameters
    ----------
    daily :
        One row per gas day (contiguous calendar, sorted), with the forecast,
        the first-published actual, that actual's publication time and the
        issue time of D's forecast.

    Returns
    -------
    pandas.DataFrame
        ``e_known`` (the error, NaN if nothing was public in the window) and
        ``e_known_lag_days`` (D - d), aligned to ``daily``.
    """
    frame = daily.set_index("gas_day").asfreq("D")
    error = frame[forecast_column] - frame[actual_column]
    issue = frame[issue_column]
    result = pd.Series(np.nan, index=frame.index)
    lag_used = pd.Series(np.nan, index=frame.index)
    # Shortest lag first, filling only rows still empty, so each row gets the
    # most recent day that was already public.
    for lag in range(1, max_lag_days + 1):
        candidate_error = error.shift(lag)
        candidate_published = frame[actual_published_column].shift(lag)
        public = (candidate_published < issue) & candidate_error.notna()
        fill = public & result.isna()
        result = result.where(~fill, candidate_error)
        lag_used = lag_used.where(~fill, float(lag))
    aligned = pd.DataFrame({"e_known": result, "e_known_lag_days": lag_used})
    aligned = aligned.reindex(pd.DatetimeIndex(daily["gas_day"]))
    return aligned.reset_index(drop=True)
