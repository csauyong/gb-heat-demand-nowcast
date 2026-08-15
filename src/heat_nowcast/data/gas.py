"""National Gas Transmission LDZ loaders: offtake actuals, the D-1 forecast, CWV.

Why this module is the primary target
-------------------------------------
``docs/research_plan.md`` recommends gas LDZ offtakes over electricity as the
validation target, because ~85% of GB homes heat with gas. Phase 1 scored the
secondary target and found the electricity gap dominated by embedded
renewables and transmission metering -- neither of which has a gas analogue.
This module supplies the series that test the primary claim, at Local
Distribution Zone level so that cross-sectional stock heterogeneity is
identifiable rather than integrated away.

Endpoint, and how it was established
------------------------------------
``docs/data_inventory.md`` §4 warns that National Gas was migrating away from
SOAP and instructs the loader author to check current endpoints. Checked on
2026-08-14:

* the legacy MIPI SOAP service at ``marketinformation.natgrid.co.uk`` is
  **dead** -- the connection fails outright, and National Gas confirms the SOAP
  APIs are "permanently decommissioned";
* the documented replacement catalogue lives at
  ``https://apideveloper.nationalgas.com/`` behind account registration;
* the Gas Data Portal at ``https://data.nationalgas.com`` -- which
  ``docs/data_inventory.md`` §4 already names -- serves the same operational
  data anonymously from ``POST /api/find-gas-data``.

This module uses the portal endpoint. It is the inventoried source, it needs no
credentials, and the request shape mirrors the old MIPI
``GetPublicationDataWM`` call it replaced::

    POST https://data.nationalgas.com/api/find-gas-data
    {"latestFlag":"N","applicableFor":"Y","dateFrom":"2025-01-01",
     "dateTo":"2025-12-31","dateType":"GASDAY","ids":"PUBOB609,PUBOB624"}

A ``User-Agent`` header is **required** -- the endpoint returns 403 without
one. Requests identify this project.

The point-in-time trap in this dataset
--------------------------------------
**This is the most important thing in the module and it is easy to get wrong.**

``Demand Forecast, LDZ (XX)`` is not a single daily number. It is republished
roughly eight times per gas day: twice on D-1 (13:15 and 16:15) and then
repeatedly through D itself (00:15, 10:15, 13:15, 16:15, 21:15) plus a final
value at 00:15 on D+1.

The portal's default ``latestFlag=Y`` returns **the last of these** -- the
value generated at 00:15 on D+1, *after the gas day has ended*. Treating that
as "the day-ahead forecast" would be a severe leak: it is a near-outturn
estimate wearing a forecast's name, and it would make the incumbent look
far better than it is while being completely untradeable.

:func:`load_ldz_demand_forecast` therefore pulls ``latestFlag=N`` -- every
publication -- and selects by ``generatedTimeStamp``. See
:class:`ForecastGate`.

Timestamp conventions
---------------------
* ``applicableFor`` is the **gas day** (05:00-05:00 UTC, ``CLAUDE.md`` §2.3),
  rendered ``DD/MM/YYYY``.
* ``generatedTimeStamp`` is the publication instant, rendered
  ``DD/MM/YYYY HH:MM:SS``.

Its timezone is **not determinable from the data**, unlike NESO's. Publication
times are identical in January and July (00:15, 10:15, 13:15, 16:15, 21:15),
which is equally consistent with a London-local clock and a UTC clock -- the
Phase 1 trick of comparing winter and summer renderings cannot separate them
here. The gate is therefore defined on **calendar dates**, not hours, which is
robust to the ambiguity: see :class:`ForecastGate`. Where an hour is needed,
the timestamp is read as London local and that reading is stated.

Units
-----
Demand is published in **mscm** (million standard cubic metres per gas day).
:data:`MSCM_PER_DAY_TO_MW` converts to an average-MW equivalent for comparison
with Phase 1's electricity figures; the conversion is approximate and is only
ever used for presentation, never inside a model.
"""

from __future__ import annotations

import datetime as dt
import json
import time
from enum import StrEnum
from typing import Any, Final, cast

import numpy as np
import pandas as pd
import requests

from heat_nowcast.data.cache import cached_pull

FIND_GAS_DATA_URL: Final[str] = "https://data.nationalgas.com/api/find-gas-data"
FOLDERS_URL: Final[str] = "https://data.nationalgas.com/api/find-gas-data-folders"

#: The endpoint returns 403 without a User-Agent.
USER_AGENT: Final[str] = (
    "gb-heat-demand-nowcast/0.1 (academic research; contact auyongchunsang@gmail.com)"
)

NATIONAL_GAS_LICENCE: Final[str] = (
    "National Gas Transmission Data Portal terms; free to access. Not OGL -- "
    "check portal terms before redistributing derived data "
    "(docs/data_inventory.md §4)."
)

_TIMEOUT: Final[int] = 300
_RETRIES: Final[int] = 3

#: The 13 Local Distribution Zones.
LDZ_CODES: Final[tuple[str, ...]] = (
    "EA",
    "EM",
    "NE",
    "NO",
    "NT",
    "NW",
    "SC",
    "SE",
    "SO",
    "SW",
    "WM",
    "WN",
    "WS",
)

LDZ_NAMES: Final[dict[str, str]] = {
    "EA": "East Anglia",
    "EM": "East Midlands",
    "NE": "North East",
    "NO": "Northern",
    "NT": "North Thames",
    "NW": "North West",
    "SC": "Scotland",
    "SE": "South East",
    "SO": "Southern",
    "SW": "South West",
    "WM": "West Midlands",
    "WN": "Wales North",
    "WS": "Wales South",
}

#: Publication-object ids, harvested from the portal's own catalogue endpoint
#: (``/api/find-gas-data-folders``) on 2026-08-14 and verified 13/13 for every
#: series. Regenerate with :func:`refresh_publication_object_ids`.
PUBLICATION_OBJECTS: Final[dict[str, dict[str, str]]] = {
    "demand_actual_d_plus_1": {
        "EA": "PUBOB624",
        "EM": "PUBOB625",
        "NE": "PUBOB626",
        "NO": "PUBOB627",
        "NT": "PUBOB628",
        "NW": "PUBOB629",
        "SC": "PUBOB630",
        "SE": "PUBOB631",
        "SO": "PUBOB632",
        "SW": "PUBOB633",
        "WM": "PUBOB634",
        "WN": "PUBOB635",
        "WS": "PUBOB636",
    },
    "demand_actual_d_plus_6": {
        "EA": "PUBOB639",
        "EM": "PUBOB640",
        "NE": "PUBOB641",
        "NO": "PUBOB642",
        "NT": "PUBOB643",
        "NW": "PUBOB644",
        "SC": "PUBOB645",
        "SE": "PUBOB646",
        "SO": "PUBOB647",
        "SW": "PUBOB648",
        "WM": "PUBOB649",
        "WN": "PUBOB650",
        "WS": "PUBOB651",
    },
    "demand_forecast": {
        "EA": "PUBOB609",
        "EM": "PUBOB610",
        "NE": "PUBOB611",
        "NO": "PUBOB612",
        "NT": "PUBOB613",
        "NW": "PUBOB614",
        "SC": "PUBOB615",
        "SE": "PUBOB616",
        "SO": "PUBOB617",
        "SW": "PUBOB618",
        "WM": "PUBOB619",
        "WN": "PUBOB620",
        "WS": "PUBOB621",
    },
    "cwv_forecast_d_minus_1": {
        "EA": "PUBOB3726",
        "EM": "PUBOB3727",
        "NE": "PUBOB3728",
        "NO": "PUBOB3729",
        "NT": "PUBOB3730",
        "NW": "PUBOB3731",
        "SC": "PUBOB3734",
        "SE": "PUBOB3732",
        "SO": "PUBOB3733",
        "SW": "PUBOB3735",
        "WM": "PUBOB3736",
        "WN": "PUBOB3737",
        "WS": "PUBOB3738",
    },
    "cwv_actual": {
        "EA": "PUBOB3700",
        "EM": "PUBOB3701",
        "NE": "PUBOB3702",
        "NO": "PUBOB3703",
        "NT": "PUBOB3704",
        "NW": "PUBOB3705",
        "SC": "PUBOB3708",
        "SE": "PUBOB3706",
        "SO": "PUBOB3707",
        "SW": "PUBOB3709",
        "WM": "PUBOB3710",
        "WN": "PUBOB3711",
        "WS": "PUBOB3712",
    },
}

#: Earliest gas day with data, established by probing on 2026-08-14: all five
#: series are empty at 2021-06-01 and populated at 2021-12-01.
GAS_HISTORY_START: Final[dt.date] = dt.date(2021, 12, 1)

#: 1 mscm/day of gas ~= 11.1 GWh/day ~= 462.5 MW average, at a typical GB
#: calorific value of ~39.5 MJ/m3. **Presentation only** -- never used inside a
#: model, and the true calorific value varies by LDZ and by day (the portal
#: publishes it per offtake if it is ever needed properly).
MSCM_PER_DAY_TO_MW: Final[float] = 11_100.0 / 24.0


class ForecastGate(StrEnum):
    """Which publication of a repeatedly-revised forecast counts as "the" forecast.

    Defined on **calendar dates**, not clock hours, because the publication
    timestamp's timezone is not determinable from the data (see the module
    docstring). A date-based gate is correct under either reading.

    Attributes
    ----------
    LAST_ON_D_MINUS_1 :
        The last publication dated on calendar day D-1. This is the closest
        analogue to NESO's day-ahead forecast, which publishes once on D-1, and
        it is the **default and the headline**. In practice this is the 16:15
        publication.
    LAST_BEFORE_GAS_DAY :
        The last publication strictly before the gas day begins (05:00 UTC on
        D). This additionally admits the 00:15 publication dated on day D,
        which genuinely precedes the 05:00 UTC gas-day start. Slightly more
        information, still legal, reported as a sensitivity.
    FIRST_ON_D_MINUS_1 :
        The first publication dated on D-1 (13:15). Strictly the most
        conservative; used to bound how much the incumbent gains from its
        afternoon revision.
    """

    LAST_ON_D_MINUS_1 = "last_on_d_minus_1"
    LAST_BEFORE_GAS_DAY = "last_before_gas_day"
    FIRST_ON_D_MINUS_1 = "first_on_d_minus_1"


def _post(body: dict[str, Any]) -> list[dict[str, Any]]:
    """POST to the find-gas-data endpoint, with retries on transient failures."""
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }
    last_error: Exception | None = None
    for attempt in range(_RETRIES):
        try:
            response = requests.post(
                FIND_GAS_DATA_URL,
                data=json.dumps(body),
                headers=headers,
                timeout=_TIMEOUT,
            )
            response.raise_for_status()
            payload = response.json()
            return list(payload.get("data") or [])
        except (requests.RequestException, ValueError) as error:
            last_error = error
            if attempt < _RETRIES - 1:
                time.sleep(2.0 * (attempt + 1))
    msg = f"find-gas-data failed after {_RETRIES} attempts: {last_error}"
    raise RuntimeError(msg)


def _year_chunks(start: dt.date, end: dt.date) -> list[tuple[dt.date, dt.date]]:
    """Split an inclusive date range into calendar-year chunks."""
    chunks: list[tuple[dt.date, dt.date]] = []
    cursor = start
    while cursor <= end:
        year_end = dt.date(cursor.year, 12, 31)
        chunks.append((cursor, min(year_end, end)))
        cursor = year_end + dt.timedelta(days=1)
    return chunks


def _fetch_series(
    series: str,
    start: dt.date,
    end: dt.date,
    *,
    all_publications: bool,
) -> tuple[pd.DataFrame, list[str]]:
    """Fetch one series for all 13 LDZs, chunked by calendar year.

    Parameters
    ----------
    series :
        Key into :data:`PUBLICATION_OBJECTS`.
    start, end :
        Inclusive gas-day bounds.
    all_publications :
        ``True`` sends ``latestFlag=N`` and returns every publication of every
        gas day -- required for any point-in-time selection. ``False`` sends
        ``latestFlag=Y`` and returns only the final value per gas day, which is
        correct for a settled *actual* and a leak for a *forecast*.
    """
    objects = PUBLICATION_OBJECTS[series]
    id_to_ldz = {object_id: ldz for ldz, object_id in objects.items()}
    ids = ",".join(objects[ldz] for ldz in LDZ_CODES)

    records: list[dict[str, Any]] = []
    urls: list[str] = []
    for chunk_start, chunk_end in _year_chunks(start, end):
        body = {
            "latestFlag": "N" if all_publications else "Y",
            "applicableFor": "Y",
            "dateFrom": chunk_start.isoformat(),
            "dateTo": chunk_end.isoformat(),
            "dateType": "GASDAY",
            "ids": ids,
        }
        records.extend(_post(body))
        urls.append(f"POST {FIND_GAS_DATA_URL} {json.dumps(body, sort_keys=True)}")

    if not records:
        msg = (
            f"no rows returned for series '{series}' over "
            f"{start.isoformat()}..{end.isoformat()}"
        )
        raise RuntimeError(msg)

    frame = pd.DataFrame.from_records(records)
    # `itemName` carries the human name; map back to the LDZ code via the id
    # ordering is unsafe, so parse the code out of the name instead.
    ldz_pattern = rf"LDZ\s*\(({'|'.join(LDZ_CODES)})\)"
    frame["ldz"] = frame["itemName"].str.extract(ldz_pattern)[0]
    unmapped = int(frame["ldz"].isna().sum())
    if unmapped:
        examples = frame.loc[frame["ldz"].isna(), "itemName"].unique()[:3].tolist()
        msg = f"{unmapped} rows had an unparseable LDZ in itemName: {examples}"
        raise ValueError(msg)
    del id_to_ldz

    frame["gas_day"] = pd.to_datetime(
        frame["applicableFor"], format="%d/%m/%Y", errors="coerce"
    )
    frame["generated_at"] = pd.to_datetime(
        frame["generatedTimeStamp"], format="%d/%m/%Y %H:%M:%S", errors="coerce"
    )
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")

    bad = int(frame["gas_day"].isna().sum() + frame["generated_at"].isna().sum())
    if bad:
        msg = f"{bad} rows had unparseable timestamps in series '{series}'"
        raise ValueError(msg)

    keep = ["gas_day", "ldz", "value", "generated_at", "UnitOfMeasure", "itemName"]
    return frame[keep].rename(columns={"UnitOfMeasure": "unit"}), urls


def _assert_full_panel(frame: pd.DataFrame, series: str) -> None:
    """Fail if any LDZ is missing, rather than silently modelling 12 zones.

    Phase 1 lost a third of England & Wales' LSOAs to a silent short page, and
    the loss was geographically correlated. The same failure here would drop a
    whole region from a 13-unit panel and quietly change every fixed effect.
    """
    present = set(frame["ldz"].dropna().unique())
    missing = sorted(set(LDZ_CODES) - present)
    if missing:
        msg = f"series '{series}' is missing LDZ(s) {missing}; refusing partial panel"
        raise ValueError(msg)


def load_ldz_demand_actual(
    *,
    start: dt.date = GAS_HISTORY_START,
    end: dt.date | None = None,
    vintage_run: str = "d_plus_1",
    vintage: str = "2026-08-14",
    refresh: bool = False,
) -> pd.DataFrame:
    """Load daily LDZ gas offtake actuals for all 13 LDZs.

    Source: https://data.nationalgas.com/find-gas-data
        ``POST https://data.nationalgas.com/api/find-gas-data`` with the
        publication-object ids in :data:`PUBLICATION_OBJECTS`
        (``Demand Actual, LDZ (XX), D+1`` / ``D+6``). Catalogue harvested from
        ``https://data.nationalgas.com/api/find-gas-data-folders``.
    Licence: National Gas Transmission Data Portal terms -- free to access, not
        OGL. See ``docs/data_inventory.md`` §4 before redistributing.
    Vintage: downloaded {vintage}. **Two vintages are available and both are
        exposed**: ``d_plus_1`` is the first publication (gas day D+1) and
        ``d_plus_6`` is the reconciled value (D+6). This is a genuine vintage
        pair of the kind ``CLAUDE.md`` §2.2 asks for and NESO does not provide
        on the electricity side -- the restatement can be measured here rather
        than merely acknowledged.
    Publication lag: ``d_plus_1`` is published on gas day D+1 (~12:00 in the
        published clock); ``d_plus_6`` on D+6. Neither is knowable during gas
        day D, so **neither may be used as a feature for D**. Both are outturn
        (the thing being predicted), not features.

    Parameters
    ----------
    start, end :
        Inclusive gas-day bounds. ``end`` defaults to 8 days before today, so
        that the D+6 reconciled vintage has published for every day returned.
    vintage_run :
        ``"d_plus_1"`` (first publication) or ``"d_plus_6"`` (reconciled).
    vintage :
        Vintage label; also part of the cache key.
    refresh :
        Force a re-pull.

    Returns
    -------
    pandas.DataFrame
        Columns ``gas_day`` (naive date), ``ldz``, ``demand_mscm``,
        ``published_at``, ``unit``. One row per LDZ per gas day.
    """
    series = f"demand_actual_{vintage_run}"
    if series not in PUBLICATION_OBJECTS:
        msg = f"vintage_run must be 'd_plus_1' or 'd_plus_6', got {vintage_run!r}"
        raise ValueError(msg)
    end = end or (dt.datetime.now(tz=dt.UTC).date() - dt.timedelta(days=8))

    def fetch() -> tuple[pd.DataFrame, list[str]]:
        frame, urls = _fetch_series(series, start, end, all_publications=False)
        return frame, urls

    raw = cached_pull(
        dataset=f"ng_ldz_{series}_{start.isoformat()}_{end.isoformat()}",
        vintage=vintage,
        licence=NATIONAL_GAS_LICENCE,
        publication_lag=(
            f"Published on gas day {vintage_run.replace('_', '+').upper()}; "
            f"not knowable during gas day D. Outturn, never a feature for D."
        ),
        fetch=fetch,
        params={
            "series": series,
            "ids": PUBLICATION_OBJECTS[series],
            "latestFlag": "Y",
            "start": start.isoformat(),
            "end": end.isoformat(),
        },
        notes="Daily LDZ offtake actuals, mscm per gas day. 13 LDZs.",
        refresh=refresh,
    )

    frame = (
        raw.rename(columns={"value": "demand_mscm", "generated_at": "published_at"})
        .sort_values(["gas_day", "ldz"])
        .drop_duplicates(["gas_day", "ldz"], keep="last")
        .reset_index(drop=True)
    )
    _assert_full_panel(frame, series)
    return frame[["gas_day", "ldz", "demand_mscm", "published_at", "unit"]]


def select_publication_at_gate(
    publications: pd.DataFrame,
    *,
    gate: ForecastGate = ForecastGate.LAST_ON_D_MINUS_1,
    value_column: str = "value",
) -> pd.DataFrame:
    """Pick the one publication per (gas day, LDZ) that a decision-maker had.

    This function is the point-in-time gate for every repeatedly-revised gas
    series, and it is deliberately separated from the loaders so it can be
    tested directly against a hand-built publication history.

    Parameters
    ----------
    publications :
        Long frame with ``gas_day``, ``ldz``, ``generated_at`` and
        ``value_column``; one row per publication.
    gate :
        Which publication counts. See :class:`ForecastGate`.
    value_column :
        Column holding the published value.

    Returns
    -------
    pandas.DataFrame
        One row per ``(gas_day, ldz)`` with the selected value and the
        ``generated_at`` it came from, so the choice is auditable downstream.
        Gas days with no publication satisfying the gate are **dropped**, not
        back-filled from a later publication.
    """
    working = publications.copy()
    gas_day = pd.DatetimeIndex(working["gas_day"]).normalize()
    generated = pd.DatetimeIndex(working["generated_at"])
    generated_date = generated.normalize()

    if gate in (ForecastGate.LAST_ON_D_MINUS_1, ForecastGate.FIRST_ON_D_MINUS_1):
        # Publications dated strictly before the gas day. Under either
        # timezone reading of `generated_at`, a publication dated D-1 or
        # earlier is unambiguously available before gas day D opens.
        eligible = generated_date < gas_day
    else:
        # Additionally admit publications dated on day D but timestamped before
        # the 05:00 UTC gas-day start. Read as London local; in winter the two
        # readings coincide, and in summer this reading is the *later* UTC
        # instant, which is the conservative direction.
        before_gas_day_start = (generated_date == gas_day) & (generated.hour < 5)
        eligible = (generated_date < gas_day) | before_gas_day_start

    working = working.loc[np.asarray(eligible)].copy()
    if len(working) == 0:
        msg = f"no publications satisfy gate {gate.value}"
        raise ValueError(msg)

    working = working.sort_values(["gas_day", "ldz", "generated_at"])
    keep_first = gate is ForecastGate.FIRST_ON_D_MINUS_1
    # `.nth` is typed as DataFrame | Series in pandas-stubs; on a grouped
    # DataFrame it is always a DataFrame.
    selected = cast(
        "pd.DataFrame",
        working.groupby(["gas_day", "ldz"], as_index=False).nth(
            0 if keep_first else -1
        ),
    )
    return (
        selected[["gas_day", "ldz", value_column, "generated_at"]]
        .sort_values(["gas_day", "ldz"])
        .reset_index(drop=True)
    )


def load_ldz_demand_forecast(
    *,
    start: dt.date = GAS_HISTORY_START,
    end: dt.date | None = None,
    gate: ForecastGate = ForecastGate.LAST_ON_D_MINUS_1,
    vintage: str = "2026-08-14",
    refresh: bool = False,
) -> pd.DataFrame:
    """Load National Gas's published LDZ demand forecast, gated to D-1.

    **This is the competitor** -- the gas analogue of the NESO day-ahead
    national demand forecast that Phase 1 scored against.

    Source: https://data.nationalgas.com/find-gas-data
        ``POST https://data.nationalgas.com/api/find-gas-data``, publication
        objects ``Demand Forecast, LDZ (XX)`` (``PUBOB609``-``PUBOB621``),
        pulled with ``latestFlag=N`` so that every publication is returned.
    Licence: National Gas Transmission Data Portal terms; see
        ``docs/data_inventory.md`` §4.
    Vintage: downloaded {vintage}. The publication history itself is not
        restated -- each publication is a dated record — so this series is
        reproducible in a way the demand actuals are not.
    Publication lag: **the item is republished ~8 times per gas day** -- twice
        on D-1 (13:15, 16:15) and repeatedly through D (00:15, 10:15, 13:15,
        16:15, 21:15) plus a final value at 00:15 on D+1. The portal's default
        ``latestFlag=Y`` returns the **last** of these, generated *after the
        gas day has ended*; using it as a day-ahead forecast is a severe leak.
        This loader selects by ``generated_at`` per ``gate``, defaulting to the
        last publication dated on D-1, and records which publication was
        chosen.

    Parameters
    ----------
    start, end :
        Inclusive gas-day bounds.
    gate :
        Which publication counts as the D-1 forecast. See :class:`ForecastGate`.
    vintage :
        Vintage label; also part of the cache key.
    refresh :
        Force a re-pull.

    Returns
    -------
    pandas.DataFrame
        Columns ``gas_day``, ``ldz``, ``ng_forecast_mscm``, ``forecast_published_at``.
    """
    end = end or (dt.datetime.now(tz=dt.UTC).date() - dt.timedelta(days=8))

    def fetch() -> tuple[pd.DataFrame, list[str]]:
        return _fetch_series("demand_forecast", start, end, all_publications=True)

    raw = cached_pull(
        dataset=f"ng_ldz_demand_forecast_all_pubs_{start.isoformat()}_{end.isoformat()}",
        vintage=vintage,
        licence=NATIONAL_GAS_LICENCE,
        publication_lag=(
            "Republished ~8x per gas day: 13:15 and 16:15 on D-1, then 00:15, "
            "10:15, 13:15, 16:15, 21:15 on D and 00:15 on D+1. The D-1 "
            "publications are the only ones available at a day-ahead decision."
        ),
        fetch=fetch,
        params={
            "series": "demand_forecast",
            "ids": PUBLICATION_OBJECTS["demand_forecast"],
            "latestFlag": "N",
            "start": start.isoformat(),
            "end": end.isoformat(),
        },
        notes=(
            "FULL PUBLICATION HISTORY. Gate with select_publication_at_gate "
            "before use -- the latest publication post-dates the gas day."
        ),
        refresh=refresh,
    )

    selected = select_publication_at_gate(raw, gate=gate, value_column="value")
    frame = selected.rename(
        columns={"value": "ng_forecast_mscm", "generated_at": "forecast_published_at"}
    )
    _assert_full_panel(frame, "demand_forecast")
    return frame


def load_ldz_cwv(
    *,
    kind: str = "forecast_d_minus_1",
    start: dt.date = GAS_HISTORY_START,
    end: dt.date | None = None,
    gate: ForecastGate = ForecastGate.LAST_ON_D_MINUS_1,
    vintage: str = "2026-08-14",
    refresh: bool = False,
) -> pd.DataFrame:
    """Load the Composite Weather Variable per LDZ, forecast or actual.

    The CWV is the gas industry's own weather-to-demand transform: a per-LDZ
    variable built from temperature and wind speed and constructed to be
    *linear* in gas demand. It is the correct weather variable for this target
    and the incumbent's own input, which is why ``docs/data_inventory.md`` §4
    calls it "the industry's own ... natural comparator". Raw HDD is reported
    alongside it rather than substituted for it.

    Source: https://data.nationalgas.com/find-gas-data
        ``POST https://data.nationalgas.com/api/find-gas-data``; publication
        objects ``Composite Weather Variable, Forecast, LDZ(XX), D-1``
        (``PUBOB3726``-``PUBOB3738``) and
        ``Composite Weather Variable, Actual, LDZ(XX), D+1``
        (``PUBOB3700``-``PUBOB3712``).
    Licence: National Gas Transmission Data Portal terms; see
        ``docs/data_inventory.md`` §4.
    Vintage: downloaded {vintage}.
    Publication lag:
        ``forecast_d_minus_1`` is issued on D-1 and is **point-in-time legal**
        -- it is what the incumbent's own forecast consumed, at the same
        moment. ``actual`` is published on D+1 and is
        ``REALISED-WEATHER-DIAGNOSTIC``: it must never drive a result reported
        as a forecast, only oracle bounds and error decomposition
        (`CLAUDE.md` §2.1).

    Parameters
    ----------
    kind :
        ``"forecast_d_minus_1"`` or ``"actual"``.
    start, end :
        Inclusive gas-day bounds.
    gate :
        Publication gate applied to the forecast variant. Ignored for actuals.
    vintage :
        Vintage label; also part of the cache key.
    refresh :
        Force a re-pull.

    Returns
    -------
    pandas.DataFrame
        Columns ``gas_day``, ``ldz`` and either ``cwv_forecast`` (legal) or
        ``cwv_actual_realised`` (diagnostic only -- the ``_realised`` suffix is
        deliberate and must survive downstream, `CLAUDE.md` §2.1).
    """
    if kind not in ("forecast_d_minus_1", "actual"):
        msg = f"kind must be 'forecast_d_minus_1' or 'actual', got {kind!r}"
        raise ValueError(msg)
    end = end or (dt.datetime.now(tz=dt.UTC).date() - dt.timedelta(days=8))
    series = "cwv_forecast_d_minus_1" if kind == "forecast_d_minus_1" else "cwv_actual"
    is_forecast = kind == "forecast_d_minus_1"

    def fetch() -> tuple[pd.DataFrame, list[str]]:
        return _fetch_series(series, start, end, all_publications=is_forecast)

    raw = cached_pull(
        dataset=f"ng_ldz_{series}_{start.isoformat()}_{end.isoformat()}",
        vintage=vintage,
        licence=NATIONAL_GAS_LICENCE,
        publication_lag=(
            "Issued D-1; point-in-time legal."
            if is_forecast
            else "Published D+1; REALISED-WEATHER-DIAGNOSTIC, never in a signal."
        ),
        fetch=fetch,
        params={
            "series": series,
            "ids": PUBLICATION_OBJECTS[series],
            "latestFlag": "N" if is_forecast else "Y",
            "start": start.isoformat(),
            "end": end.isoformat(),
        },
        notes=(
            "POINT-IN-TIME LEGAL: CWV as forecast on D-1."
            if is_forecast
            else "REALISED-WEATHER-DIAGNOSTIC: outturn CWV, diagnostic use only."
        ),
        refresh=refresh,
    )

    if is_forecast:
        selected = select_publication_at_gate(raw, gate=gate, value_column="value")
        frame = selected.rename(
            columns={"value": "cwv_forecast", "generated_at": "cwv_published_at"}
        )
        columns = ["gas_day", "ldz", "cwv_forecast", "cwv_published_at"]
    else:
        # REALISED-WEATHER-DIAGNOSTIC -- outturn CWV, published D+1.
        frame = (
            raw.rename(columns={"value": "cwv_actual_realised"})
            .sort_values(["gas_day", "ldz", "generated_at"])
            .drop_duplicates(["gas_day", "ldz"], keep="last")
            .reset_index(drop=True)
        )
        columns = ["gas_day", "ldz", "cwv_actual_realised"]

    _assert_full_panel(frame, series)
    return frame[columns].sort_values(["gas_day", "ldz"]).reset_index(drop=True)


def refresh_publication_object_ids(
    *,
    timeout: int = _TIMEOUT,
) -> dict[str, dict[str, str]]:
    """Re-harvest publication-object ids from the portal catalogue.

    Source: ``GET https://data.nationalgas.com/api/find-gas-data-folders``

    The ids in :data:`PUBLICATION_OBJECTS` are pinned rather than fetched at
    import time, so a portal reorganisation cannot silently change which series
    a cached backtest used. Call this to check the pinned values still match,
    and update the constant deliberately if they do not.

    Returns
    -------
    dict
        Same shape as :data:`PUBLICATION_OBJECTS`.
    """
    import re

    response = requests.get(
        FOLDERS_URL, headers={"User-Agent": USER_AGENT}, timeout=timeout
    )
    response.raise_for_status()

    leaves: list[tuple[str, str]] = []

    def walk(node: dict[str, Any]) -> None:
        children = node.get("children")
        if children:
            for child in children:
                walk(child)
        else:
            leaves.append((node.get("name", ""), node.get("description", "") or ""))

    for root in response.json()["data"]:
        walk(root)

    codes = "|".join(LDZ_CODES)
    patterns = {
        "demand_actual_d_plus_1": rf"^Demand Actual, LDZ \(({codes})\), D\+1$",
        "demand_actual_d_plus_6": rf"^Demand Actual, LDZ \(({codes})\), D\+6$",
        "demand_forecast": rf"^Demand Forecast, LDZ \(({codes})\)$",
        "cwv_forecast_d_minus_1": (
            rf"^Composite Weather Variable, Forecast, LDZ\(({codes})\), D-1$"
        ),
        "cwv_actual": rf"^Composite Weather Variable, Actual, LDZ\(({codes})\), D\+1$",
    }

    harvested: dict[str, dict[str, str]] = {}
    for series, pattern in patterns.items():
        regex = re.compile(pattern)
        found: dict[str, str] = {}
        for name, description in leaves:
            match = regex.match(name)
            if match:
                object_id = re.match(r"\s*(PUBOB\w+)", description)
                if object_id:
                    found[match.group(1)] = object_id.group(1)
        harvested[series] = found
    return harvested
