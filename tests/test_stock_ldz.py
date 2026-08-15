"""Postcode-to-LDZ assignment and LDZ stock feature tests.

The failure this guards against is the Phase 1 one repeating in a worse place:
a silent coverage gap that lands directly on the regressor of interest. A zone
with no dwellings must be *flagged*, never imputed to the mean.
"""

from __future__ import annotations

import pandas as pd
import polars as pl
import pytest

from heat_nowcast.data.gas import LDZ_CODES
from heat_nowcast.data.ldz_postcode import (
    NON_NTS_LDZ_CODES,
    assign_ldz,
    build_outcode_fallback,
    normalise_postcode,
    outcode_of,
)
from heat_nowcast.features.stock_ldz import (
    MIN_DWELLINGS_FOR_COVERAGE,
    build_ldz_stock_features,
    standardise_stock_features,
)


def lookup() -> pd.DataFrame:
    """Small lookup with an ambiguous outcode and a non-NTS zone."""
    rows = [
        ("SM14PY", "SM1", "EA", True),
        ("SM14PZ", "SM1", "EA", True),
        ("M11AA", "M1", "NW", True),
        ("M11AB", "M1", "NW", True),
        # AB1 deliberately spans two LDZs -- the ambiguity the real file has
        ("AB11AA", "AB1", "SC", True),
        ("AB11AB", "AB1", "NE", True),
        ("LP10AA", "LP1", "LC", False),
    ]
    return pd.DataFrame(rows, columns=["postcode", "outcode", "ldz", "is_nts"])


# --------------------------------------------------------------------------
# postcode normalisation
# --------------------------------------------------------------------------


def test_normalisation_makes_epc_and_xoserve_forms_agree():
    """EPC writes 'SM1 4PY'; Xoserve splits it. Both must reduce to one key."""
    epc = normalise_postcode(pd.Series(["SM1 4PY", "sm1  4py", " SM14PY "]))
    assert set(epc) == {"SM14PY"}


def test_outcode_is_everything_before_the_final_three_characters():
    """UK inward codes are always three characters -- exact, not a regex guess."""
    result = outcode_of(pd.Series(["SM1 4PY", "M1 1AA", "EC1A 1BB"]))
    assert list(result) == ["SM1", "M1", "EC1A"]


def test_outcode_of_rejects_too_short_input():
    assert pd.isna(outcode_of(pd.Series(["ABC"])).iloc[0])


# --------------------------------------------------------------------------
# assignment
# --------------------------------------------------------------------------


def test_full_postcode_match_is_preferred():
    result = assign_ldz(pd.Series(["SM1 4PY"]), lookup())
    assert result["ldz"].iloc[0] == "EA"
    assert result["match_level"].iloc[0] == "full"


def test_outcode_fallback_used_only_when_full_match_missing():
    """A postcode absent from the 2017 file falls back to its outcode."""
    result = assign_ldz(pd.Series(["SM1 9ZZ"]), lookup())
    assert result["ldz"].iloc[0] == "EA"
    assert result["match_level"].iloc[0] == "outcode"


def test_ambiguous_outcode_is_never_guessed():
    """188 real outcodes span >1 LDZ. Guessing would put measurement error
    directly on the regressor of interest, so they must stay unmatched."""
    fallback = build_outcode_fallback(lookup())
    assert "AB1" not in set(fallback["outcode"])

    result = assign_ldz(pd.Series(["AB1 9ZZ"]), lookup())
    assert pd.isna(result["ldz"].iloc[0])
    assert result["match_level"].iloc[0] == "none"


def test_unmatched_postcode_returns_na_not_a_default_zone():
    result = assign_ldz(pd.Series(["ZZ9 9ZZ"]), lookup())
    assert pd.isna(result["ldz"].iloc[0])
    assert result["match_level"].iloc[0] == "none"


def test_non_nts_zones_are_flagged():
    """LPG/isolated networks have no published LDZ demand series."""
    result = assign_ldz(pd.Series(["LP1 0AA"]), lookup())
    assert result["ldz"].iloc[0] == "LC"
    assert bool(result["is_nts"].iloc[0]) is False
    assert "LC" in NON_NTS_LDZ_CODES


def test_assignment_is_aligned_by_position():
    postcodes = pd.Series(["SM1 4PY", "ZZ9 9ZZ", "M1 1AA"])
    result = assign_ldz(postcodes, lookup())
    assert len(result) == 3
    assert list(result["match_level"]) == ["full", "none", "full"]


# --------------------------------------------------------------------------
# stock features
# --------------------------------------------------------------------------


def dwellings(scotland_rows: int = 10) -> pl.DataFrame:
    """Synthetic dwelling frame covering all 13 zones, SC deliberately tiny.

    Composition is varied **by zone** -- the real panel's whole point is
    cross-sectional differences, and a fixture with identical stock everywhere
    would give every feature zero variance and mask real bugs behind the
    zero-variance guard.
    """
    records: list[dict[str, object]] = []
    for index, ldz in enumerate(LDZ_CODES):
        count = scotland_rows if ldz == "SC" else MIN_DWELLINGS_FOR_COVERAGE + 100
        # Solid-wall share ranges from ~8% to ~50% across zones, roughly the
        # real spread (WS 6.5% to NT 49.8%).
        solid_every = 2 + (index % 11)
        for row in range(count):
            is_solid = row % solid_every == 0
            records.append(
                {
                    "ldz": ldz,
                    "current_energy_efficiency": str(60 + index + (row % 3)),
                    "total_floor_area": str(80 + index),
                    "construction_age_band": (
                        "England and Wales: 1900-1929"
                        if row % (2 + index % 3) == 0
                        else "England and Wales: 1983-1990"
                    ),
                    "walls_description": (
                        "Solid brick, as built, no insulation (assumed)"
                        if is_solid
                        else "Cavity wall, filled cavity"
                    ),
                    "walls_energy_eff": "Poor" if is_solid else "Good",
                    "mains_gas_flag": "Y" if row % (3 + index % 4) else "N",
                    "main_fuel": "mains gas (not community)",
                    "mainheat_description": "Boilers, mains gas",
                    "property_type": "House",
                    "built_form": "Semi-Detached",
                    "tenure": "owner-occupied",
                    "postcode": "AA1 1AA",
                    "country": "England",
                }
            )
    return pl.DataFrame(records)


def test_all_thirteen_zones_required():
    frame = dwellings().filter(pl.col("ldz") != "WN")
    with pytest.raises(ValueError, match="absent from the stock aggregate"):
        build_ldz_stock_features(frame)


def test_low_coverage_zone_is_flagged_not_dropped():
    """Scotland has 478 real dwellings. It must survive as a row, flagged."""
    features = build_ldz_stock_features(dwellings())
    assert features.height == 13
    scotland = features.filter(pl.col("ldz") == "SC")
    assert scotland.height == 1
    assert bool(scotland["has_stock_coverage"][0]) is False
    assert bool(features.filter(pl.col("ldz") == "NW")["has_stock_coverage"][0]) is True


def test_uncovered_zone_gets_null_not_zero_after_standardisation():
    """Imputing 'average stock' for a zone with no data would be a fabrication
    sitting directly on the regressor of interest."""
    features = standardise_stock_features(build_ldz_stock_features(dwellings()))
    scotland = features.filter(pl.col("ldz") == "SC")
    assert scotland["mean_sap_z"][0] is None
    covered = features.filter(pl.col("has_stock_coverage"))
    assert covered["mean_sap_z"].null_count() == 0


def test_standardised_features_have_zero_mean_over_covered_zones():
    features = standardise_stock_features(build_ldz_stock_features(dwellings()))
    covered = features.filter(pl.col("has_stock_coverage"))
    assert covered["mean_sap_z"].mean() == pytest.approx(0.0, abs=1e-9)
    assert covered["mean_sap_z"].std(ddof=0) == pytest.approx(1.0, abs=1e-9)


def test_standardisation_excludes_the_uncovered_zone_from_its_moments():
    """SC must not drag the mean it is then compared against."""
    features = build_ldz_stock_features(dwellings())
    standardised = standardise_stock_features(features)
    covered = features.filter(pl.col("has_stock_coverage"))
    expected_mean = covered["mean_sap"].mean()
    recovered = standardised.filter(pl.col("ldz") == "NW")
    raw = recovered["mean_sap"][0]
    z_value = recovered["mean_sap_z"][0]
    assert (raw - expected_mean) / covered["mean_sap"].std(ddof=0) == pytest.approx(
        z_value
    )


def test_zero_variance_feature_raises():
    frame = dwellings().with_columns(pl.lit("70").alias("current_energy_efficiency"))
    features = build_ldz_stock_features(frame)
    with pytest.raises(ValueError, match="zero variance"):
        standardise_stock_features(features, columns=("mean_sap",))


def test_wall_classification_separates_solid_from_cavity():
    """Solid and cavity shares must partition the stock and vary across zones."""
    features = build_ldz_stock_features(dwellings())
    covered = features.filter(pl.col("has_stock_coverage"))
    total = covered["share_solid_wall"] + covered["share_cavity_wall"]
    assert all(value == pytest.approx(1.0, abs=1e-9) for value in total)
    # Cross-sectional spread is the whole point of the panel.
    spread = covered["share_solid_wall"].to_numpy().std()
    assert spread > 0.05
