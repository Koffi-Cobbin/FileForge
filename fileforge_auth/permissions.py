"""Custom DRF permission classes for FileForge.

Two distinct permission surfaces:

  IsAuthenticatedApp
      Used by the File / Credential / storage API.
      Requires the request to have been authenticated by ApiKeyAuthentication
      (i.e. request.auth is an ApiKey instance).

  IsAuthenticatedDeveloper
      Used by the management/dashboard API.
      Requires the request to have been authenticated by JWTAuthentication
      (i.e. request.user is a DeveloperUser, request.auth is a JWT token).

  IsAppOwner
      Object-level permission.  Confirms the ApiKey's App owns the object
      being accessed (compares obj.owner to request.auth.app.owner_slug).
"""
from __future__ import annotations

from rest_framework.permissions import BasePermission

from .models import ApiKey


class IsAuthenticatedApp(BasePermission):
    """Allow access only to valid API-key-authenticated requests."""

    message = "A valid API key is required."

    def has_permission(self, request, view):
        return (
            request.user is not None
            and request.user.is_authenticated
            and isinstance(request.auth, ApiKey)
        )


class IsAuthenticatedDeveloper(BasePermission):
    """Allow access only to JWT-authenticated developer sessions."""

    message = "Authentication credentials were not provided or are invalid."

    def has_permission(self, request, view):
        return (
            request.user is not None
            and request.user.is_authenticated
            and not isinstance(request.auth, ApiKey)  # JWT, not an API key
        )


class IsAppOwner(BasePermission):
    """Object-level check: the API key's app must own the object."""

    message = "You do not have permission to access this resource."

    def has_object_permission(self, request, view, obj):
        if not isinstance(request.auth, ApiKey):
            return False
        owner_slug = request.auth.app.owner_slug
        # obj may be a File, a StorageCredential, or any model with .owner
        return getattr(obj, "owner", None) == owner_slug
