"""NESO Data Portal loaders: demand outturn and the published day-ahead forecast.

Two series matter for Phase 1.

* ``load_neso_historic_demand`` -- half-hourly National Demand (ND) and
  Transmission System Demand (TSD) outturn, one CKAN resource per calendar
  year. This is the long history.
* ``load_neso_day_ahead_forecast_performance`` -- NESO's own scoring file for
  its published day-ahead forecast. It carries the forecast, the outturn NESO
  scores itself against, **and the publication timestamp**, which is the field
  that makes a point-in-time comparison possible at all.

The second is the one Phase 1 scores against, because it is the only NESO
product that pairs a half-hourly published forecast with a publication
timestamp. The `1-day-ahead-demand-forecast` resource that the data inventory
points at (``historic_day_ahead_demand_forecasts``) was inspected on
2026-08-14 and turned out to be **cardinal points, not a half-hourly series**
-- roughly 19 rows per day keyed by ``CARDINALPOINT`` (peaks, troughs and
named period ranges), not 48. It cannot be scored half-hourly against a
half-hourly baseline, so it is not used here. See
`reports/phase1_findings.md`.
"""

from __future__ import annotations

import io
from typing import Any, Final
from urllib.parse import urlencode

import pandas as pd
import requests

from heat_nowcast.data.cache import cached_pull
from heat_nowcast.timeutils import LONDON, UTC, settlement_period_to_utc

CKAN_BASE: Final[str] = "https://api.neso.energy/api/3/action"
NESO_LICENCE: Final[str] = (
    "NESO Open Data Licence (OGL-compatible, attribution required)"
)

#: Resource id of "Day Ahead Half Hourly Demand Forecast Performance".
DA_PERFORMANCE_RESOURCE_ID: Final[str] = "08e41551-80f8-4e28-a416-ea473a695db9"

#: CKAN resource ids for "Historic Demand Data", one per calendar year.
#: Captured from ``package_show?id=historic-demand-data`` on 2026-08-14.
HISTORIC_DEMAND_RESOURCE_IDS: Final[dict[int, str]] = {
    2019: "dd9de980-d724-415a-b344-d8ae11321432",
    2020: "33ba6857-2a55-479f-9308-e5c4c53d4381",
    2021: "18c69c42-f20d-46f0-84e9-e279045befc6",
    2022: "bb44a1b5-75b1-4db2-8491-257f23385006",
    2023: "bf5ab335-9b40-4ea4-b93a-ab4af7bce003",
    2024: "f6d02c0f-957b-48cb-82ee-09003f2ba759",
    2025: "b2bde559-3455-4021-b179-dfe60c0337b0",
    2026: "8a4a771c-3929-4e56-93ad-cdf13219dea5",
}

_TIMEOUT: Final[int] = 180


def _datastore_dump_url(resource_id: str) -> str:
    """Return the CKAN datastore CSV dump URL for a resource."""
    return f"https://api.neso.energy/datastore/dump/{resource_id}?bom=true"


def _fetch_csv(url: str) -> pd.DataFrame:
    """GET a CSV endpoint and parse it, raising on a non-200."""
    response = requests.get(url, timeout=_TIMEOUT)
    response.raise_for_status()
    return pd.read_csv(io.StringIO(response.text))


#: NESO's historic demand resources are not consistent about date format --
#: the per-year CSVs were produced by different exports. As at 2026-08-14 the
#: 2021-2026 files contain all three of these. They are tried in order and any
#: value that matches none of them raises, because a silent fallback to
#: `dateutil` inference is exactly how a whole year of demand ends up shifted
#: by an unnoticed offset.
_SETTLEMENT_DATE_FORMATS: Final[tuple[str, ...]] = (
    "%Y-%m-%d",  # 2021, 2022, 2024: ISO
    "%d-%b-%Y",  # 2025, 2026: Oracle-style, four-digit year
    "%d-%b-%y",  # 2023: Oracle-style, two-digit year
)


def _parse_settlement_date(values: pd.Series) -> pd.Series:
    """Parse NESO settlement dates across every format the portal emits.

    See :data:`_SETTLEMENT_DATE_FORMATS`. Unparsed values raise rather than
    becoming ``NaT``, which would silently drop rows from the panel.
    """
    text = values.astype("string").str.strip()
    combined = pd.Series(pd.NaT, index=text.index, dtype="datetime64[ns]")
    for date_format in _SETTLEMENT_DATE_FORMATS:
        remaining = combined.isna()
        if not remaining.any():
            break
        parsed = pd.to_datetime(text[remaining], format=date_format, errors="coerce")
        combined[remaining] = parsed

    unparsed = int(combined.isna().sum())
    if unparsed:
        sample = text[combined.isna()].head(3).tolist()
        msg = (
            f"{unparsed} settlement dates matched none of "
            f"{_SETTLEMENT_DATE_FORMATS}; examples: {sample}"
        )
        raise ValueError(msg)
    normalised: pd.Series = combined.dt.normalize()
    return normalised


def _resource_last_modified(resource_id: str) -> str:
    """Return the upstream ``last_modified`` for a CKAN resource, as a vintage."""
    query = urlencode({"id": resource_id})
    response = requests.get(f"{CKAN_BASE}/resource_show?{query}", timeout=_TIMEOUT)
    response.raise_for_status()
    result: dict[str, Any] = response.json()["result"]
    stamp = result.get("last_modified") or result.get("created") or "unknown"
    return str(stamp)[:10]


def load_neso_day_ahead_forecast_performance(
    *,
    vintage: str = "2026-08-14",
    refresh: bool = False,
) -> pd.DataFrame:
    """Load NESO's published day-ahead demand forecast together with its outturn.

    Source: https://www.neso.energy/data-portal/day-ahead-half-hourly-demand-forecast-performance
        CKAN resource id ``08e41551-80f8-4e28-a416-ea473a695db9``, fetched via
        ``https://api.neso.energy/datastore/dump/<resource_id>``.
    Licence: NESO Open Data Licence, OGL-compatible, attribution required
        (see ``docs/data_inventory.md`` §2).
    Vintage: downloaded {vintage}; upstream resource ``last_modified``
        2026-08-14T09:15:09Z. Coverage 2021-04-01 to 2026-08-14, 94,145
        half-hourly rows.
    Publication lag: the ``Publish_Datetime`` column gives the exact
        publication instant per delivery day, and every row in the file is
        published on D-1 for delivery day D. Inspection of the file on
        2026-08-14 shows the publication time is fixed in **UTC**, not in
        London local time: January rows carry 08:45 and July rows carry 09:45
        in the file's own London-local clock, i.e. 08:45 UTC in both cases. A
        later regime publishes at 08:33 UTC. The forecast for delivery day D
        is therefore knowable from **08:45 UTC on D-1** and must not enter any
        prediction timestamped before that.

    Returns
    -------
    pandas.DataFrame
        One row per settlement period with columns:

        ``settlement_datetime``
            UTC instant at the **end** of the settlement period.
        ``settlement_date``
            London calendar date of the settlement day (naive).
        ``settlement_period``
            1-based settlement period, 1..50.
        ``neso_da_forecast_mw``
            NESO's published day-ahead national demand forecast.
        ``demand_outturn_mw``
            The outturn NESO scores itself against. This is the scoring target
            used in Phase 1 so that both forecasts are judged on identical
            rows against an identical truth (`CLAUDE.md` §4).
        ``demand_outturn_triad_corrected_mw``
            Outturn with NESO's TRIAD-avoidance correction applied.
        ``neso_publish_datetime``
            UTC instant at which the forecast became public.

    Notes
    -----
    ``Demand_Outturn`` here is NESO's own restated outturn as of the download
    date, not a point-in-time first publication. `CLAUDE.md` §2.2 requires
    this be stated rather than hidden: restatement contamination is present in
    the *target*, affects both forecasts identically, and therefore cannot
    flatter the baseline relative to NESO.
    """

    def fetch() -> tuple[pd.DataFrame, list[str]]:
        url = _datastore_dump_url(DA_PERFORMANCE_RESOURCE_ID)
        raw = _fetch_csv(url)
        return raw, [url]

    raw = cached_pull(
        dataset="neso_da_forecast_performance",
        vintage=vintage,
        licence=NESO_LICENCE,
        publication_lag=(
            "Published D-1 at a fixed 08:45 UTC (08:33 UTC in the later "
            "regime) for delivery day D; see Publish_Datetime column."
        ),
        fetch=fetch,
        params={"resource_id": DA_PERFORMANCE_RESOURCE_ID},
        notes=(
            "Half-hourly published day-ahead forecast paired with NESO's own "
            "outturn and publication timestamp. Coverage starts 2021-04-01."
        ),
        refresh=refresh,
    )

    frame = pd.DataFrame(
        {
            "settlement_date": _parse_settlement_date(raw["Date"]),
            "settlement_period": raw["Settlement_Period"].astype("int64"),
            "neso_da_forecast_mw": pd.to_numeric(
                raw["Demand_Forecast"], errors="coerce"
            ),
            "demand_outturn_mw": pd.to_numeric(raw["Demand_Outturn"], errors="coerce"),
            "demand_outturn_triad_corrected_mw": pd.to_numeric(
                raw["TRIAD_Avoidance_Corrected_Demand_Outturn"], errors="coerce"
            ),
        }
    )
    frame["settlement_datetime"] = settlement_period_to_utc(
        frame["settlement_date"], frame["settlement_period"]
    )
    # Publish_Datetime is London wall-clock in the file; convert to UTC so the
    # point-in-time gate is expressed in absolute time.
    publish_local = pd.to_datetime(raw["Publish_Datetime"])
    frame["neso_publish_datetime"] = (
        pd.DatetimeIndex(publish_local)
        .tz_localize(LONDON, ambiguous=True, nonexistent="shift_forward")
        .tz_convert(UTC)
    )

    ordered = [
        "settlement_datetime",
        "settlement_date",
        "settlement_period",
        "neso_da_forecast_mw",
        "demand_outturn_mw",
        "demand_outturn_triad_corrected_mw",
        "neso_publish_datetime",
    ]
    return (
        frame[ordered]
        .sort_values("settlement_datetime")
        .drop_duplicates("settlement_datetime", keep="last")
        .reset_index(drop=True)
    )


def load_neso_historic_demand(
    *,
    years: tuple[int, ...] = (2021, 2022, 2023, 2024, 2025, 2026),
    vintage: str = "2026-08-14",
    refresh: bool = False,
) -> pd.DataFrame:
    """Load NESO half-hourly historic GB demand outturn (ND and TSD).

    Source: https://www.neso.energy/data-portal/historic-demand-data
        One CKAN resource per calendar year; ids in
        ``HISTORIC_DEMAND_RESOURCE_IDS``, captured from
        ``package_show?id=historic-demand-data`` on 2026-08-14. Fetched via
        ``https://api.neso.energy/datastore/dump/<resource_id>``.
    Licence: NESO Open Data Licence, OGL-compatible, attribution required
        (see ``docs/data_inventory.md`` §2.1).
    Vintage: downloaded {vintage}. Per-resource upstream ``last_modified`` is
        recorded in each sidecar under ``params.upstream_last_modified``.
    Publication lag: initial values appear roughly one day after the
        settlement day. **The series is restated** -- embedded wind and solar
        estimates in particular are revised, and NESO does not publish a
        vintage archive. Any backtest using this series carries restatement
        contamination and must say so (`CLAUDE.md` §2.2).

    Parameters
    ----------
    years :
        Calendar years to load and concatenate.
    vintage :
        Vintage label; also the cache key.
    refresh :
        Force a re-pull. Comparing the resulting sidecar ``content_sha256``
        against the previous one is how restatement is detected.

    Returns
    -------
    pandas.DataFrame
        Columns ``settlement_datetime`` (UTC, period end), ``settlement_date``
        (London, naive), ``settlement_period``, ``nd_mw``, ``tsd_mw``,
        ``embedded_wind_mw``, ``embedded_solar_mw``.

    Notes
    -----
    Neither ND nor TSD is domestic heat demand. Both are transmission-metered
    and therefore net of embedded generation and of everything behind the
    distribution boundary (``docs/data_inventory.md`` §2.1). Phase 1 uses this
    series only to reconcile against the outturn in the forecast-performance
    file; it is not the Phase 1 scoring target.
    """
    missing = [year for year in years if year not in HISTORIC_DEMAND_RESOURCE_IDS]
    if missing:
        msg = f"no known CKAN resource id for year(s) {missing}"
        raise KeyError(msg)

    # `cached_pull` builds the sidecar *after* calling `fetch`, so the upstream
    # `last_modified` lookup is done inside `fetch` and written into this dict.
    # That keeps the cache-hit path free of network I/O, which is what makes
    # the loader idempotent rather than merely repeatable.
    params: dict[str, Any] = {
        "years": list(years),
        "resource_ids": {str(y): HISTORIC_DEMAND_RESOURCE_IDS[y] for y in years},
    }

    def fetch() -> tuple[pd.DataFrame, list[str]]:
        parts: list[pd.DataFrame] = []
        urls: list[str] = []
        for year in years:
            resource_id = HISTORIC_DEMAND_RESOURCE_IDS[year]
            url = _datastore_dump_url(resource_id)
            parts.append(_fetch_csv(url))
            urls.append(url)
        params["upstream_last_modified"] = {
            str(year): _resource_last_modified(HISTORIC_DEMAND_RESOURCE_IDS[year])
            for year in years
        }
        return pd.concat(parts, ignore_index=True), urls

    raw = cached_pull(
        dataset=f"neso_historic_demand_{years[0]}_{years[-1]}",
        vintage=vintage,
        licence=NESO_LICENCE,
        publication_lag=(
            "~1 day for initial values; series is restated afterwards and "
            "NESO publishes no vintage archive."
        ),
        fetch=fetch,
        params=params,
        notes="ND and TSD are transmission-metered; neither is domestic heat demand.",
        refresh=refresh,
    )

    frame = pd.DataFrame(
        {
            "settlement_date": _parse_settlement_date(raw["SETTLEMENT_DATE"]),
            "settlement_period": raw["SETTLEMENT_PERIOD"].astype("int64"),
            "nd_mw": pd.to_numeric(raw["ND"], errors="coerce"),
            "tsd_mw": pd.to_numeric(raw["TSD"], errors="coerce"),
            "embedded_wind_mw": pd.to_numeric(
                raw["EMBEDDED_WIND_GENERATION"], errors="coerce"
            ),
            "embedded_solar_mw": pd.to_numeric(
                raw["EMBEDDED_SOLAR_GENERATION"], errors="coerce"
            ),
        }
    )
    frame = frame[frame["settlement_period"].between(1, 50)]
    frame["settlement_datetime"] = settlement_period_to_utc(
        frame["settlement_date"], frame["settlement_period"]
    )
    ordered = [
        "settlement_datetime",
        "settlement_date",
        "settlement_period",
        "nd_mw",
        "tsd_mw",
        "embedded_wind_mw",
        "embedded_solar_mw",
    ]
    return (
        frame[ordered]
        .sort_values("settlement_datetime")
        .drop_duplicates("settlement_datetime", keep="last")
        .reset_index(drop=True)
    )
