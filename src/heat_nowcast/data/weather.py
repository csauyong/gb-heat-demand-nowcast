"""Temperature loaders: archived *forecast* weather, and realised weather.

The distinction between these two functions is the most important thing in the
package (`CLAUDE.md` §2.1).

``load_forecast_temperature``
    What the weather model **said at the time**, at a fixed forecast lead.
    Point-in-time legal. This is the only temperature that may drive a result
    reported as a forecast or a signal.

``load_realised_temperature``
    What the weather **actually did**, from ERA5 reanalysis. Not knowable at
    prediction time -- ERA5 has a ~5-day preliminary lag and a ~2-3 month
    final release that silently overwrites it. Sanctioned uses are exactly
    two: model-error decomposition, and oracle upper bounds. Columns it
    produces carry a ``_realised`` suffix and call sites carry the literal
    marker ``REALISED-WEATHER-DIAGNOSTIC``.

Which Open-Meteo endpoint gives point-in-time forecast weather
-------------------------------------------------------------
``docs/data_inventory.md`` §5.1 points at the **Historical Forecast API**.
That endpoint was tested on 2026-08-14 and is *not* usable as a fixed-lead
archive for this project:

* it archives the *most recent* forecast for each timestamp, i.e. a rolling
  0-24 hour lead. For a timestamp at 18:00 on delivery day D, the value comes
  from a model run initialised on day D -- long after the 08:45 UTC on D-1
  decision point at which NESO publishes. Scoring a baseline built on it
  against NESO's day-ahead forecast would hand the baseline a later, better
  weather forecast than the competitor had. That is a leak, and a large one;
* its ``temperature_2m_previous_dayN`` fields return all-null.

The **Previous Model Runs API** at ``previous-runs-api.open-meteo.com`` does
provide a fixed lead: ``temperature_2m_previous_day1`` is the forecast for a
timestamp taken from the model run of the previous day. Same provider, same
CC-BY-4.0 licence, same free tier -- a different endpoint of an inventoried
source, chosen because it is the *less* permissive one. Its archive was
bisected on 2026-08-14 and **begins 2024-02-04**, not 2021. That is the
binding constraint on the point-in-time evaluation window and it is reported
as such in ``reports/phase1_findings.md``.

Residual caveat, stated rather than hidden: Open-Meteo documents
``previous_day1`` as "the forecast initialised one day earlier" but does not
publish the initialisation *hour*. If that snapshot is taken from a 12Z run on
D-1 rather than a 00Z run, it lands after NESO's 08:45 UTC publication and the
lead-1 series is very slightly optimistic. ``lead_days`` is therefore a
parameter, and ``lead_days=2`` is the strictly-safe variant used as a
sensitivity check.
"""

from __future__ import annotations

import datetime as dt
from typing import Final

import pandas as pd
import requests

from heat_nowcast.data.cache import cached_pull

_TIMEOUT: Final[int] = 300

PREVIOUS_RUNS_URL: Final[str] = "https://previous-runs-api.open-meteo.com/v1/forecast"
ARCHIVE_URL: Final[str] = "https://archive-api.open-meteo.com/v1/archive"
HISTORICAL_FORECAST_URL: Final[str] = (
    "https://historical-forecast-api.open-meteo.com/v1/forecast"
)

OPEN_METEO_LICENCE: Final[str] = (
    "CC BY 4.0 -- attribution 'Weather data by Open-Meteo.com' required; "
    "free tier is non-commercial, <=10,000 API calls/day"
)

#: First date for which the Previous Model Runs archive returns non-null
#: values, established by bisection on 2026-08-14 at 51.5N 0.12W.
PREVIOUS_RUNS_ARCHIVE_START: Final[dt.date] = dt.date(2024, 2, 4)

_LOCATIONS_PER_REQUEST: Final[int] = 10


def _chunk_years(start: dt.date, end: dt.date) -> list[tuple[dt.date, dt.date]]:
    """Split a date range into calendar-year chunks, inclusive of both ends."""
    chunks: list[tuple[dt.date, dt.date]] = []
    cursor = start
    while cursor <= end:
        year_end = dt.date(cursor.year, 12, 31)
        chunks.append((cursor, min(year_end, end)))
        cursor = year_end + dt.timedelta(days=1)
    return chunks


def _fetch_open_meteo(
    url: str,
    points: pd.DataFrame,
    start: dt.date,
    end: dt.date,
    hourly_variable: str,
    value_column: str,
) -> tuple[pd.DataFrame, list[str]]:
    """Fetch one hourly variable for many points, chunked by location and year.

    Open-Meteo accepts comma-separated ``latitude``/``longitude`` and returns a
    JSON array in the same order, so location chunking is a straight zip.
    """
    frames: list[pd.DataFrame] = []
    urls: list[str] = []
    ordered = points.sort_values("point_id").reset_index(drop=True)

    for block_start in range(0, len(ordered), _LOCATIONS_PER_REQUEST):
        block = ordered.iloc[block_start : block_start + _LOCATIONS_PER_REQUEST]
        for chunk_start, chunk_end in _chunk_years(start, end):
            params = {
                "latitude": ",".join(f"{v:.4f}" for v in block["latitude"]),
                "longitude": ",".join(f"{v:.4f}" for v in block["longitude"]),
                "start_date": chunk_start.isoformat(),
                "end_date": chunk_end.isoformat(),
                "hourly": hourly_variable,
                "timezone": "UTC",
            }
            response = requests.get(url, params=params, timeout=_TIMEOUT)
            response.raise_for_status()
            urls.append(response.url)
            payload = response.json()
            if isinstance(payload, dict):
                payload = [payload]
            for point_id, location in zip(block["point_id"], payload, strict=True):
                hourly = location["hourly"]
                frames.append(
                    pd.DataFrame(
                        {
                            "time_utc": pd.to_datetime(hourly["time"], utc=True),
                            "point_id": point_id,
                            value_column: pd.to_numeric(
                                pd.Series(hourly[hourly_variable]), errors="coerce"
                            ),
                        }
                    )
                )

    combined = pd.concat(frames, ignore_index=True)
    return combined, urls


def load_forecast_temperature(
    points: pd.DataFrame,
    start: dt.date,
    end: dt.date,
    *,
    lead_days: int = 1,
    vintage: str = "2026-08-14",
    refresh: bool = False,
) -> pd.DataFrame:
    """Load archived **forecast** 2 m temperature at a fixed forecast lead.

    Source: https://previous-runs-api.open-meteo.com/v1/forecast
        (Open-Meteo Previous Model Runs API; variable
        ``temperature_2m_previous_day{lead_days}``). Documented at
        https://open-meteo.com/en/docs/previous-runs-api
    Licence: CC BY 4.0. "Weather data by Open-Meteo.com" must appear in any
        published output (``docs/data_inventory.md`` §11). Free tier is
        non-commercial, capped at ~10,000 calls/day.
    Vintage: downloaded {vintage}. The archive is append-only; values for past
        dates are the model runs as issued and are not restated.
    Publication lag: **none, by construction** -- these are the values the
        model published at the time. With ``lead_days=1`` the value for a
        timestamp on delivery day D comes from a model run on D-1, so it is
        knowable during D-1. See the module docstring for the residual
        uncertainty about the run *hour* within D-1.

    Parameters
    ----------
    points :
        Frame with ``point_id``, ``latitude``, ``longitude``.
    start, end :
        Inclusive date bounds. ``start`` earlier than
        ``PREVIOUS_RUNS_ARCHIVE_START`` raises, rather than silently returning
        nulls that would later be dropped without anyone noticing.
    lead_days :
        Forecast lead in whole days. 1 is the day-ahead lead that matches
        NESO's published forecast; 2 is the strictly-safe sensitivity variant.
    vintage :
        Vintage label; also part of the cache key.
    refresh :
        Force a re-pull.

    Returns
    -------
    pandas.DataFrame
        Long frame with ``time_utc`` (UTC-aware, hourly), ``point_id`` and
        ``temp_c_forecast``.

    Raises
    ------
    ValueError
        If ``start`` predates the Previous Model Runs archive, or
        ``lead_days`` is outside 1..7.
    """
    if not 1 <= lead_days <= 7:
        msg = "lead_days must lie in [1, 7]"
        raise ValueError(msg)
    if start < PREVIOUS_RUNS_ARCHIVE_START:
        msg = (
            f"Open-Meteo previous-runs archive starts "
            f"{PREVIOUS_RUNS_ARCHIVE_START.isoformat()}; requested start "
            f"{start.isoformat()} would return nulls. Point-in-time forecast "
            f"weather does not exist before that date -- shorten the window "
            f"rather than back-filling with realised weather."
        )
        raise ValueError(msg)

    variable = f"temperature_2m_previous_day{lead_days}"

    def fetch() -> tuple[pd.DataFrame, list[str]]:
        return _fetch_open_meteo(
            PREVIOUS_RUNS_URL, points, start, end, variable, "temp_c_forecast"
        )

    return cached_pull(
        dataset=(
            f"openmeteo_forecast_temp_lead{lead_days}_"
            f"{start.isoformat()}_{end.isoformat()}_n{len(points)}"
        ),
        vintage=vintage,
        licence=OPEN_METEO_LICENCE,
        publication_lag=(
            f"None by construction: archived forecast at a fixed lead of "
            f"{lead_days} day(s); knowable on D-{lead_days}."
        ),
        fetch=fetch,
        params={
            "endpoint": PREVIOUS_RUNS_URL,
            "variable": variable,
            "lead_days": lead_days,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "n_points": len(points),
        },
        notes="POINT-IN-TIME LEGAL. Archived forecast weather at fixed lead.",
        refresh=refresh,
    )


def load_realised_temperature(
    points: pd.DataFrame,
    start: dt.date,
    end: dt.date,
    *,
    vintage: str = "2026-08-14",
    refresh: bool = False,
) -> pd.DataFrame:
    """Load **realised** ERA5 2 m temperature. Diagnostic and oracle use only.

    REALISED-WEATHER-DIAGNOSTIC -- this function returns weather that was not
    knowable at prediction time. It must never drive a headline forecast or a
    signal (`CLAUDE.md` §2.1). Its column is named ``temp_c_realised`` so that
    a leak is visible at every downstream call site.

    Source: https://archive-api.open-meteo.com/v1/archive
        (Open-Meteo Historical Weather API, ERA5/ERA5-Land backed;
        ``docs/data_inventory.md`` §5.2).
    Licence: CC BY 4.0 for the Open-Meteo service; the underlying reanalysis
        is Copernicus, requiring "Generated using Copernicus Climate Change
        Service information".
    Vintage: downloaded {vintage}. ERA5 is **not reproducible without this
        date**: the preliminary ERA5T release (~5 days behind real time) is
        silently overwritten by the quality-controlled final release ~2-3
        months later.
    Publication lag: ~5 days for ERA5T preliminary, ~2-3 months for final.
        The 5-day lag alone disqualifies it from any nowcast. Legal uses:
        (a) training a model on data far enough in the past that ERA5 had
        published by the fit date -- enforced downstream by the walk-forward
        embargo; (b) oracle runs establishing the ceiling a perfect weather
        forecast would allow.

    Parameters
    ----------
    points :
        Frame with ``point_id``, ``latitude``, ``longitude``.
    start, end :
        Inclusive date bounds.
    vintage :
        Vintage label; also part of the cache key. Do not omit it -- see the
        restatement note above.
    refresh :
        Force a re-pull.

    Returns
    -------
    pandas.DataFrame
        Long frame with ``time_utc`` (UTC-aware, hourly), ``point_id`` and
        ``temp_c_realised``.
    """

    def fetch() -> tuple[pd.DataFrame, list[str]]:
        return _fetch_open_meteo(
            ARCHIVE_URL, points, start, end, "temperature_2m", "temp_c_realised"
        )

    return cached_pull(
        dataset=(
            f"openmeteo_realised_temp_{start.isoformat()}_"
            f"{end.isoformat()}_n{len(points)}"
        ),
        vintage=vintage,
        licence=OPEN_METEO_LICENCE + "; underlying reanalysis (C) Copernicus",
        publication_lag=(
            "~5 days (ERA5T preliminary), ~2-3 months (final, overwrites "
            "preliminary). Disqualified from any nowcast."
        ),
        fetch=fetch,
        params={
            "endpoint": ARCHIVE_URL,
            "variable": "temperature_2m",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "n_points": len(points),
        },
        notes=(
            "REALISED-WEATHER-DIAGNOSTIC. Not knowable at prediction time. "
            "Diagnostic decomposition and oracle upper bounds only."
        ),
        refresh=refresh,
    )
