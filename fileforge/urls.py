"""Root URL configuration for FileForge."""
from __future__ import annotations

from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path


def root(_request):
    return JsonResponse(
        {
            "service": "FileForge",
            "description": "Pluggable cloud storage bridge",
            "endpoints": {
                "files_list_create": "/api/files/",
                "file_detail": "/api/files/{id}/",
                "direct_upload_init": "/api/files/direct-upload/",
                "direct_upload_complete": "/api/files/direct-upload/complete/",
                "providers": "/api/providers/",
                "credentials": "/api/credentials/",
                "health": "/api/health/",
            },
        }
    )


urlpatterns = [
    path("", root),
    path("admin/", admin.site.urls),
    path("api/", include("storage.urls")),
]
