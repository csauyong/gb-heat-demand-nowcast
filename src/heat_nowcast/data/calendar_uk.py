"""UK bank holidays, by nation.

England & Wales and Scotland keep different bank holidays, and the difference
is not cosmetic for a GB demand model: 2 January is a Scottish holiday and not
an English one, and the English late-summer holiday falls a week after the
Scottish one. A single "UK holiday" flag gets both wrong.
"""

from __future__ import annotations

import datetime as dt
from typing import Final

import pandas as pd
import requests

from heat_nowcast.data.cache import cached_pull

BANK_HOLIDAYS_URL: Final[str] = "https://www.gov.uk/bank-holidays.json"
_TIMEOUT: Final[int] = 60

#: gov.uk division keys. Northern Ireland is excluded: NESO National Demand is
#: a GB series.
GB_DIVISIONS: Final[tuple[str, ...]] = ("england-and-wales", "scotland")


def load_uk_bank_holidays(
    *,
    vintage: str = "2026-08-14",
    refresh: bool = False,
) -> pd.DataFrame:
    """Load GB bank holidays by nation.

    Source: https://www.gov.uk/bank-holidays.json
    Licence: Open Government Licence v3.0.
    Vintage: downloaded {vintage}. The feed carries a rolling window of past
        and announced future holidays.
    Publication lag: bank holidays are announced years ahead and are known to
        every market participant well before the delivery day, so the flag is
        legal at any prediction timestamp. Substitute days for royal or
        one-off events (for example the 2022 state funeral and the 2023
        coronation) were announced only weeks ahead; both fall inside the
        training period rather than the 2024-2026 evaluation window, so they
        raise no point-in-time issue here.

    Parameters
    ----------
    vintage :
        Vintage label; also the cache key.
    refresh :
        Force a re-pull.

    Returns
    -------
    pandas.DataFrame
        Columns ``date`` (naive London date), ``division``, ``title``.
    """

    def fetch() -> tuple[pd.DataFrame, list[str]]:
        response = requests.get(BANK_HOLIDAYS_URL, timeout=_TIMEOUT)
        response.raise_for_status()
        payload = response.json()
        rows = [
            {
                "date": event["date"],
                "division": division,
                "title": event["title"],
            }
            for division in GB_DIVISIONS
            for event in payload[division]["events"]
        ]
        frame = pd.DataFrame(rows)
        frame["date"] = pd.to_datetime(frame["date"])
        return frame, [BANK_HOLIDAYS_URL]

    return cached_pull(
        dataset="uk_bank_holidays",
        vintage=vintage,
        licence="Open Government Licence v3.0",
        publication_lag=("Announced years ahead; legal at any prediction timestamp."),
        fetch=fetch,
        params={"divisions": list(GB_DIVISIONS)},
        notes="England & Wales and Scotland differ; both are kept separately.",
        refresh=refresh,
    )


def holiday_flags(
    dates: pd.Series,
    holidays: pd.DataFrame,
) -> pd.DataFrame:
    """Build per-nation and combined bank-holiday flags for a series of dates.

    Parameters
    ----------
    dates :
        Naive London calendar dates.
    holidays :
        Frame from :func:`load_uk_bank_holidays`.

    Returns
    -------
    pandas.DataFrame
        Columns ``is_holiday_ew``, ``is_holiday_scotland``, ``is_holiday_any``,
        aligned to ``dates`` by position.
    """
    normalised = pd.to_datetime(pd.Series(dates).to_numpy()).normalize()
    lookup = {
        division: set(
            holidays.loc[holidays["division"] == division, "date"]
            .dt.normalize()
            .to_numpy()
        )
        for division in GB_DIVISIONS
    }
    flags = pd.DataFrame(index=pd.RangeIndex(len(normalised)))
    flags["is_holiday_ew"] = [d in lookup["england-and-wales"] for d in normalised]
    flags["is_holiday_scotland"] = [d in lookup["scotland"] for d in normalised]
    flags["is_holiday_any"] = flags["is_holiday_ew"] | flags["is_holiday_scotland"]
    return flags


def christmas_period_flag(dates: pd.Series) -> pd.Series:
    """Flag the 24 December to 1 January period.

    GB demand between Christmas and New Year is a distinct regime that bank
    holiday flags alone do not capture -- much of the commercial and
    industrial load simply stops for the whole week, not only on the two
    statutory days.
    """
    normalised = pd.to_datetime(pd.Series(dates).to_numpy()).normalize()
    month = normalised.month
    day = normalised.day
    return pd.Series(
        ((month == 12) & (day >= 24)) | ((month == 1) & (day <= 1)),
        index=pd.RangeIndex(len(normalised)),
    )


def uk_season(dates: pd.Series) -> pd.Series:
    """Map dates to meteorological seasons.

    Winter is December-February, spring March-May, summer June-August, autumn
    September-November. Used to break the error tables out by season.
    """
    normalised = pd.to_datetime(pd.Series(dates).to_numpy()).normalize()
    month_to_season = {
        12: "winter",
        1: "winter",
        2: "winter",
        3: "spring",
        4: "spring",
        5: "spring",
        6: "summer",
        7: "summer",
        8: "summer",
        9: "autumn",
        10: "autumn",
        11: "autumn",
    }
    return pd.Series(
        [month_to_season[m] for m in normalised.month],
        index=pd.RangeIndex(len(normalised)),
        dtype="object",
    )


def day_type(dates: pd.Series, holidays: pd.DataFrame) -> pd.Series:
    """Classify each date as ``weekday``, ``saturday``, ``sunday`` or ``holiday``.

    A bank holiday in either nation overrides the weekday label, because that
    is what the demand profile does.
    """
    normalised = pd.to_datetime(pd.Series(dates).to_numpy()).normalize()
    flags = holiday_flags(dates, holidays)
    weekday = normalised.dayofweek
    labels: list[str] = []
    for position, day_of_week in enumerate(weekday):
        if bool(flags["is_holiday_any"].iloc[position]):
            labels.append("holiday")
        elif day_of_week == 5:
            labels.append("saturday")
        elif day_of_week == 6:
            labels.append("sunday")
        else:
            labels.append("weekday")
    return pd.Series(labels, index=pd.RangeIndex(len(normalised)), dtype="object")


def latest_complete_settlement_date(as_of: dt.date, lag_days: int = 2) -> dt.date:
    """Return the most recent settlement date whose outturn should be published.

    NESO's historic demand appears roughly a day after the settlement day;
    ``lag_days`` defaults to 2 to stay clear of the boundary.
    """
    return as_of - dt.timedelta(days=lag_days)
