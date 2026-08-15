"""LSOA-level population points for GB, used to weight the temperature index.

GB needs two publishers, because LSOA is an England-and-Wales geography and
Scotland has no equivalent (``docs/data_inventory.md`` §6):

* **England & Wales** -- ONS Open Geography Portal supplies LSOA 2021
  population-weighted centroids, and Nomis supplies the Census 2021 usual
  resident population per LSOA (table TS001). The two are joined on LSOA21CD.
* **Scotland** -- the Scottish Government spatial hub supplies Data Zone 2022
  population-weighted centroids **with population attached**, so no join is
  needed.

Together these give ~43,000 population points covering GB. Ignoring Scotland
here would make a "GB" temperature index that is silently England-and-Wales
only, which ``docs/data_inventory.md`` §1 explicitly forbids.

Northern Ireland is out of scope: NESO's National Demand series covers GB, not
the whole UK, so including NI population would weight the index towards a
region whose demand is not in the target series.
"""

from __future__ import annotations

import io
from typing import Any, Final

import pandas as pd
import requests

from heat_nowcast.data.cache import cached_pull

_TIMEOUT: Final[int] = 180

ONS_PWC_SERVICE: Final[str] = (
    "https://services1.arcgis.com/ESMARspQHYMw9BZ9/arcgis/rest/services/"
    "LSOA_PopCentroids_EW_2021_V4/FeatureServer/0/query"
)
NOMIS_TS001_URL: Final[str] = (
    "https://www.nomisweb.co.uk/api/v01/dataset/NM_2021_1.data.csv"
    "?date=latest&geography=TYPE151&c2021_restype_3=0&measures=20100"
    "&select=geography_code,obs_value"
)
#: Nomis caps a single ``data.csv`` response at 25,000 rows and returns a
#: short page without erroring. There are 35,672 LSOAs, so an unpaged request
#: silently loses a third of England & Wales -- and the loss is geographic,
#: not random, because the rows come back in area-code order.
NOMIS_PAGE_SIZE: Final[int] = 25_000
SCOTGOV_DZ_SERVICE: Final[str] = (
    "https://maps.gov.scot/server/rest/services/ScotGov/StatisticalUnits/"
    "MapServer/11/query"
)

OGL_V3: Final[str] = (
    "Open Government Licence v3.0; contains OS data (C) Crown copyright "
    "and database right, and National Statistics data (C) Crown copyright"
)


def _arcgis_paged_query(
    service_url: str,
    out_fields: str,
    page_size: int,
) -> tuple[pd.DataFrame, list[str]]:
    """Page through an ArcGIS FeatureServer/MapServer query in WGS84.

    ArcGIS caps a single response at ``maxRecordCount`` (2000 for the ONS
    service, 1000 for the Scottish one), so results are paged with
    ``resultOffset`` until a short page comes back.
    """
    rows: list[dict[str, Any]] = []
    urls: list[str] = []
    offset = 0
    while True:
        params = {
            "where": "1=1",
            "outFields": out_fields,
            "returnGeometry": "true",
            "outSR": "4326",
            "f": "json",
            "resultOffset": str(offset),
            "resultRecordCount": str(page_size),
        }
        response = requests.get(service_url, params=params, timeout=_TIMEOUT)
        response.raise_for_status()
        urls.append(response.url)
        features = response.json().get("features", [])
        for feature in features:
            geometry = feature.get("geometry") or {}
            rows.append(
                {
                    **feature.get("attributes", {}),
                    "longitude": geometry.get("x"),
                    "latitude": geometry.get("y"),
                }
            )
        if len(features) < page_size:
            break
        offset += page_size
    return pd.DataFrame(rows), urls


def load_gb_population_points(
    *,
    vintage: str = "2026-08-14",
    refresh: bool = False,
) -> pd.DataFrame:
    """Load GB small-area population-weighted centroids with populations.

    Source:
        England & Wales centroids --
        https://services1.arcgis.com/ESMARspQHYMw9BZ9/arcgis/rest/services/LSOA_PopCentroids_EW_2021_V4/FeatureServer/0
        (ONS Open Geography Portal, LSOA 2021 population-weighted centroids,
        35,672 features).
        England & Wales population -- https://www.nomisweb.co.uk/api/v01/dataset/NM_2021_1.data.csv
        (Nomis, Census 2021 table TS001, geography TYPE151 = LSOA 2021).
        Scotland -- https://maps.gov.scot/server/rest/services/ScotGov/StatisticalUnits/MapServer/11
        (Scottish Government spatial hub, Data Zone 2022 population-weighted
        centroids carrying ``totpop2022``, 7,392 features).
    Licence: Open Government Licence v3.0 for all three. Attribution strings
        in ``docs/data_inventory.md`` §11 apply to any published output.
    Vintage: downloaded {vintage}. Census 2021 for England & Wales
        (2021-03-21 reference date); NRS 2022 small-area estimates for
        Scotland. Boundaries and centroids are static per census.
    Publication lag: irrelevant to point-in-time discipline here. These are
        **static** geography and census products, published years before the
        2024-2026 evaluation window, and the weights they produce do not vary
        over the backtest. Using them at any prediction timestamp in the
        evaluation window is legal (`CLAUDE.md` §2.3).

    Parameters
    ----------
    vintage :
        Vintage label; also the cache key.
    refresh :
        Force a re-pull.

    Returns
    -------
    pandas.DataFrame
        Columns ``area_code``, ``country`` (``EW`` or ``S``), ``latitude``,
        ``longitude``, ``population``.

    Notes
    -----
    Population, not dwelling count, is the weight. Dwelling counts would be
    the better weight for a *heat* model and are what Phase A1 will use for
    the stock reweighting; for a national temperature index the two are
    correlated at ~0.99 across small areas and the difference is immaterial
    beside the choice of base temperature. This is a documented approximation,
    not an oversight.
    """

    def fetch() -> tuple[pd.DataFrame, list[str]]:
        urls: list[str] = []

        centroids, ew_urls = _arcgis_paged_query(
            ONS_PWC_SERVICE, out_fields="LSOA21CD", page_size=2000
        )
        urls.extend(ew_urls[:3])

        pages: list[pd.DataFrame] = []
        offset = 0
        while True:
            page_url = (
                f"{NOMIS_TS001_URL}&RecordOffset={offset}&RecordLimit={NOMIS_PAGE_SIZE}"
            )
            response = requests.get(page_url, timeout=_TIMEOUT)
            response.raise_for_status()
            urls.append(page_url)
            page = pd.read_csv(io.StringIO(response.text))
            pages.append(page)
            if len(page) < NOMIS_PAGE_SIZE:
                break
            offset += NOMIS_PAGE_SIZE
        populations = pd.concat(pages, ignore_index=True)
        populations.columns = [c.strip().lower() for c in populations.columns]

        england_wales = centroids.merge(
            populations.rename(
                columns={"geography_code": "LSOA21CD", "obs_value": "population"}
            )[["LSOA21CD", "population"]],
            on="LSOA21CD",
            how="inner",
        ).rename(columns={"LSOA21CD": "area_code"})
        england_wales["country"] = "EW"

        # Both upstreams page, and both return a short page rather than an
        # error when a request is capped. A silently truncated join would give
        # a population-weighted temperature that is quietly weighted towards
        # whichever LSOAs sort first -- a geographic bias, not random noise.
        matched = len(england_wales) / max(len(centroids), 1)
        if matched < 0.99:
            msg = (
                f"only {len(england_wales):,} of {len(centroids):,} E&W LSOA "
                f"centroids matched a Census population ({matched:.1%}). "
                f"Refusing to build a national weighting from a partial join."
            )
            raise ValueError(msg)

        scotland, scot_urls = _arcgis_paged_query(
            SCOTGOV_DZ_SERVICE,
            out_fields="dzcode,totpop2022",
            page_size=1000,
        )
        urls.extend(scot_urls[:3])
        scotland = scotland.rename(
            columns={"dzcode": "area_code", "totpop2022": "population"}
        )
        scotland["country"] = "S"

        columns = ["area_code", "country", "latitude", "longitude", "population"]
        combined = pd.concat(
            [england_wales[columns], scotland[columns]], ignore_index=True
        )
        return combined, urls

    frame = cached_pull(
        dataset="gb_population_points",
        vintage=vintage,
        licence=OGL_V3,
        publication_lag=(
            "Static census/geography products; no point-in-time constraint "
            "within the 2024-2026 evaluation window."
        ),
        fetch=fetch,
        params={
            "ew_centroids": "LSOA_PopCentroids_EW_2021_V4",
            "ew_population": "Nomis NM_2021_1 (TS001), geography TYPE151",
            "scotland": "ScotGov StatisticalUnits/MapServer/11 DataZoneCent2022",
        },
        notes=(
            "GB only: Northern Ireland excluded because NESO National Demand "
            "covers GB. Weight is usual resident population."
        ),
        refresh=refresh,
    )

    frame = frame.dropna(subset=["latitude", "longitude", "population"])
    frame = frame[frame["population"] > 0]
    return frame.reset_index(drop=True)
