"""Custom SimpleJWT token serializer.

Adds ``email`` and ``full_name`` to the token obtain response so
the frontend can display the developer's identity without an extra
round-trip to /auth/me/.
"""
from __future__ import annotations

from rest_framework_simplejwt.serializers import TokenObtainPairSerializer


class EmailTokenObtainPairSerializer(TokenObtainPairSerializer):
    """Extend the default JWT pair serializer to embed user metadata."""

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        # Embed non-sensitive fields directly in the token payload.
        token["email"] = user.email
        token["full_name"] = user.full_name
        return token

    def validate(self, attrs):
        data = super().validate(attrs)
        # Also echo them in the response body for convenience.
        data["email"] = self.user.email
        data["full_name"] = self.user.full_name
        return data
