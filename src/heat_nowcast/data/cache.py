"""Idempotent on-disk cache for raw upstream pulls, with provenance sidecars.

Every cached artefact is a pair of files under ``data/raw/``::

    <name>__<vintage>.parquet    the payload
    <name>__<vintage>.json       the sidecar

The sidecar is the point of this module. `CLAUDE.md` §2.2 requires that a
backtest be able to state which *vintage* of a restated series it used, and
§7 requires every loader to record its source URL. A parquet file on its own
cannot answer either question six months later, so the sidecar records:

* every URL actually requested (not the documentation URL -- the real one);
* the UTC timestamp at which the bytes were retrieved;
* the licence string;
* the caller-supplied vintage label, which also appears in the filename;
* the row count and a SHA-256 of the payload, so silent upstream restatement
  is detectable by re-pulling and comparing;
* a free-text ``notes`` field for publication-lag facts worth carrying with
  the data.

Idempotence contract: calling a loader twice with the same arguments performs
zero network I/O the second time and returns an identical frame. Passing
``refresh=True`` forces a re-pull and *rewrites* the sidecar, which is how a
restatement is detected -- the ``content_sha256`` changes.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from heat_nowcast.paths import RAW_DIR

SIDECAR_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Provenance:
    """Everything needed to explain where a cached frame came from.

    Attributes
    ----------
    dataset :
        Stable short name for the artefact, used as the filename stem.
    source_urls :
        The URLs actually requested, in request order. Truncated to the first
        20 for multi-request pulls, with ``request_count`` recording the total.
    request_count :
        Number of HTTP requests made to assemble the payload.
    retrieved_at_utc :
        ISO-8601 UTC timestamp at which the pull completed.
    licence :
        Licence under which the upstream data is published.
    vintage :
        Caller-supplied vintage label (download date, dataset version, or
        upstream ``last_modified``). Also embedded in the filename.
    publication_lag :
        Free text describing when the values became knowable. This is the
        field that determines point-in-time legality (`CLAUDE.md` §2.3).
    rows :
        Row count of the cached frame.
    content_sha256 :
        SHA-256 over the payload bytes. Compare across pulls to detect
        upstream restatement.
    notes :
        Anything else worth carrying with the data.
    params :
        The loader arguments that produced this artefact.
    """

    dataset: str
    source_urls: list[str]
    request_count: int
    retrieved_at_utc: str
    licence: str
    vintage: str
    publication_lag: str
    rows: int
    content_sha256: str
    notes: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    schema_version: int = SIDECAR_SCHEMA_VERSION


def _slug(value: str) -> str:
    """Make a string safe to use inside a filename."""
    keep = [c if (c.isalnum() or c in "-_") else "-" for c in value]
    return "".join(keep).strip("-")


def cache_paths(dataset: str, vintage: str) -> tuple[Path, Path]:
    """Return the ``(payload, sidecar)`` paths for a dataset/vintage pair."""
    stem = f"{_slug(dataset)}__{_slug(vintage)}"
    return RAW_DIR / f"{stem}.parquet", RAW_DIR / f"{stem}.json"


def read_sidecar(dataset: str, vintage: str) -> Provenance | None:
    """Load the sidecar for a cached artefact, or ``None`` if absent."""
    _, sidecar_path = cache_paths(dataset, vintage)
    if not sidecar_path.exists():
        return None
    payload = json.loads(sidecar_path.read_text(encoding="utf-8"))
    payload.pop("schema_version", None)
    return Provenance(**payload, schema_version=SIDECAR_SCHEMA_VERSION)


def cached_pull(
    *,
    dataset: str,
    vintage: str,
    licence: str,
    publication_lag: str,
    fetch: Callable[[], tuple[pd.DataFrame, list[str]]],
    params: dict[str, Any] | None = None,
    notes: str = "",
    refresh: bool = False,
) -> pd.DataFrame:
    """Return a cached frame, pulling it from upstream only when necessary.

    Parameters
    ----------
    dataset :
        Short stable name; becomes the filename stem.
    vintage :
        Vintage label. Changing it forces a separate cache entry, which is how
        two vintages of a restated series are held side by side.
    licence :
        Upstream licence string, recorded in the sidecar.
    publication_lag :
        Statement of when the values became knowable (`CLAUDE.md` §2.3).
    fetch :
        Zero-argument callable performing the network I/O. Returns the frame
        and the list of URLs it requested. Only called on a cache miss or when
        ``refresh`` is set.
    params :
        Loader arguments, recorded in the sidecar for reproducibility.
    notes :
        Free text recorded in the sidecar.
    refresh :
        Re-pull even if the cache is warm, and overwrite the sidecar. Use this
        to detect upstream restatement by comparing ``content_sha256``.

    Returns
    -------
    pandas.DataFrame
        The cached payload.
    """
    payload_path, sidecar_path = cache_paths(dataset, vintage)
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    if payload_path.exists() and sidecar_path.exists() and not refresh:
        return pd.read_parquet(payload_path)

    frame, urls = fetch()
    frame.to_parquet(payload_path, index=False)
    digest = hashlib.sha256(payload_path.read_bytes()).hexdigest()

    provenance = Provenance(
        dataset=dataset,
        source_urls=urls[:20],
        request_count=len(urls),
        retrieved_at_utc=dt.datetime.now(tz=dt.UTC).isoformat(timespec="seconds"),
        licence=licence,
        vintage=vintage,
        publication_lag=publication_lag,
        rows=len(frame),
        content_sha256=digest,
        notes=notes,
        params=params or {},
    )
    sidecar_path.write_text(
        json.dumps(asdict(provenance), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return frame
