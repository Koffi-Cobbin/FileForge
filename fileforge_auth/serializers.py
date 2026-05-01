"""DRF serializers for the fileforge_auth app."""
from __future__ import annotations

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from storage.models import StorageCredential

from .models import ApiKey, App, DeveloperUser


# ---------------------------------------------------------------------------
# DeveloperUser
# ---------------------------------------------------------------------------

class DeveloperRegistrationSerializer(serializers.ModelSerializer):
    """Used for POST /auth/register/."""

    password = serializers.CharField(write_only=True, min_length=8)
    password_confirm = serializers.CharField(write_only=True)

    class Meta:
        model = DeveloperUser
        fields = ("email", "full_name", "password", "password_confirm")

    def validate(self, data):
        if data["password"] != data.pop("password_confirm"):
            raise serializers.ValidationError(
                {"password_confirm": "Passwords do not match."}
            )
        try:
            validate_password(data["password"])
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"password": list(exc.messages)})
        return data

    def create(self, validated_data):
        return DeveloperUser.objects.create_user(**validated_data)


class DeveloperProfileSerializer(serializers.ModelSerializer):
    """Read/update the authenticated developer's own profile."""

    class Meta:
        model = DeveloperUser
        fields = ("id", "email", "full_name", "date_joined")
        read_only_fields = ("id", "email", "date_joined")


class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True, min_length=8)

    def validate_new_password(self, value):
        try:
            validate_password(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages))
        return value


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

class AppSerializer(serializers.ModelSerializer):
    """Full read representation of an App (no API keys embedded)."""

    api_key_count = serializers.SerializerMethodField()
    configured_providers = serializers.SerializerMethodField()

    class Meta:
        model = App
        fields = (
            "id",
            "name",
            "description",
            "owner_slug",
            "is_active",
            "api_key_count",
            "configured_providers",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "owner_slug",
            "api_key_count",
            "configured_providers",
            "created_at",
            "updated_at",
        )

    def get_api_key_count(self, obj: App) -> int:
        return obj.api_keys.filter(is_active=True).count()

    def get_configured_providers(self, obj: App) -> list[str]:
        """Return a sorted list of provider names that have credentials stored
        for this app.  Use ``GET /auth/apps/{id}/providers/`` for the full
        credential records (with secrets masked)."""
        return list(
            StorageCredential.objects.filter(owner=obj.owner_slug)
            .order_by("provider")
            .values_list("provider", flat=True)
        )


class AppCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = App
        fields = ("name", "description")

    def validate_name(self, value: str) -> str:
        developer = self.context["request"].user
        if App.objects.filter(developer=developer, name=value).exists():
            raise serializers.ValidationError(
                "You already have an app with this name."
            )
        return value

    def create(self, validated_data):
        return App.objects.create(
            developer=self.context["request"].user,
            **validated_data,
        )


class AppUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = App
        fields = ("name", "description", "is_active")


# ---------------------------------------------------------------------------
# ApiKey
# ---------------------------------------------------------------------------

class ApiKeySerializer(serializers.ModelSerializer):
    """Safe read representation — never exposes the raw key."""

    app_name = serializers.CharField(source="app.name", read_only=True)

    class Meta:
        model = ApiKey
        fields = (
            "id",
            "app",
            "app_name",
            "name",
            "key_prefix",
            "is_active",
            "last_used_at",
            "expires_at",
            "created_at",
        )
        read_only_fields = (
            "id",
            "app",
            "app_name",
            "key_prefix",
            "last_used_at",
            "created_at",
        )


class ApiKeyCreateSerializer(serializers.Serializer):
    """Input for creating a new key.  Returns the raw key once."""

    name = serializers.CharField(max_length=255)
    expires_at = serializers.DateTimeField(required=False, allow_null=True)


class ApiKeyCreatedSerializer(serializers.ModelSerializer):
    """Response for a newly created key — includes the raw key."""

    raw_key = serializers.CharField(read_only=True)

    class Meta:
        model = ApiKey
        fields = (
            "id",
            "name",
            "key_prefix",
            "raw_key",
            "expires_at",
            "created_at",
        )


class ApiKeyRevokeSerializer(serializers.Serializer):
    """Body for PATCH /auth/apps/{app_id}/keys/{key_id}/revoke/."""
    # No input needed; the action is implicit.
    pass
