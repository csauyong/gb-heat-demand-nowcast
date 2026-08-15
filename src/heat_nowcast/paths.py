"""Filesystem locations for the project.

`data/` is gitignored (see .gitignore). Nothing in this module creates
anything outside the project tree.
"""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]
DATA_DIR: Path = PROJECT_ROOT / "data"
RAW_DIR: Path = DATA_DIR / "raw"
INTERIM_DIR: Path = DATA_DIR / "interim"
PROCESSED_DIR: Path = DATA_DIR / "processed"
REPORTS_DIR: Path = PROJECT_ROOT / "reports"
FIGURES_DIR: Path = REPORTS_DIR / "figures"
TABLES_DIR: Path = REPORTS_DIR / "tables"


def ensure_dirs() -> None:
    """Create the data and report output directories if they are absent."""
    for directory in (
        RAW_DIR,
        INTERIM_DIR,
        PROCESSED_DIR,
        FIGURES_DIR,
        TABLES_DIR,
    ):
        directory.mkdir(parents=True, exist_ok=True)
