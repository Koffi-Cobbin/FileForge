"""Views for the fileforge_auth management API.

All endpoints here are authenticated by JWT (IsAuthenticatedDeveloper).
They form the "control plane" — managing Apps and ApiKeys.

The storage/file API (the "data plane") is NOT in this file; those views
remain in storage/views.py and will be updated to use IsAuthenticatedApp.

URL layout (mounted at /auth/):
  POST   /auth/register/
  POST   /auth/token/                          ← provided by SimpleJWT
  POST   /auth/token/refresh/                  ← provided by SimpleJWT
  GET    /auth/me/
  PATCH  /auth/me/
  POST   /auth/me/change-password/
  GET    POST /auth/apps/
  GET PATCH DELETE /auth/apps/{id}/
  GET POST /auth/apps/{id}/keys/
  POST   /auth/apps/{id}/keys/{key_id}/revoke/
  GET POST /auth/apps/{id}/providers/          ← provider credential management
  GET PATCH DELETE /auth/apps/{id}/providers/{provider}/
"""
from __future__ import annotations

from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTAuthentication

from .models import ApiKey, App
from .permissions import IsAuthenticatedDeveloper
from .serializers import (
    ApiKeyCreatedSerializer,
    ApiKeyCreateSerializer,
    ApiKeySerializer,
    AppCreateSerializer,
    AppSerializer,
    AppUpdateSerializer,
    ChangePasswordSerializer,
    DeveloperProfileSerializer,
    DeveloperRegistrationSerializer,
)


# ---------------------------------------------------------------------------
# Registration (public)
# ---------------------------------------------------------------------------

class RegisterView(APIView):
    """POST /auth/register/ — create a developer account."""

    authentication_classes = []
    permission_classes = []

    def post(self, request):
        s = DeveloperRegistrationSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        user = s.save()
        return Response(
            DeveloperProfileSerializer(user).data,
            status=status.HTTP_201_CREATED,
        )


# ---------------------------------------------------------------------------
# Developer profile
# ---------------------------------------------------------------------------

class MeView(APIView):
    """GET / PATCH /auth/me/ — read or update the authenticated developer."""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticatedDeveloper]

    def get(self, request):
        return Response(DeveloperProfileSerializer(request.user).data)

    def patch(self, request):
        s = DeveloperProfileSerializer(
            request.user, data=request.data, partial=True
        )
        s.is_valid(raise_exception=True)
        s.save()
        return Response(s.data)


class ChangePasswordView(APIView):
    """POST /auth/me/change-password/."""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticatedDeveloper]

    def post(self, request):
        s = ChangePasswordSerializer(data=request.data)
        s.is_valid(raise_exception=True)

        if not request.user.check_password(s.validated_data["current_password"]):
            return Response(
                {"current_password": ["Incorrect password."]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        request.user.set_password(s.validated_data["new_password"])
        request.user.save(update_fields=["password"])
        return Response({"detail": "Password updated."})


# ---------------------------------------------------------------------------
# Apps
# ---------------------------------------------------------------------------

class AppListCreateView(APIView):
    """GET /auth/apps/ and POST /auth/apps/."""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticatedDeveloper]

    def get(self, request):
        apps = App.objects.filter(developer=request.user)
        return Response(AppSerializer(apps, many=True).data)

    def post(self, request):
        s = AppCreateSerializer(data=request.data, context={"request": request})
        s.is_valid(raise_exception=True)
        app = s.save()
        return Response(AppSerializer(app).data, status=status.HTTP_201_CREATED)


class AppDetailView(APIView):
    """GET / PATCH / DELETE /auth/apps/{id}/."""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticatedDeveloper]

    def _get_app(self, request, pk):
        return get_object_or_404(App, pk=pk, developer=request.user)

    def get(self, request, pk):
        return Response(AppSerializer(self._get_app(request, pk)).data)

    def patch(self, request, pk):
        app = self._get_app(request, pk)
        s = AppUpdateSerializer(app, data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        s.save()
        return Response(AppSerializer(app).data)

    def delete(self, request, pk):
        app = self._get_app(request, pk)
        app.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# API Keys
# ---------------------------------------------------------------------------

class ApiKeyListCreateView(APIView):
    """GET /auth/apps/{app_id}/keys/ and POST /auth/apps/{app_id}/keys/."""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticatedDeveloper]

    def _get_app(self, request, app_id):
        return get_object_or_404(App, pk=app_id, developer=request.user)

    def get(self, request, app_id):
        app = self._get_app(request, app_id)
        keys = app.api_keys.all()
        return Response(ApiKeySerializer(keys, many=True).data)

    def post(self, request, app_id):
        app = self._get_app(request, app_id)
        s = ApiKeyCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)

        api_key, raw_key = ApiKey.create_for_app(
            app=app,
            name=s.validated_data["name"],
            expires_at=s.validated_data.get("expires_at"),
        )

        # Attach the raw key transiently so the serializer can include it.
        api_key.raw_key = raw_key

        return Response(
            ApiKeyCreatedSerializer(api_key).data,
            status=status.HTTP_201_CREATED,
        )


class ApiKeyRevokeView(APIView):
    """POST /auth/apps/{app_id}/keys/{key_id}/revoke/."""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticatedDeveloper]

    def post(self, request, app_id, key_id):
        app = get_object_or_404(App, pk=app_id, developer=request.user)
        key = get_object_or_404(ApiKey, pk=key_id, app=app)
        key.is_active = False
        key.save(update_fields=["is_active", "updated_at"])
        return Response({"detail": "API key revoked."})
