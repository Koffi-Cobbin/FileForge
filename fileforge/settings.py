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
    # staticfiles must come BEFORE cloudinary_storage so Django's own
    # static/media handling is not replaced by Cloudinary's backend.
    'django.contrib.staticfiles',

    # cloudinary must be listed before cloudinary_storage.
    'cloudinary',
    # cloudinary_storage is present for the SDK's benefit; we explicitly
    # keep DEFAULT_FILE_STORAGE and STATICFILES_STORAGE as Django's
    # defaults below so it never takes over static/media serving.
    'cloudinary_storage',

    "corsheaders",
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "django_q",
    "fileforge_auth",
    "storage",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "fileforge.urls"

# ---------------------------------------------------------------------------
# Custom user model
# ---------------------------------------------------------------------------
AUTH_USER_MODEL = "fileforge_auth.DeveloperUser"

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

# ---------------------------------------------------------------------------
# Static & media files — always use Django's local backends.
# Explicitly set here so cloudinary_storage never silently takes over,
# regardless of its own auto-configuration behaviour.
# ---------------------------------------------------------------------------
STATIC_URL = '/static/'
STATICFILES_STORAGE = 'django.contrib.staticfiles.storage.StaticFilesStorage'

if ON_PYTHONANYWHERE:
    STATIC_ROOT = os.path.join(BASE_DIR, 'static')
else:
    STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = []

MEDIA_URL = '/media/'
DEFAULT_FILE_STORAGE = 'django.core.files.storage.FileSystemStorage'

if ON_PYTHONANYWHERE:
    MEDIA_ROOT = os.path.join(BASE_DIR, 'media')
else:
    MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# Django REST Framework
# ---------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_PERMISSION_CLASSES": [
        # Storage API requires a valid API key by default.
        # Management (auth) endpoints override this per-view.
        "fileforge_auth.permissions.IsAuthenticatedApp",
    ],
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "fileforge_auth.authentication.ApiKeyAuthentication",
        "rest_framework_simplejwt.authentication.JWTAuthentication",
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

# ---------------------------------------------------------------------------
# SimpleJWT
# ---------------------------------------------------------------------------
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(
        minutes=int(os.environ.get("JWT_ACCESS_MINUTES", 30))
    ),
    "REFRESH_TOKEN_LIFETIME": timedelta(
        days=int(os.environ.get("JWT_REFRESH_DAYS", 7))
    ),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
    "ALGORITHM": "HS256",
    "SIGNING_KEY": SECRET_KEY,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
    "AUTH_TOKEN_CLASSES": ("rest_framework_simplejwt.tokens.AccessToken",),
    # Return the developer's email in the token response for convenience.
    "TOKEN_OBTAIN_SERIALIZER": "fileforge_auth.token_serializers.EmailTokenObtainPairSerializer",
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
# Cloudinary SDK configuration
#
# Keys follow the Cloudinary Python SDK convention (uppercase).
# CLOUDINARY_URL, if set, takes priority over individual keys.
#
# api_proxy is required on PythonAnywhere free accounts where outbound
# connections must go through their HTTP proxy.
# ---------------------------------------------------------------------------
_cloudinary_proxy = os.environ.get(
    "CLOUDINARY_API_PROXY",
    "http://proxy.server:3128" if ON_PYTHONANYWHERE else "",
)

CLOUDINARY_STORAGE = {
    # Credentials — CLOUDINARY_URL wins if present.
    'CLOUD_NAME': os.environ.get('CLOUDINARY_CLOUD_NAME', ''),
    'API_KEY': os.environ.get('CLOUDINARY_API_KEY', ''),
    'API_SECRET': os.environ.get('CLOUDINARY_API_SECRET', ''),
    # Proxy — only injected when non-empty so local/Replit runs are unaffected.
    **({'API_PROXY': _cloudinary_proxy} if _cloudinary_proxy else {}),
    # Tell cloudinary_storage to use HTTPS everywhere.
    'SECURE': True,
    # Never let cloudinary_storage serve static or media files; FileForge
    # handles uploads directly through its provider layer.
    'MEDIA_TAG': 'fileforge_media',
    'INVALID_VIDEO_ERROR_MESSAGE': 'Please upload a valid video file.',
    'EXCLUDE_DELETE_ORPHANED_MEDIA_UNDER_FOLDER': '',
    'SAVE_FILES_ON_MODEL_SAVE': False,
}

# ---------------------------------------------------------------------------
# FileForge configuration
# ---------------------------------------------------------------------------
FILEFORGE_TEMP_DIR = Path(
    os.environ.get("FILEFORGE_TEMP_DIR", BASE_DIR / "tmp_uploads")
)
FILEFORGE_TEMP_DIR.mkdir(parents=True, exist_ok=True)

FILEFORGE_MAX_UPLOAD_SIZE = int(
    os.environ.get("FILEFORGE_MAX_UPLOAD_SIZE", 100 * 1024 * 1024)
)

FILEFORGE_DEFAULT_MAX_SYNC_SIZE = int(
    os.environ.get("FILEFORGE_DEFAULT_MAX_SYNC_SIZE", 5 * 1024 * 1024)
)

FILEFORGE_PROVIDER_MAX_SYNC_SIZE = {
    "google_drive": int(
        os.environ.get("FILEFORGE_GOOGLE_DRIVE_MAX_SYNC_SIZE", 5 * 1024 * 1024)
    ),
    "cloudinary": int(
        os.environ.get("FILEFORGE_CLOUDINARY_MAX_SYNC_SIZE", 10 * 1024 * 1024)
    ),
}

FILEFORGE_PROVIDER_ENV_CREDENTIALS = {
    "google_drive": {
        "service_account_json": os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON"),
        "service_account_file": os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE"),
        "folder_id": os.environ.get("GOOGLE_DRIVE_FOLDER_ID"),
    },
    "cloudinary": {
        "cloud_name": os.environ.get("CLOUDINARY_CLOUD_NAME"),
        "api_key": os.environ.get("CLOUDINARY_API_KEY"),
        "api_secret": os.environ.get("CLOUDINARY_API_SECRET"),
        "url": os.environ.get("CLOUDINARY_URL"),
        # Proxy for PythonAnywhere free tier — empty string means "no proxy"
        # and the provider skips injecting it into cloudinary.config().
        "api_proxy": _cloudinary_proxy,
    },
}

# Kept for backward-compat — new code reads owner from request.auth.app.owner_slug
FILEFORGE_OWNER_HEADER = "X-App-Owner"
FILEFORGE_DEFAULT_OWNER = os.environ.get("FILEFORGE_DEFAULT_OWNER", "default")

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
        "fileforge_auth": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}