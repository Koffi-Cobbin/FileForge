"""Tests for the fileforge_auth app.

Covers:
  - Model helpers (ApiKey.create_for_app, is_valid, touch)
  - ApiKeyAuthentication backend
  - IsAuthenticatedApp / IsAuthenticatedDeveloper permissions
  - All auth management views (register, token, me, apps, keys)
  - Storage views honouring the new auth (owner resolution, 401 without key)
"""
from __future__ import annotations

import hashlib
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from fileforge_auth.models import ApiKey, App, DeveloperUser, _hash_key, _KEY_PREFIX
from storage.models import File, FileStatus, StorageCredential


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_developer(email="dev@example.com", password="StrongPass123!"):
    return DeveloperUser.objects.create_user(email=email, password=password)


def make_app(developer, name="Test App"):
    return App.objects.create(developer=developer, name=name)


def make_api_key(app, name="default key"):
    key, raw = ApiKey.create_for_app(app=app, name=name)
    return key, raw


def bearer(raw_key):
    return {"HTTP_AUTHORIZATION": f"Bearer {raw_key}"}


def jwt_headers(client, email, password):
    """Obtain a JWT access token and return headers dict."""
    resp = client.post(
        reverse("auth-token"),
        {"email": email, "password": password},
        content_type="application/json",
    )
    assert resp.status_code == 200, resp.data
    return {"HTTP_AUTHORIZATION": f"Bearer {resp.data['access']}"}


# ===========================================================================
# Model tests
# ===========================================================================

class ApiKeyModelTests(TestCase):
    def setUp(self):
        self.dev = make_developer()
        self.app = make_app(self.dev)

    def test_raw_key_has_prefix(self):
        _, raw = ApiKey.create_for_app(self.app, "prod")
        self.assertTrue(raw.startswith(_KEY_PREFIX))

    def test_hash_stored_not_raw(self):
        key, raw = ApiKey.create_for_app(self.app, "prod")
        self.assertEqual(key.key_hash, _hash_key(raw))
        self.assertNotEqual(key.key_hash, raw)

    def test_key_prefix_saved(self):
        key, raw = ApiKey.create_for_app(self.app, "prod")
        self.assertEqual(key.key_prefix, raw[:8])

    def test_is_valid_active_key(self):
        key, _ = ApiKey.create_for_app(self.app, "prod")
        self.assertTrue(key.is_valid())

    def test_is_valid_inactive(self):
        key, _ = ApiKey.create_for_app(self.app, "prod")
        key.is_active = False
        self.assertFalse(key.is_valid())

    def test_is_valid_expired(self):
        key, _ = ApiKey.create_for_app(self.app, "prod")
        key.expires_at = timezone.now() - timedelta(seconds=1)
        self.assertFalse(key.is_valid())

    def test_is_valid_not_yet_expired(self):
        key, _ = ApiKey.create_for_app(self.app, "prod")
        key.expires_at = timezone.now() + timedelta(hours=1)
        self.assertTrue(key.is_valid())

    def test_touch_updates_last_used_at(self):
        key, _ = ApiKey.create_for_app(self.app, "prod")
        self.assertIsNone(key.last_used_at)
        key.touch()
        key.refresh_from_db()
        self.assertIsNotNone(key.last_used_at)

    def test_unique_hashes(self):
        _, r1 = ApiKey.create_for_app(self.app, "key1")
        _, r2 = ApiKey.create_for_app(self.app, "key2")
        self.assertNotEqual(r1, r2)

    def test_app_owner_slug_generated(self):
        self.assertTrue(self.app.owner_slug.startswith("app_"))
        self.assertEqual(len(self.app.owner_slug), 16)  # "app_" + 12 chars


# ===========================================================================
# Authentication backend
# ===========================================================================

class ApiKeyAuthenticationTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.dev = make_developer()
        self.app = make_app(self.dev)
        self.key, self.raw = make_api_key(self.app)

    def test_valid_key_authenticates(self):
        resp = self.client.get(
            reverse("file-list"), **bearer(self.raw)
        )
        # 200 means auth passed (empty list is fine)
        self.assertEqual(resp.status_code, 200)

    def test_missing_auth_header_returns_403(self):
        resp = self.client.get(reverse("file-list"))
        self.assertIn(resp.status_code, [401, 403])

    def test_wrong_prefix_returns_403(self):
        resp = self.client.get(
            reverse("file-list"),
            HTTP_AUTHORIZATION="Bearer not_a_fileforge_key_xyz"
        )
        self.assertIn(resp.status_code, [401, 403])

    def test_revoked_key_returns_401(self):
        self.key.is_active = False
        self.key.save()
        resp = self.client.get(reverse("file-list"), **bearer(self.raw))
        self.assertEqual(resp.status_code, 401)

    def test_expired_key_returns_401(self):
        self.key.expires_at = timezone.now() - timedelta(seconds=1)
        self.key.save()
        resp = self.client.get(reverse("file-list"), **bearer(self.raw))
        self.assertEqual(resp.status_code, 401)

    def test_inactive_app_returns_401(self):
        self.app.is_active = False
        self.app.save()
        resp = self.client.get(reverse("file-list"), **bearer(self.raw))
        self.assertEqual(resp.status_code, 401)

    def test_inactive_developer_returns_401(self):
        self.dev.is_active = False
        self.dev.save()
        resp = self.client.get(reverse("file-list"), **bearer(self.raw))
        self.assertEqual(resp.status_code, 401)

    def test_last_used_updated_on_valid_auth(self):
        self.assertIsNone(self.key.last_used_at)
        self.client.get(reverse("file-list"), **bearer(self.raw))
        self.key.refresh_from_db()
        self.assertIsNotNone(self.key.last_used_at)


# ===========================================================================
# Registration & JWT views
# ===========================================================================

class RegistrationTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_register_success(self):
        resp = self.client.post(
            reverse("auth-register"),
            {"email": "new@example.com", "full_name": "New Dev",
             "password": "StrongPass123!", "password_confirm": "StrongPass123!"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["email"], "new@example.com")
        self.assertNotIn("password", resp.data)

    def test_register_password_mismatch(self):
        resp = self.client.post(
            reverse("auth-register"),
            {"email": "x@example.com", "password": "StrongPass123!",
             "password_confirm": "Different1!"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_register_duplicate_email(self):
        make_developer(email="dup@example.com")
        resp = self.client.post(
            reverse("auth-register"),
            {"email": "dup@example.com", "password": "StrongPass123!",
             "password_confirm": "StrongPass123!"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_token_obtain(self):
        make_developer(email="login@example.com", password="StrongPass123!")
        resp = self.client.post(
            reverse("auth-token"),
            {"email": "login@example.com", "password": "StrongPass123!"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("access", resp.data)
        self.assertIn("refresh", resp.data)
        self.assertEqual(resp.data["email"], "login@example.com")

    def test_token_wrong_password(self):
        make_developer(email="login2@example.com", password="StrongPass123!")
        resp = self.client.post(
            reverse("auth-token"),
            {"email": "login2@example.com", "password": "WrongPassword"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 401)


# ===========================================================================
# Me / profile views
# ===========================================================================

class MeViewTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.dev = make_developer(email="me@example.com", password="StrongPass123!")
        self.headers = jwt_headers(self.client, "me@example.com", "StrongPass123!")

    def test_get_me(self):
        resp = self.client.get(reverse("auth-me"), **self.headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["email"], "me@example.com")

    def test_patch_full_name(self):
        resp = self.client.patch(
            reverse("auth-me"),
            {"full_name": "Updated Name"},
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["full_name"], "Updated Name")

    def test_me_requires_jwt(self):
        resp = self.client.get(reverse("auth-me"))
        self.assertIn(resp.status_code, [401, 403])

    def test_me_rejects_api_key_auth(self):
        app = make_app(self.dev)
        _, raw = make_api_key(app)
        resp = self.client.get(reverse("auth-me"), **bearer(raw))
        self.assertIn(resp.status_code, [401, 403])

    def test_change_password_success(self):
        resp = self.client.post(
            reverse("auth-change-password"),
            {"current_password": "StrongPass123!", "new_password": "NewStrong456!"},
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(resp.status_code, 200)
        self.dev.refresh_from_db()
        self.assertTrue(self.dev.check_password("NewStrong456!"))

    def test_change_password_wrong_current(self):
        resp = self.client.post(
            reverse("auth-change-password"),
            {"current_password": "wrong", "new_password": "NewStrong456!"},
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(resp.status_code, 400)


# ===========================================================================
# App CRUD views
# ===========================================================================

class AppViewTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.dev = make_developer(email="appdev@example.com", password="StrongPass123!")
        self.headers = jwt_headers(self.client, "appdev@example.com", "StrongPass123!")

    def test_create_app(self):
        resp = self.client.post(
            reverse("auth-app-list"),
            {"name": "My App", "description": "Test app"},
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["name"], "My App")
        self.assertTrue(resp.data["owner_slug"].startswith("app_"))

    def test_list_apps_scoped_to_developer(self):
        other_dev = make_developer(email="other@example.com")
        other_app = make_app(other_dev, "Other App")
        make_app(self.dev, "My App")

        resp = self.client.get(reverse("auth-app-list"), **self.headers)
        self.assertEqual(resp.status_code, 200)
        names = [a["name"] for a in resp.data]
        self.assertIn("My App", names)
        self.assertNotIn("Other App", names)

    def test_duplicate_app_name_rejected(self):
        make_app(self.dev, "Unique App")
        resp = self.client.post(
            reverse("auth-app-list"),
            {"name": "Unique App"},
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(resp.status_code, 400)

    def test_get_app_detail(self):
        app = make_app(self.dev)
        resp = self.client.get(
            reverse("auth-app-detail", kwargs={"pk": app.pk}),
            **self.headers,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["id"], app.pk)

    def test_cannot_access_other_developers_app(self):
        other_dev = make_developer(email="other2@example.com")
        other_app = make_app(other_dev, "Foreign App")
        resp = self.client.get(
            reverse("auth-app-detail", kwargs={"pk": other_app.pk}),
            **self.headers,
        )
        self.assertEqual(resp.status_code, 404)

    def test_patch_app(self):
        app = make_app(self.dev)
        resp = self.client.patch(
            reverse("auth-app-detail", kwargs={"pk": app.pk}),
            {"description": "Updated desc"},
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["description"], "Updated desc")

    def test_delete_app(self):
        app = make_app(self.dev)
        resp = self.client.delete(
            reverse("auth-app-detail", kwargs={"pk": app.pk}),
            **self.headers,
        )
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(App.objects.filter(pk=app.pk).exists())

    def test_owner_slug_immutable(self):
        app = make_app(self.dev)
        original_slug = app.owner_slug
        self.client.patch(
            reverse("auth-app-detail", kwargs={"pk": app.pk}),
            {"owner_slug": "tampered"},
            content_type="application/json",
            **self.headers,
        )
        app.refresh_from_db()
        self.assertEqual(app.owner_slug, original_slug)


# ===========================================================================
# API Key management views
# ===========================================================================

class ApiKeyViewTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.dev = make_developer(email="keydev@example.com", password="StrongPass123!")
        self.headers = jwt_headers(self.client, "keydev@example.com", "StrongPass123!")
        self.app = make_app(self.dev, "Key Test App")

    def _key_list_url(self):
        return reverse("auth-key-list", kwargs={"app_id": self.app.pk})

    def _revoke_url(self, key_id):
        return reverse("auth-key-revoke", kwargs={"app_id": self.app.pk, "key_id": key_id})

    def test_create_key_returns_raw_key(self):
        resp = self.client.post(
            self._key_list_url(),
            {"name": "prod server"},
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(resp.status_code, 201)
        self.assertIn("raw_key", resp.data)
        self.assertTrue(resp.data["raw_key"].startswith(_KEY_PREFIX))

    def test_raw_key_not_in_list_response(self):
        make_api_key(self.app, "server1")
        resp = self.client.get(self._key_list_url(), **self.headers)
        self.assertEqual(resp.status_code, 200)
        for key_data in resp.data:
            self.assertNotIn("raw_key", key_data)

    def test_key_prefix_visible_in_list(self):
        key, raw = make_api_key(self.app, "server1")
        resp = self.client.get(self._key_list_url(), **self.headers)
        prefixes = [k["key_prefix"] for k in resp.data]
        self.assertIn(raw[:8], prefixes)

    def test_revoke_key(self):
        key, _ = make_api_key(self.app, "to revoke")
        resp = self.client.post(self._revoke_url(key.pk), **self.headers)
        self.assertEqual(resp.status_code, 200)
        key.refresh_from_db()
        self.assertFalse(key.is_active)

    def test_revoked_key_cannot_authenticate(self):
        key, raw = make_api_key(self.app, "to revoke")
        self.client.post(self._revoke_url(key.pk), **self.headers)
        resp = self.client.get(reverse("file-list"), **bearer(raw))
        self.assertEqual(resp.status_code, 401)

    def test_create_key_with_expiry(self):
        future = (timezone.now() + timedelta(days=30)).isoformat()
        resp = self.client.post(
            self._key_list_url(),
            {"name": "expiring key", "expires_at": future},
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(resp.status_code, 201)
        self.assertIsNotNone(resp.data["expires_at"])

    def test_cannot_manage_keys_of_other_developers_app(self):
        other_dev = make_developer(email="other3@example.com")
        other_app = make_app(other_dev, "Foreign App")
        url = reverse("auth-key-list", kwargs={"app_id": other_app.pk})
        resp = self.client.get(url, **self.headers)
        self.assertEqual(resp.status_code, 404)

    def test_api_key_count_in_app_response(self):
        make_api_key(self.app, "k1")
        make_api_key(self.app, "k2")
        resp = self.client.get(
            reverse("auth-app-detail", kwargs={"pk": self.app.pk}),
            **self.headers,
        )
        self.assertEqual(resp.data["api_key_count"], 2)


# ===========================================================================
# Storage API owner resolution
# ===========================================================================

class OwnerResolutionTests(TestCase):
    """Files are scoped to the API key's app owner_slug."""

    def setUp(self):
        self.client = APIClient()
        self.dev = make_developer(email="owner@example.com", password="StrongPass123!")
        self.app = make_app(self.dev, "Owner Test")
        self.key, self.raw = make_api_key(self.app)

    def test_files_scoped_to_app_owner_slug(self):
        # Create a file belonging to this app's owner slug.
        File.objects.create(
            name="mine.txt",
            provider="cloudinary",
            owner=self.app.owner_slug,
            status=FileStatus.COMPLETED,
        )
        # Create a file belonging to a different owner.
        File.objects.create(
            name="theirs.txt",
            provider="cloudinary",
            owner="app_someoneelsexxxx",
            status=FileStatus.COMPLETED,
        )
        resp = self.client.get(reverse("file-list"), **bearer(self.raw))
        self.assertEqual(resp.status_code, 200)
        names = [f["name"] for f in resp.data]
        self.assertIn("mine.txt", names)
        self.assertNotIn("theirs.txt", names)

    def test_two_apps_cannot_see_each_others_files(self):
        app2 = make_app(self.dev, "Second App")
        _, raw2 = make_api_key(app2, "key2")

        File.objects.create(
            name="app1file.txt", provider="cloudinary",
            owner=self.app.owner_slug, status=FileStatus.COMPLETED,
        )
        File.objects.create(
            name="app2file.txt", provider="cloudinary",
            owner=app2.owner_slug, status=FileStatus.COMPLETED,
        )

        resp1 = self.client.get(reverse("file-list"), **bearer(self.raw))
        resp2 = self.client.get(reverse("file-list"), **bearer(raw2))

        self.assertIn("app1file.txt", [f["name"] for f in resp1.data])
        self.assertNotIn("app2file.txt", [f["name"] for f in resp1.data])
        self.assertIn("app2file.txt", [f["name"] for f in resp2.data])
        self.assertNotIn("app1file.txt", [f["name"] for f in resp2.data])

    def test_file_detail_404_for_wrong_owner(self):
        f = File.objects.create(
            name="secret.txt", provider="cloudinary",
            owner="app_someoneelsexxxx", status=FileStatus.COMPLETED,
        )
        resp = self.client.get(
            reverse("file-detail", kwargs={"pk": f.pk}),
            **bearer(self.raw),
        )
        self.assertEqual(resp.status_code, 404)

    def test_credentials_scoped_to_app(self):
        StorageCredential.objects.create(
            owner=self.app.owner_slug,
            provider="cloudinary",
            credentials={"cloud_name": "mine"},
        )
        StorageCredential.objects.create(
            owner="app_someoneelsexxxx",
            provider="cloudinary",
            credentials={"cloud_name": "theirs"},
        )
        resp = self.client.get(reverse("credential-list"), **bearer(self.raw))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data), 1)
        self.assertEqual(resp.data[0]["credentials"]["cloud_name"], "mine")


# ===========================================================================
# Health endpoint (public)
# ===========================================================================

class HealthViewTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_health_no_auth_required(self):
        resp = self.client.get(reverse("health"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["status"], "ok")
        self.assertIn("providers", resp.data)


# ===========================================================================
# Upload mode (sync / async)
# ===========================================================================

class UploadModeTests(TestCase):
    """POST /api/files/ ``mode`` field — sync vs async behaviour."""

    def setUp(self):
        self.client = APIClient()
        self.dev = make_developer(email="uploader@example.com", password="StrongPass123!")
        self.app = make_app(self.dev, "Upload Mode App")
        self.key, self.raw = make_api_key(self.app)

    def _small_file(self, name="test.txt", content=b"hello"):
        from django.core.files.uploadedfile import SimpleUploadedFile
        return SimpleUploadedFile(name, content, content_type="text/plain")

    # ------------------------------------------------------------------
    # async mode (default)
    # ------------------------------------------------------------------

    @patch("storage.views.async_task")
    def test_async_mode_returns_202_pending(self, mock_task):
        """Default async mode queues a task and returns 202 with status pending."""
        resp = self.client.post(
            reverse("file-list"),
            {"file": self._small_file(), "provider": "cloudinary", "mode": "async"},
            format="multipart",
            **bearer(self.raw),
        )
        self.assertEqual(resp.status_code, 202)
        self.assertEqual(resp.data["status"], "pending")
        self.assertEqual(resp.data["upload_strategy"], "async")
        mock_task.assert_called_once()

    @patch("storage.views.async_task")
    def test_default_mode_is_async(self, mock_task):
        """Omitting ``mode`` behaves identically to ``mode='async'``."""
        resp = self.client.post(
            reverse("file-list"),
            {"file": self._small_file(), "provider": "cloudinary"},
            format="multipart",
            **bearer(self.raw),
        )
        self.assertEqual(resp.status_code, 202)
        self.assertEqual(resp.data["status"], "pending")
        mock_task.assert_called_once()

    # ------------------------------------------------------------------
    # sync mode — success path
    # ------------------------------------------------------------------

    @patch("storage.views.process_file_upload")
    def test_sync_mode_returns_200_completed(self, mock_upload):
        """Sync mode calls process_file_upload inline and returns 200."""
        def _fake_upload(file_id):
            File.objects.filter(pk=file_id).update(
                status=FileStatus.COMPLETED,
                provider_file_id="remote-id-123",
                url="https://example.com/file.txt",
                temp_path="",
            )
        mock_upload.side_effect = _fake_upload

        resp = self.client.post(
            reverse("file-list"),
            {"file": self._small_file(), "provider": "cloudinary", "mode": "sync"},
            format="multipart",
            **bearer(self.raw),
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["status"], "completed")
        self.assertEqual(resp.data["provider_file_id"], "remote-id-123")
        self.assertEqual(resp.data["upload_strategy"], "sync")
        mock_upload.assert_called_once()

    @patch("storage.views.process_file_upload")
    def test_sync_mode_no_polling_needed(self, mock_upload):
        """A sync upload response contains a final status — no follow-up GET needed."""
        def _fake_upload(file_id):
            File.objects.filter(pk=file_id).update(
                status=FileStatus.COMPLETED,
                provider_file_id="xyz",
                url="https://example.com/xyz",
                temp_path="",
            )
        mock_upload.side_effect = _fake_upload

        resp = self.client.post(
            reverse("file-list"),
            {"file": self._small_file(), "provider": "cloudinary", "mode": "sync"},
            format="multipart",
            **bearer(self.raw),
        )
        # Status is already terminal — caller doesn't need to poll.
        self.assertIn(resp.data["status"], ["completed", "failed"])

    # ------------------------------------------------------------------
    # sync mode — failure path
    # ------------------------------------------------------------------

    @patch("storage.views.process_file_upload")
    def test_sync_mode_provider_failure_returns_502(self, mock_upload):
        """When the provider fails in sync mode the view returns 502 with detail."""
        def _fake_failed_upload(file_id):
            File.objects.filter(pk=file_id).update(
                status=FileStatus.FAILED,
                error_message="Cloudinary credentials invalid.",
                temp_path="",
            )
        mock_upload.side_effect = _fake_failed_upload

        resp = self.client.post(
            reverse("file-list"),
            {"file": self._small_file(), "provider": "cloudinary", "mode": "sync"},
            format="multipart",
            **bearer(self.raw),
        )
        self.assertEqual(resp.status_code, 502)
        self.assertIn("detail", resp.data)
        self.assertEqual(resp.data["detail"], "Cloudinary credentials invalid.")
        # The file record is still accessible in the response body.
        self.assertEqual(resp.data["file"]["status"], "failed")

    @patch("storage.views.process_file_upload")
    def test_sync_failure_file_record_persisted(self, mock_upload):
        """Even on sync failure the File row exists and is queryable."""
        def _fake_failed_upload(file_id):
            File.objects.filter(pk=file_id).update(
                status=FileStatus.FAILED,
                error_message="Network error.",
                temp_path="",
            )
        mock_upload.side_effect = _fake_failed_upload

        resp = self.client.post(
            reverse("file-list"),
            {"file": self._small_file(), "provider": "cloudinary", "mode": "sync"},
            format="multipart",
            **bearer(self.raw),
        )
        self.assertEqual(resp.status_code, 502)
        file_id = resp.data["file"]["id"]
        detail_resp = self.client.get(
            reverse("file-detail", kwargs={"pk": file_id}),
            **bearer(self.raw),
        )
        self.assertEqual(detail_resp.status_code, 200)
        self.assertEqual(detail_resp.data["status"], "failed")

    # ------------------------------------------------------------------
    # Invalid mode value
    # ------------------------------------------------------------------

    def test_invalid_mode_returns_400(self):
        """An unrecognised mode value is rejected at the serializer level."""
        resp = self.client.post(
            reverse("file-list"),
            {"file": self._small_file(), "provider": "cloudinary", "mode": "turbo"},
            format="multipart",
            **bearer(self.raw),
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("mode", resp.data)

    # ------------------------------------------------------------------
    # upload_strategy field reflects chosen mode
    # ------------------------------------------------------------------

    @patch("storage.views.async_task")
    def test_upload_strategy_reflects_async_mode(self, mock_task):
        resp = self.client.post(
            reverse("file-list"),
            {"file": self._small_file(), "provider": "cloudinary", "mode": "async"},
            format="multipart",
            **bearer(self.raw),
        )
        self.assertEqual(resp.data["upload_strategy"], "async")

    @patch("storage.views.process_file_upload")
    def test_upload_strategy_reflects_sync_mode(self, mock_upload):
        def _complete(file_id):
            File.objects.filter(pk=file_id).update(
                status=FileStatus.COMPLETED, provider_file_id="x", temp_path=""
            )
        mock_upload.side_effect = _complete

        resp = self.client.post(
            reverse("file-list"),
            {"file": self._small_file(), "provider": "cloudinary", "mode": "sync"},
            format="multipart",
            **bearer(self.raw),
        )
        self.assertEqual(resp.data["upload_strategy"], "sync")