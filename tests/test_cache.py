"""Cache idempotence and provenance-sidecar tests.

No network. The ``fetch`` callable is a counter, so "did this hit the network"
is directly observable.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pandas as pd
import pytest

from heat_nowcast.data import cache as cache_module
from heat_nowcast.data.cache import cache_paths, cached_pull, read_sidecar


@pytest.fixture(autouse=True)
def temporary_raw_dir(tmp_path, monkeypatch):
    """Point the cache at a temporary directory for every test in this file."""
    raw = tmp_path / "raw"
    raw.mkdir()
    monkeypatch.setattr(cache_module, "RAW_DIR", raw)
    return raw


def make_fetch(counter: list[int]) -> Callable[[], tuple[pd.DataFrame, list[str]]]:
    def fetch() -> tuple[pd.DataFrame, list[str]]:
        counter.append(1)
        return pd.DataFrame({"value": [1, 2, 3]}), ["https://example.invalid/data.csv"]

    return fetch


def pull(counter: list[int], **overrides: Any) -> pd.DataFrame:
    kwargs: dict[str, Any] = {
        "dataset": "demo",
        "vintage": "2026-08-14",
        "licence": "OGL v3.0",
        "publication_lag": "knowable from D-1 08:45 UTC",
        "fetch": make_fetch(counter),
        "params": {"a": 1},
        "notes": "demo notes",
    }
    kwargs.update(overrides)
    return cached_pull(**kwargs)


def test_second_call_does_no_network_io():
    counter: list[int] = []
    first = pull(counter)
    second = pull(counter)
    assert len(counter) == 1
    pd.testing.assert_frame_equal(first, second)


def test_refresh_forces_a_repull():
    counter: list[int] = []
    pull(counter)
    pull(counter, refresh=True)
    assert len(counter) == 2


def test_sidecar_records_provenance():
    counter: list[int] = []
    pull(counter)
    provenance = read_sidecar("demo", "2026-08-14")

    assert provenance is not None
    assert provenance.source_urls == ["https://example.invalid/data.csv"]
    assert provenance.licence == "OGL v3.0"
    assert provenance.vintage == "2026-08-14"
    assert provenance.publication_lag == "knowable from D-1 08:45 UTC"
    assert provenance.rows == 3
    assert provenance.params == {"a": 1}
    assert len(provenance.content_sha256) == 64
    # retrieval timestamp is UTC and parseable
    assert pd.Timestamp(provenance.retrieved_at_utc).tz is not None


def test_sidecar_is_written_next_to_the_payload():
    counter: list[int] = []
    pull(counter)
    payload_path, sidecar_path = cache_paths("demo", "2026-08-14")
    assert payload_path.exists()
    assert sidecar_path.exists()
    assert json.loads(sidecar_path.read_text())["dataset"] == "demo"


def test_different_vintages_are_separate_cache_entries():
    counter: list[int] = []
    pull(counter, vintage="2026-08-14")
    pull(counter, vintage="2026-09-01")
    assert len(counter) == 2
    assert read_sidecar("demo", "2026-08-14") is not None
    assert read_sidecar("demo", "2026-09-01") is not None


def test_content_hash_changes_when_upstream_restates():
    """The restatement detector: same vintage label, different bytes."""
    counter: list[int] = []
    pull(counter)
    before = read_sidecar("demo", "2026-08-14")

    def restated_fetch() -> tuple[pd.DataFrame, list[str]]:
        return pd.DataFrame({"value": [1, 2, 99]}), ["https://example.invalid/data.csv"]

    pull(counter, fetch=restated_fetch, refresh=True)
    after = read_sidecar("demo", "2026-08-14")

    assert before is not None
    assert after is not None
    assert before.content_sha256 != after.content_sha256


def test_missing_sidecar_reads_as_none():
    assert read_sidecar("never-pulled", "2026-08-14") is None
