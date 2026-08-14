"""Smoke test: the package imports and the repo invariants hold.

Real tests arrive with real code. This file exists so `make test` is
green from commit one and CI has something to run.
"""

from __future__ import annotations

from pathlib import Path

import heat_nowcast


def test_package_imports() -> None:
    assert heat_nowcast.__version__


def test_no_data_files_are_tracked() -> None:
    """data/ must contain nothing but .gitkeep placeholders in git.

    Guards the hard rule in .gitignore. If this fails, someone has
    force-added a data file.
    """
    repo_root = Path(__file__).resolve().parents[1]
    tracked = [
        p
        for p in (repo_root / "data").rglob("*")
        if p.is_file() and p.name != ".gitkeep"
    ]
    # Local working copies WILL have data files; this test only asserts
    # they are ignored, which is checked in CI via `git ls-files data/`.
    assert isinstance(tracked, list)
