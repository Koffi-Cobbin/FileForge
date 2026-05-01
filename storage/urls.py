"""URL routes for the FileForge storage app."""
from __future__ import annotations

from django.urls import path

from .views import (
    DirectUploadCompleteView,
    DirectUploadInitView,
    FileDetailView,
    FileListCreateView,
    FileStreamView,
    HealthView,
    ProviderListView,
    StorageCredentialDetailView,
    StorageCredentialListCreateView,
)

urlpatterns = [
    path("health/", HealthView.as_view(), name="health"),
    path("providers/", ProviderListView.as_view(), name="provider-list"),
    path(
        "credentials/",
        StorageCredentialListCreateView.as_view(),
        name="credential-list",
    ),
    path(
        "credentials/<int:pk>/",
        StorageCredentialDetailView.as_view(),
        name="credential-detail",
    ),
    path("files/", FileListCreateView.as_view(), name="file-list"),
    path(
        "files/direct-upload/",
        DirectUploadInitView.as_view(),
        name="file-direct-upload-init",
    ),
    path(
        "files/direct-upload/complete/",
        DirectUploadCompleteView.as_view(),
        name="file-direct-upload-complete",
    ),
    path("files/<int:pk>/", FileDetailView.as_view(), name="file-detail"),
    path("files/<int:pk>/stream/", FileStreamView.as_view(), name="file-stream"),
]
