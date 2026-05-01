"""Strict base interface for cloud storage providers.

A provider is a thin, stateless adapter around a specific cloud storage
service. Adding a new provider must only require:

    1. Implementing a subclass of :class:`BaseStorageProvider`.
    2. Registering it in :mod:`storage.providers.registry`.

No other layer of the system (views, serializers, services, tasks) may
import from a concrete provider module.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, BinaryIO, Generator, Mapping


class ProviderError(Exception):
    """Raised by providers when an underlying operation fails."""


class ProviderConfigurationError(ProviderError):
    """Raised when a provider is missing required credentials or settings."""


class ProviderUnsupportedOperation(ProviderError):
    """Raised when a provider does not implement an optional operation."""


@dataclass
class UploadResult:
    """Normalized result returned by ``BaseStorageProvider.upload``."""

    provider_file_id: str
    url: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class DirectUploadTicket:
    """Normalized response for ``BaseStorageProvider.generate_upload_url``.

    The client uses ``upload_url`` (and optional ``fields`` / ``headers`` /
    ``method``) to upload the file directly to the provider, bypassing
    FileForge entirely. ``provider_ref`` is opaque data the provider needs to
    finalize the upload later.
    """

    upload_url: str
    method: str = "PUT"
    fields: dict[str, Any] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    provider_ref: dict[str, Any] = field(default_factory=dict)
    expires_in: int | None = None


class BaseStorageProvider:
    """Strict interface every storage provider MUST implement."""

    #: Short, stable identifier (e.g. ``"google_drive"``).
    name: str = ""

    def __init__(self, credentials: Mapping[str, Any] | None = None) -> None:
        self.credentials: dict[str, Any] = dict(credentials or {})

    # ------------------------------------------------------------------
    # Core CRUD
    # ------------------------------------------------------------------

    def upload(
        self,
        file: BinaryIO,
        path: str,
        *,
        content_type: str | None = None,
        size: int | None = None,
        **kwargs: Any,
    ) -> UploadResult:
        """Upload ``file`` and return identifiers + metadata."""
        raise NotImplementedError

    def download(self, file_id: str, **kwargs: Any) -> bytes:
        """Return the raw bytes of ``file_id``."""
        raise NotImplementedError

    def delete(self, file_id: str, **kwargs: Any) -> None:
        """Delete ``file_id`` from the underlying provider."""
        raise NotImplementedError

    def update(self, file_id: str, **kwargs: Any) -> dict[str, Any]:
        """Update metadata (e.g. rename) for ``file_id``."""
        raise NotImplementedError

    def get_url(self, file_id: str, **kwargs: Any) -> str:
        """Return a viewable URL for ``file_id``."""
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Hybrid / direct upload support
    # ------------------------------------------------------------------

    def generate_upload_url(
        self,
        path: str,
        *,
        content_type: str | None = None,
        size: int | None = None,
        **kwargs: Any,
    ) -> DirectUploadTicket:
        """Return a signed URL the client can upload to directly."""
        raise ProviderUnsupportedOperation(
            f"Provider {self.name!r} does not support direct uploads."
        )

    def finalize_direct_upload(
        self, data: Mapping[str, Any]
    ) -> UploadResult:
        """Validate / persist a direct upload after the client finishes."""
        raise ProviderUnsupportedOperation(
            f"Provider {self.name!r} does not support direct uploads."
        )

    # ------------------------------------------------------------------
    # Streaming support (optional)
    # ------------------------------------------------------------------

    def stream(
        self,
        file_id: str,
        *,
        start: int = 0,
        end: int | None = None,
        **kwargs: Any,
    ) -> Generator[bytes, None, None]:
        """Yield byte chunks for ``file_id``, optionally honoring Range offsets.

        Providers that support streaming should set ``supports_streaming = True``
        and override this method.  The default implementation falls back to
        ``download()`` and yields the relevant slice in one chunk.
        """
        data = self.download(file_id, **kwargs)
        yield data[start: None if end is None else end + 1]

    # ------------------------------------------------------------------
    # Capability flags
    # ------------------------------------------------------------------

    #: Whether this provider supports the direct-upload flow.
    supports_direct_upload: bool = False

    #: Whether this provider natively streams in chunks (Range-request aware).
    supports_streaming: bool = False
