## FileForge (Django REST Framework)

A pluggable cloud storage bridge that lets external apps connect multiple
cloud storage providers (Google Drive, Cloudinary) and route each file to a
specific provider via a unified REST API.

- **Location**: `fileforge/`
- **Workflow**: `FileForge` (runs `./fileforge/run.sh`, port 5000)
- **Stack**: Python 3.11, Django 5, Django REST Framework, Django-Q2 (ORM
  broker — PythonAnywhere-compatible), SQLite
- **Run**: `./fileforge/run.sh` (migrates, starts the Q cluster, then the
  Django dev server)

### Architecture

| Layer | Path | Notes |
| --- | --- | --- |
| Provider interface | `storage/providers/base.py` | `BaseStorageProvider` — strict contract |
| Provider registry | `storage/providers/registry.py` | Name → class, plugin-ready |
| Built-in providers | `storage/providers/{google_drive,cloudinary_provider}.py` | |
| Service layer | `storage/services/storage_manager.py` | Single entry point; views never call providers directly |
| Async tasks | `storage/tasks/file_tasks.py` | `process_file_upload`, `cleanup_temp_files` |
| Utilities | `storage/utils/{temp_storage,upload_strategy}.py` | Disk-only temp storage, hybrid threshold helper |
| Models | `storage/models.py` | `File`, `StorageCredential` |
| API | `storage/views.py`, `storage/urls.py` | DRF views mounted at `/api/` |

### Endpoints (mounted at `/api/`)

- `GET /health/` — liveness + registered providers
- `GET /providers/` — registered providers and their capabilities
- `GET /credentials/`, `POST /credentials/` — per-owner credential CRUD
- `GET /credentials/{id}/`, `PATCH/PUT/DELETE` — credential detail
- `POST /files/` — multipart hybrid upload (small files; spawns async task)
- `GET /files/`, `GET /files/{id}/`, `PATCH /files/{id}/`, `DELETE /files/{id}/`
- `POST /files/direct-upload/` — return signed URL + fields for large files
- `POST /files/direct-upload/complete/` — finalize a direct upload

The `X-App-Owner` header identifies the calling app; rows are scoped per
owner. Without the header the owner defaults to `default`.

### Adding a new provider

1. Create `storage/providers/<name>.py` subclassing `BaseStorageProvider`.
2. Register it in `storage/providers/registry.py::register_default_providers`.

No views, serializers, or services need to change.

### Configuration (env vars)

- `FILEFORGE_DEFAULT_MAX_SYNC_SIZE` (default 5 MB)
- `FILEFORGE_GOOGLE_DRIVE_MAX_SYNC_SIZE`, `FILEFORGE_CLOUDINARY_MAX_SYNC_SIZE`
- `FILEFORGE_MAX_UPLOAD_SIZE` (hard limit, default 100 MB)
- `GOOGLE_SERVICE_ACCOUNT_JSON` or `GOOGLE_SERVICE_ACCOUNT_FILE`,
  `GOOGLE_DRIVE_FOLDER_ID`
- `CLOUDINARY_URL`, or `CLOUDINARY_CLOUD_NAME` + `CLOUDINARY_API_KEY` +
  `CLOUDINARY_API_SECRET`
- Per-owner overrides live in the `StorageCredential` model and win over env
  defaults.
