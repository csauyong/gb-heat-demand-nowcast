"""Dwelling-stock characteristics aggregated to Local Distribution Zone.

What this produces, and why these variables
-------------------------------------------
One row per LDZ describing the dwelling stock as of the point-in-time cutoff:
mean SAP, wall-fabric mix, insulation-quality bands, mean floor area,
construction-age mix, and the mains-gas share. These are the only things EPC
adds over a weather variable -- they are *cross-sectional* and essentially
time-invariant over a two-year window, which is exactly why the Phase 1b core
test identifies them through an interaction with weather severity rather than
as levels (see :mod:`heat_nowcast.analysis.twoway`).

Every feature is produced in **standardised** form across the zones that have
coverage, so a coefficient reads as "per standard deviation of the stock
characteristic" and does not depend on the arbitrary units of any particular
metric.

The Scotland gap is carried, not hidden
---------------------------------------
The MHCLG EPC register covers England and Wales. The SC zone therefore has
essentially no dwellings in it -- a few hundred border postcodes that Xoserve
maps to SC, which is statistical noise rather than coverage. Per the recorded
decision, SC is **kept in the panel and flagged**: it retains its LDZ fixed
effect and contributes to day fixed effects, but its stock features are marked
unusable via ``has_stock_coverage`` and it is excluded from standardisation.
:data:`MIN_DWELLINGS_FOR_COVERAGE` is the threshold, and it is deliberately far
above 478 so the judgement is explicit rather than incidental.

Coverage assertions
-------------------
Phase 1 lost a third of England & Wales' LSOAs to a silently truncated page,
and the loss was geographically correlated. Every aggregation here therefore
asserts before returning: all 13 zones present, dwelling counts above a floor
for the zones claimed to have coverage, and the postcode match rate reported
rather than assumed.
"""

from __future__ import annotations

from typing import Final

import polars as pl

from heat_nowcast.data.gas import LDZ_CODES

#: A zone below this many matched dwellings is treated as having no usable
#: stock features. Scotland lands around 478; England & Wales zones are all
#: above 200,000, so the threshold separates them by three orders of magnitude
#: and no borderline judgement is involved.
MIN_DWELLINGS_FOR_COVERAGE: Final[int] = 50_000

#: Construction-age bands collapsed to a monotone pre/post-regulation ordering.
#: The 1976 boundary is the first meaningful thermal building regulation in
#: England and Wales; 1996 and 2007 are subsequent step changes.
AGE_BANDS: Final[dict[str, tuple[int, int]]] = {
    "pre_1930": (0, 1929),
    "1930_1975": (1930, 1975),
    "1976_1995": (1976, 1995),
    "post_1996": (1996, 2100),
}


def _age_band_expression() -> pl.Expr:
    """Map EPC's free-text age band to a coarse, monotone band.

    EPC renders these as e.g. ``"England and Wales: 1967-1975"``. The leading
    four-digit year is extracted and bucketed; anything unparseable becomes
    null rather than being forced into a bucket.
    """
    start_year = (
        pl.col("construction_age_band")
        .str.extract(r"(\d{4})", 1)
        .cast(pl.Int32, strict=False)
    )
    return (
        pl.when(start_year <= 1929)
        .then(pl.lit("pre_1930"))
        .when(start_year <= 1975)
        .then(pl.lit("1930_1975"))
        .when(start_year <= 1995)
        .then(pl.lit("1976_1995"))
        .when(start_year.is_not_null())
        .then(pl.lit("post_1996"))
        .otherwise(None)
        .alias("age_band")
    )


def _wall_type_expression() -> pl.Expr:
    """Classify wall construction from EPC's free-text description.

    Three categories that matter thermally: solid walls (worst, hardest to
    treat), cavity walls (the bulk of the stock, cheap to insulate), and
    system-built or timber frame. Insulation state is captured separately by
    :func:`_wall_insulated_expression` because a solid wall with internal
    insulation behaves very differently from one without.
    """
    description = pl.col("walls_description").str.to_lowercase()
    return (
        pl.when(description.str.contains("cavity"))
        .then(pl.lit("cavity"))
        .when(description.str.contains("solid"))
        .then(pl.lit("solid"))
        .when(description.str.contains("timber|system|cob|granite|sandstone"))
        .then(pl.lit("other"))
        .otherwise(None)
        .alias("wall_type")
    )


def _wall_insulated_expression() -> pl.Expr:
    """Flag walls recorded as insulated.

    EPC descriptions distinguish "as built" and "no insulation (assumed)" from
    "filled cavity" and "with internal/external insulation". The negative
    phrasings are tested first because "no insulation" contains "insulation".
    """
    description = pl.col("walls_description").str.to_lowercase()
    return (
        pl.when(description.str.contains("no insulation|as built"))
        .then(pl.lit(value=False))
        .when(description.str.contains("insulat|filled cavity"))
        .then(pl.lit(value=True))
        .otherwise(None)
        .alias("wall_insulated")
    )


def build_ldz_stock_features(dwellings: pl.DataFrame) -> pl.DataFrame:
    """Aggregate dwelling-level EPC records to one row per LDZ.

    Parameters
    ----------
    dwellings :
        Deduplicated dwelling-level frame carrying ``ldz`` plus the EPC stock
        columns. One row per dwelling.

    Returns
    -------
    polars.DataFrame
        One row per LDZ with raw feature values, ``n_dwellings`` and
        ``has_stock_coverage``.

    Raises
    ------
    ValueError
        If any of the 13 zones is absent -- a missing zone would silently
        change every fixed effect in the downstream panel.
    """
    sap = pl.col("current_energy_efficiency").cast(pl.Float64, strict=False)
    floor_area = pl.col("total_floor_area").cast(pl.Float64, strict=False)
    # Floor areas outside this range are data errors, not dwellings.
    floor_area_clean = pl.when((floor_area > 10) & (floor_area < 1000)).then(floor_area)

    prepared = dwellings.with_columns(
        _age_band_expression(),
        _wall_type_expression(),
        _wall_insulated_expression(),
        sap.alias("sap"),
        floor_area_clean.alias("floor_area"),
        (pl.col("mains_gas_flag").str.to_uppercase() == "Y").alias("is_mains_gas"),
        pl.col("walls_energy_eff").str.to_lowercase().alias("wall_eff"),
    )

    aggregated = prepared.group_by("ldz").agg(
        pl.len().alias("n_dwellings"),
        pl.col("sap").mean().alias("mean_sap"),
        pl.col("floor_area").mean().alias("mean_floor_area"),
        pl.col("is_mains_gas").mean().alias("share_mains_gas"),
        (pl.col("wall_type") == "solid").mean().alias("share_solid_wall"),
        (pl.col("wall_type") == "cavity").mean().alias("share_cavity_wall"),
        pl.col("wall_insulated").mean().alias("share_wall_insulated"),
        (pl.col("wall_eff").is_in(["poor", "very poor"]))
        .mean()
        .alias("share_wall_eff_poor"),
        (pl.col("age_band") == "pre_1930").mean().alias("share_pre_1930"),
        (pl.col("age_band") == "1930_1975").mean().alias("share_1930_1975"),
        (pl.col("age_band") == "1976_1995").mean().alias("share_1976_1995"),
        (pl.col("age_band") == "post_1996").mean().alias("share_post_1996"),
    )

    present = set(aggregated["ldz"].to_list())
    missing = sorted(set(LDZ_CODES) - present)
    if missing:
        msg = (
            f"LDZ(s) {missing} absent from the stock aggregate; refusing partial panel"
        )
        raise ValueError(msg)

    return aggregated.with_columns(
        (pl.col("n_dwellings") >= MIN_DWELLINGS_FOR_COVERAGE).alias(
            "has_stock_coverage"
        )
    ).sort("ldz")


#: Features offered to the core test. Deliberately short: each additional
#: candidate is another implicit comparison, and the decision log counts them.
STOCK_FEATURES: Final[tuple[str, ...]] = (
    "mean_sap",
    "share_solid_wall",
    "share_wall_eff_poor",
    "share_pre_1930",
    "mean_floor_area",
    "share_mains_gas",
)


def standardise_stock_features(
    features: pl.DataFrame,
    *,
    columns: tuple[str, ...] = STOCK_FEATURES,
) -> pl.DataFrame:
    """Standardise each stock feature across zones **with coverage only**.

    Zones without coverage keep null standardised values rather than a zero,
    so that any attempt to use them in a regression fails loudly instead of
    quietly asserting that Scotland has exactly average housing stock.

    Returns
    -------
    polars.DataFrame
        Input columns plus ``<feature>_z`` for each standardised feature.
    """
    covered = features.filter(pl.col("has_stock_coverage"))
    if covered.height < 3:
        msg = f"only {covered.height} zone(s) have stock coverage; cannot standardise"
        raise ValueError(msg)

    result = features
    for column in columns:
        mean = covered[column].mean()
        std = covered[column].std(ddof=0)
        if std is None or std == 0:
            msg = f"stock feature {column!r} has zero variance across covered zones"
            raise ValueError(msg)
        result = result.with_columns(
            pl.when(pl.col("has_stock_coverage"))
            .then((pl.col(column) - mean) / std)
            .otherwise(None)
            .alias(f"{column}_z")
        )
    return result
