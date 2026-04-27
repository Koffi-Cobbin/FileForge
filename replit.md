# FileForge

A pluggable cloud-storage bridge built with Django + Django REST Framework.
External apps register through the `X-App-Owner` header and route file
uploads to one of the registered providers (Google Drive, Cloudinary, or any
custom provider that implements `BaseStorageProvider`).

## Stack

- Python 3.12
- Django 5.1, Django REST Framework
- Django-Q2 (ORM broker, no Redis required) for background tasks
- SQLite (development); ready to swap for Postgres in production
- Gunicorn (production WSGI server)

## Project Layout

| Path | Purpose |
| --- | --- |
| `fileforge/` | Django project (settings, URLs, WSGI/ASGI) |
| `storage/` | DRF app: models, serializers, views, providers, services, tasks |
| `manage.py` | Django management entry point at the repo root |
| `run.sh` | Dev launcher — migrates, starts the Q cluster, runs the dev server on `0.0.0.0:5000` |
| `requirements.txt` | Python dependencies |

## Running on Replit

The `FileForge` workflow runs `./run.sh` and serves the API on port 5000
(webview). The Django dev server binds to `0.0.0.0` and `ALLOWED_HOSTS = ["*"]`
so the Replit preview proxy can reach it.

Useful endpoints (all mounted under `/api/`):

- `GET /` — service description with all endpoint URLs
- `GET /api/health/` — liveness + registered providers
- `GET /api/providers/` — provider capabilities
- `GET|POST /api/credentials/` and `/api/credentials/{id}/`
- `GET|POST /api/files/` and `/api/files/{id}/`
- `POST /api/files/direct-upload/` and `/api/files/direct-upload/complete/`

## Production / Deployment

Configured as a **VM** deployment so the Django-Q worker stays alive
alongside the web server. The production command runs migrations, starts the
Q cluster in the background, and serves the WSGI app with Gunicorn:

```
python manage.py migrate --noinput && python manage.py qcluster &
exec gunicorn --bind 0.0.0.0:5000 --workers 2 fileforge.wsgi:application
```

## Required environment variables (production)

Set these as Replit Secrets before publishing:

- `SESSION_SECRET` — Django `SECRET_KEY`
- `GOOGLE_SERVICE_ACCOUNT_JSON` (or `GOOGLE_SERVICE_ACCOUNT_FILE`) and
  `GOOGLE_DRIVE_FOLDER_ID` — for the Google Drive provider
- `CLOUDINARY_URL` (or `CLOUDINARY_CLOUD_NAME` + `CLOUDINARY_API_KEY` +
  `CLOUDINARY_API_SECRET`) — for the Cloudinary provider

Optional tunables: `FILEFORGE_DEFAULT_MAX_SYNC_SIZE`,
`FILEFORGE_GOOGLE_DRIVE_MAX_SYNC_SIZE`, `FILEFORGE_CLOUDINARY_MAX_SYNC_SIZE`,
`FILEFORGE_MAX_UPLOAD_SIZE`, `FILEFORGE_DEFAULT_OWNER`, `FILEFORGE_Q_WORKERS`.
