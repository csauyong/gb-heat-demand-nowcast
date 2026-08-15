"""Postcode to Local Distribution Zone lookup, from Xoserve.

Why this rather than boundary polygons
--------------------------------------
LDZ is a **gas-industry operational geography**, not a statistical one: the
region served by one gas distribution network downstream of the National
Transmission System, inherited from the old regional gas boards. ONS does not
publish it, so there is no LSOA-style boundary product, and an LSOA boundary
file cannot resolve it either -- knowing a dwelling's coordinates does not tell
you its LDZ without LDZ geometry.

Xoserve, the gas industry's central data agent, publishes the **Postcode Exit
Zone List**: a full-postcode to LDZ mapping compiled by the network operators
themselves. It is the mapping actually used for settlement, which makes it
authoritative rather than an approximation, and it removes the need for any
spatial join -- EPC carries `postcode`, so this is a direct key lookup.

Source: https://www.xoserve.com/a-to-z/ -> "Postcode Exit Zone List"
    (``https://www.xoserve.com/media/2008/postcode-exit-zone-list-may-2017.zip``,
    a 23 MB zip containing a 34 MB xlsx with one sheet per distribution
    network: WWU, SGN, NGN, NG).
Licence: published freely by Xoserve on behalf of the GB gas Distribution
    Network Operators. Not OGL. Free to access; check Xoserve's terms before
    redistributing derived data.
Vintage: **May 2017** -- see the caveat below.
Publication lag: not applicable. LDZ boundaries derive from the regional gas
    board structure and are effectively static.

Two caveats, both disclosed rather than smoothed over
-----------------------------------------------------
**Vintage.** The list is dated May 2017, which is *older* than the
2023-11-30 stock cutoff. That is the safe direction -- it cannot contain
information from after the cutoff -- but postcodes created since 2017 will not
match. :func:`assign_ldz` falls back to outcode-level matching for those and
reports the residual unmatched share so it can be stated rather than assumed
negligible.

**Outcode is not sufficient.** 188 of 3,100 outcodes (**6.1%**) span more than
one LDZ. Matching on outcode alone would misassign a meaningful slice of the
stock, so the full postcode is the primary key and outcode is only a fallback,
and only where that outcode maps unambiguously to a single LDZ.

The 13 zones, and the five that are not
---------------------------------------
The file contains 18 LDZ codes. Thirteen are the NTS-connected zones that
National Gas publishes demand and forecasts for, and that form the Phase 1b
panel. The other five (LC, LO, LS, LT, LW) are small LPG or otherwise isolated
networks totalling ~1,045 postcodes; they are not on the NTS, have no published
LDZ demand series, and are excluded. That the file's thirteen main codes match
:data:`heat_nowcast.data.gas.LDZ_CODES` exactly is a useful independent check
on the panel definition.
"""

from __future__ import annotations

import io
import zipfile
from typing import Final

import pandas as pd
import requests

from heat_nowcast.data.cache import cached_pull
from heat_nowcast.data.gas import LDZ_CODES

XOSERVE_PEZ_URL: Final[str] = (
    "https://www.xoserve.com/media/2008/postcode-exit-zone-list-may-2017.zip"
)
XOSERVE_LICENCE: Final[str] = (
    "Published freely by Xoserve for the GB gas Distribution Network "
    "Operators. Not OGL. Free to access; check Xoserve terms before "
    "redistributing derived data."
)

#: One sheet per distribution network.
PEZ_SHEETS: Final[tuple[str, ...]] = ("WWU", "SGN", "NGN", "NG")

#: LPG / isolated networks present in the file but not on the NTS, and with no
#: published LDZ demand series. Excluded from the panel.
NON_NTS_LDZ_CODES: Final[frozenset[str]] = frozenset({"LC", "LO", "LS", "LT", "LW"})

_TIMEOUT: Final[int] = 600


def normalise_postcode(values: pd.Series) -> pd.Series:
    """Reduce postcodes to a comparable key: uppercase, no whitespace.

    EPC renders postcodes as ``"SM1 4PY"``; Xoserve splits them into
    ``Outcode``/``Incode``. Stripping all whitespace and upper-casing makes the
    two directly joinable without guessing at spacing conventions.
    """
    return (
        values.astype("string")
        .str.upper()
        .str.replace(r"\s+", "", regex=True)
        .str.strip()
    )


def outcode_of(values: pd.Series) -> pd.Series:
    """Extract the outward code from a normalised postcode.

    The inward code is always the final three characters of a UK postcode, so
    the outward code is everything before them. This is exact, unlike a regex
    on letter/digit patterns.
    """
    normalised = normalise_postcode(values)
    return normalised.str.slice(0, -3).where(normalised.str.len() > 3)


def load_postcode_to_ldz(
    *,
    vintage: str = "2017-05",
    refresh: bool = False,
) -> pd.DataFrame:
    """Load the Xoserve full-postcode to LDZ mapping.

    Source, licence, vintage and caveats: see the module docstring.

    Parameters
    ----------
    vintage :
        Vintage label; also the cache key. Defaults to the file's own date.
    refresh :
        Force a re-pull.

    Returns
    -------
    pandas.DataFrame
        Columns ``postcode`` (normalised, no spaces), ``outcode``, ``ldz``,
        ``exit_zone``, ``gdn``, ``is_nts`` -- one row per postcode. NTS and
        non-NTS rows are both returned; filtering is the caller's decision and
        is made explicitly in :func:`assign_ldz`.
    """

    def fetch() -> tuple[pd.DataFrame, list[str]]:
        response = requests.get(XOSERVE_PEZ_URL, timeout=_TIMEOUT)
        response.raise_for_status()
        archive = zipfile.ZipFile(io.BytesIO(response.content))
        member = next(n for n in archive.namelist() if n.lower().endswith(".xlsx"))
        with archive.open(member) as handle:
            payload = io.BytesIO(handle.read())

        frames: list[pd.DataFrame] = []
        for sheet in PEZ_SHEETS:
            sheet_frame = pd.read_excel(
                payload, sheet_name=sheet, engine="openpyxl", dtype="string"
            )
            sheet_frame["gdn"] = sheet
            frames.append(sheet_frame)
        return pd.concat(frames, ignore_index=True), [XOSERVE_PEZ_URL]

    raw = cached_pull(
        dataset="xoserve_postcode_exit_zone",
        vintage=vintage,
        licence=XOSERVE_LICENCE,
        publication_lag=(
            "Not applicable -- LDZ boundaries are effectively static. File "
            "vintage May 2017, older than the 2023-11-30 stock cutoff."
        ),
        fetch=fetch,
        params={"sheets": list(PEZ_SHEETS), "url": XOSERVE_PEZ_URL},
        notes=(
            "Full-postcode to LDZ mapping compiled by the GB gas Distribution "
            "Network Operators. 6.1% of outcodes span >1 LDZ, so match on full "
            "postcode."
        ),
        refresh=refresh,
    )

    frame = pd.DataFrame(
        {
            "postcode": normalise_postcode(
                raw["Outcode"].fillna("") + raw["Incode"].fillna("")
            ),
            "outcode": normalise_postcode(raw["Outcode"]),
            "ldz": raw["LDZ"].astype("string").str.strip().str.upper(),
            "exit_zone": raw["Exit Zone"].astype("string").str.strip(),
            "gdn": raw["gdn"].astype("string"),
        }
    )
    frame = frame.dropna(subset=["postcode", "ldz"])
    frame = frame[frame["postcode"].str.len() >= 5]
    frame["is_nts"] = ~frame["ldz"].isin(NON_NTS_LDZ_CODES)

    known = set(frame.loc[frame["is_nts"], "ldz"].unique())
    expected = set(LDZ_CODES)
    if known != expected:
        msg = (
            f"Xoserve NTS LDZ codes {sorted(known)} do not match the panel "
            f"definition {sorted(expected)}"
        )
        raise ValueError(msg)

    return frame.drop_duplicates("postcode", keep="first").reset_index(drop=True)


def build_outcode_fallback(lookup: pd.DataFrame) -> pd.DataFrame:
    """Outcode to LDZ, restricted to outcodes that map to exactly one LDZ.

    Ambiguous outcodes are deliberately excluded rather than resolved by
    majority vote: a 6.1% ambiguity rate is large enough that guessing would
    introduce exactly the kind of measurement error the core test is least able
    to tolerate, since it lands directly on the regressor of interest.
    """
    counts = lookup.groupby("outcode")["ldz"].nunique()
    unambiguous = counts[counts == 1].index
    return (
        lookup[lookup["outcode"].isin(unambiguous)]
        .drop_duplicates("outcode", keep="first")[["outcode", "ldz", "is_nts"]]
        .reset_index(drop=True)
    )


def assign_ldz(
    postcodes: pd.Series,
    lookup: pd.DataFrame,
) -> pd.DataFrame:
    """Assign an LDZ to each postcode, full match first then outcode fallback.

    Parameters
    ----------
    postcodes :
        Raw postcodes, any spacing or case.
    lookup :
        Frame from :func:`load_postcode_to_ldz`.

    Returns
    -------
    pandas.DataFrame
        Aligned to ``postcodes`` by position, with columns ``ldz``,
        ``match_level`` (``"full"``, ``"outcode"`` or ``"none"``) and
        ``is_nts``. Unmatched rows carry NA rather than a guess.
    """
    normalised = normalise_postcode(postcodes)
    full = lookup.set_index("postcode")[["ldz", "is_nts"]]
    matched = full.reindex(normalised.to_numpy())

    result = pd.DataFrame(
        {
            "ldz": matched["ldz"].to_numpy(),
            "is_nts": matched["is_nts"].to_numpy(),
        },
        index=pd.RangeIndex(len(normalised)),
    )
    result["match_level"] = pd.Series(pd.notna(result["ldz"]), index=result.index).map(
        {True: "full", False: "none"}
    )

    missing = result["ldz"].isna()
    if missing.any():
        fallback = build_outcode_fallback(lookup).set_index("outcode")
        outcodes = outcode_of(postcodes)[missing.to_numpy()]
        recovered = fallback.reindex(outcodes.to_numpy())
        result.loc[missing, "ldz"] = recovered["ldz"].to_numpy()
        result.loc[missing, "is_nts"] = recovered["is_nts"].to_numpy()
        result.loc[missing & result["ldz"].notna(), "match_level"] = "outcode"

    return result
