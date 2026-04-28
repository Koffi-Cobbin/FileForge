"""URL routes for the fileforge_auth app."""
from __future__ import annotations

from django.urls import path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .views import (
    ApiKeyListCreateView,
    ApiKeyRevokeView,
    AppDetailView,
    AppListCreateView,
    ChangePasswordView,
    MeView,
    RegisterView,
)

urlpatterns = [
    # ── Auth ────────────────────────────────────────────────────────────────
    path("register/", RegisterView.as_view(), name="auth-register"),
    path("token/", TokenObtainPairView.as_view(), name="auth-token"),
    path("token/refresh/", TokenRefreshView.as_view(), name="auth-token-refresh"),

    # ── Developer profile ───────────────────────────────────────────────────
    path("me/", MeView.as_view(), name="auth-me"),
    path("me/change-password/", ChangePasswordView.as_view(), name="auth-change-password"),

    # ── Apps ────────────────────────────────────────────────────────────────
    path("apps/", AppListCreateView.as_view(), name="auth-app-list"),
    path("apps/<int:pk>/", AppDetailView.as_view(), name="auth-app-detail"),

    # ── API Keys ────────────────────────────────────────────────────────────
    path("apps/<int:app_id>/keys/", ApiKeyListCreateView.as_view(), name="auth-key-list"),
    path("apps/<int:app_id>/keys/<int:key_id>/revoke/", ApiKeyRevokeView.as_view(), name="auth-key-revoke"),
]
