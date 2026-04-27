"""DRF views for FileForge.

Views are deliberately thin: they validate input, talk to
:class:`StorageManager` for any provider operation, and persist
:class:`File` rows. They never import provider classes directly.
"""
from __future__ import annotations

from dataclasses import asdict

from django.conf import settings
from django.shortcuts import get_object_or_404
from django_q.tasks import async_task
from rest_framework import generics, status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import File, FileStatus, StorageCredential
from .providers import (
    ProviderConfigurationError,
    ProviderError,
    ProviderUnsupportedOperation,
    registry,
)
from .serializers import (
    DirectUploadCompleteSerializer,
    DirectUploadInitSerializer,
    FilePatchSerializer,
    FileSerializer,
    FileUploadSerializer,
    StorageCredentialSerializer,
)
from .services import StorageManager
from .utils import (
    delete_temp_file,
    save_to_temp,
    should_use_direct_upload,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_owner(request) -> str:
    header = getattr(settings, "FILEFORGE_OWNER_HEADER", "X-App-Owner")
    value = request.headers.get(header)
    if value:
        return value.strip()
    return getattr(settings, "FILEFORGE_DEFAULT_OWNER", "default")


def _provider_error_response(exc: Exception) -> Response:
    if isinstance(exc, ProviderConfigurationError):
        code = status.HTTP_400_BAD_REQUEST
    elif isinstance(exc, ProviderUnsupportedOperation):
        code = status.HTTP_400_BAD_REQUEST
    elif isinstance(exc, ProviderError):
        code = status.HTTP_502_BAD_GATEWAY
    else:
        code = status.HTTP_500_INTERNAL_SERVER_ERROR
    return Response({"detail": str(exc)}, status=code)


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------


class FileListCreateView(APIView):
    """``GET /files/`` and ``POST /files/`` (hybrid upload)."""

    parser_classes = (MultiPartParser, FormParser, JSONParser)

    def get(self, request):
        owner = _resolve_owner(request)
        qs = File.objects.filter(owner=owner)
        provider = request.query_params.get("provider")
        if provider:
            qs = qs.filter(provider=provider)
        s = FileSerializer(qs, many=True)
        return Response(s.data)

    def post(self, request):
        serializer = FileUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        upload = serializer.validated_data["file"]
        provider = serializer.validated_data["provider"]
        owner = _resolve_owner(request)
        original_name = (
            serializer.validated_data.get("name")
            or getattr(upload, "name", "upload")
        )

        max_upload = int(
            getattr(settings, "FILEFORGE_MAX_UPLOAD_SIZE", 100 * 1024 * 1024)
        )
        size = getattr(upload, "size", None) or 0
        if size and size > max_upload:
            return Response(
                {
                    "detail": (
                        f"File exceeds maximum upload size of "
                        f"{max_upload} bytes."
                    )
                },
                status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            )

        if size and should_use_direct_upload(provider, size):
            return Response(
                {
                    "detail": (
                        "File is too large for sync upload on this provider; "
                        "use POST /files/direct-upload/ instead."
                    ),
                    "provider": provider,
                    "size": size,
                },
                status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            )

        # Stream to disk first — we never buffer the whole upload in memory.
        temp_path, real_size = save_to_temp(upload, original_name=original_name)

        file_obj = File.objects.create(
            name=original_name,
            size=real_size,
            content_type=getattr(upload, "content_type", "") or "",
            provider=provider,
            owner=owner,
            status=FileStatus.PENDING,
            temp_path=str(temp_path),
            upload_strategy="async_backend",
        )

        # Schedule async work; fall back to in-process execution if django-q2
        # cannot enqueue (e.g. no cluster running) so we still respect the
        # spec's flow even in dev.
        try:
            async_task(
                "storage.tasks.process_file_upload",
                file_obj.id,
                task_name=f"upload-file-{file_obj.id}",
            )
        except Exception:
            from .tasks import process_file_upload

            process_file_upload(file_obj.id)
            file_obj.refresh_from_db()

        return Response(
            FileSerializer(file_obj).data,
            status=status.HTTP_202_ACCEPTED,
        )


class FileDetailView(APIView):
    """``GET``, ``PATCH``, ``DELETE`` on ``/files/{id}/``."""

    def _get_file(self, request, pk):
        owner = _resolve_owner(request)
        return get_object_or_404(File, pk=pk, owner=owner)

    def get(self, request, pk):
        return Response(FileSerializer(self._get_file(request, pk)).data)

    def patch(self, request, pk):
        file_obj = self._get_file(request, pk)
        s = FilePatchSerializer(file_obj, data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        new_name = s.validated_data.get("name")
        if new_name and file_obj.provider_file_id:
            try:
                StorageManager.update(
                    file_obj.provider,
                    file_obj.provider_file_id,
                    owner=file_obj.owner,
                    name=new_name,
                    new_public_id=new_name,
                )
            except (
                ProviderError,
                ProviderConfigurationError,
                ProviderUnsupportedOperation,
            ) as exc:
                return _provider_error_response(exc)
        s.save()
        return Response(FileSerializer(file_obj).data)

    def delete(self, request, pk):
        file_obj = self._get_file(request, pk)
        if file_obj.provider_file_id:
            try:
                StorageManager.delete(
                    file_obj.provider,
                    file_obj.provider_file_id,
                    owner=file_obj.owner,
                )
            except (
                ProviderError,
                ProviderConfigurationError,
                ProviderUnsupportedOperation,
            ) as exc:
                return _provider_error_response(exc)
        delete_temp_file(file_obj.temp_path)
        file_obj.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Direct upload
# ---------------------------------------------------------------------------


class DirectUploadInitView(APIView):
    """``POST /files/direct-upload/`` — get a signed upload URL."""

    def post(self, request):
        serializer = DirectUploadInitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        provider = serializer.validated_data["provider"]
        name = serializer.validated_data["name"]
        size = serializer.validated_data["size"]
        content_type = serializer.validated_data.get("content_type", "")
        owner = _resolve_owner(request)

        try:
            ticket = StorageManager.generate_upload_url(
                provider,
                name,
                owner=owner,
                content_type=content_type or None,
                size=size,
            )
        except (
            ProviderError,
            ProviderConfigurationError,
            ProviderUnsupportedOperation,
        ) as exc:
            return _provider_error_response(exc)

        file_obj = File.objects.create(
            name=name,
            size=size,
            content_type=content_type or "",
            provider=provider,
            owner=owner,
            status=FileStatus.PENDING,
            upload_strategy="direct",
            metadata={"provider_ref": ticket.provider_ref},
        )

        return Response(
            {
                "file_id": file_obj.id,
                "upload_url": ticket.upload_url,
                "method": ticket.method,
                "fields": ticket.fields,
                "headers": ticket.headers,
                "expires_in": ticket.expires_in,
                "provider_ref": ticket.provider_ref,
            },
            status=status.HTTP_201_CREATED,
        )


class DirectUploadCompleteView(APIView):
    """``POST /files/direct-upload/complete/`` — finalize a direct upload."""

    def post(self, request):
        serializer = DirectUploadCompleteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        owner = _resolve_owner(request)

        file_id = serializer.validated_data["file_id"]
        file_obj = get_object_or_404(File, pk=file_id, owner=owner)

        payload = dict(serializer.validated_data.get("provider_response") or {})
        if serializer.validated_data.get("provider_file_id"):
            payload["provider_file_id"] = serializer.validated_data[
                "provider_file_id"
            ]
        if serializer.validated_data.get("url"):
            payload["url"] = serializer.validated_data["url"]
        # Pass along the provider_ref captured at init time.
        provider_ref = (file_obj.metadata or {}).get("provider_ref") or {}
        for k, v in provider_ref.items():
            payload.setdefault(k, v)

        try:
            result = StorageManager.finalize_direct_upload(
                file_obj.provider, payload, owner=owner
            )
        except (
            ProviderError,
            ProviderConfigurationError,
            ProviderUnsupportedOperation,
        ) as exc:
            file_obj.status = FileStatus.FAILED
            file_obj.error_message = str(exc)[:2000]
            file_obj.save(update_fields=["status", "error_message", "updated_at"])
            return _provider_error_response(exc)

        file_obj.provider_file_id = result.provider_file_id
        file_obj.url = result.url or ""
        merged_meta = dict(file_obj.metadata or {})
        merged_meta.update(result.metadata or {})
        file_obj.metadata = merged_meta
        file_obj.status = FileStatus.COMPLETED
        file_obj.error_message = ""
        file_obj.save(
            update_fields=[
                "provider_file_id",
                "url",
                "metadata",
                "status",
                "error_message",
                "updated_at",
            ]
        )
        return Response(FileSerializer(file_obj).data)


# ---------------------------------------------------------------------------
# Providers + credentials
# ---------------------------------------------------------------------------


class ProviderListView(APIView):
    """``GET /providers/`` — list available providers."""

    def get(self, request):
        return Response({"providers": StorageManager.list_providers()})


class StorageCredentialListCreateView(generics.ListCreateAPIView):
    serializer_class = StorageCredentialSerializer

    def get_queryset(self):
        return StorageCredential.objects.filter(
            owner=_resolve_owner(self.request)
        )

    def perform_create(self, serializer):
        owner = _resolve_owner(self.request)
        provider = serializer.validated_data["provider"]
        StorageCredential.objects.update_or_create(
            owner=owner,
            provider=provider,
            defaults={
                "credentials": serializer.validated_data.get("credentials", {}),
                "is_default": serializer.validated_data.get("is_default", True),
            },
        )


class StorageCredentialDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = StorageCredentialSerializer

    def get_queryset(self):
        return StorageCredential.objects.filter(
            owner=_resolve_owner(self.request)
        )


class HealthView(APIView):
    """``GET /health/`` — liveness probe."""

    def get(self, request):
        return Response(
            {
                "status": "ok",
                "providers": registry.names(),
            }
        )
