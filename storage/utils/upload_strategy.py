"""Decide whether to use the async backend upload or the direct upload flow."""
from __future__ import annotations

from django.conf import settings


def get_max_sync_size(provider: str) -> int:
    """Resolve the per-provider sync size threshold (bytes)."""
    overrides = getattr(settings, "FILEFORGE_PROVIDER_MAX_SYNC_SIZE", {}) or {}
    if provider in overrides:
        return int(overrides[provider])
    return int(getattr(settings, "FILEFORGE_DEFAULT_MAX_SYNC_SIZE", 5 * 1024 * 1024))


def should_use_direct_upload(provider: str, size: int) -> bool:
    """Return ``True`` when ``size`` exceeds the provider's sync threshold."""
    return int(size) > get_max_sync_size(provider)
