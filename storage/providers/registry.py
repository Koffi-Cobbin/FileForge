"""Provider registry.

A small, plugin-ready registry mapping a provider name (e.g.
``"google_drive"``) to a :class:`BaseStorageProvider` subclass. Providers
register themselves at import time. Future versions can extend this with
``importlib.metadata`` entry-point discovery without changing call sites.
"""
from __future__ import annotations

from typing import Iterable

from .base import BaseStorageProvider


class ProviderRegistry:
    """In-memory registry of provider classes."""

    def __init__(self) -> None:
        self._providers: dict[str, type[BaseStorageProvider]] = {}

    def register(
        self,
        name: str,
        provider_cls: type[BaseStorageProvider],
        *,
        replace: bool = False,
    ) -> None:
        if not name:
            raise ValueError("Provider name is required")
        if not issubclass(provider_cls, BaseStorageProvider):
            raise TypeError(
                "Provider must subclass BaseStorageProvider, "
                f"got {provider_cls!r}"
            )
        if name in self._providers and not replace:
            raise ValueError(f"Provider {name!r} is already registered")
        provider_cls.name = name
        self._providers[name] = provider_cls

    def unregister(self, name: str) -> None:
        self._providers.pop(name, None)

    def get(self, name: str) -> type[BaseStorageProvider]:
        try:
            return self._providers[name]
        except KeyError as exc:
            raise KeyError(
                f"Unknown provider {name!r}. Registered: "
                f"{sorted(self._providers)}"
            ) from exc

    def names(self) -> list[str]:
        return sorted(self._providers)

    def items(self) -> Iterable[tuple[str, type[BaseStorageProvider]]]:
        return self._providers.items()

    def __contains__(self, name: str) -> bool:
        return name in self._providers


registry = ProviderRegistry()


def register_default_providers() -> None:
    """Register the providers shipped with FileForge.

    Imports are local so that the registry module itself stays free of
    provider-specific dependencies.
    """
    # Import here to avoid circular imports and to keep optional SDKs lazy.
    from .google_drive import GoogleDriveProvider
    from .cloudinary_provider import CloudinaryProvider

    if "google_drive" not in registry:
        registry.register("google_drive", GoogleDriveProvider)
    if "cloudinary" not in registry:
        registry.register("cloudinary", CloudinaryProvider)


register_default_providers()
