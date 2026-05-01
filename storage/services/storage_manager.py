"""Single entry point for all storage operations.

Views and tasks must talk to this module instead of importing providers
directly. The manager is responsible for:

  * Resolving the provider class from the registry.
  * Merging environment-level credentials with per-owner credentials stored
    in :class:`StorageCredential`.
  * Instantiating the provider and routing the call.
"""
from __future__ import annotations

from typing import Any, BinaryIO, Generator, Mapping

from django.conf import settings

from ..models import StorageCredential
from ..providers import (
    BaseStorageProvider,
    DirectUploadTicket,
    ProviderConfigurationError,
    UploadResult,
    registry,
)


def _resolve_credentials(
    provider: str, owner: str | None
) -> dict[str, Any]:
    """Merge env defaults with the owner's stored credentials.

    Owner credentials win over env defaults. Empty-string / ``None`` values
    in either source are dropped so missing keys fall back as expected.
    """
    env_defaults = (
        getattr(settings, "FILEFORGE_PROVIDER_ENV_CREDENTIALS", {}) or {}
    ).get(provider, {}) or {}
    merged: dict[str, Any] = {
        k: v for k, v in env_defaults.items() if v not in (None, "")
    }
    if owner:
        try:
            cred = StorageCredential.objects.get(owner=owner, provider=provider)
        except StorageCredential.DoesNotExist:
            cred = None
        if cred:
            for k, v in (cred.credentials or {}).items():
                if v not in (None, ""):
                    merged[k] = v
    return merged


def _build_provider(
    provider: str, owner: str | None
) -> BaseStorageProvider:
    if provider not in registry:
        raise ProviderConfigurationError(
            f"Unknown provider {provider!r}. Available: "
            f"{registry.names()}"
        )
    creds = _resolve_credentials(provider, owner)
    provider_cls = registry.get(provider)
    return provider_cls(credentials=creds)


class StorageManager:
    """Stateless orchestrator that routes calls to the right provider."""

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    @staticmethod
    def list_providers() -> list[dict[str, Any]]:
        return [
            {
                "name": name,
                "supports_direct_upload": cls.supports_direct_upload,
                "supports_streaming": cls.supports_streaming,
            }
            for name, cls in sorted(registry.items())
        ]

    @staticmethod
    def has_provider(name: str) -> bool:
        return name in registry

    # ------------------------------------------------------------------
    # Operations
    # ------------------------------------------------------------------

    @staticmethod
    def upload(
        file: BinaryIO,
        *,
        provider: str,
        path: str,
        owner: str | None = None,
        content_type: str | None = None,
        size: int | None = None,
        **kwargs: Any,
    ) -> UploadResult:
        return _build_provider(provider, owner).upload(
            file,
            path,
            content_type=content_type,
            size=size,
            **kwargs,
        )

    @staticmethod
    def download(
        provider: str,
        file_id: str,
        *,
        owner: str | None = None,
        **kwargs: Any,
    ) -> bytes:
        return _build_provider(provider, owner).download(file_id, **kwargs)

    @staticmethod
    def delete(
        provider: str,
        file_id: str,
        *,
        owner: str | None = None,
        **kwargs: Any,
    ) -> None:
        _build_provider(provider, owner).delete(file_id, **kwargs)

    @staticmethod
    def update(
        provider: str,
        file_id: str,
        *,
        owner: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return _build_provider(provider, owner).update(file_id, **kwargs)

    @staticmethod
    def get_url(
        provider: str,
        file_id: str,
        *,
        owner: str | None = None,
        **kwargs: Any,
    ) -> str:
        return _build_provider(provider, owner).get_url(file_id, **kwargs)

    @staticmethod
    def generate_upload_url(
        provider: str,
        path: str,
        *,
        owner: str | None = None,
        content_type: str | None = None,
        size: int | None = None,
        **kwargs: Any,
    ) -> DirectUploadTicket:
        return _build_provider(provider, owner).generate_upload_url(
            path,
            content_type=content_type,
            size=size,
            **kwargs,
        )

    @staticmethod
    def finalize_direct_upload(
        provider: str,
        data: Mapping[str, Any],
        *,
        owner: str | None = None,
    ) -> UploadResult:
        return _build_provider(provider, owner).finalize_direct_upload(data)

    @staticmethod
    def stream(
        provider: str,
        file_id: str,
        *,
        owner: str | None = None,
        start: int = 0,
        end: int | None = None,
        **kwargs: Any,
    ) -> Generator[bytes, None, None]:
        """Yield byte chunks for *file_id*, optionally honouring a byte Range.

        Delegates to the provider's ``stream()`` method.  All providers have a
        default implementation that falls back to ``download()`` and slices the
        result; providers like Google Drive override it with a true chunked
        streaming implementation (adapted from MuseWave-Backend).
        """
        return _build_provider(provider, owner).stream(
            file_id, start=start, end=end, **kwargs
        )
