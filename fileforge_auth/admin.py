from __future__ import annotations

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import ApiKey, App, DeveloperUser


@admin.register(DeveloperUser)
class DeveloperUserAdmin(UserAdmin):
    model = DeveloperUser
    list_display = ("email", "full_name", "is_active", "is_staff", "date_joined")
    list_filter = ("is_active", "is_staff")
    search_fields = ("email", "full_name")
    ordering = ("-date_joined",)

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Personal info", {"fields": ("full_name",)}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Dates", {"fields": ("date_joined", "last_login")}),
    )
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("email", "full_name", "password1", "password2", "is_staff"),
        }),
    )


@admin.register(App)
class AppAdmin(admin.ModelAdmin):
    list_display = ("name", "developer", "owner_slug", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name", "owner_slug", "developer__email")
    readonly_fields = ("owner_slug", "created_at", "updated_at")


@admin.register(ApiKey)
class ApiKeyAdmin(admin.ModelAdmin):
    list_display = ("name", "app", "key_prefix", "is_active", "last_used_at", "expires_at", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name", "app__name", "key_prefix")
    readonly_fields = ("key_hash", "key_prefix", "last_used_at", "created_at", "updated_at")
