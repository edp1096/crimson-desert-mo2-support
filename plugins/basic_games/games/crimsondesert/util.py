"""Shared utility functions for Crimson Desert MO2 plugins."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from .constants import META_DIR, PAPGT_FILENAME, PATHC_FILENAME, PAVER_FILENAME

BuildLogger = Callable[[str], None]

_CRASH_LOG = Path(__file__).parent / "crash_trace.log"


def trace(msg: str):
    """Append a timestamped line to crash_trace.log and flush immediately."""
    try:
        mode = "w" if msg.startswith("=== BUILD") else "a"
        with open(_CRASH_LOG, mode, encoding="utf-8") as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
            f.flush()
    except Exception:
        pass


def clean_overwrite_meta(overwrite_path: Path, log: BuildLogger | None = None):
    meta_dir = overwrite_path / META_DIR
    for fname in (PAPGT_FILENAME, PATHC_FILENAME, PAVER_FILENAME):
        fpath = meta_dir / fname
        if fpath.is_file():
            fpath.unlink()
            if log:
                log(f"Removed: overwrite/{META_DIR}/{fname}")
