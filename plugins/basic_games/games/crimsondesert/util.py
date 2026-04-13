"""Shared utility functions for Crimson Desert MO2 plugins."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from .constants import META_DIR, PAPGT_FILENAME, PATHC_FILENAME, PAVER_FILENAME

BuildLogger = Callable[[str], None]


def clean_overwrite_meta(overwrite_path: Path, log: BuildLogger | None = None):
    meta_dir = overwrite_path / META_DIR
    for fname in (PAPGT_FILENAME, PATHC_FILENAME, PAVER_FILENAME):
        fpath = meta_dir / fname
        if fpath.is_file():
            fpath.unlink()
            if log:
                log(f"Removed: overwrite/{META_DIR}/{fname}")
