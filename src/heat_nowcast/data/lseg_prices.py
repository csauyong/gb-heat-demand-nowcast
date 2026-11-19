"""NBP day-ahead prices from LSEG Workspace (Paper 1, gate G0).

Paper 1's price hypotheses are pre-registered (``docs/paper1_preregistration.md``)
and prices are embargoed until the freeze. Before the freeze only one thing may
be learnt about a candidate price series: whether its **history covers the
development sample**. :func:`probe_history_coverage` answers that **blind**: it
fetches the series, keeps only dates and non-null counts, and discards the
values before returning. Nothing is cached and no value is ever returned,
printed or written (decision log row 52).

The full loader for the chosen series is added at the freeze, behind
:func:`heat_nowcast.data.nts_market.check_price_embargo`.

Access
------
LSEG Data Library for Python (``lseg-data``), **desktop session**: LSEG
Workspace must be running and signed in on this machine, and an application
key generated in Workspace's APPKEY app must be in the environment variable
:data:`APP_KEY_ENV` (``.env`` is read; it is gitignored). The key is never
logged, printed or stored by this module.

Source: LSEG Workspace via ``lseg.data.get_history``; the underlying index
publisher is named per RIC in :data:`CANDIDATE_SERIES`.
Licence: the owner's institutional LSEG licence. Prices may be used for
research and published as derived results; raw values are not redistributed.
"""

from __future__ import annotations

import datetime as dt
import os
from dataclasses import dataclass
from typing import Any, Final

import pandas as pd
from dotenv import load_dotenv

#: Environment variable holding the Workspace application key.
APP_KEY_ENV: Final[str] = "LSEG_APP_KEY"

#: Candidate day-ahead NBP series (decision log row 52). Metadata only.
CANDIDATE_SERIES: Final[dict[str, str]] = {
    "PNX-NBPEOD-DA": (
        "EEX (Powernext) NBP Day Ahead European Gas Spot Index (EOD), p/therm; "
        "trades and order book 17:15-17:30 CE(S)T = 16:15-16:30 UK"
    ),
    "PNX-NBPEGSI-DA": (
        "EEX NBP Day Ahead EGSI, p/therm; VWAP 08:00-18:00 CE(S)T; NBP from 2023-06-26"
    ),
    "GA2NB": "Marex Spectron Natural Gas NBP Day-Ahead, p/therm",
}

#: The development sample must be covered from this date (pre-registration §1).
REQUIRED_START: Final[dt.date] = dt.date(2021, 12, 1)


@dataclass(frozen=True)
class CoverageReport:
    """What a blind probe may reveal: dates and counts, never values.

    Attributes
    ----------
    ric :
        The instrument code probed.
    rows :
        Number of dated rows returned.
    first_date, last_date :
        First and last dated row, or ``None`` if nothing came back.
    columns :
        Field names returned.
    non_null :
        Non-null count per field.
    missing_weekdays_from_required_start :
        Weekdays from :data:`REQUIRED_START` (or the first date, if later) to
        ``last_date`` with no row. UK holidays are not removed, so a handful
        is expected.
    covers_development_sample :
        ``first_date <= REQUIRED_START``.
    error :
        The access error message, if the request failed (e.g. no entitlement).
    """

    ric: str
    rows: int
    first_date: dt.date | None
    last_date: dt.date | None
    columns: tuple[str, ...]
    non_null: dict[str, int]
    missing_weekdays_from_required_start: int | None
    covers_development_sample: bool
    error: str | None = None


def coverage_from_frame(ric: str, frame: pd.DataFrame) -> CoverageReport:
    """Reduce a fetched history to a :class:`CoverageReport`, dropping values.

    Parameters
    ----------
    ric :
        Instrument code.
    frame :
        History as returned by ``lseg.data.get_history``: a DatetimeIndex and
        one column per field.
    """
    if frame.empty:
        return CoverageReport(ric, 0, None, None, (), {}, None, False)
    dates = pd.DatetimeIndex(frame.index).normalize()
    first, last = dates.min().date(), dates.max().date()
    non_null = {str(column): int(frame[column].notna().sum()) for column in frame}
    window_start = max(first, REQUIRED_START)
    weekdays = pd.bdate_range(window_start, last)
    missing = len(weekdays.difference(dates))
    return CoverageReport(
        ric=ric,
        rows=len(frame),
        first_date=first,
        last_date=last,
        columns=tuple(str(column) for column in frame.columns),
        non_null=non_null,
        missing_weekdays_from_required_start=missing,
        covers_development_sample=first <= REQUIRED_START,
    )


def _get_history(ric: str, start: dt.date, end: dt.date) -> pd.DataFrame:
    """Fetch daily history through an LSEG desktop session.

    Kept separate so tests can replace it; the key is read here and passed
    straight to the library.
    """
    # lseg-data ships without type information; imported lazily (live pulls only).
    import lseg.data as ld  # type: ignore[import-untyped]

    load_dotenv()
    app_key = os.environ.get(APP_KEY_ENV)
    if not app_key:
        msg = (
            f"set {APP_KEY_ENV} (in .env or the environment) to a Workspace "
            "application key; LSEG Workspace must be running"
        )
        raise RuntimeError(msg)
    ld.open_session(app_key=app_key)
    try:
        history: Any = ld.get_history(
            universe=ric,
            interval="daily",
            start=start.isoformat(),
            end=end.isoformat(),
        )
    finally:
        ld.close_session()
    return pd.DataFrame(history)


def probe_history_coverage(
    ric: str,
    *,
    start: dt.date = dt.date(2015, 1, 1),
    end: dt.date | None = None,
) -> CoverageReport:
    """Report a series' date coverage without returning any price value.

    The fetched frame lives only inside this function and is reduced by
    :func:`coverage_from_frame` before return. Nothing is cached.

    Parameters
    ----------
    ric :
        Instrument code, e.g. ``"PNX-NBPEOD-DA"``.
    start, end :
        Request window; ``start`` is early so the true first date shows.
    """
    end = end or dt.datetime.now(tz=dt.UTC).date()
    try:
        frame = _get_history(ric, start, end)
    except Exception as error:  # any access failure (entitlement, session) is reported
        return CoverageReport(
            ric, 0, None, None, (), {}, None, False, error=str(error)[:300]
        )
    report = coverage_from_frame(ric, frame)
    del frame
    return report
