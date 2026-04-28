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

---

### Sample Requests & Responses

#### `GET /` — Service description

```http
GET / HTTP/1.1
Host: localhost:5000
```

```json
{
  "service": "FileForge",
  "description": "Pluggable cloud storage bridge",
  "endpoints": {
    "files_list_create": "/api/files/",
    "file_detail": "/api/files/{id}/",
    "direct_upload_init": "/api/files/direct-upload/",
    "direct_upload_complete": "/api/files/direct-upload/complete/",
    "providers": "/api/providers/",
    "credentials": "/api/credentials/",
    "health": "/api/health/"
  }
}
```

---

#### `GET /api/health/` — Liveness probe

```http
GET /api/health/ HTTP/1.1
Host: localhost:5000
```

```json
{
  "status": "ok",
  "providers": ["cloudinary", "google_drive"]
}
```

---

#### `GET /api/providers/` — List providers and capabilities

```http
GET /api/providers/ HTTP/1.1
Host: localhost:5000
```

```json
{
  "providers": [
    {
      "name": "cloudinary",
      "supports_direct_upload": true
    },
    {
      "name": "google_drive",
      "supports_direct_upload": true
    }
  ]
}
```

---

#### `GET /api/credentials/` — List credentials for an owner

```http
GET /api/credentials/ HTTP/1.1
Host: localhost:5000
X-App-Owner: my-app
```

```json
[
  {
    "id": 1,
    "owner": "my-app",
    "provider": "cloudinary",
    "credentials": {
      "cloud_name": "my-cloud",
      "api_key": "123456789012345",
      "api_secret": "••••••••••••••••••••••••"
    },
    "is_default": true,
    "created_at": "2026-04-01T10:00:00Z",
    "updated_at": "2026-04-01T10:00:00Z"
  }
]
```

---

#### `POST /api/credentials/` — Create or update credentials

```http
POST /api/credentials/ HTTP/1.1
Host: localhost:5000
Content-Type: application/json
X-App-Owner: my-app

{
  "provider": "cloudinary",
  "credentials": {
    "cloud_name": "my-cloud",
    "api_key": "123456789012345",
    "api_secret": "my-api-secret"
  },
  "is_default": true
}
```

```json
HTTP/1.1 201 Created

{
  "id": 1,
  "owner": "my-app",
  "provider": "cloudinary",
  "credentials": {
    "cloud_name": "my-cloud",
    "api_key": "123456789012345",
    "api_secret": "my-api-secret"
  },
  "is_default": true,
  "created_at": "2026-04-01T10:00:00Z",
  "updated_at": "2026-04-01T10:00:00Z"
}
```

---

#### `GET /api/credentials/{id}/` — Retrieve a credential

```http
GET /api/credentials/1/ HTTP/1.1
Host: localhost:5000
X-App-Owner: my-app
```

```json
{
  "id": 1,
  "owner": "my-app",
  "provider": "cloudinary",
  "credentials": {
    "cloud_name": "my-cloud",
    "api_key": "123456789012345",
    "api_secret": "my-api-secret"
  },
  "is_default": true,
  "created_at": "2026-04-01T10:00:00Z",
  "updated_at": "2026-04-01T10:00:00Z"
}
```

---

#### `PATCH /api/credentials/{id}/` — Update a credential

```http
PATCH /api/credentials/1/ HTTP/1.1
Host: localhost:5000
Content-Type: application/json
X-App-Owner: my-app

{
  "credentials": {
    "cloud_name": "my-cloud",
    "api_key": "999999999999999",
    "api_secret": "new-api-secret"
  }
}
```

```json
{
  "id": 1,
  "owner": "my-app",
  "provider": "cloudinary",
  "credentials": {
    "cloud_name": "my-cloud",
    "api_key": "999999999999999",
    "api_secret": "new-api-secret"
  },
  "is_default": true,
  "created_at": "2026-04-01T10:00:00Z",
  "updated_at": "2026-04-27T08:30:00Z"
}
```

---

#### `DELETE /api/credentials/{id}/` — Delete a credential

```http
DELETE /api/credentials/1/ HTTP/1.1
Host: localhost:5000
X-App-Owner: my-app
```

```
HTTP/1.1 204 No Content
```

---

#### `GET /api/files/` — List files for an owner

```http
GET /api/files/?provider=cloudinary HTTP/1.1
Host: localhost:5000
X-App-Owner: my-app
```

```json
[
  {
    "id": 42,
    "name": "profile-photo.jpg",
    "size": 204800,
    "content_type": "image/jpeg",
    "provider": "cloudinary",
    "provider_file_id": "profile-photo",
    "url": "https://res.cloudinary.com/my-cloud/image/upload/profile-photo.jpg",
    "status": "completed",
    "error_message": "",
    "owner": "my-app",
    "metadata": {
      "resource_type": "image",
      "format": "jpg",
      "bytes": 204800,
      "version": 1711920000
    },
    "upload_strategy": "async_backend",
    "created_at": "2026-04-10T12:00:00Z",
    "updated_at": "2026-04-10T12:00:05Z"
  }
]
```

---

#### `POST /api/files/` — Upload a file (multipart, ≤ sync threshold)

Files at or below the provider's sync threshold (default 5 MB) are streamed
to disk and handed off to a background worker. The response is returned
immediately with `status: "pending"`.

```http
POST /api/files/ HTTP/1.1
Host: localhost:5000
Content-Type: multipart/form-data; boundary=----Boundary
X-App-Owner: my-app

------Boundary
Content-Disposition: form-data; name="file"; filename="report.pdf"
Content-Type: application/pdf

<binary file data>
------Boundary
Content-Disposition: form-data; name="provider"

cloudinary
------Boundary
Content-Disposition: form-data; name="name"

q1-report.pdf
------Boundary--
```

```json
HTTP/1.1 202 Accepted

{
  "id": 43,
  "name": "q1-report.pdf",
  "size": 512000,
  "content_type": "application/pdf",
  "provider": "cloudinary",
  "provider_file_id": null,
  "url": null,
  "status": "pending",
  "error_message": "",
  "owner": "my-app",
  "metadata": {},
  "upload_strategy": "async_backend",
  "created_at": "2026-04-27T09:00:00Z",
  "updated_at": "2026-04-27T09:00:00Z"
}
```

Poll `GET /api/files/43/` until `status` becomes `"completed"` or `"failed"`.

**Error — file exceeds hard upload limit (100 MB):**

```json
HTTP/1.1 413 Request Entity Too Large

{
  "detail": "File exceeds maximum upload size of 104857600 bytes."
}
```

**Error — file exceeds provider sync threshold (use direct upload instead):**

```json
HTTP/1.1 413 Request Entity Too Large

{
  "detail": "File is too large for sync upload on this provider; use POST /files/direct-upload/ instead.",
  "provider": "cloudinary",
  "size": 12582912
}
```

---

#### `GET /api/files/{id}/` — Retrieve a file

```http
GET /api/files/43/ HTTP/1.1
Host: localhost:5000
X-App-Owner: my-app
```

```json
{
  "id": 43,
  "name": "q1-report.pdf",
  "size": 512000,
  "content_type": "application/pdf",
  "provider": "cloudinary",
  "provider_file_id": "q1-report",
  "url": "https://res.cloudinary.com/my-cloud/raw/upload/q1-report.pdf",
  "status": "completed",
  "error_message": "",
  "owner": "my-app",
  "metadata": {
    "resource_type": "raw",
    "format": "pdf",
    "bytes": 512000,
    "version": 1745744400
  },
  "upload_strategy": "async_backend",
  "created_at": "2026-04-27T09:00:00Z",
  "updated_at": "2026-04-27T09:00:06Z"
}
```

---

#### `PATCH /api/files/{id}/` — Rename a file

```http
PATCH /api/files/43/ HTTP/1.1
Host: localhost:5000
Content-Type: application/json
X-App-Owner: my-app

{
  "name": "q1-report-final.pdf"
}
```

```json
{
  "id": 43,
  "name": "q1-report-final.pdf",
  "size": 512000,
  "content_type": "application/pdf",
  "provider": "cloudinary",
  "provider_file_id": "q1-report-final",
  "url": "https://res.cloudinary.com/my-cloud/raw/upload/q1-report-final.pdf",
  "status": "completed",
  "error_message": "",
  "owner": "my-app",
  "metadata": {
    "resource_type": "raw",
    "format": "pdf",
    "bytes": 512000,
    "version": 1745744400
  },
  "upload_strategy": "async_backend",
  "created_at": "2026-04-27T09:00:00Z",
  "updated_at": "2026-04-27T09:15:00Z"
}
```

---

#### `DELETE /api/files/{id}/` — Delete a file

Removes the record from FileForge and deletes the underlying object from the
provider.

```http
DELETE /api/files/43/ HTTP/1.1
Host: localhost:5000
X-App-Owner: my-app
```

```
HTTP/1.1 204 No Content
```

---

#### `POST /api/files/direct-upload/` — Initiate a direct upload

Use this flow for files that exceed the provider's sync threshold. FileForge
returns a pre-signed URL; the client uploads directly to the provider without
the bytes passing through FileForge.

```http
POST /api/files/direct-upload/ HTTP/1.1
Host: localhost:5000
Content-Type: application/json
X-App-Owner: my-app

{
  "name": "large-video.mp4",
  "provider": "cloudinary",
  "size": 52428800,
  "content_type": "video/mp4"
}
```

```json
HTTP/1.1 201 Created

{
  "file_id": 44,
  "upload_url": "https://api.cloudinary.com/v1_1/my-cloud/video/upload",
  "method": "POST",
  "fields": {
    "timestamp": "1745744400",
    "public_id": "large-video",
    "overwrite": "true",
    "unique_filename": "false",
    "use_filename": "false",
    "api_key": "123456789012345",
    "signature": "abc123def456..."
  },
  "headers": {},
  "expires_in": null,
  "provider_ref": {
    "public_id": "large-video",
    "resource_type": "video",
    "folder": null
  }
}
```

The client then performs the actual upload directly against `upload_url` using
the returned `method` and `fields`. For Cloudinary this is a multipart POST;
for Google Drive it is a `PUT` to the resumable session URL.

**Google Drive example response:**

```json
HTTP/1.1 201 Created

{
  "file_id": 45,
  "upload_url": "https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable&upload_id=xyz...",
  "method": "PUT",
  "fields": {},
  "headers": {
    "Content-Type": "video/mp4"
  },
  "expires_in": null,
  "provider_ref": {
    "path": "large-video.mp4"
  }
}
```

---

#### `POST /api/files/direct-upload/complete/` — Finalize a direct upload

After the client has successfully uploaded the file to the provider, call
this endpoint to record the result and mark the `File` as completed.

```http
POST /api/files/direct-upload/complete/ HTTP/1.1
Host: localhost:5000
Content-Type: application/json
X-App-Owner: my-app

{
  "file_id": 44,
  "provider_file_id": "large-video",
  "url": "https://res.cloudinary.com/my-cloud/video/upload/large-video.mp4",
  "provider_response": {
    "public_id": "large-video",
    "secure_url": "https://res.cloudinary.com/my-cloud/video/upload/large-video.mp4",
    "resource_type": "video",
    "format": "mp4",
    "bytes": 52428800,
    "version": 1745744500
  }
}
```

```json
HTTP/1.1 200 OK

{
  "id": 44,
  "name": "large-video.mp4",
  "size": 52428800,
  "content_type": "video/mp4",
  "provider": "cloudinary",
  "provider_file_id": "large-video",
  "url": "https://res.cloudinary.com/my-cloud/video/upload/large-video.mp4",
  "status": "completed",
  "error_message": "",
  "owner": "my-app",
  "metadata": {
    "resource_type": "video",
    "format": "mp4",
    "bytes": 52428800,
    "version": 1745744500,
    "provider_ref": {
      "public_id": "large-video",
      "resource_type": "video",
      "folder": null
    }
  },
  "upload_strategy": "direct",
  "created_at": "2026-04-27T09:30:00Z",
  "updated_at": "2026-04-27T09:30:45Z"
}
```

**Error — provider finalization failed:**

```json
HTTP/1.1 502 Bad Gateway

{
  "detail": "Cloudinary finalize requires `public_id`."
}
```

---

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