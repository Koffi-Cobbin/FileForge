"""DRF serializers for FileForge."""
from __future__ import annotations

from rest_framework import serializers

from .models import File, StorageCredential
from .providers import registry


class FileSerializer(serializers.ModelSerializer):
    class Meta:
        model = File
        fields = (
            "id",
            "name",
            "size",
            "content_type",
            "provider",
            "provider_file_id",
            "url",
            "status",
            "error_message",
            "owner",
            "metadata",
            "upload_strategy",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "size",
            "provider_file_id",
            "url",
            "status",
            "error_message",
            "owner",
            "metadata",
            "upload_strategy",
            "created_at",
            "updated_at",
        )


class FilePatchSerializer(serializers.ModelSerializer):
    """Limited PATCH surface — clients can only rename a file."""

    class Meta:
        model = File
        fields = ("name",)


class FileUploadSerializer(serializers.Serializer):
    """Body for ``POST /files/`` (multipart).

    ``mode`` controls the upload execution path:

    * ``"async"`` (default) — the file is queued for background upload and
      the response is returned immediately with ``status: "pending"``.
      The caller should poll ``GET /files/{id}/`` until the status is
      ``"completed"`` or ``"failed"``.

    * ``"sync"`` — the upload to the provider is performed within the
      request/response cycle.  The response is returned only after the
      provider call completes (or fails), so the returned ``File`` object
      will already carry ``status: "completed"`` or ``"failed"`` — no
      polling required.  Only valid for files at or below the provider's
      max sync size threshold.
    """

    file = serializers.FileField()
    provider = serializers.CharField()
    name = serializers.CharField(required=False, allow_blank=True)
    mode = serializers.ChoiceField(
        choices=["async", "sync"],
        default="async",
        required=False,
    )

    def validate_provider(self, value: str) -> str:
        if value not in registry:
            raise serializers.ValidationError(
                f"Unknown provider {value!r}. "
                f"Available: {registry.names()}"
            )
        return value


class DirectUploadInitSerializer(serializers.Serializer):
    """Body for ``POST /files/direct-upload/``."""

    name = serializers.CharField()
    provider = serializers.CharField()
    size = serializers.IntegerField(min_value=0)
    content_type = serializers.CharField(required=False, allow_blank=True)

    def validate_provider(self, value: str) -> str:
        if value not in registry:
            raise serializers.ValidationError(
                f"Unknown provider {value!r}. "
                f"Available: {registry.names()}"
            )
        return value


class DirectUploadCompleteSerializer(serializers.Serializer):
    """Body for ``POST /files/direct-upload/complete/``."""

    file_id = serializers.IntegerField()
    provider_file_id = serializers.CharField(required=False, allow_blank=True)
    url = serializers.URLField(required=False, allow_blank=True)
    provider_response = serializers.JSONField(required=False)


class StorageCredentialSerializer(serializers.ModelSerializer):
    class Meta:
        model = StorageCredential
        fields = (
            "id",
            "owner",
            "provider",
            "credentials",
            "is_default",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "owner", "created_at", "updated_at")

    def validate_provider(self, value: str) -> str:
        if value not in registry:
            raise serializers.ValidationError(
                f"Unknown provider {value!r}. "
                f"Available: {registry.names()}"
            )
        return value