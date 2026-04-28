"""Root URL configuration for FileForge."""
from __future__ import annotations

from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path
from django.conf import settings
from django.conf.urls.static import static


def root(_request):
    return JsonResponse(
        {
            "service": "FileForge",
            "description": "Pluggable cloud storage bridge",
            "endpoints": {
                # Auth / management (JWT-authenticated)
                "register":              "/auth/register/",
                "token_obtain":          "/auth/token/",
                "token_refresh":         "/auth/token/refresh/",
                "me":                    "/auth/me/",
                "change_password":       "/auth/me/change-password/",
                "apps":                  "/auth/apps/",
                "app_detail":            "/auth/apps/{id}/",
                "app_keys":              "/auth/apps/{id}/keys/",
                "app_key_revoke":        "/auth/apps/{id}/keys/{key_id}/revoke/",
                # Storage API (API-key-authenticated)
                "files_list_create":     "/api/files/",
                "file_detail":           "/api/files/{id}/",
                "direct_upload_init":    "/api/files/direct-upload/",
                "direct_upload_complete":"/api/files/direct-upload/complete/",
                "providers":             "/api/providers/",
                "credentials":           "/api/credentials/",
                "health":                "/api/health/",
            },
        }
    )


urlpatterns = [
    path("", root),
    path("admin/", admin.site.urls),
    path("auth/", include("fileforge_auth.urls")),
    path("api/", include("storage.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
