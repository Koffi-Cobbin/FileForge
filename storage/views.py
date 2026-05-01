"""DRF views for FileForge storage API.

Authentication is now handled by ``ApiKeyAuthentication``.  On a
successfully authenticated request:
    request.user  → DeveloperUser
    request.auth  → ApiKey instance

``_resolve_owner`` reads the owner slug directly from
``request.auth.app.owner_slug``.  The legacy ``X-App-Owner`` header
fallback is kept so that existing integrations and the test-runner
continue to work during a transition period; it is ignored once a valid
API key is present.
"""
from __future__ import annotations

from django.conf import settings
from django.http import StreamingHttpResponse
from django.shortcuts import get_object_or_404
from django_q.tasks import async_task
from rest_framework import generics, status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from fileforge_auth.authentication import ApiKeyAuthentication
from fileforge_auth.models import ApiKey
from fileforge_auth.permissions import IsAuthenticatedApp

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
    """Return the owner slug for the current request.

    Priority:
      1. API key auth  → owner_slug from the key's App (authoritative).
      2. Legacy header → X-App-Owner (transition / dev convenience).
      3. Default       → FILEFORGE_DEFAULT_OWNER setting.
    """
    if isinstance(request.auth, ApiKey):
        return request.auth.app.owner_slug

    # Legacy / unauthenticated fallback (dev mode or migration period).
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
    """``GET /api/files/`` and ``POST /api/files/`` (hybrid upload).

    POST accepts an optional ``mode`` field:

    * ``"async"`` (default) — queues a background task and returns 202
      immediately with ``status: "pending"``.  The caller polls
      ``GET /api/files/{id}/`` for the final outcome.

    * ``"sync"`` — performs the provider upload inline and returns 200
      with the final ``File`` state (``status: "completed"`` or
      ``"failed"``).  Only accepted for files at or below the provider's
      max sync size threshold; larger files must use the direct-upload
      flow regardless of ``mode``.
    """

    authentication_classes = [ApiKeyAuthentication]
    permission_classes = [IsAuthenticatedApp]
    parser_classes = (MultiPartParser, FormParser, JSONParser)

    def get(self, request):
        owner = _resolve_owner(request)
        qs = File.objects.filter(owner=owner)
        provider = request.query_params.get("provider")
        if provider:
            qs = qs.filter(provider=provider)
        return Response(FileSerializer(qs, many=True).data)

    def post(self, request):
        serializer = FileUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        upload = serializer.validated_data["file"]
        provider = serializer.validated_data["provider"]
        mode = serializer.validated_data.get("mode", "async")
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
                {"detail": f"File exceeds maximum upload size of {max_upload} bytes."},
                status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            )

        if size and should_use_direct_upload(provider, size):
            return Response(
                {
                    "detail": (
                        "File is too large for sync upload on this provider; "
                        "use POST /api/files/direct-upload/ instead."
                    ),
                    "provider": provider,
                    "size": size,
                },
                status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            )

        temp_path, real_size = save_to_temp(upload, original_name=original_name)

        file_obj = File.objects.create(
            name=original_name,
            size=real_size,
            content_type=getattr(upload, "content_type", "") or "",
            provider=provider,
            owner=owner,
            status=FileStatus.PENDING,
            temp_path=str(temp_path),
            upload_strategy=mode,
        )

        if mode == "sync":
            return self._upload_sync(file_obj)
        else:
            return self._upload_async(file_obj)

    # ------------------------------------------------------------------
    # Private upload helpers
    # ------------------------------------------------------------------

    def _upload_async(self, file_obj: File) -> Response:
        """Queue a background task and return 202 immediately."""
        try:
            async_task(
                "storage.tasks.process_file_upload",
                file_obj.id,
                task_name=f"upload-file-{file_obj.id}",
            )
        except Exception:
            # If the queue is unavailable, fall back to an inline call so
            # the upload is not silently lost.
            from .tasks import process_file_upload
            process_file_upload(file_obj.id)
            file_obj.refresh_from_db()

        return Response(
            FileSerializer(file_obj).data,
            status=status.HTTP_202_ACCEPTED,
        )

    def _upload_sync(self, file_obj: File) -> Response:
        """Run the provider upload inline and return the final File state."""
        from .tasks import process_file_upload

        process_file_upload(file_obj.id)
        file_obj.refresh_from_db()

        # Surface provider errors as a non-2xx response so callers don't
        # have to inspect the status field to detect failures.
        if file_obj.status == FileStatus.FAILED:
            return Response(
                {
                    "detail": file_obj.error_message or "Upload failed.",
                    "file": FileSerializer(file_obj).data,
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response(FileSerializer(file_obj).data, status=status.HTTP_200_OK)


class FileDetailView(APIView):
    """``GET``, ``PATCH``, ``DELETE`` on ``/api/files/{id}/``."""

    authentication_classes = [ApiKeyAuthentication]
    permission_classes = [IsAuthenticatedApp]

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
            except (ProviderError, ProviderConfigurationError, ProviderUnsupportedOperation) as exc:
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
            except (ProviderError, ProviderConfigurationError, ProviderUnsupportedOperation) as exc:
                return _provider_error_response(exc)
        delete_temp_file(file_obj.temp_path)
        file_obj.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Direct upload
# ---------------------------------------------------------------------------

class DirectUploadInitView(APIView):
    """``POST /api/files/direct-upload/``."""

    authentication_classes = [ApiKeyAuthentication]
    permission_classes = [IsAuthenticatedApp]

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
                provider, name,
                owner=owner,
                content_type=content_type or None,
                size=size,
            )
        except (ProviderError, ProviderConfigurationError, ProviderUnsupportedOperation) as exc:
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
    """``POST /api/files/direct-upload/complete/``."""

    authentication_classes = [ApiKeyAuthentication]
    permission_classes = [IsAuthenticatedApp]

    def post(self, request):
        serializer = DirectUploadCompleteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        owner = _resolve_owner(request)

        file_id = serializer.validated_data["file_id"]
        file_obj = get_object_or_404(File, pk=file_id, owner=owner)

        payload = dict(serializer.validated_data.get("provider_response") or {})
        if serializer.validated_data.get("provider_file_id"):
            payload["provider_file_id"] = serializer.validated_data["provider_file_id"]
        if serializer.validated_data.get("url"):
            payload["url"] = serializer.validated_data["url"]
        provider_ref = (file_obj.metadata or {}).get("provider_ref") or {}
        for k, v in provider_ref.items():
            payload.setdefault(k, v)

        try:
            result = StorageManager.finalize_direct_upload(
                file_obj.provider, payload, owner=owner
            )
        except (ProviderError, ProviderConfigurationError, ProviderUnsupportedOperation) as exc:
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
        file_obj.save(update_fields=[
            "provider_file_id", "url", "metadata",
            "status", "error_message", "updated_at",
        ])
        return Response(FileSerializer(file_obj).data)


# ---------------------------------------------------------------------------
# Providers + credentials
# ---------------------------------------------------------------------------

class ProviderListView(APIView):
    """``GET /api/providers/`` — list available providers."""

    authentication_classes = [ApiKeyAuthentication]
    permission_classes = [IsAuthenticatedApp]

    def get(self, request):
        return Response({"providers": StorageManager.list_providers()})


class StorageCredentialListCreateView(generics.ListCreateAPIView):
    authentication_classes = [ApiKeyAuthentication]
    permission_classes = [IsAuthenticatedApp]
    serializer_class = StorageCredentialSerializer

    def get_queryset(self):
        return StorageCredential.objects.filter(owner=_resolve_owner(self.request))

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
    authentication_classes = [ApiKeyAuthentication]
    permission_classes = [IsAuthenticatedApp]
    serializer_class = StorageCredentialSerializer

    def get_queryset(self):
        return StorageCredential.objects.filter(owner=_resolve_owner(self.request))


class HealthView(APIView):
    """``GET /api/health/`` — liveness probe (public, no auth required)."""

    authentication_classes = []
    permission_classes = []

    def get(self, request):
        return Response({"status": "ok", "providers": registry.names()})


class FileStreamView(APIView):
    """``GET /api/files/<pk>/stream/`` — proxy-stream a file from its provider.

    Supports HTTP Range requests so clients can seek within audio/video files.
    Only available for providers that expose the ``stream()`` method (e.g.
    Google Drive with OAuth2 or service-account credentials).

    Adapted from MuseWave-Backend's streaming infrastructure.
    """

    authentication_classes = [ApiKeyAuthentication]
    permission_classes = [IsAuthenticatedApp]

    def get(self, request, pk):
        owner = _resolve_owner(request)
        file_obj = get_object_or_404(File, pk=pk, owner=owner)

        if not file_obj.provider_file_id:
            return Response(
                {"detail": "File has no provider ID yet (upload may still be pending)."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Parse Range header (e.g. "bytes=0-1023")
        range_header = request.headers.get("Range", "")
        start = 0
        end = None
        if range_header.startswith("bytes="):
            parts = range_header[6:].split("-")
            try:
                start = int(parts[0]) if parts[0] else 0
                end = int(parts[1]) if len(parts) > 1 and parts[1] else None
            except ValueError:
                pass

        try:
            chunk_gen = StorageManager.stream(
                file_obj.provider,
                file_obj.provider_file_id,
                owner=owner,
                start=start,
                end=end,
            )
        except Exception as exc:
            return _provider_error_response(exc)

        content_type = file_obj.content_type or "application/octet-stream"
        response = StreamingHttpResponse(chunk_gen, content_type=content_type)

        if range_header:
            # Partial content
            content_length = (end - start + 1) if end is not None else ""
            response["Content-Range"] = (
                f"bytes {start}-{end if end is not None else '*'}/"
                f"{file_obj.size or '*'}"
            )
            response["Content-Length"] = content_length
            response.status_code = 206
        elif file_obj.size:
            response["Content-Length"] = file_obj.size

        response["Accept-Ranges"] = "bytes"
        response["Content-Disposition"] = (
            f'inline; filename="{file_obj.name}"'
        )
        return response