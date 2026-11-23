"""National (NTS) gas demand forecasts, actuals and system prices (Paper 1).

Paper 1 (``docs/paper1_plan.md``) needs three things the LDZ loaders in
:mod:`heat_nowcast.data.gas` do not provide:

* the **NTS total demand forecast** at every publication. Prices clear on
  total demand (LDZ plus power, industry, exports, storage, shrinkage), and the
  13:00 D-1 NTS forecast is the one National Gas is financially incentivised
  on (licence Special Condition 5.6 Part C; annual weighted-average absolute
  error);
* **NTS actual demand**, D+1 and D+6 vintages, with their publication times;
* **system prices** from the On-the-day Commodity Market (OCM): SAP and the
  SMP buy/sell cash-out prices.

Clock
-----
Portal timestamps are **UK local time** (decision log row 49): the hourly
forecast skips hour 01 on every spring clock change. Every loader here returns
the portal's naive ``generated_at`` *and* a UTC ``generated_at_utc`` from
:func:`heat_nowcast.timeutils.portal_local_to_utc`.

Price embargo (pre-registration)
--------------------------------
Paper 1's price hypotheses are pre-registered before any price is analysed
(``docs/paper1_plan.md`` §5, decision log row 48). :func:`load_system_price`
therefore refuses windows longer than :data:`PRICE_PROBE_MAX_DAYS` until
:data:`PRICE_PREREGISTRATION_ROW` names the decision-log row that froze them.
The guard is technical, not just a convention, so the freeze can be shown to
have come first.
"""

from __future__ import annotations

import datetime as dt
from typing import Final

import pandas as pd

from heat_nowcast.data.cache import cached_pull
from heat_nowcast.data.gas import (
    GAS_HISTORY_START,
    NATIONAL_GAS_LICENCE,
    fetch_publication_object,
)
from heat_nowcast.timeutils import portal_local_to_utc

#: NTS demand objects, harvested from ``/api/find-gas-data-folders`` on
#: 2026-11-17. Pinned so a portal reorganisation cannot change a cached run.
NTS_DEMAND_OBJECTS: Final[dict[str, str]] = {
    # ~8 publications per gas day: D-1 13:10 and 16:15; D 00:15, 10:15, 13:10,
    # 16:15, 21:10; D+1 00:15 (portal UK-local clock). D-1 values are whole
    # mscm; within-day values are unrounded model output.
    "demand_forecast": "PUBOB623",
    # ~31 publications per gas day: D-1 13:01, 16:01, then hourly from D 00:0x
    # to D+1 04:0x.
    "demand_forecast_hourly": "PUBOB28",
    # One publication each, ~16:00 on D-k.
    "demand_forecast_d_minus_2": "PUBOB36",
    "demand_forecast_d_minus_3": "PUBOB39",
    "demand_forecast_d_minus_4": "PUBOB42",
    "demand_forecast_d_minus_5": "PUBOB45",
    # Outturn: D+1 at ~12:00 on D+1; D+6 at ~12:00 on D+6, with occasional
    # restatements months later (e.g. +140 days).
    "demand_actual_d_plus_1": "PUBOB637",
    "demand_actual_d_plus_6": "PUBOB652",
}

#: OCM system prices, p/kWh, harvested 2026-11-17.
SYSTEM_PRICE_OBJECTS: Final[dict[str, str]] = {
    # Day value, republished daily for ~30 days from ~11:41 on D+1.
    "sap_day": "PUBOB603",
    # Within-day SAP path by hour of D (``applicable_at``), published ~08:30 D+1.
    "sap_hourly": "PUBOB47",
    "smp_buy_day": "PUBOB604",
    "smp_sell_day": "PUBOB605",
}

#: Price windows up to this length may be pulled before the freeze, to check
#: schema and timestamps only.
PRICE_PROBE_MAX_DAYS: Final[int] = 7

#: Decision-log row that froze Paper 1's price hypotheses (OSF https://osf.io/zdytk/).
PRICE_PREREGISTRATION_ROW: Final[int | None] = 55


class PriceEmbargoError(RuntimeError):
    """A price window was requested before the hypotheses were frozen."""


def _default_end() -> dt.date:
    return dt.datetime.now(tz=dt.UTC).date() - dt.timedelta(days=8)


def _with_utc(frame: pd.DataFrame) -> pd.DataFrame:
    """Add UTC columns next to the portal's UK-local timestamps."""
    out = frame.copy()
    out["generated_at_utc"] = portal_local_to_utc(out["generated_at"])
    out["applicable_at_utc"] = portal_local_to_utc(out["applicable_at"])
    return out.sort_values(["gas_day", "generated_at"]).reset_index(drop=True)


def first_publication(frame: pd.DataFrame) -> pd.DataFrame:
    """Keep the earliest publication of each gas day.

    For a republished series (an actual, a day price) this is the value first
    knowable, which is the point-in-time default. Ties keep the first row.
    """
    ordered = frame.sort_values(["gas_day", "generated_at"], kind="stable")
    return ordered.drop_duplicates("gas_day", keep="first").reset_index(drop=True)


def load_nts_publication_history(
    series: str,
    *,
    start: dt.date = GAS_HISTORY_START,
    end: dt.date | None = None,
    vintage: str = "2026-11-17",
    refresh: bool = False,
) -> pd.DataFrame:
    """Load every publication of an NTS demand series, ungated.

    Source: https://data.nationalgas.com/find-gas-data
        ``POST https://data.nationalgas.com/api/find-gas-data`` with
        ``latestFlag=N``; publication object per :data:`NTS_DEMAND_OBJECTS`.
    Licence: National Gas Transmission Data Portal terms; free to access, not
        OGL (``docs/data_inventory.md`` §4).
    Vintage: downloaded {vintage}. Forecast publications are dated records and
        are not restated; actuals are (D+6 rows reappear months later), which
        is why every publication is kept.
    Publication lag: each row is knowable from its own ``generated_at``
        (portal UK-local clock; ``generated_at_utc`` is the UTC instant).
        Forecasts: from 13:01-13:10 on D-1 onward (see
        :data:`NTS_DEMAND_OBJECTS`). Actuals: ~12:00 on D+1 / D+6. Portal
        history for every series starts at gas day 2021-12-01.

    Parameters
    ----------
    series :
        Key of :data:`NTS_DEMAND_OBJECTS`.
    start, end :
        Inclusive gas-day bounds; ``end`` defaults to 8 days before today.
    vintage :
        Vintage label; also part of the cache key.
    refresh :
        Force a re-pull.

    Returns
    -------
    pandas.DataFrame
        ``gas_day``, ``value`` (mscm/day), ``generated_at``, ``applicable_at``,
        ``generated_at_utc``, ``applicable_at_utc``, ``unit``, ``item_name``;
        one row per publication.
    """
    if series not in NTS_DEMAND_OBJECTS:
        msg = f"series must be one of {sorted(NTS_DEMAND_OBJECTS)}, got {series!r}"
        raise ValueError(msg)
    end = end or _default_end()
    object_id = NTS_DEMAND_OBJECTS[series]

    def fetch() -> tuple[pd.DataFrame, list[str]]:
        frame, urls = fetch_publication_object(
            object_id, start, end, all_publications=True
        )
        if frame.empty:
            msg = f"no rows for {series} ({object_id}) over {start}..{end}"
            raise RuntimeError(msg)
        return frame, urls

    raw = cached_pull(
        dataset=f"ng_nts_{series}_all_pubs_{start.isoformat()}_{end.isoformat()}",
        vintage=vintage,
        licence=NATIONAL_GAS_LICENCE,
        publication_lag=(
            "Every publication kept; each row knowable from its generated_at "
            "(portal UK-local clock)."
        ),
        fetch=fetch,
        params={
            "series": series,
            "id": object_id,
            "latestFlag": "N",
            "start": start.isoformat(),
            "end": end.isoformat(),
        },
        notes="FULL PUBLICATION HISTORY. Gate on generated_at before any use.",
        refresh=refresh,
    )
    return _with_utc(raw)


def load_system_price(
    series: str,
    *,
    start: dt.date,
    end: dt.date,
    vintage: str = "2026-11-17",
    refresh: bool = False,
) -> pd.DataFrame:
    """Load an OCM system price (SAP or SMP), every publication.

    Source: https://data.nationalgas.com/find-gas-data
        ``POST https://data.nationalgas.com/api/find-gas-data`` with
        ``latestFlag=N``; publication object per :data:`SYSTEM_PRICE_OBJECTS`.
        SAP is also published by ONS ("System Average Price (SAP) of gas").
    Licence: National Gas Transmission Data Portal terms; see
        ``docs/data_inventory.md`` §4.
    Vintage: downloaded {vintage}. Day values are republished daily for ~30
        days; :func:`first_publication` gives the first-knowable value.
    Publication lag: **all of these are outcomes of gas day D, never
        features for D.** Day values first publish ~11:41 on D+1; the hourly
        SAP path for D publishes ~08:30 on D+1 (portal UK-local clock).

    Embargo: windows longer than :data:`PRICE_PROBE_MAX_DAYS` raise
    :class:`PriceEmbargoError` until :data:`PRICE_PREREGISTRATION_ROW` is set.

    Parameters
    ----------
    series :
        Key of :data:`SYSTEM_PRICE_OBJECTS`.
    start, end :
        Inclusive gas-day bounds.
    vintage :
        Vintage label; also part of the cache key.
    refresh :
        Force a re-pull.

    Returns
    -------
    pandas.DataFrame
        Same columns as :func:`load_nts_publication_history`; ``value`` in p/kWh.
    """
    if series not in SYSTEM_PRICE_OBJECTS:
        msg = f"series must be one of {sorted(SYSTEM_PRICE_OBJECTS)}, got {series!r}"
        raise ValueError(msg)
    check_price_embargo(start, end)
    object_id = SYSTEM_PRICE_OBJECTS[series]

    def fetch() -> tuple[pd.DataFrame, list[str]]:
        frame, urls = fetch_publication_object(
            object_id, start, end, all_publications=True
        )
        if frame.empty:
            msg = f"no rows for {series} ({object_id}) over {start}..{end}"
            raise RuntimeError(msg)
        return frame, urls

    raw = cached_pull(
        dataset=f"ng_price_{series}_all_pubs_{start.isoformat()}_{end.isoformat()}",
        vintage=vintage,
        licence=NATIONAL_GAS_LICENCE,
        publication_lag=(
            "Outcome of gas day D: day values from ~11:41 D+1, hourly SAP path "
            "~08:30 D+1. Never a feature for D."
        ),
        fetch=fetch,
        params={
            "series": series,
            "id": object_id,
            "latestFlag": "N",
            "start": start.isoformat(),
            "end": end.isoformat(),
        },
        notes="OCM system price, p/kWh. Outcome only.",
        refresh=refresh,
    )
    return _with_utc(raw)


def check_price_embargo(
    start: dt.date,
    end: dt.date,
    *,
    preregistration_row: int | None = PRICE_PREREGISTRATION_ROW,
) -> None:
    """Raise :class:`PriceEmbargoError` for a full price pull before the freeze.

    Parameters
    ----------
    start, end :
        Inclusive gas-day bounds of the request.
    preregistration_row :
        Decision-log row that froze the price hypotheses; defaults to
        :data:`PRICE_PREREGISTRATION_ROW`.
    """
    span_days = (end - start).days + 1
    if preregistration_row is None and span_days > PRICE_PROBE_MAX_DAYS:
        msg = (
            f"price window of {span_days} days requested before Paper 1's price "
            f"hypotheses were frozen; probes are limited to "
            f"{PRICE_PROBE_MAX_DAYS} days (docs/paper1_plan.md §5)"
        )
        raise PriceEmbargoError(msg)
