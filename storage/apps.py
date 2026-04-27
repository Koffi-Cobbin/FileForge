"""App configuration for the storage app."""
from __future__ import annotations

from django.apps import AppConfig


class StorageConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "storage"
    verbose_name = "FileForge Storage"

    def ready(self) -> None:
        # Eager-import the registry so providers are registered at startup.
        from .providers import registry  # noqa: F401
