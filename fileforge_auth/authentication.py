"""DRF authentication backend for FileForge API keys.

Incoming requests are authenticated with:

    Authorization: Bearer ffk_<token>

On success the request gets:
    request.user  → the DeveloperUser who owns the App
    request.auth  → the ApiKey instance (so views can read request.auth.app)

The backend also updates ``ApiKey.last_used_at`` on every successful auth.
"""
from __future__ import annotations

import hashlib

from django.utils import timezone
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

from .models import ApiKey, _KEY_PREFIX


def _hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


class ApiKeyAuthentication(BaseAuthentication):
    """Authenticate via ``Authorization: Bearer ffk_<token>``."""

    keyword = "Bearer"

    def authenticate(self, request):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith(f"{self.keyword} "):
            return None  # Not our scheme — let other backends try.

        raw_key = auth_header[len(self.keyword) + 1:].strip()

        if not raw_key.startswith(_KEY_PREFIX):
            return None  # Fast-path: definitely not a FileForge key.

        key_hash = _hash_key(raw_key)

        try:
            api_key = (
                ApiKey.objects
                .select_related("app__developer")
                .get(key_hash=key_hash)
            )
        except ApiKey.DoesNotExist:
            raise AuthenticationFailed("Invalid API key.")

        if not api_key.is_valid():
            raise AuthenticationFailed(
                "API key is inactive or expired."
            )

        if not api_key.app.is_active:
            raise AuthenticationFailed("This app has been deactivated.")

        if not api_key.app.developer.is_active:
            raise AuthenticationFailed("Developer account is deactivated.")

        # Non-blocking last_used update — don't fail the request if this errors.
        try:
            api_key.touch()
        except Exception:  # noqa: BLE001
            pass

        return api_key.app.developer, api_key

    def authenticate_header(self, request):
        return self.keyword
