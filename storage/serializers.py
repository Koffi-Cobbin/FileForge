"""DRF serializers for FileForge."""
from __future__ import annotations

from rest_framework import serializers

from .models import File, StorageCredential
from .providers import registry


# ---------------------------------------------------------------------------
# Credential masking
# ---------------------------------------------------------------------------

_SECRET_FIELD_NAMES: frozenset[str] = frozenset({
    "api_key",
    "api_secret",
    "api_secret_key",
    "oauth2_client_secret",
    "oauth2_refresh_token",
    "service_account_json",
    "service_account_file",
})

_SECRET_SUBSTRINGS: tuple[str, ...] = ("secret", "private", "password", "refresh_token")

MASKED_SENTINEL = "***"


def mask_credentials(raw: dict) -> dict:
    """Return a copy of *raw* with sensitive values replaced by ``'***'``.

    A field is masked when its name is in ``_SECRET_FIELD_NAMES`` or when its
    lower-cased name contains any substring in ``_SECRET_SUBSTRINGS``.

    Safe fields (e.g. ``cloud_name``, ``folder_id``, ``oauth2_client_id``,
    ``resource_type``) are returned unchanged.
    """
    masked: dict = {}
    for key, value in (raw or {}).items():
        k_lower = key.lower()
        if key in _SECRET_FIELD_NAMES or any(s in k_lower for s in _SECRET_SUBSTRINGS):
            masked[key] = MASKED_SENTINEL
        else:
            masked[key] = value
    return masked


def merge_credentials(existing: dict, incoming: dict) -> dict:
    """Merge *incoming* into *existing*, skipping sentinel-valued fields.

    When the frontend sends ``"***"`` for a field it did not change, that
    field is left untouched so the stored secret is preserved.
    """
    merged = dict(existing or {})
    for key, value in (incoming or {}).items():
        if value != MASKED_SENTINEL:
            merged[key] = value
    return merged


# ---------------------------------------------------------------------------
# File serializers
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Storage credential serializers
# ---------------------------------------------------------------------------

class StorageCredentialSerializer(serializers.ModelSerializer):
    """API-key-authenticated storage API credential serializer.

    Secrets in the ``credentials`` JSON blob are masked in all responses —
    they are replaced with ``'***'`` so that ``GET /api/credentials/``
    never echoes back raw keys or tokens.
    """

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

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["credentials"] = mask_credentials(instance.credentials or {})
        return data


class AppProviderCredentialSerializer(serializers.Serializer):
    """JWT-authenticated management API serializer for provider credentials.

    Used by ``GET|POST /auth/apps/{id}/providers/`` and
    ``GET|PATCH|DELETE /auth/apps/{id}/providers/{provider}/``.

    On read:  sensitive fields in ``credentials`` are masked with ``'***'``.
    On write: incoming ``'***'`` values are ignored so existing secrets are
              preserved when the user only updates non-secret fields.
    """

    provider = serializers.CharField(max_length=64)
    credentials = serializers.DictField(
        child=serializers.CharField(allow_blank=True),
        required=False,
        default=dict,
    )
    is_default = serializers.BooleanField(default=True, required=False)

    def validate_provider(self, value: str) -> str:
        if value not in registry:
            raise serializers.ValidationError(
                f"Unknown provider '{value}'. "
                f"Available: {registry.names()}"
            )
        return value

    def to_representation(self, instance: StorageCredential) -> dict:
        return {
            "id": instance.id,
            "provider": instance.provider,
            "credentials": mask_credentials(instance.credentials or {}),
            "is_default": instance.is_default,
            "created_at": instance.created_at,
            "updated_at": instance.updated_at,
        }
