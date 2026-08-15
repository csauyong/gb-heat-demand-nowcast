"""Population-weighted GB temperature and heating degree days.

Two steps, kept separate so each can be tested on its own.

**Step 1 -- the weighting scheme.** ~43,000 LSOA / Data Zone population points
are binned onto a coarse weather grid; each cell's weight is the share of GB
population inside it, and its representative location is the population-
weighted centroid of the points it contains. The scheme is a function of
static census geography only. It contains no weather and no demand, so it
cannot leak: the same weights apply at every timestamp in the backtest. This
is the pattern ``docs/data_inventory.md`` §5.4 describes -- estimate the
spatial scheme on static/climatological data, then feed it forecast values at
run time.

**Step 2 -- degree days.** The weighted temperature is reduced to heating
degree days against a base temperature. **15.5 degC is the long-standing UK
convention** (the Met Office / CIBSE base, chosen because a typical dwelling's
internal gains carry it from 15.5 degC to a ~18 degC internal temperature),
but it is a convention and not a constant of nature, and different bases suit
different stock. Every function here takes ``base_c`` as a parameter with the
UK convention as its default; nothing hardcodes it.

Grid resolution is a compute/accuracy trade-off, not a physical choice. The
default 0.75 degC latitude by 1.5 degC longitude is roughly 83 km by 90 km at
GB latitudes -- fine enough that the population-weighted mean is stable, coarse
enough to keep the Open-Meteo free tier comfortable. It is exposed as a
parameter and the sensitivity is reported in ``reports/phase1_findings.md``.
"""

from __future__ import annotations

from typing import Final, overload

import numpy as np
import pandas as pd

#: UK convention for heating degree days (Met Office / CIBSE), in degrees C.
#: A default, never a hardcoded constant -- every public function here takes
#: ``base_c`` and callers are expected to vary it.
UK_HDD_BASE_C: Final[float] = 15.5

DEFAULT_GRID_LAT_DEG: Final[float] = 0.75
DEFAULT_GRID_LON_DEG: Final[float] = 1.5


def build_population_weights(
    population_points: pd.DataFrame,
    *,
    grid_lat_deg: float = DEFAULT_GRID_LAT_DEG,
    grid_lon_deg: float = DEFAULT_GRID_LON_DEG,
    population_coverage: float = 0.995,
) -> pd.DataFrame:
    """Aggregate LSOA-level population points into weighted weather grid cells.

    Parameters
    ----------
    population_points :
        Frame with ``latitude``, ``longitude``, ``population`` -- one row per
        LSOA (England & Wales) or Data Zone (Scotland). See
        :func:`heat_nowcast.data.ons_geography.load_gb_population_points`.
    grid_lat_deg, grid_lon_deg :
        Cell size in degrees. Smaller cells mean more Open-Meteo requests.
    population_coverage :
        Keep the largest cells until this share of GB population is covered,
        then drop the rest and renormalise. The tail is thousands of people
        spread over the Highlands and islands; sampling weather there costs
        requests and moves the national mean by a few hundredths of a degree.

    Returns
    -------
    pandas.DataFrame
        One row per retained cell, sorted by descending weight, with columns
        ``point_id``, ``latitude``, ``longitude`` (the population-weighted
        centroid of the cell's points), ``population`` and ``weight``.
        ``weight`` sums to exactly 1.

    Raises
    ------
    ValueError
        If required columns are missing, or ``population_coverage`` is not in
        (0, 1].
    """
    required = {"latitude", "longitude", "population"}
    missing = required - set(population_points.columns)
    if missing:
        msg = f"population_points is missing columns: {sorted(missing)}"
        raise ValueError(msg)
    if not 0.0 < population_coverage <= 1.0:
        msg = "population_coverage must lie in (0, 1]"
        raise ValueError(msg)

    points = population_points.loc[
        population_points["population"] > 0, list(required)
    ].copy()
    points["lat_bin"] = np.floor(points["latitude"] / grid_lat_deg).astype("int64")
    points["lon_bin"] = np.floor(points["longitude"] / grid_lon_deg).astype("int64")
    points["lat_weighted"] = points["latitude"] * points["population"]
    points["lon_weighted"] = points["longitude"] * points["population"]

    cells = (
        points.groupby(["lat_bin", "lon_bin"], as_index=False)
        .agg(
            population=("population", "sum"),
            lat_weighted=("lat_weighted", "sum"),
            lon_weighted=("lon_weighted", "sum"),
        )
        .sort_values("population", ascending=False)
        .reset_index(drop=True)
    )
    cells["latitude"] = cells["lat_weighted"] / cells["population"]
    cells["longitude"] = cells["lon_weighted"] / cells["population"]

    cumulative = cells["population"].cumsum() / cells["population"].sum()
    # Keep the first cell that crosses the threshold, so coverage is met, not
    # merely approached.
    keep = cumulative.le(population_coverage)
    keep.iloc[: int(keep.sum()) + 1] = True
    cells = cells.loc[keep.to_numpy()].reset_index(drop=True)

    cells["weight"] = cells["population"] / cells["population"].sum()
    cells["point_id"] = [
        f"c{lat:+03d}{lon:+03d}"
        for lat, lon in zip(cells["lat_bin"], cells["lon_bin"], strict=True)
    ]
    result: pd.DataFrame = cells[
        ["point_id", "latitude", "longitude", "population", "weight"]
    ].reset_index(drop=True)
    return result


def population_weighted_temperature(
    temperature_long: pd.DataFrame,
    weights: pd.DataFrame,
    *,
    value_column: str,
    output_column: str | None = None,
) -> pd.DataFrame:
    """Collapse per-cell temperatures into one population-weighted GB series.

    Parameters
    ----------
    temperature_long :
        Long frame with ``time_utc``, ``point_id`` and ``value_column``.
    weights :
        Frame from :func:`build_population_weights`.
    value_column :
        Column holding the temperature, e.g. ``temp_c_forecast`` or
        ``temp_c_realised``.
    output_column :
        Name for the weighted series. Defaults to ``value_column``, which
        preserves any ``_realised`` suffix -- deliberately, so realised
        weather stays labelled all the way through the pipeline
        (`CLAUDE.md` §2.1).

    Returns
    -------
    pandas.DataFrame
        Two columns: ``time_utc`` and the weighted temperature, one row per
        timestamp, sorted by time.

    Raises
    ------
    ValueError
        If any timestamp is missing one or more cells. A partially-covered
        timestamp would silently reweight the national mean towards whichever
        cells happened to return data, which is exactly the kind of quiet
        distortion that is worse than a crash.
    """
    output_column = output_column or value_column
    merged = temperature_long.merge(
        weights[["point_id", "weight"]], on="point_id", how="inner"
    ).dropna(subset=[value_column])
    merged["contribution"] = merged[value_column] * merged["weight"]

    per_timestamp = merged.groupby("time_utc", as_index=False).agg(
        contribution=("contribution", "sum"),
        weight_sum=("weight", "sum"),
        n_cells=("point_id", "nunique"),
    )

    expected_cells = weights["point_id"].nunique()
    incomplete = per_timestamp.loc[per_timestamp["n_cells"] < expected_cells]
    if len(incomplete) > 0:
        first = incomplete["time_utc"].iloc[0]
        msg = (
            f"{len(incomplete)} timestamp(s) are missing weather cells "
            f"(expected {expected_cells}); first is {first}. Refusing to "
            f"compute a national mean from a partial grid."
        )
        raise ValueError(msg)

    # weight_sum is 1 by construction when the grid is complete, but dividing
    # by it keeps the function correct if a caller passes a subset of cells.
    per_timestamp[output_column] = (
        per_timestamp["contribution"] / per_timestamp["weight_sum"]
    )
    return (
        per_timestamp[["time_utc", output_column]]
        .sort_values("time_utc")
        .reset_index(drop=True)
    )


@overload
def degree_deficit(temperature_c: pd.Series, *, base_c: float = ...) -> pd.Series: ...


@overload
def degree_deficit(temperature_c: np.ndarray, *, base_c: float = ...) -> np.ndarray: ...


@overload
def degree_deficit(temperature_c: float, *, base_c: float = ...) -> float: ...


def degree_deficit(
    temperature_c: pd.Series | np.ndarray | float,
    *,
    base_c: float = UK_HDD_BASE_C,
) -> pd.Series | np.ndarray | float:
    """Instantaneous heating degree deficit, ``max(0, base_c - T)``.

    The sub-daily analogue of a heating degree day. Applied to an
    instantaneous temperature it gives the instantaneous shortfall below the
    base; averaged over a day it gives a *different* quantity from
    :func:`heating_degree_days`, because the mean of a truncation is not the
    truncation of a mean. Both are legitimate; they are not interchangeable,
    which is why they are separate functions.

    Parameters
    ----------
    temperature_c :
        Temperature in degrees Celsius.
    base_c :
        Base temperature. Defaults to the UK convention, 15.5 degC.

    Returns
    -------
    Same type as ``temperature_c``
        The degree deficit, never negative.
    """
    if isinstance(temperature_c, pd.Series):
        return (base_c - temperature_c).clip(lower=0.0)
    if isinstance(temperature_c, np.ndarray):
        return np.maximum(base_c - temperature_c, 0.0)
    return max(base_c - float(temperature_c), 0.0)


def heating_degree_days(
    temperature: pd.DataFrame,
    *,
    value_column: str,
    base_c: float = UK_HDD_BASE_C,
    tz: str = "Europe/London",
    min_hours: int = 20,
) -> pd.DataFrame:
    """Compute daily heating degree days from an hourly temperature series.

    Uses the mean-temperature definition::

        HDD(d) = max(0, base_c - mean_over_day(T))

    which is the UK convention and the one the Met Office and CIBSE degree-day
    services publish. The daily mean is taken over the **local** calendar day,
    because that is the day a household experiences and the day the demand
    calendar uses; the underlying timestamps stay UTC until this point
    (`CLAUDE.md` §7).

    Parameters
    ----------
    temperature :
        Frame with ``time_utc`` (UTC-aware, hourly) and ``value_column``.
    value_column :
        Column holding the temperature.
    base_c :
        Base temperature in degrees Celsius. Defaults to the UK convention,
        15.5 degC. **Vary this** -- it is the single most consequential free
        parameter in the baseline.
    tz :
        Timezone whose calendar day defines "a day".
    min_hours :
        Days with fewer than this many hourly observations are dropped rather
        than averaged over a partial day. Clock-change days legitimately have
        23 or 25 hours, so the default sits below 23.

    Returns
    -------
    pandas.DataFrame
        Columns ``settlement_date`` (naive local date), ``mean_temp_c``,
        ``hdd``, ``n_hours``. The ``hdd`` column is suffixed by the caller if
        it derives from realised weather.

    Raises
    ------
    ValueError
        If ``time_utc`` is not timezone-aware.
    """
    index = pd.DatetimeIndex(temperature["time_utc"])
    if index.tz is None:
        msg = "heating_degree_days requires timezone-aware UTC timestamps"
        raise ValueError(msg)

    local_day = index.tz_convert(tz).tz_localize(None).normalize()
    working = pd.DataFrame(
        {
            "settlement_date": local_day,
            "temperature": pd.to_numeric(
                temperature[value_column].to_numpy(), errors="coerce"
            ),
        }
    ).dropna(subset=["temperature"])

    daily = working.groupby("settlement_date", as_index=False).agg(
        mean_temp_c=("temperature", "mean"),
        n_hours=("temperature", "size"),
    )
    daily = daily.loc[daily["n_hours"] >= min_hours].reset_index(drop=True)
    daily["hdd"] = (base_c - daily["mean_temp_c"]).clip(lower=0.0)
    return daily[["settlement_date", "mean_temp_c", "hdd", "n_hours"]]
