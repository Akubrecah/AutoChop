"""
AutoChop AI Studio - File Utilities
Handles session-scoped temporary directory lifecycles, path sanitization,
safe file naming, and zip archiving.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import tempfile
import uuid
import zipfile
from pathlib import Path
from typing import Generator
from contextlib import contextmanager

from autochop.config import TEMP_DIR_ROOT

logger = logging.getLogger("autochop.file_utils")


def sanitize_filename(filename: str, fallback: str = "clip") -> str:
    """
    Sanitizes user-provided filenames to prevent path traversal or shell character issues.
    Removes invalid characters and returns a clean base name.
    """
    if not filename:
        return fallback
    # Strip directory components if any
    base = Path(filename).name
    # Replace non-alphanumeric (except . - _) with underscore
    clean = re.sub(r"[^\w\.-]", "_", base).strip(" ._")
    return clean if clean else fallback


def format_file_size(size_bytes: int) -> str:
    """Formats raw byte count into human-readable size string (KB, MB, GB)."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def get_session_dir(session_id: str | None = None) -> Path:
    """
    Generates a unique session directory under the configured temp root.
    Ensures the directory exists and returns its resolved Path.
    """
    TEMP_DIR_ROOT.mkdir(parents=True, exist_ok=True)
    sid = session_id or uuid.uuid4().hex[:12]
    session_dir = TEMP_DIR_ROOT / f"session_{sid}"
    session_dir.mkdir(parents=True, exist_ok=True)
    return session_dir.resolve()


@contextmanager
def temporary_session_scope(session_id: str | None = None, keep_on_error: bool = False) -> Generator[Path, None, None]:
    """
    Context manager that yields a temporary directory and safely cleans it up
    unless keep_on_error is True and an exception occurs.
    """
    s_dir = get_session_dir(session_id)
    try:
        yield s_dir
    finally:
        if not keep_on_error and s_dir.exists():
            try:
                shutil.rmtree(s_dir, ignore_errors=True)
                logger.debug(f"Cleaned up session directory: {s_dir}")
            except Exception as exc:
                logger.warning(f"Failed to remove session directory {s_dir}: {exc}")


def create_export_zip(
    zip_output_path: str | Path,
    take_paths: list[str | Path],
    srt_paths: list[str | Path],
    manifest_path: str | Path | None = None,
    master_path: str | Path | None = None,
) -> Path:
    """
    Packages individual takes, SRTs, and manifest into a single downloadable .zip archive.
    """
    out_path = Path(zip_output_path).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        # Takes
        for tp in take_paths:
            p = Path(tp)
            if p.exists():
                zf.write(p, arcname=f"takes/{p.name}")

        # SRTs
        for sp in srt_paths:
            p = Path(sp)
            if p.exists():
                zf.write(p, arcname=f"subtitles/{p.name}")

        # Manifest
        if manifest_path:
            mp = Path(manifest_path)
            if mp.exists():
                zf.write(mp, arcname="manifest.md")

        # Master cut (if provided)
        if master_path:
            mcp = Path(master_path)
            if mcp.exists():
                zf.write(mcp, arcname=f"master/{mcp.name}")

    logger.info(f"Created export archive at {out_path} ({format_file_size(out_path.stat().st_size)})")
    return out_path
