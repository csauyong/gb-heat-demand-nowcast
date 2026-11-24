"""Point-in-time features for Paper 1 (pre-registration and decision log row 56).

Everything here is a feature-construction rule fixed before any price was
estimated. Timestamps are compared on the National Gas portal's own clock (UK
local wall time, decision log row 49); every gate is strict (``<``), so a
publication stamped exactly at a cut-off is treated as not yet known.

* :func:`label_nts_slots` -- NTS demand-forecast publications to canonical
  slots (nearest within +/-30 minutes).
* :func:`gated_ldz_values` / :func:`gb_weighted_cwv` -- the latest LDZ CWV
  forecast published before a cut-off, aggregated to GB with weights known at
  the time (:func:`cwv_weights_by_gas_year`).
* :func:`product_rule` -- which delivery days enter the price tests.
"""

from __future__ import annotations

from typing import Final

import numpy as np
import pandas as pd

#: NTS canonical slots: (day offset from the gas day, portal clock) -> label.
NTS_SLOTS: Final[dict[tuple[int, str], str]] = {
    (-1, "13:10"): "dm1_1310",
    (-1, "16:15"): "dm1_1615",
    (0, "00:15"): "d_0015",
    (0, "10:15"): "d_1015",
    (0, "13:10"): "d_1310",
    (0, "16:15"): "d_1615",
    (0, "21:10"): "d_2110",
    (1, "00:15"): "dp1_0015",
}
NTS_SLOT_ORDER: Final[tuple[str, ...]] = tuple(NTS_SLOTS.values())
SLOT_TOLERANCE: Final[pd.Timedelta] = pd.Timedelta(minutes=30)

#: Cut-offs relative to the gas day (portal clock), pre-registration §2.
CUTOFF_DM1_1310: Final[pd.Timedelta] = pd.Timedelta(hours=-24 + 13, minutes=10)
CUTOFF_DM1_1615: Final[pd.Timedelta] = pd.Timedelta(hours=-24 + 16, minutes=15)
CUTOFF_D_0500: Final[pd.Timedelta] = pd.Timedelta(hours=5)

#: Gas year starts 1 October.
GAS_YEAR_START_MONTH: Final[int] = 10


def _slot_instants(gas_day: pd.Series) -> pd.DataFrame:
    """Canonical publication instants of every slot for each gas day."""
    out = {}
    for (offset, clock), label in NTS_SLOTS.items():
        hours, minutes = (int(part) for part in clock.split(":"))
        out[label] = gas_day + pd.Timedelta(days=offset, hours=hours, minutes=minutes)
    return pd.DataFrame(out, index=gas_day.index)


def label_nts_slots(publications: pd.DataFrame) -> pd.DataFrame:
    """Assign NTS forecast publications to canonical slots and pivot wide.

    Each publication takes the nearest canonical slot within
    :data:`SLOT_TOLERANCE`; anything else is dropped. If two publications fall
    in one slot, the one nearer the canonical time is kept (earlier on a tie).

    Parameters
    ----------
    publications :
        ``gas_day``, ``value``, ``generated_at`` (naive portal clock).

    Returns
    -------
    pandas.DataFrame
        One row per gas day: ``f_<slot>`` and ``issued_<slot>`` for every slot
        in :data:`NTS_SLOT_ORDER`, plus ``rows_dropped`` in ``attrs``.
    """
    frame = publications[["gas_day", "value", "generated_at"]].copy()
    instants = _slot_instants(frame["gas_day"])
    distance = instants.sub(frame["generated_at"], axis=0).abs()
    nearest = distance.idxmin(axis=1)
    gap = distance.min(axis=1)
    frame["slot"] = nearest.where(gap <= SLOT_TOLERANCE)
    frame["gap"] = gap
    dropped = int(frame["slot"].isna().sum())
    frame = frame.dropna(subset=["slot"])
    frame = frame.sort_values(["gas_day", "slot", "gap", "generated_at"])
    frame = frame.drop_duplicates(["gas_day", "slot"], keep="first")
    values = frame.pivot_table(
        index="gas_day", columns="slot", values="value", aggfunc="first"
    )
    issued = frame.pivot_table(
        index="gas_day", columns="slot", values="generated_at", aggfunc="first"
    )
    values = values.reindex(columns=list(NTS_SLOT_ORDER)).add_prefix("f_")
    issued = issued.reindex(columns=list(NTS_SLOT_ORDER)).add_prefix("issued_")
    wide = values.join(issued).reset_index()
    wide.columns.name = None
    wide.attrs["rows_dropped"] = dropped
    return wide


def gated_ldz_values(
    history: pd.DataFrame, cutoff_offset: pd.Timedelta
) -> pd.DataFrame:
    """Latest value per (gas day, LDZ) published strictly before a cut-off.

    Parameters
    ----------
    history :
        Every publication: ``gas_day``, ``ldz``, ``value``, ``generated_at``.
    cutoff_offset :
        Cut-off relative to the gas day's midnight, e.g. ``-10h50m`` for
        D-1 13:10.

    Returns
    -------
    pandas.DataFrame
        ``gas_day``, ``ldz``, ``value``, ``generated_at``.
    """
    cutoff = history["gas_day"] + cutoff_offset
    known = history.loc[history["generated_at"] < cutoff]
    known = known.sort_values(["gas_day", "ldz", "generated_at"], kind="stable")
    latest = known.drop_duplicates(["gas_day", "ldz"], keep="last")
    return latest[["gas_day", "ldz", "value", "generated_at"]].reset_index(drop=True)


def gas_year(dates: pd.Series) -> pd.Series:
    """Gas year label: the calendar year in which it starts (1 October)."""
    dates = pd.to_datetime(dates)
    return dates.dt.year - (dates.dt.month < GAS_YEAR_START_MONTH).astype(int)


def cwv_weights_by_gas_year(
    actual_d6: pd.DataFrame, gas_years: list[int], ldz_codes: tuple[str, ...]
) -> pd.DataFrame:
    """Each LDZ's share of D+6 demand in the previous gas year, as known then.

    For gas year ``y`` (starting 1 October ``y``) the weights use gas days in
    gas year ``y - 1`` whose D+6 actual was **first published before
    1 October y**. If none exist (the portal starts 2021-12-01), weights are
    equal (decision log row 56, item 3).

    Parameters
    ----------
    actual_d6 :
        ``gas_day``, ``ldz``, ``actual``, ``published_at``.
    gas_years :
        Gas years to produce weights for.
    ldz_codes :
        The 13 LDZ codes.

    Returns
    -------
    pandas.DataFrame
        ``gas_year``, ``ldz``, ``weight`` (sums to 1 within a gas year),
        ``basis_days`` (gas days used; 0 means equal weights).
    """
    frame = actual_d6.assign(gy=gas_year(actual_d6["gas_day"]))
    rows: list[dict[str, object]] = []
    for year in gas_years:
        cutoff = pd.Timestamp(year=year, month=GAS_YEAR_START_MONTH, day=1)
        basis = frame.loc[(frame["gy"] == year - 1) & (frame["published_at"] < cutoff)]
        totals = basis.groupby("ldz")["actual"].sum().reindex(list(ldz_codes))
        complete_days = basis.groupby("gas_day")["ldz"].nunique()
        n_days = int((complete_days == len(ldz_codes)).sum())
        if totals.isna().any() or n_days == 0:
            weights = pd.Series(1.0 / len(ldz_codes), index=list(ldz_codes))
            n_days = 0
        else:
            weights = totals / totals.sum()
        rows.extend(
            {"gas_year": year, "ldz": ldz, "weight": float(w), "basis_days": n_days}
            for ldz, w in weights.items()
        )
    return pd.DataFrame(rows)


def gb_weighted_cwv(
    gated: pd.DataFrame, weights: pd.DataFrame, n_zones: int = 13
) -> pd.Series:
    """Weighted GB CWV per gas day; NaN unless all ``n_zones`` are present.

    Parameters
    ----------
    gated :
        Output of :func:`gated_ldz_values`.
    weights :
        Output of :func:`cwv_weights_by_gas_year`.

    Returns
    -------
    pandas.Series
        Indexed by ``gas_day``.
    """
    frame = gated.assign(gas_year=gas_year(gated["gas_day"]))
    frame = frame.merge(weights[["gas_year", "ldz", "weight"]], on=["gas_year", "ldz"])
    frame["wv"] = frame["weight"] * frame["value"]
    grouped = frame.groupby("gas_day")
    total = grouped["wv"].sum()
    count = grouped["value"].count()
    return total.where(count == n_zones).rename("cwv")


def product_rule(
    delivery_days: pd.Series,
    trade_dates_available: pd.Series,
    holidays_ew: pd.Series,
) -> pd.Series:
    """Apply the day-ahead product rule (pre-registration §1, row 56 item 2).

    Keep D if t = D - 1 is Mon-Thu, neither t nor D is an England & Wales bank
    holiday, and an EEX row exists for t.

    Parameters
    ----------
    delivery_days :
        Naive gas days D.
    trade_dates_available :
        Trade dates with an EEX value.
    holidays_ew :
        England & Wales bank-holiday dates.

    Returns
    -------
    pandas.Series
        Boolean, aligned to ``delivery_days``.
    """
    days = pd.to_datetime(delivery_days).dt.normalize()
    trade = days - pd.Timedelta(days=1)
    holiday = set(pd.to_datetime(holidays_ew).dt.normalize())
    available = set(pd.to_datetime(trade_dates_available).dt.normalize())
    keep = (
        (trade.dt.dayofweek <= 3)
        & ~trade.isin(holiday)
        & ~days.isin(holiday)
        & trade.isin(available)
    )
    return keep.astype(bool)


def latest_known_actual(
    daily: pd.DataFrame,
    *,
    actual_column: str,
    actual_published_column: str,
    issue_column: str,
    max_lag_days: int = 5,
) -> pd.Series:
    """Return the most recent actual first published before each issue time.

    The "no-change" forecast. Looks back over D-1 ... D-``max_lag_days``.

    Parameters
    ----------
    daily :
        One row per gas day, contiguous and sorted.

    Returns
    -------
    pandas.Series
        Aligned to ``daily`` by position.
    """
    frame = daily.set_index("gas_day")
    result = pd.Series(np.nan, index=frame.index)
    for lag in range(1, max_lag_days + 1):
        candidate = frame[actual_column].shift(lag)
        published = frame[actual_published_column].shift(lag)
        public = (published < frame[issue_column]) & candidate.notna()
        result = result.where(~(public & result.isna()), candidate)
    return pd.Series(result.to_numpy(), index=daily.index)


def classify_row_dating(row_dates: pd.Series, prices: pd.Series) -> str:
    """Decide whether a daily power price is dated by delivery or auction day.

    Decision log row 60, item 3, fixed before any value was seen: compare the
    mean price by weekday of the row date. Weekend delivery is cheap, so
    Saturday and Sunday as the two lowest weekdays means **delivery-dated**;
    Friday and Saturday means **auction-dated** (the auction runs the day
    before delivery). Anything else is ``"unclear"`` and the caller stops.

    Returns
    -------
    str
        ``"delivery"``, ``"auction"`` or ``"unclear"``.
    """
    weekday = pd.to_datetime(row_dates).dt.dayofweek
    means = pd.Series(prices.to_numpy(), index=weekday.to_numpy()).groupby(level=0)
    lowest = set(means.mean().nsmallest(2).index.tolist())
    if lowest == {5, 6}:
        return "delivery"
    if lowest == {4, 5}:
        return "auction"
    return "unclear"
