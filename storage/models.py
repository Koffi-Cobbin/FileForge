"""Database models for FileForge."""
from __future__ import annotations

from django.db import models


class FileStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    UPLOADING = "uploading", "Uploading"
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"


class File(models.Model):
    """A file tracked by FileForge.

    A file maps to exactly ONE storage provider; FileForge does not duplicate
    or replicate the underlying object across providers.
    """

    name = models.CharField(max_length=512)
    size = models.BigIntegerField(default=0)
    content_type = models.CharField(max_length=255, blank=True, default="")
    provider = models.CharField(max_length=64)
    provider_file_id = models.CharField(
        max_length=512, null=True, blank=True, db_index=True
    )
    url = models.URLField(max_length=2048, null=True, blank=True)
    status = models.CharField(
        max_length=16,
        choices=FileStatus.choices,
        default=FileStatus.PENDING,
    )
    error_message = models.TextField(blank=True, default="")
    owner = models.CharField(max_length=255, db_index=True, default="default")
    metadata = models.JSONField(default=dict, blank=True)
    temp_path = models.CharField(max_length=1024, blank=True, default="")
    upload_strategy = models.CharField(max_length=16, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=("owner", "provider")),
            models.Index(fields=("status",)),
        ]

    def __str__(self) -> str:  # pragma: no cover - debug helper
        return f"File(id={self.pk}, name={self.name!r}, provider={self.provider})"


class StorageCredential(models.Model):
    """Per-owner credentials for a single provider.

    `credentials` is a JSON blob whose shape is provider-specific. The
    StorageManager merges these with environment-level defaults before
    instantiating the provider.
    """

    owner = models.CharField(max_length=255, db_index=True)
    provider = models.CharField(max_length=64)
    credentials = models.JSONField(default=dict)
    is_default = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("owner", "provider")
        constraints = [
            models.UniqueConstraint(
                fields=("owner", "provider"),
                name="uniq_owner_provider_credential",
            ),
        ]

    def __str__(self) -> str:  # pragma: no cover - debug helper
        return f"StorageCredential(owner={self.owner}, provider={self.provider})"
