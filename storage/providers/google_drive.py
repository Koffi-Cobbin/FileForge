"""Google Drive provider implementation.

Authentication modes (in priority order):
  1. OAuth2 refresh token — credentials keys:
       ``oauth2_client_id``, ``oauth2_client_secret``, ``oauth2_refresh_token``
     Suitable for personal Google Drive accounts (adapted from MuseWave-Backend).

  2. Service account — credentials keys:
       ``service_account_json``  (JSON string or dict)
       OR ``service_account_file`` (filesystem path to the JSON key file)
     Suitable for Google Workspace / shared drives.

Optional credential keys (both modes):
  ``folder_id`` — parent Drive folder ID to upload files into.
"""
from __future__ import annotations

import io
import json
import logging
from typing import Any, BinaryIO, Generator, Mapping

from .base import (
    BaseStorageProvider,
    DirectUploadTicket,
    ProviderConfigurationError,
    ProviderError,
    UploadResult,
)

logger = logging.getLogger(__name__)

_SCOPES = ["https://www.googleapis.com/auth/drive"]
_CHUNK_SIZE = 5 * 1024 * 1024  # 5 MB — matches MuseWave default


class GoogleDriveProvider(BaseStorageProvider):
    """Upload, download, stream, and manage files in Google Drive.

    Supports both OAuth2 refresh-token credentials (personal Drive) and
    service-account credentials (Workspace / shared drives).
    """

    name = "google_drive"
    supports_direct_upload = True
    supports_streaming = True

    def __init__(self, credentials: Mapping[str, Any] | None = None) -> None:
        super().__init__(credentials)
        self._service = None  # lazy-initialised

    # ------------------------------------------------------------------
    # Auth helpers
    # ------------------------------------------------------------------

    def _build_service(self):
        """Return a cached Drive API client, building it on first call.

        Tries OAuth2 refresh-token credentials first, then falls back to
        service-account credentials.
        """
        if self._service is not None:
            return self._service

        try:
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise ProviderConfigurationError(
                "google-api-python-client is not installed"
            ) from exc

        creds = self._build_oauth2_credentials() or self._build_service_account_credentials()
        if creds is None:
            raise ProviderConfigurationError(
                "Google Drive provider requires OAuth2 credentials "
                "(oauth2_client_id / oauth2_client_secret / oauth2_refresh_token) "
                "or service-account credentials "
                "(service_account_json or service_account_file)."
            )

        self._service = build("drive", "v3", credentials=creds, cache_discovery=False)
        return self._service

    def _build_oauth2_credentials(self):
        """Build OAuth2 refresh-token credentials (adapted from MuseWave-Backend).

        Proactively refreshes the access token so credential errors surface early.
        """
        client_id = self.credentials.get("oauth2_client_id")
        client_secret = self.credentials.get("oauth2_client_secret")
        refresh_token = self.credentials.get("oauth2_refresh_token")

        if not all([client_id, client_secret, refresh_token]):
            return None

        try:
            from google.oauth2.credentials import Credentials
            from google.auth.transport.requests import Request
        except ImportError as exc:
            raise ProviderConfigurationError(
                "google-auth is not installed"
            ) from exc

        creds = Credentials(
            token=None,
            refresh_token=refresh_token,
            client_id=client_id,
            client_secret=client_secret,
            token_uri="https://oauth2.googleapis.com/token",
            scopes=_SCOPES,
        )
        if not creds.valid:
            creds.refresh(Request())

        logger.info("Google Drive: authenticated via OAuth2 refresh token")
        return creds

    def _build_service_account_credentials(self):
        """Build service-account credentials from a JSON blob or file path."""
        sa_json = self.credentials.get("service_account_json")
        sa_file = self.credentials.get("service_account_file")

        if not sa_json and not sa_file:
            return None

        try:
            from google.oauth2 import service_account
        except ImportError as exc:
            raise ProviderConfigurationError(
                "google-auth is not installed"
            ) from exc

        if sa_json:
            info = sa_json if isinstance(sa_json, dict) else json.loads(sa_json)
            creds = service_account.Credentials.from_service_account_info(
                info, scopes=_SCOPES
            )
        else:
            creds = service_account.Credentials.from_service_account_file(
                sa_file, scopes=_SCOPES
            )

        logger.info("Google Drive: authenticated via service account")
        return creds

    def _refresh_token_if_needed(self, creds) -> None:
        """Refresh the access token if it has expired (used before raw HTTP calls)."""
        if not creds.valid:
            from google.auth.transport.requests import Request as GAuthRequest
            creds.refresh(GAuthRequest())

    def _folder_id(self) -> str | None:
        return self.credentials.get("folder_id") or None

    # ------------------------------------------------------------------
    # Folder utilities (adapted from MuseWave-Backend folder_manager)
    # ------------------------------------------------------------------

    def find_or_create_folder(self, name: str, parent_id: str) -> str:
        """Return the Drive folder ID for *name* inside *parent_id*.

        Creates the folder if it does not already exist.  Adapted from
        MuseWave-Backend's ``folder_manager._find_or_create_folder``.
        """
        service = self._build_service()
        safe_name = name.replace("'", "\\'")
        query = (
            f"mimeType='application/vnd.google-apps.folder' "
            f"and name='{safe_name}' "
            f"and '{parent_id}' in parents "
            f"and trashed=false"
        )
        try:
            results = (
                service.files()
                .list(q=query, fields="files(id, name)", spaces="drive")
                .execute()
            )
        except Exception as exc:
            raise ProviderError(f"Google Drive folder search failed: {exc}") from exc

        files = results.get("files", [])
        if files:
            return files[0]["id"]

        metadata = {
            "name": name,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [parent_id],
        }
        try:
            folder = service.files().create(body=metadata, fields="id").execute()
        except Exception as exc:
            raise ProviderError(f"Google Drive folder creation failed: {exc}") from exc

        logger.info(
            "Google Drive: created folder '%s' (id=%s) under parent=%s",
            name, folder["id"], parent_id,
        )
        return folder["id"]

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
        """Upload *file* using a resumable chunked session (5 MB chunks).

        Chunked/resumable upload adapted from MuseWave-Backend for reliability
        with larger files.
        """
        from googleapiclient.http import MediaIoBaseUpload

        service = self._build_service()

        # Measure size if not supplied (mirrors MuseWave-Backend upload_file)
        if size is None and hasattr(file, "seek"):
            file.seek(0, 2)
            size = file.tell()
            file.seek(0)

        body: dict[str, Any] = {"name": path}
        folder_id = self._folder_id()
        if folder_id:
            body["parents"] = [folder_id]

        media = MediaIoBaseUpload(
            file,
            mimetype=content_type or "application/octet-stream",
            chunksize=_CHUNK_SIZE,
            resumable=True,
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
        except Exception as exc:
            raise ProviderError(f"Google Drive upload failed: {exc}") from exc

        logger.info(
            "Google Drive: uploaded '%s' (file_id=%s, folder=%s)",
            path, response["id"], folder_id,
        )
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
        """Download the full content of *file_id* into memory."""
        buf = io.BytesIO()
        for chunk in self.stream(file_id):
            buf.write(chunk)
        return buf.getvalue()

    def stream(
        self,
        file_id: str,
        *,
        start: int = 0,
        end: int | None = None,
        **kwargs: Any,
    ) -> Generator[bytes, None, None]:
        """Yield byte chunks for *file_id*, honouring Range byte offsets.

        Adapted from MuseWave-Backend ``stream_file_chunks()``.  Uses the same
        5 MB chunk size and correctly slices each chunk to honour the requested
        *start* / *end* byte window.
        """
        from googleapiclient.http import MediaIoBaseDownload

        service = self._build_service()

        try:
            meta = (
                service.files()
                .get(fileId=file_id, fields="size, mimeType", supportsAllDrives=True)
                .execute()
            )
        except Exception as exc:
            raise ProviderError(f"Google Drive metadata fetch failed: {exc}") from exc

        total_size = int(meta.get("size", 0))
        if end is None or end >= total_size:
            end = total_size - 1

        request = service.files().get_media(fileId=file_id)
        buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(buffer, request, chunksize=_CHUNK_SIZE)

        bytes_yielded = 0
        done = False
        while not done:
            try:
                _status, done = downloader.next_chunk()
            except Exception as exc:
                raise ProviderError(f"Google Drive stream failed: {exc}") from exc

            buffer.seek(0)
            chunk = buffer.read()
            buffer.seek(0)
            buffer.truncate(0)

            chunk_start = bytes_yielded
            chunk_end = bytes_yielded + len(chunk) - 1

            if chunk_end < start:
                bytes_yielded += len(chunk)
                continue
            if chunk_start > end:
                return

            slice_start = max(0, start - chunk_start)
            slice_end = min(len(chunk), end - chunk_start + 1)
            yield chunk[slice_start:slice_end]
            bytes_yielded += len(chunk)

    def delete(self, file_id: str, **kwargs: Any) -> None:
        service = self._build_service()
        try:
            service.files().delete(
                fileId=file_id, supportsAllDrives=True
            ).execute()
        except Exception as exc:
            raise ProviderError(f"Google Drive delete failed: {exc}") from exc
        logger.info("Google Drive: deleted file_id=%s", file_id)

    def update(self, file_id: str, **kwargs: Any) -> dict[str, Any]:
        service = self._build_service()
        body: dict[str, Any] = {}
        if "name" in kwargs:
            body["name"] = kwargs["name"]

        # Support updating file content as well (adapted from MuseWave update_file)
        file_obj = kwargs.get("file")
        if file_obj is not None:
            from googleapiclient.http import MediaIoBaseUpload
            mime = kwargs.get("content_type", "application/octet-stream")
            media = MediaIoBaseUpload(file_obj, mimetype=mime, chunksize=_CHUNK_SIZE, resumable=True)
            try:
                response = (
                    service.files()
                    .update(
                        fileId=file_id,
                        body=body,
                        media_body=media,
                        fields="id, name, mimeType, webViewLink, webContentLink",
                        supportsAllDrives=True,
                    )
                    .execute()
                )
            except Exception as exc:
                raise ProviderError(f"Google Drive update failed: {exc}") from exc
        else:
            try:
                response = (
                    service.files()
                    .update(
                        fileId=file_id,
                        body=body,
                        fields="id, name, mimeType, webViewLink, webContentLink",
                        supportsAllDrives=True,
                    )
                    .execute()
                )
            except Exception as exc:
                raise ProviderError(f"Google Drive update failed: {exc}") from exc

        logger.info("Google Drive: updated file_id=%s", file_id)
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
        except Exception as exc:
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

        The client PUTs the file bytes directly to ``upload_url``.  After
        completion Drive responds with the new file metadata.
        """
        import requests as req_lib

        service = self._build_service()
        creds = service._http.credentials  # type: ignore[attr-defined]
        self._refresh_token_if_needed(creds)

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

        resp = req_lib.post(
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
            headers={"Content-Type": content_type or "application/octet-stream"},
            provider_ref={"path": path},
        )

    def finalize_direct_upload(
        self, data: Mapping[str, Any]
    ) -> UploadResult:
        """Look up file metadata after the client has finished uploading."""
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
        except Exception as exc:
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
