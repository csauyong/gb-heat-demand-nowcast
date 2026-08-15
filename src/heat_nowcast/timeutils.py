"""Timestamp conventions for GB electricity data.

Three facts drive everything in this module.

1. **Settlement periods are counted in London local time, not UTC.** A GB
   settlement day starts at local midnight and runs in half-hour periods. On
   the spring-forward Sunday the day is 23 hours long and has **46** periods;
   on the autumn Sunday it is 25 hours long and has **50**. Code that assumes
   48 is wrong twice a year, and wrong in a way that silently misaligns
   weather with demand for a whole day.

2. **The safe conversion goes through local midnight, not through the local
   wall clock of the period itself.** Localising a wall-clock timestamp on the
   autumn Sunday is ambiguous -- 01:30 local happens twice. Localising *local
   midnight* is never ambiguous, so we anchor there and add half-hour
   multiples in absolute (UTC) time. That reproduces 46/48/50-period days for
   free and needs no ``ambiguous=`` guesswork.

3. **Internally everything is timezone-aware UTC** (`CLAUDE.md` §7). London
   appears only where the convention demands it -- the settlement date, the
   calendar features a consumer actually experiences, and the display layer.

Convention used throughout this package: ``settlement_datetime`` is the
**end** of the settlement period, in UTC. Settlement period ``p`` on local
date ``d`` covers ``[local_midnight + (p-1)*30min, local_midnight + p*30min)``,
and we label it with the right-hand edge. This matches the ``Datetime`` column
NESO publishes in its day-ahead forecast performance dataset, which was
verified against the 2022-03-27 spring-forward day (46 periods, local
timestamps stepping 00:30 -> 02:00).
"""

from __future__ import annotations

import datetime as dt
from typing import Final

import numpy as np
import pandas as pd

LONDON: Final[str] = "Europe/London"
UTC: Final[str] = "UTC"
HALF_HOUR: Final[pd.Timedelta] = pd.Timedelta(minutes=30)

#: Gas day runs 05:00-05:00 UTC and is *not* the electricity day
#: (`CLAUDE.md` §2.3, `docs/data_inventory.md` §4).
GAS_DAY_START_UTC_HOUR: Final[int] = 5


def london_midnight_utc(settlement_date: pd.Series | pd.DatetimeIndex) -> pd.Series:
    """Return the UTC instant of local midnight starting each settlement date.

    Parameters
    ----------
    settlement_date :
        Naive dates (no timezone). These are London calendar dates, which is
        how GB settlement data labels its days.

    Returns
    -------
    pandas.Series
        Timezone-aware UTC timestamps.
    """
    dates = pd.to_datetime(pd.Series(settlement_date).to_numpy()).normalize()
    localised = dates.tz_localize(LONDON)
    return pd.Series(localised.tz_convert(UTC))


def settlement_period_to_utc(
    settlement_date: pd.Series | pd.DatetimeIndex,
    settlement_period: pd.Series | np.ndarray,
) -> pd.Series:
    """Convert (London settlement date, settlement period) to a UTC instant.

    The returned timestamp is the **end** of the settlement period.

    Because the anchor is local midnight expressed in UTC, this is correct on
    46-period (spring-forward) and 50-period (autumn) days without special
    casing: local midnight simply lands on a different UTC hour either side of
    the transition.

    Parameters
    ----------
    settlement_date :
        London calendar dates, timezone-naive.
    settlement_period :
        1-based settlement period. Values above 48 are legitimate on the
        autumn clock-change day.

    Returns
    -------
    pandas.Series
        Timezone-aware UTC timestamps at the period end.
    """
    periods = np.asarray(settlement_period, dtype="int64")
    if (periods < 1).any() or (periods > 50).any():
        msg = "settlement_period must lie in [1, 50]"
        raise ValueError(msg)
    anchor = pd.DatetimeIndex(london_midnight_utc(settlement_date))
    return pd.Series(anchor + pd.to_timedelta(periods * 30, unit="m"))


def settlement_periods_in_day(settlement_date: dt.date) -> int:
    """Return the number of settlement periods in a London calendar day.

    Returns 46, 48 or 50.
    """
    start = pd.Timestamp(settlement_date).tz_localize(LONDON)
    end = (pd.Timestamp(settlement_date) + pd.Timedelta(days=1)).tz_localize(LONDON)
    hours = (end - start) / pd.Timedelta(hours=1)
    return round(hours * 2)


def to_london(timestamps: pd.Series) -> pd.Series:
    """Convert UTC-aware timestamps to London local time (display boundary)."""
    return pd.Series(pd.DatetimeIndex(timestamps).tz_convert(LONDON))


def gas_day(timestamps: pd.Series) -> pd.Series:
    """Map UTC instants to their gas day (05:00-05:00 UTC).

    Provided so that any future gas-side work has to call an explicit
    conversion rather than reusing the electricity day by accident
    (`CLAUDE.md` §2.3). Not used by the Phase 1 electricity baseline.

    Parameters
    ----------
    timestamps :
        Timezone-aware UTC timestamps.

    Returns
    -------
    pandas.Series
        Timezone-naive dates identifying the gas day.
    """
    index = pd.DatetimeIndex(timestamps)
    if index.tz is None:
        msg = "gas_day requires timezone-aware UTC timestamps"
        raise ValueError(msg)
    shifted = index.tz_convert(UTC) - pd.Timedelta(hours=GAS_DAY_START_UTC_HOUR)
    return pd.Series(shifted.tz_localize(None).normalize())
