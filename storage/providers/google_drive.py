"""Google Drive provider implementation."""
from __future__ import annotations

import io
import json
import logging
from typing import Any, BinaryIO, Mapping

from .base import (
    BaseStorageProvider,
    DirectUploadTicket,
    ProviderConfigurationError,
    ProviderError,
    UploadResult,
)

logger = logging.getLogger(__name__)

_SCOPES = ["https://www.googleapis.com/auth/drive"]


class GoogleDriveProvider(BaseStorageProvider):
    """Upload, download, and delete files in Google Drive.

    Credentials are expected to contain either:
      * ``service_account_json`` — a JSON string with the service account key.
      * ``service_account_file`` — a filesystem path to the JSON key file.

    Optional:
      * ``folder_id`` — the parent folder ID to upload files into.
    """

    name = "google_drive"
    supports_direct_upload = True

    def __init__(self, credentials: Mapping[str, Any] | None = None) -> None:
        super().__init__(credentials)
        self._service = None  # Lazy

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _build_service(self):
        if self._service is not None:
            return self._service
        try:
            from google.oauth2 import service_account
            from googleapiclient.discovery import build
        except ImportError as exc:  # pragma: no cover
            raise ProviderConfigurationError(
                "google-api-python-client is not installed"
            ) from exc

        sa_json = self.credentials.get("service_account_json")
        sa_file = self.credentials.get("service_account_file")
        creds = None
        if sa_json:
            info = sa_json if isinstance(sa_json, dict) else json.loads(sa_json)
            creds = service_account.Credentials.from_service_account_info(
                info, scopes=_SCOPES
            )
        elif sa_file:
            creds = service_account.Credentials.from_service_account_file(
                sa_file, scopes=_SCOPES
            )
        else:
            raise ProviderConfigurationError(
                "Google Drive provider requires `service_account_json` or "
                "`service_account_file` in credentials."
            )
        self._service = build(
            "drive", "v3", credentials=creds, cache_discovery=False
        )
        return self._service

    def _folder_id(self) -> str | None:
        return self.credentials.get("folder_id") or None

    # ------------------------------------------------------------------
    # Core CRUD
    # ------------------------------------------------------------------

    def upload(
        self,
        file: BinaryIO,
        path: str,
        *,
        content_type: str | None = None,
        size: int | None = None,
        **kwargs: Any,
    ) -> UploadResult:
        from googleapiclient.http import MediaIoBaseUpload

        service = self._build_service()
        body: dict[str, Any] = {"name": path}
        folder_id = self._folder_id()
        if folder_id:
            body["parents"] = [folder_id]

        media = MediaIoBaseUpload(
            file,
            mimetype=content_type or "application/octet-stream",
            resumable=False,
        )
        try:
            response = (
                service.files()
                .create(
                    body=body,
                    media_body=media,
                    fields="id, name, size, mimeType, webViewLink, webContentLink",
                    supportsAllDrives=True,
                )
                .execute()
            )
        except Exception as exc:  # pragma: no cover - network errors
            raise ProviderError(f"Google Drive upload failed: {exc}") from exc

        return UploadResult(
            provider_file_id=response["id"],
            url=response.get("webViewLink") or response.get("webContentLink"),
            metadata={
                "mime_type": response.get("mimeType"),
                "size": response.get("size"),
                "name": response.get("name"),
            },
        )

    def download(self, file_id: str, **kwargs: Any) -> bytes:
        from googleapiclient.http import MediaIoBaseDownload

        service = self._build_service()
        request = service.files().get_media(fileId=file_id)
        buf = io.BytesIO()
        downloader = MediaIoBaseDownload(buf, request)
        done = False
        while not done:
            _status, done = downloader.next_chunk()
        return buf.getvalue()

    def delete(self, file_id: str, **kwargs: Any) -> None:
        service = self._build_service()
        try:
            service.files().delete(
                fileId=file_id, supportsAllDrives=True
            ).execute()
        except Exception as exc:  # pragma: no cover
            raise ProviderError(f"Google Drive delete failed: {exc}") from exc

    def update(self, file_id: str, **kwargs: Any) -> dict[str, Any]:
        service = self._build_service()
        body: dict[str, Any] = {}
        if "name" in kwargs:
            body["name"] = kwargs["name"]
        try:
            response = (
                service.files()
                .update(
                    fileId=file_id,
                    body=body,
                    fields="id, name, mimeType, webViewLink",
                    supportsAllDrives=True,
                )
                .execute()
            )
        except Exception as exc:  # pragma: no cover
            raise ProviderError(f"Google Drive update failed: {exc}") from exc
        return response

    def get_url(self, file_id: str, **kwargs: Any) -> str:
        service = self._build_service()
        try:
            response = (
                service.files()
                .get(
                    fileId=file_id,
                    fields="id, webViewLink, webContentLink",
                    supportsAllDrives=True,
                )
                .execute()
            )
        except Exception as exc:  # pragma: no cover
            raise ProviderError(f"Google Drive get_url failed: {exc}") from exc
        return response.get("webViewLink") or response.get("webContentLink") or ""

    # ------------------------------------------------------------------
    # Direct upload (resumable session URL)
    # ------------------------------------------------------------------

    def generate_upload_url(
        self,
        path: str,
        *,
        content_type: str | None = None,
        size: int | None = None,
        **kwargs: Any,
    ) -> DirectUploadTicket:
        """Create a Drive resumable upload session and return its session URL.

        The client PUTs the bytes directly to ``upload_url``. After completion
        Drive responds with the new file metadata.
        """
        import requests

        service = self._build_service()
        # Drive's discovery client doesn't expose resumable session creation
        # cleanly, so issue the HTTP call ourselves using its credentials.
        creds = service._http.credentials  # type: ignore[attr-defined]
        if not creds.valid:
            from google.auth.transport.requests import Request as GAuthRequest

            creds.refresh(GAuthRequest())
        headers = {
            "Authorization": f"Bearer {creds.token}",
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Type": content_type or "application/octet-stream",
        }
        if size is not None:
            headers["X-Upload-Content-Length"] = str(size)

        body: dict[str, Any] = {"name": path}
        folder_id = self._folder_id()
        if folder_id:
            body["parents"] = [folder_id]

        resp = requests.post(
            "https://www.googleapis.com/upload/drive/v3/files"
            "?uploadType=resumable&supportsAllDrives=true",
            headers=headers,
            data=json.dumps(body),
            timeout=30,
        )
        if resp.status_code >= 300:
            raise ProviderError(
                f"Failed to start Drive resumable upload: "
                f"{resp.status_code} {resp.text}"
            )
        session_url = resp.headers.get("Location")
        if not session_url:
            raise ProviderError(
                "Drive did not return a resumable upload Location header."
            )

        return DirectUploadTicket(
            upload_url=session_url,
            method="PUT",
            headers={
                "Content-Type": content_type or "application/octet-stream",
            },
            provider_ref={"path": path},
        )

    def finalize_direct_upload(
        self, data: Mapping[str, Any]
    ) -> UploadResult:
        """Look up file metadata after the client has uploaded the bytes."""
        provider_file_id = data.get("provider_file_id")
        if not provider_file_id:
            raise ProviderError(
                "Google Drive finalize requires `provider_file_id`."
            )
        service = self._build_service()
        try:
            response = (
                service.files()
                .get(
                    fileId=provider_file_id,
                    fields="id, name, size, mimeType, webViewLink, webContentLink",
                    supportsAllDrives=True,
                )
                .execute()
            )
        except Exception as exc:  # pragma: no cover
            raise ProviderError(
                f"Google Drive finalize lookup failed: {exc}"
            ) from exc

        return UploadResult(
            provider_file_id=response["id"],
            url=response.get("webViewLink") or response.get("webContentLink"),
            metadata={
                "mime_type": response.get("mimeType"),
                "size": response.get("size"),
                "name": response.get("name"),
            },
        )
