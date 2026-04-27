"""Django settings for FileForge."""
from __future__ import annotations

import os
from pathlib import Path
from datetime import timedelta
from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(os.path.join(BASE_DIR, '.env'))

SECRET_KEY = os.environ.get(
    "SESSION_SECRET",
    "django-insecure-dev-only-key-do-not-use-in-production",
)

DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"

# Detect if running on PythonAnywhere
ON_PYTHONANYWHERE = 'PYTHONANYWHERE_DOMAIN' in os.environ or 'fileforge1.pythonanywhere.com' in os.environ.get('ALLOWED_HOSTS', '')

# Allowed hosts configuration
if ON_PYTHONANYWHERE or not DEBUG:
    ALLOWED_HOSTS = ['fileforge1.pythonanywhere.com', 'www.fileforge1.pythonanywhere.com']
else:
    ALLOWED_HOSTS = ['localhost', '127.0.0.1', '*']

CSRF_TRUSTED_ORIGINS = [
    'https://fileforge1.pythonanywhere.com',
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:5000",
    "http://127.0.0.1:5000"
    "https://*.replit.dev",
    "https://*.replit.app",
    "https://*.repl.co",
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "django_q",
    "storage",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "fileforge.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "fileforge.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = '/static/'

if ON_PYTHONANYWHERE:
    STATIC_ROOT = os.path.join(BASE_DIR, 'static')
else:
    STATIC_ROOT = BASE_DIR / 'staticfiles'

STATICFILES_DIRS = []

# Media files configuration
MEDIA_URL = '/media/'

if ON_PYTHONANYWHERE:
    MEDIA_ROOT = os.path.join(BASE_DIR, 'media')
else:
    MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.AllowAny",
    ],
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
        "rest_framework.parsers.MultiPartParser",
        "rest_framework.parsers.FormParser",
    ],
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
    ],
}

# CORS settings
if DEBUG:
    CORS_ALLOW_ALL_ORIGINS = True
else:
    CORS_ALLOWED_ORIGINS = [
        'https://fileforge1.pythonanywhere.com',
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5000",
        "http://127.0.0.1:5000"
    ]

CORS_ALLOW_CREDENTIALS = True

# ---------------------------------------------------------------------------
# FileForge configuration
# ---------------------------------------------------------------------------

FILEFORGE_TEMP_DIR = Path(
    os.environ.get("FILEFORGE_TEMP_DIR", BASE_DIR / "tmp_uploads")
)
FILEFORGE_TEMP_DIR.mkdir(parents=True, exist_ok=True)

# Hard upload limit (bytes) enforced at the API layer.
FILEFORGE_MAX_UPLOAD_SIZE = int(
    os.environ.get("FILEFORGE_MAX_UPLOAD_SIZE", 100 * 1024 * 1024)  # 100 MB
)

# Default sync threshold. Files at or below this size go through the async
# backend upload path; larger files MUST use the direct upload flow.
FILEFORGE_DEFAULT_MAX_SYNC_SIZE = int(
    os.environ.get("FILEFORGE_DEFAULT_MAX_SYNC_SIZE", 5 * 1024 * 1024)  # 5 MB
)

# Per-provider overrides. Resolved by `utils.upload_strategy`.
FILEFORGE_PROVIDER_MAX_SYNC_SIZE = {
    "google_drive": int(
        os.environ.get(
            "FILEFORGE_GOOGLE_DRIVE_MAX_SYNC_SIZE", 5 * 1024 * 1024
        )
    ),
    "cloudinary": int(
        os.environ.get(
            "FILEFORGE_CLOUDINARY_MAX_SYNC_SIZE", 10 * 1024 * 1024
        )
    ),
}

# Default credentials sourced from environment variables. These are merged with
# (and overridden by) per-owner credentials stored in StorageCredential.
FILEFORGE_PROVIDER_ENV_CREDENTIALS = {
    "google_drive": {
        "service_account_json": os.environ.get(
            "GOOGLE_SERVICE_ACCOUNT_JSON"
        ),
        "service_account_file": os.environ.get(
            "GOOGLE_SERVICE_ACCOUNT_FILE"
        ),
        "folder_id": os.environ.get("GOOGLE_DRIVE_FOLDER_ID"),
    },
    "cloudinary": {
        "cloud_name": os.environ.get("CLOUDINARY_CLOUD_NAME"),
        "api_key": os.environ.get("CLOUDINARY_API_KEY"),
        "api_secret": os.environ.get("CLOUDINARY_API_SECRET"),
        "url": os.environ.get("CLOUDINARY_URL"),
    },
}

# Header used by external apps to identify themselves. The value is stored on
# StorageCredential.owner and on File.owner so credentials are injected per
# request without requiring a full auth system in this MVP.
FILEFORGE_OWNER_HEADER = "X-App-Owner"
FILEFORGE_DEFAULT_OWNER = os.environ.get("FILEFORGE_DEFAULT_OWNER", "default")

# Django-Q2 (PythonAnywhere-compatible). Uses the ORM broker so we don't need
# Redis or a separate process supervisor in development.
Q_CLUSTER = {
    "name": "fileforge",
    "workers": int(os.environ.get("FILEFORGE_Q_WORKERS", 2)),
    "timeout": 600,
    "retry": 660,
    "queue_limit": 50,
    "bulk": 1,
    "orm": "default",
    "sync": os.environ.get("FILEFORGE_Q_SYNC", "0") == "1",
    "save_limit": 250,
    "catch_up": False,
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "simple": {"format": "[%(asctime)s] %(levelname)s %(name)s: %(message)s"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "simple",
        },
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "fileforge": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "storage": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}
