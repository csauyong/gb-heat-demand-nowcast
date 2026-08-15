"""EPC bulk register loader, streamed without ever landing 88 GB on disk.

The access route
----------------
``docs/data_inventory.md`` §1 names the EPC Open Data service at
``epc.opendatacommunities.org``. As at 2026-08-15 the bulk download has moved to
MHCLG's newer API::

    GET https://api.get-energy-performance-data.communities.gov.uk/api/files/domestic/csv
    Authorization: Bearer <token>

Same publisher, same dataset, new host and a bearer token instead of HTTP Basic
with an email plus key. The token is read from ``EPC_API_BEARER_TOKEN`` in the
gitignored ``.env`` and **never** appears in a URL, a cache sidecar, a log line
or a committed file.

Why streaming, and why by year
------------------------------
The endpoint 303-redirects to a presigned S3 object of **7.57 GB compressed**
that expands to **87.8 GB** across 36 members. Neither figure fits the machine
this runs on. But the archive is partitioned::

    certificates-2009.csv ... certificates-2026.csv
    recommendations-2009.csv ... recommendations-2026.csv

which makes the problem tractable three ways:

1. **Recommendations are never read** -- roughly half the archive, unused.
2. **Only certificate years up to the as-of cutoff are read.** A stock snapshot
   as of 2023-11-30 needs 2009-2023 and can skip 2024-2026 entirely. This is
   not an optimisation, it is the point-in-time rule doing useful work: a
   certificate lodged after the cutoff must not enter the snapshot, and the
   cheapest way to guarantee that is never to download it.
3. **Only ~15 of 93 columns are kept**, and the slim per-year extract is
   written to parquet as it streams.

:class:`PresignedRangeReader` presents the remote object as a seekable file via
HTTP Range requests, so ``zipfile`` can read the central directory and
decompress one member at a time. Peak disk is the slim extract (~1 GB), not
88 GB. Presigned URLs expire, so the reader re-resolves on a 403 mid-stream.

Coverage: England and Wales only
--------------------------------
This register is MHCLG's and covers **England and Wales**. Its ``country``
column contains only those two values. Scotland has a separate register with a
different schema (``docs/data_inventory.md`` §1). That matters here more than
usual: Scotland is one of the 13 Local Distribution Zones in the Phase 1b
panel, so any LDZ stock feature built from this source is **missing for SC**.
:func:`load_epc_lsoa_aggregates` does not paper over it -- the SC rows simply do
not exist, and the caller must decide between dropping the zone (12 clusters,
worse power) or flagging it. Silently treating an absent zone as zero would be
the worst of the three.

Deduplication and the point-in-time rule
----------------------------------------
``docs/data_inventory.md`` §1 is explicit: deduplicate to latest-certificate-
per-address **as of the analysis date**, not latest-ever, because latest-ever
is a leak. Implemented by filtering to ``lodgement_date <= as_of`` *before*
taking the latest per address, keyed on UPRN where present and on a hash of the
address plus postcode where it is not.
"""

from __future__ import annotations

import datetime as dt
import io
import os
import zipfile
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Final

import pandas as pd
import requests

if TYPE_CHECKING:
    import polars as pl

from heat_nowcast.paths import RAW_DIR

EPC_BULK_URL: Final[str] = (
    "https://api.get-energy-performance-data.communities.gov.uk/api/files/domestic/csv"
)
TOKEN_ENV_VAR: Final[str] = "EPC_API_BEARER_TOKEN"

EPC_LICENCE: Final[str] = (
    "Open Government Licence v3.0, EXCEPT address and postcode fields which "
    "carry Royal Mail / Ordnance Survey terms. Do not redistribute or commit "
    "address-level data; aggregate before anything leaves data/raw "
    "(docs/data_inventory.md §1)."
)

#: First and last certificate year present in the archive as at 2026-08-15.
FIRST_CERTIFICATE_YEAR: Final[int] = 2009
LAST_CERTIFICATE_YEAR: Final[int] = 2026

#: The ~15 columns actually used, out of 93. Keeping the list explicit means a
#: schema change upstream fails loudly instead of silently producing nulls.
REQUIRED_COLUMNS: Final[tuple[str, ...]] = (
    "certificate_number",
    "uprn",
    "postcode",
    "local_authority_label",
    "country",
    "lodgement_date",
    "property_type",
    "built_form",
    "tenure",
    "construction_age_band",
    "total_floor_area",
    "current_energy_efficiency",
    "walls_description",
    "walls_energy_eff",
    "main_fuel",
    "mainheat_description",
    "mains_gas_flag",
)

_TIMEOUT: Final[int] = 600
_CHUNK_BYTES: Final[int] = 8 * 1024 * 1024


def _bearer_token() -> str:
    """Read the API token from the environment, or from a gitignored .env.

    Never returned to a caller that logs it, never interpolated into a URL.
    """
    token = os.environ.get(TOKEN_ENV_VAR)
    if token:
        return token
    env_file = Path(__file__).resolve().parents[3] / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                key, value = stripped.split("=", 1)
                if key.strip() == TOKEN_ENV_VAR:
                    return value.strip()
    msg = (
        f"{TOKEN_ENV_VAR} not set. Put it in the gitignored .env "
        f"(see .env.example); it must never be committed."
    )
    raise RuntimeError(msg)


class PresignedRangeReader(io.RawIOBase):
    """Seekable file-like over a presigned S3 object, backed by HTTP Range.

    Lets ``zipfile`` read a multi-gigabyte remote archive without downloading
    it. Presigned URLs expire, so a non-206 response triggers a re-resolve
    against the API and one retry.

    Parameters
    ----------
    resolve :
        Callable returning a fresh presigned URL.
    """

    def __init__(self, resolve: Callable[[], str]) -> None:
        self._resolve = resolve
        self._url: str = resolve()
        self._position = 0
        probe = requests.get(
            self._url, headers={"Range": "bytes=0-0"}, timeout=_TIMEOUT
        )
        probe.raise_for_status()
        self._size = int(probe.headers["Content-Range"].split("/")[1])

    @property
    def size(self) -> int:
        """Total object size in bytes."""
        return self._size

    def readable(self) -> bool:
        """Return True; the object is read-only."""
        return True

    def seekable(self) -> bool:
        """Return True; Range requests make the object seekable."""
        return True

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        """Move the read position."""
        if whence == io.SEEK_SET:
            self._position = offset
        elif whence == io.SEEK_CUR:
            self._position += offset
        else:
            self._position = self._size + offset
        return self._position

    def tell(self) -> int:
        """Return the current read position."""
        return self._position

    def read(self, size: int = -1) -> bytes:
        """Read ``size`` bytes from the current position."""
        if size is None or size < 0:
            size = self._size - self._position
        size = min(size, self._size - self._position)
        if size <= 0:
            return b""
        end = self._position + size - 1
        response = None
        for attempt in range(3):
            response = requests.get(
                self._url,
                headers={"Range": f"bytes={self._position}-{end}"},
                timeout=_TIMEOUT,
            )
            if response.status_code in (200, 206):
                break
            if attempt < 2:
                self._url = self._resolve()  # presigned URL expired
        if response is None or response.status_code not in (200, 206):
            msg = f"range request failed at byte {self._position}"
            raise RuntimeError(msg)
        self._position += len(response.content)
        return response.content

    def readinto(self, buffer: memoryview) -> int:  # type: ignore[override]  # RawIOBase accepts any writable buffer
        """Read into a pre-allocated buffer."""
        data = self.read(len(buffer))
        buffer[: len(data)] = data
        return len(data)


def _resolve_presigned_url() -> str:
    """Exchange the bearer token for a presigned download URL.

    The token travels in the ``Authorization`` header only. The returned URL
    carries its own signature in the query string and is therefore itself
    sensitive -- it is never logged or written to a sidecar.
    """
    response = requests.get(
        EPC_BULK_URL,
        headers={
            "Authorization": f"Bearer {_bearer_token()}",
            "Accept": "application/json",
        },
        allow_redirects=False,
        timeout=_TIMEOUT,
    )
    if response.status_code not in (302, 303, 307):
        response.raise_for_status()
    location = response.headers.get("location")
    if not location:
        msg = "EPC API did not return a download redirect"
        raise RuntimeError(msg)
    return location


def open_bulk_archive() -> tuple[zipfile.ZipFile, PresignedRangeReader]:
    """Open the remote EPC bulk archive for streaming member reads.

    The raw range reader **must** be wrapped in a large buffer. ``zipfile``
    reads its members in 4 KB chunks, and served directly that would mean one
    HTTP round trip per 4 KB -- roughly 75,000 requests per certificate year,
    which does not complete in any useful time. An 8 MB buffer turns the same
    work into ~40 requests per year and makes the whole extraction network-
    bound rather than latency-bound.
    """
    reader = PresignedRangeReader(_resolve_presigned_url)
    buffered = io.BufferedReader(reader, buffer_size=_CHUNK_BYTES)
    return zipfile.ZipFile(buffered), reader


def certificate_years(as_of: dt.date) -> list[int]:
    """Certificate member years needed for a snapshot as of ``as_of``.

    Years after the cutoff are never downloaded -- the point-in-time rule
    doing double duty as a bandwidth saving.
    """
    last = min(as_of.year, LAST_CERTIFICATE_YEAR)
    return list(range(FIRST_CERTIFICATE_YEAR, last + 1))


def _slim_path(year: int, vintage: str) -> Path:
    return RAW_DIR / "epc_slim" / f"epc_certificates_{year}__{vintage}.parquet"


def stream_certificate_year(
    archive: zipfile.ZipFile,
    year: int,
    *,
    as_of: dt.date,
    chunk_rows: int = 500_000,
) -> Iterator[pd.DataFrame]:
    """Stream one certificate year, yielding slim, cutoff-filtered chunks.

    Only :data:`REQUIRED_COLUMNS` are retained and only rows with
    ``lodgement_date <= as_of`` survive.
    """
    member = f"certificates-{year}.csv"
    with archive.open(member) as handle:
        text = io.TextIOWrapper(handle, encoding="utf-8", errors="replace")
        reader = pd.read_csv(
            text,
            usecols=list(REQUIRED_COLUMNS),
            dtype="string",
            chunksize=chunk_rows,
            on_bad_lines="warn",
        )
        for chunk in reader:
            lodgement = pd.to_datetime(
                chunk["lodgement_date"], format="%Y-%m-%d", errors="coerce"
            )
            keep = lodgement.notna() & (lodgement <= pd.Timestamp(as_of))
            slim = chunk.loc[keep].copy()
            if len(slim) == 0:
                continue
            slim["lodgement_date"] = lodgement.loc[keep]
            yield slim


def extract_slim_certificates(
    *,
    as_of: dt.date,
    vintage: str,
    refresh: bool = False,
) -> list[Path]:
    """Download and slim every certificate year needed, one parquet per year.

    Source: https://api.get-energy-performance-data.communities.gov.uk/api/files/domestic/csv
        (MHCLG EPC bulk domestic register; presigned S3 object
        ``full-load/domestic-csv.zip``).
    Licence: see :data:`EPC_LICENCE` -- OGL v3.0 except address and postcode
        fields, which must not be redistributed or committed.
    Vintage: caller-supplied; use the archive's ``Last-Modified``.
    Publication lag: certificates are lodged within days of assessment, but the
        bulk file is refreshed periodically, so an effective lag of weeks to
        months applies. Irrelevant to the point-in-time rule here because the
        snapshot is explicitly cut at ``as_of`` on ``lodgement_date``.

    Each year is cached separately, so an interrupted run resumes rather than
    restarting a multi-gigabyte stream.

    Returns
    -------
    list[pathlib.Path]
        Parquet paths, one per year, in ascending year order.
    """
    (RAW_DIR / "epc_slim").mkdir(parents=True, exist_ok=True)
    years = certificate_years(as_of)
    wanted = [
        year for year in years if refresh or not _slim_path(year, vintage).exists()
    ]

    if wanted:
        archive, _reader = open_bulk_archive()
        try:
            for year in wanted:
                frames = list(stream_certificate_year(archive, year, as_of=as_of))
                combined = (
                    pd.concat(frames, ignore_index=True)
                    if frames
                    else pd.DataFrame(columns=list(REQUIRED_COLUMNS))
                )
                combined.to_parquet(_slim_path(year, vintage), index=False)
        finally:
            archive.close()

    return [_slim_path(year, vintage) for year in years]


#: Columns needed downstream of dedupe. Narrowing here is what keeps the
#: 23 M-certificate dedupe inside memory.
STOCK_COLUMNS: Final[tuple[str, ...]] = (
    "postcode",
    "country",
    "current_energy_efficiency",
    "total_floor_area",
    "construction_age_band",
    "walls_description",
    "walls_energy_eff",
    "main_fuel",
    "mainheat_description",
    "mains_gas_flag",
    "property_type",
    "built_form",
    "tenure",
)


def dedupe_to_dwellings(
    *,
    as_of: dt.date,
    vintage: str,
) -> pl.DataFrame:
    """Reduce the certificate stream to one row per dwelling, as of ``as_of``.

    ``docs/data_inventory.md`` §1 requires latest-certificate-per-address **as
    of the analysis date**, never latest-ever. The ``as_of`` filter is already
    applied upstream by :func:`extract_slim_certificates`, so "latest" here is
    automatically "latest as of the cutoff".

    Implementation note, because the obvious version does not fit in memory:
    sorting 23 million rows and taking the last per key materialises the whole
    frame and gets the process killed. Instead the years are walked in
    **descending** order, so the first time an address is seen it is already
    its latest certificate. Only a single-column frame of keys already seen is
    carried between years, which is a few hundred megabytes rather than tens of
    gigabytes.

    Returns
    -------
    polars.DataFrame
        One row per dwelling with :data:`STOCK_COLUMNS` plus ``addr_key`` and
        ``lodgement_date``.
    """
    import polars as pl

    years = sorted(certificate_years(as_of), reverse=True)
    address_key = (
        pl.when(pl.col("uprn").is_not_null() & (pl.col("uprn").str.strip_chars() != ""))
        .then(pl.concat_str([pl.lit("U:"), pl.col("uprn").str.strip_chars()]))
        .otherwise(pl.concat_str([pl.lit("C:"), pl.col("certificate_number")]))
        .alias("addr_key")
    )

    kept: list[pl.DataFrame] = []
    seen: pl.DataFrame | None = None
    for year in years:
        frame = (
            pl.read_parquet(_slim_path(year, vintage))
            .with_columns(address_key)
            .sort("lodgement_date")
            .unique(subset=["addr_key"], keep="last")
            .select(["addr_key", "lodgement_date", *STOCK_COLUMNS])
        )
        if seen is not None:
            frame = frame.join(seen, on="addr_key", how="anti")
        kept.append(frame)
        block = frame.select("addr_key")
        seen = block if seen is None else pl.concat([seen, block])

    return pl.concat(kept)
