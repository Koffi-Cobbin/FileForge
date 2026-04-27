"""Admin registrations for FileForge models."""
from __future__ import annotations

from django.contrib import admin

from .models import File, StorageCredential


@admin.register(File)
class FileAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "provider",
        "owner",
        "size",
        "status",
        "created_at",
    )
    list_filter = ("provider", "status", "created_at")
    search_fields = ("name", "provider_file_id", "owner")


@admin.register(StorageCredential)
class StorageCredentialAdmin(admin.ModelAdmin):
    list_display = ("id", "owner", "provider", "is_default", "created_at")
    list_filter = ("provider", "is_default")
    search_fields = ("owner",)
