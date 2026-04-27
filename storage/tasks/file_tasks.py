"""Async tasks executed by django-q2."""
from __future__ import annotations

import logging
from pathlib import Path

from django.utils import timezone

from ..models import File, FileStatus
from ..services import StorageManager
from ..utils import delete_temp_file

logger = logging.getLogger(__name__)


def process_file_upload(file_id: int) -> dict:
    """Upload the temp file backing ``File(id=file_id)`` to its provider.

    The file's status transitions ``pending → uploading → completed|failed``.
    The temp file is deleted regardless of outcome.
    """
    try:
        file_obj = File.objects.get(pk=file_id)
    except File.DoesNotExist:
        logger.warning("process_file_upload: File %s no longer exists", file_id)
        return {"ok": False, "reason": "file_missing"}

    temp_path = file_obj.temp_path
    if not temp_path or not Path(temp_path).exists():
        file_obj.status = FileStatus.FAILED
        file_obj.error_message = "Temp file missing before upload."
        file_obj.save(update_fields=["status", "error_message", "updated_at"])
        return {"ok": False, "reason": "temp_missing"}

    file_obj.status = FileStatus.UPLOADING
    file_obj.save(update_fields=["status", "updated_at"])

    try:
        with open(temp_path, "rb") as fh:
            result = StorageManager.upload(
                fh,
                provider=file_obj.provider,
                path=file_obj.name,
                owner=file_obj.owner,
                content_type=file_obj.content_type or None,
                size=file_obj.size or None,
            )
        file_obj.provider_file_id = result.provider_file_id
        file_obj.url = result.url or ""
        merged_meta = dict(file_obj.metadata or {})
        merged_meta.update(result.metadata or {})
        file_obj.metadata = merged_meta
        file_obj.status = FileStatus.COMPLETED
        file_obj.error_message = ""
        file_obj.save(
            update_fields=[
                "provider_file_id",
                "url",
                "metadata",
                "status",
                "error_message",
                "updated_at",
            ]
        )
        return {"ok": True, "file_id": file_id}
    except Exception as exc:  # noqa: BLE001
        logger.exception("Upload failed for file %s", file_id)
        file_obj.status = FileStatus.FAILED
        file_obj.error_message = str(exc)[:2000]
        file_obj.save(update_fields=["status", "error_message", "updated_at"])
        return {"ok": False, "file_id": file_id, "error": str(exc)}
    finally:
        delete_temp_file(temp_path)
        if file_obj.temp_path:
            File.objects.filter(pk=file_id).update(
                temp_path="", updated_at=timezone.now()
            )


def cleanup_temp_files() -> dict:
    """Periodic cleanup target — removes stale temp files."""
    from ..utils import cleanup_orphaned_temp_files

    removed = cleanup_orphaned_temp_files()
    return {"ok": True, "removed": removed}
