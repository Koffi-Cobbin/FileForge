"""Models for FileForge authentication and multi-tenancy.

Three new first-class entities sit above the existing storage layer:

  DeveloperUser  — a human who owns one or more Apps; authenticates via JWT.
  App            — a named integration registered by a DeveloperUser.
                   Replaces the honour-system X-App-Owner string.
  ApiKey         — a hashed secret bound to an App; used by external
                   servers to authenticate File/Credential API calls.

Migration path
--------------
The existing ``File`` and ``StorageCredential`` rows have an ``owner``
CharField.  After migration, that field is back-filled with the App's
``owner_slug`` so all historical data remains queryable under the correct
App without rewriting provider logic.
"""
from __future__ import annotations

import hashlib
import secrets
import string

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone


# ---------------------------------------------------------------------------
# DeveloperUser
# ---------------------------------------------------------------------------

_SLUG_ALPHABET = string.ascii_lowercase + string.digits


class DeveloperUserManager(BaseUserManager):
    def create_user(self, email: str, password: str | None = None, **extra):
        if not email:
            raise ValueError("Email is required")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email: str, password: str, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        return self.create_user(email, password, **extra)


class DeveloperUser(AbstractBaseUser, PermissionsMixin):
    """Custom user model for FileForge developers.

    Email is the login identifier; usernames are not used.
    """

    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=255, blank=True, default="")
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)

    objects = DeveloperUserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    class Meta:
        verbose_name = "Developer"
        verbose_name_plural = "Developers"

    def __str__(self) -> str:
        return self.email


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

def _generate_owner_slug() -> str:
    """Return a compact random slug used as the owner identifier."""
    return "app_" + "".join(secrets.choice(_SLUG_ALPHABET) for _ in range(12))


class App(models.Model):
    """A named integration registered by a DeveloperUser.

    ``owner_slug`` is the value stored in ``File.owner`` and
    ``StorageCredential.owner``.  It is generated once and never changes
    so that historical rows remain correctly scoped.
    """

    developer = models.ForeignKey(
        DeveloperUser,
        on_delete=models.CASCADE,
        related_name="apps",
    )
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    owner_slug = models.CharField(
        max_length=64,
        unique=True,
        default=_generate_owner_slug,
        editable=False,
        db_index=True,
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("developer", "name"),
                name="uniq_developer_app_name",
            )
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.owner_slug})"


# ---------------------------------------------------------------------------
# ApiKey
# ---------------------------------------------------------------------------

_KEY_PREFIX = "ffk_"  # FileForge Key — makes keys recognisable in logs


def _generate_raw_key() -> str:
    """Return a cryptographically random API key string.

    Format: ``ffk_<40 random url-safe chars>``
    Total length: 44 characters — long enough to be brute-force resistant.
    """
    return _KEY_PREFIX + secrets.token_urlsafe(30)


def _hash_key(raw: str) -> str:
    """Return the SHA-256 hex digest of ``raw``."""
    return hashlib.sha256(raw.encode()).hexdigest()


class ApiKey(models.Model):
    """A hashed API key bound to an App.

    The raw key is generated once, shown to the developer exactly once,
    and then discarded — only the SHA-256 hash is stored.  This mirrors
    the GitHub personal-access-token model.

    Lookup at request time:
        1. Extract ``Authorization: Bearer ffk_...`` from the request.
        2. Hash the value with ``_hash_key``.
        3. Query ``ApiKey.objects.get(key_hash=hashed, is_active=True)``.
    """

    app = models.ForeignKey(
        App,
        on_delete=models.CASCADE,
        related_name="api_keys",
    )
    name = models.CharField(
        max_length=255,
        help_text="Human label for this key, e.g. 'production server'.",
    )
    key_hash = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        editable=False,
    )
    key_prefix = models.CharField(
        max_length=12,
        editable=False,
        help_text="First 8 chars of the raw key (safe to display in the UI).",
    )
    is_active = models.BooleanField(default=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Optional expiry. Null means the key never expires.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"{self.name} ({self.key_prefix}…)"

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def create_for_app(cls, app: App, name: str, expires_at=None) -> tuple["ApiKey", str]:
        """Create a new ApiKey for ``app``.

        Returns ``(api_key_instance, raw_key)``.  The caller MUST surface
        ``raw_key`` to the developer immediately — it cannot be recovered later.
        """
        raw = _generate_raw_key()
        key = cls(
            app=app,
            name=name,
            key_hash=_hash_key(raw),
            key_prefix=raw[:8],
            expires_at=expires_at,
        )
        key.save()
        return key, raw

    # ------------------------------------------------------------------
    # Validation helpers
    # ------------------------------------------------------------------

    def is_valid(self) -> bool:
        """Return True if the key is active and not expired."""
        if not self.is_active:
            return False
        if self.expires_at and self.expires_at < timezone.now():
            return False
        return True

    def touch(self) -> None:
        """Update last_used_at without triggering a full model save."""
        ApiKey.objects.filter(pk=self.pk).update(last_used_at=timezone.now())
