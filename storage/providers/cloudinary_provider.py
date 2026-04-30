"""Cloudinary provider implementation.

The module is named ``cloudinary_provider`` to avoid shadowing the
``cloudinary`` PyPI package.
"""
from __future__ import annotations

import io
import logging
import os
import time
from typing import Any, BinaryIO, Mapping

from .base import (
    BaseStorageProvider,
    DirectUploadTicket,
    ProviderConfigurationError,
    ProviderError,
    UploadResult,
)

logger = logging.getLogger(__name__)


class CloudinaryProvider(BaseStorageProvider):
    """Upload, download, and delete files in Cloudinary.

    Credentials are expected to contain either:
      * ``cloud_name``, ``api_key``, ``api_secret`` — preferred.
      * ``url`` — a ``cloudinary://api_key:api_secret@cloud_name`` URL.

    Optional:
      * ``folder`` — folder prefix prepended to uploads.
      * ``resource_type`` — ``"auto"`` (default), ``"image"``, ``"video"``,
        or ``"raw"``.
      * ``api_proxy`` — HTTP proxy URL required on PythonAnywhere free tier
        (e.g. ``"http://proxy.server:3128"``).  An empty string or ``None``
        means no proxy is configured.
    """

    name = "cloudinary"
    supports_direct_upload = True

    def __init__(self, credentials: Mapping[str, Any] | None = None) -> None:
        super().__init__(credentials)
        self._configured = False


    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _configure(self) -> None:
        if self._configured:
            return
        try:
            import cloudinary
        except ImportError as exc:
            raise ProviderConfigurationError("cloudinary package is not installed") from exc

        url = self.credentials.get("url")
        cloud_name = self.credentials.get("cloud_name")
        api_key = self.credentials.get("api_key")
        api_secret = self.credentials.get("api_secret")

        if url:
            cloudinary.config(cloudinary_url=url)
        elif cloud_name and api_key and api_secret:
            cloudinary.config(
                cloud_name=cloud_name,
                api_key=api_key,
                api_secret=api_secret,
                secure=True,
            )
        else:
            raise ProviderConfigurationError(
                "Cloudinary provider requires either `url` or "
                "`cloud_name`+`api_key`+`api_secret` in credentials."
            )

        api_proxy = self.credentials.get("api_proxy") or ""
        if api_proxy:
            cloudinary.config(api_proxy=api_proxy)
            self._inject_proxy_into_cloudinary_session(api_proxy)
            logger.info("Cloudinary: proxy configured as %r", api_proxy)
        else:
            logger.warning("Cloudinary: NO proxy configured")

        self._configured = True

    @staticmethod
    def _inject_proxy_into_cloudinary_session(proxy_url: str) -> None:
        import requests

        proxies = {"http": proxy_url, "https": proxy_url}

        # Monkey-patch Session.__init__ so any future sessions pick up the proxy.
        if not getattr(requests.Session, "_ff_proxy_patched", False):
            _original_init = requests.Session.__init__

            def _patched_init(self, *args, **kwargs):
                _original_init(self, *args, **kwargs)
                self.proxies.update(proxies)
                self.trust_env = True

            requests.Session.__init__ = _patched_init
            requests.Session._ff_proxy_patched = True

        # Force the cloudinary SDK to create its lazy session NOW (while the
        # patched __init__ is in place), then update it directly.
        try:
            import cloudinary.http_client as _http_client
            session = getattr(_http_client, "session", None)
            if session is None:
                # Trigger lazy session creation by calling a no-op request setup.
                # The SDK creates the session on first use of get_http_connector().
                if hasattr(_http_client, "get_http_connector"):
                    _http_client.get_http_connector()
                elif hasattr(_http_client, "HttpClient"):
                    _http_client.HttpClient()
                session = getattr(_http_client, "session", None)

            if isinstance(session, requests.Session):
                session.proxies.update(proxies)
                session.trust_env = True
                logger.info("Cloudinary: patched live http_client.session proxy")
            else:
                logger.info(
                    "Cloudinary: session is %s — proxy will apply to next created session",
                    type(session),
                )
        except Exception as exc:
            logger.warning("Cloudinary: could not patch http_client.session: %s", exc)


    def _resource_type(self, override: str | None = None) -> str:
        return (
            override
            or self.credentials.get("resource_type")
            or "auto"
        )

    def _folder(self) -> str | None:
        return self.credentials.get("folder") or None

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
        self._configure()
        import cloudinary.uploader

        options: dict[str, Any] = {
            "public_id": path,
            "resource_type": self._resource_type(kwargs.get("resource_type")),
            "use_filename": False,
            "unique_filename": False,
            "overwrite": True,
        }
        folder = self._folder()
        if folder:
            options["folder"] = folder
        try:
            response = cloudinary.uploader.upload(file, **options)
        except Exception as exc:
            raise ProviderError(f"Cloudinary upload failed: {exc}") from exc

        return UploadResult(
            provider_file_id=response["public_id"],
            url=response.get("secure_url") or response.get("url"),
            metadata={
                "resource_type": response.get("resource_type"),
                "format": response.get("format"),
                "bytes": response.get("bytes"),
                "version": response.get("version"),
            },
        )

    def download(self, file_id: str, **kwargs: Any) -> bytes:
        import requests

        url = self.get_url(file_id, **kwargs)

        proxies: dict[str, str] = {}
        api_proxy = self.credentials.get("api_proxy") or ""
        if api_proxy:
            proxies = {"http": api_proxy, "https": api_proxy}

        resp = requests.get(url, timeout=60, proxies=proxies or None)
        if resp.status_code >= 300:
            raise ProviderError(
                f"Cloudinary download failed: {resp.status_code}"
            )
        return resp.content

    def delete(self, file_id: str, **kwargs: Any) -> None:
        self._configure()
        import cloudinary.uploader

        resource_type = self._resource_type(kwargs.get("resource_type"))
        # Cloudinary's destroy doesn't accept "auto"; default to "image".
        if resource_type == "auto":
            resource_type = "image"
        try:
            response = cloudinary.uploader.destroy(
                file_id, resource_type=resource_type, invalidate=True
            )
        except Exception as exc:  # pragma: no cover
            raise ProviderError(f"Cloudinary delete failed: {exc}") from exc
        if response.get("result") not in {"ok", "not found"}:
            raise ProviderError(
                f"Cloudinary delete returned: {response!r}"
            )

    def update(self, file_id: str, **kwargs: Any) -> dict[str, Any]:
        self._configure()
        import cloudinary.uploader

        resource_type = self._resource_type(kwargs.get("resource_type"))
        if resource_type == "auto":
            resource_type = "image"
        new_id = kwargs.get("new_public_id") or kwargs.get("name")
        if not new_id:
            raise ProviderError(
                "Cloudinary update requires `new_public_id` or `name`."
            )
        try:
            response = cloudinary.uploader.rename(
                file_id, new_id, resource_type=resource_type, overwrite=True
            )
        except Exception as exc:  # pragma: no cover
            raise ProviderError(f"Cloudinary update failed: {exc}") from exc
        return response

    def get_url(self, file_id: str, **kwargs: Any) -> str:
        self._configure()
        import cloudinary.utils

        resource_type = self._resource_type(kwargs.get("resource_type"))
        if resource_type == "auto":
            resource_type = "image"
        url, _options = cloudinary.utils.cloudinary_url(
            file_id, resource_type=resource_type, secure=True
        )
        return url

    # ------------------------------------------------------------------
    # Direct upload (signed multipart POST)
    # ------------------------------------------------------------------

    def generate_upload_url(
        self,
        path: str,
        *,
        content_type: str | None = None,
        size: int | None = None,
        **kwargs: Any,
    ) -> DirectUploadTicket:
        """Return a signed POST endpoint and form fields for direct upload."""
        self._configure()
        import cloudinary
        import cloudinary.utils

        resource_type = self._resource_type(kwargs.get("resource_type"))
        timestamp = int(time.time())
        params: dict[str, Any] = {
            "timestamp": timestamp,
            "public_id": path,
            "overwrite": "true",
            "unique_filename": "false",
            "use_filename": "false",
        }
        folder = self._folder()
        if folder:
            params["folder"] = folder

        cfg = cloudinary.config()
        api_secret = cfg.api_secret
        api_key = cfg.api_key
        cloud_name = cfg.cloud_name
        if not (api_secret and api_key and cloud_name):
            raise ProviderConfigurationError(
                "Cloudinary configuration is incomplete."
            )

        signature = cloudinary.utils.api_sign_request(params, api_secret)
        upload_url = (
            f"https://api.cloudinary.com/v1_1/{cloud_name}/"
            f"{resource_type}/upload"
        )
        fields = {
            **{k: str(v) for k, v in params.items()},
            "api_key": api_key,
            "signature": signature,
        }

        return DirectUploadTicket(
            upload_url=upload_url,
            method="POST",
            fields=fields,
            provider_ref={
                "public_id": path,
                "resource_type": resource_type,
                "folder": folder,
            },
        )

    def finalize_direct_upload(
        self, data: Mapping[str, Any]
    ) -> UploadResult:
        """Persist provider metadata returned by Cloudinary's response."""
        public_id = data.get("public_id") or data.get("provider_file_id")
        if not public_id:
            raise ProviderError(
                "Cloudinary finalize requires `public_id`."
            )
        secure_url = data.get("secure_url") or data.get("url")
        if not secure_url:
            # get_url calls _configure() which ensures proxy is set.
            secure_url = self.get_url(
                public_id,
                resource_type=data.get("resource_type"),
            )
        return UploadResult(
            provider_file_id=public_id,
            url=secure_url,
            metadata={
                "resource_type": data.get("resource_type"),
                "format": data.get("format"),
                "bytes": data.get("bytes"),
                "version": data.get("version"),
            },
        )