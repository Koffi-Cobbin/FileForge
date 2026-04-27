"""Disk-based temporary storage helpers.

Files are streamed straight to disk under ``settings.FILEFORGE_TEMP_DIR``;
they are NEVER buffered fully in memory. The async upload task is
responsible for deleting the temp file after the upload succeeds or fails.
"""
from __future__ import annotations

import logging
import os
import time
import uuid
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)

CHUNK_SIZE = 1024 * 1024  # 1 MiB


def _temp_dir() -> Path:
    p = Path(settings.FILEFORGE_TEMP_DIR)
    p.mkdir(parents=True, exist_ok=True)
    return p


def save_to_temp(uploaded_file, *, original_name: str = "") -> tuple[Path, int]:
    """Stream ``uploaded_file`` to a temp file on disk.

    Returns ``(path, size_bytes)``.
    """
    suffix = ""
    if original_name and "." in original_name:
        suffix = "." + original_name.rsplit(".", 1)[-1]
    name = f"{uuid.uuid4().hex}{suffix}"
    path = _temp_dir() / name
    size = 0
    with path.open("wb") as fh:
        # Django's UploadedFile exposes either .chunks() or .read().
        if hasattr(uploaded_file, "chunks"):
            for chunk in uploaded_file.chunks(CHUNK_SIZE):
                fh.write(chunk)
                size += len(chunk)
        else:
            while True:
                chunk = uploaded_file.read(CHUNK_SIZE)
                if not chunk:
                    break
                fh.write(chunk)
                size += len(chunk)
    return path, size


def delete_temp_file(path: str | os.PathLike[str] | None) -> None:
    if not path:
        return
    try:
        Path(path).unlink(missing_ok=True)
    except OSError as exc:  # pragma: no cover
        logger.warning("Failed to delete temp file %s: %s", path, exc)


def cleanup_orphaned_temp_files(max_age_seconds: int = 24 * 3600) -> int:
    """Delete temp files older than ``max_age_seconds``. Returns count removed."""
    deleted = 0
    cutoff = time.time() - max_age_seconds
    for entry in _temp_dir().iterdir():
        if not entry.is_file():
            continue
        try:
            if entry.stat().st_mtime < cutoff:
                entry.unlink(missing_ok=True)
                deleted += 1
        except OSError:  # pragma: no cover
            continue
    return deleted
