**FileForge**

Developer Documentation

*Pluggable Cloud Storage Bridge*

Version 2.0 · April 2026

**Table of Contents**

**1. Overview**

FileForge is a pluggable cloud-storage bridge built with Django and
Django REST Framework. It lets external applications connect one or more
cloud storage providers---Google Drive, Cloudinary, or any custom
provider---and route file uploads through a unified REST API, without
each calling application needing to know the specifics of any individual
storage service.

FileForge is infrastructure: a self-hosted service that a developer
deploys and then calls from their own backend. It handles credential
management, async upload queuing, direct-upload orchestration, and file
lifecycle tracking. Version 2.0 adds a full authentication and
multi-tenancy layer: developer accounts, registered apps, and
cryptographic API keys.

**1.1 Key Concepts**

  -----------------------------------------------------------------------
  **Concept**      **Description**
  ---------------- ------------------------------------------------------
  Provider         A cloud storage backend (Google Drive, Cloudinary).
                   Each provider is a stateless adapter implementing a
                   standard interface.

  DeveloperUser    A human who registers an account and owns one or more
                   Apps. Authenticates via JWT.

  App              A named integration registered by a DeveloperUser.
                   Holds an owner_slug that scopes all files and
                   credentials to that integration. Replaces the old
                   X-App-Owner honour-system header.

  ApiKey           A hashed secret (prefix ffk\_) bound to an App.
                   External servers include it as a Bearer token to
                   authenticate storage API calls.

  Owner slug       A stable random identifier (e.g. app_xk3m9pq7rz1c)
                   generated when an App is created. Stored on every File
                   and StorageCredential row so data is scoped correctly.

  File record      A database row tracking a file\'s metadata, upload
                   status, and reference to the provider\'s own file ID.

  Async upload     Small files are buffered to disk then uploaded to the
                   provider by a background worker (Django-Q2). The API
                   returns immediately with status: pending.

  Direct upload    Large files bypass FileForge entirely. FileForge
                   issues a signed URL; the client uploads straight to
                   the provider.

  Credential       Provider-specific secrets stored per app owner. Merged
                   with environment-level defaults to authenticate the
                   provider call.
  -----------------------------------------------------------------------

**1.2 Architecture Overview**

  --------------------------------------------------------------------------------------
  **Layer**        **Path**                              **Responsibility**
  ---------------- ------------------------------------- -------------------------------
  Auth models      fileforge_auth/models.py              DeveloperUser, App, ApiKey ---
                                                         the identity and ownership
                                                         layer

  Auth backend     fileforge_auth/authentication.py      ApiKeyAuthentication ---
                                                         validates Bearer ffk\_\...
                                                         tokens

  Permissions      fileforge_auth/permissions.py         IsAuthenticatedApp (API key),
                                                         IsAuthenticatedDeveloper (JWT)

  Auth views       fileforge_auth/views.py               Register, login, me, app CRUD,
                                                         key management

  Provider         storage/providers/base.py             BaseStorageProvider --- strict
  interface                                              contract all providers must
                                                         satisfy

  Provider         storage/providers/registry.py         Name → class mapping;
  registry                                               plugin-ready

  Built-in         storage/providers/                    Google Drive and Cloudinary
  providers                                              adapters

  Service layer    storage/services/storage_manager.py   Single orchestration entry
                                                         point; resolves credentials and
                                                         routes calls

  Async tasks      storage/tasks/file_tasks.py           process_file_upload,
                                                         cleanup_temp_files

  Utilities        storage/utils/                        Disk temp storage; upload
                                                         strategy threshold helper

  Storage models   storage/models.py                     File and StorageCredential

  Storage API      storage/views.py + urls.py            DRF views mounted at /api/ ---
                                                         require API key auth
  --------------------------------------------------------------------------------------

+-----------------------------------------------------------------------+
| **Design principle**                                                  |
|                                                                       |
| Views and tasks never import provider classes directly --- all        |
| provider access goes through StorageManager. The management (auth)    |
| API and the storage API are two independent surfaces with two         |
| independent authentication schemes: JWT for humans, API keys for      |
| machines.                                                             |
+-----------------------------------------------------------------------+

**1.3 Two-Surface API Design**

FileForge exposes two distinct API surfaces that must never be mixed:

  -----------------------------------------------------------------------
  **Surface**    **Base      **Authentication**   **Actors**
                 path**
  -------------- ----------- -------------------- -----------------------
  Management API /auth/      JWT (Bearer access   Developer (human,
                             token)               browser or tooling)

  Storage API    /api/       API Key (Bearer      External app
                             ffk\_\...)           (server-to-server)
  -----------------------------------------------------------------------

**2. Getting Started**

**2.1 Requirements**

-   Python 3.11 or 3.12

-   No Redis or external broker required --- Django-Q2 uses the SQLite
    ORM broker in development

-   Internet access from the server to the chosen cloud provider APIs

**2.2 Installation**

1.  Clone the repository and enter the project directory.

  -----------------------------------------------------------------------
  git clone https://github.com/your-org/fileforge.git

  cd fileforge
  -----------------------------------------------------------------------

2.  Create and activate a virtual environment, then install
    dependencies.

  -----------------------------------------------------------------------
  python -m venv venv

  source venv/bin/activate \# Windows: venv\\Scripts\\activate

  pip install -r requirements.txt
  -----------------------------------------------------------------------

3.  Copy the sample environment file and fill in your secrets (see
    Section 3).

  -----------------------------------------------------------------------
  cp .env.example .env

  -----------------------------------------------------------------------

4.  Run migrations. This creates all tables including the new auth
    tables.

  -----------------------------------------------------------------------
  python manage.py migrate

  -----------------------------------------------------------------------

5.  If you have existing data from v1, migrate legacy owner strings to
    App records.

  -----------------------------------------------------------------------
  python manage.py migrate_legacy_owners

  -----------------------------------------------------------------------

6.  Start the service (migrates, starts Q2 worker, launches dev server
    on port 5000).

  -----------------------------------------------------------------------
  ./run.sh

  -----------------------------------------------------------------------

7.  Verify the service is live.

  -----------------------------------------------------------------------
  curl http://localhost:5000/api/health/

  -----------------------------------------------------------------------

  -----------------------------------------------------------------------
  {

  \"status\": \"ok\",

  \"providers\": \[\"cloudinary\", \"google_drive\"\]

  }
  -----------------------------------------------------------------------

**2.3 First Steps After Installation**

The typical onboarding flow for a new developer integrating their
application:

8.  Register a developer account via POST /auth/register/.

9.  Obtain a JWT access token via POST /auth/token/.

10. Create an App via POST /auth/apps/ --- note the owner_slug in the
    response.

11. Create an API key for that app via POST /auth/apps/{id}/keys/ ---
    copy the raw_key immediately, it is shown only once.

12. Use that API key as a Bearer token on all storage API calls
    (/api/\...).

13. Register your provider credentials via POST /api/credentials/.

14. Start uploading files via POST /api/files/.

**2.4 Production Deployment**

For production, use Gunicorn and keep the Q2 worker alive in the
background:

  -----------------------------------------------------------------------
  python manage.py migrate \--noinput

  python manage.py qcluster &

  exec gunicorn \--bind 0.0.0.0:5000 \--workers 2
  fileforge.wsgi:application
  -----------------------------------------------------------------------

+-----------------------------------------------------------------------+
| **PythonAnywhere**                                                    |
|                                                                       |
| FileForge detects PythonAnywhere automatically. Set                   |
| PYTHONANYWHERE_DOMAIN in your environment and ALLOWED_HOSTS,          |
| STATIC_ROOT, and MEDIA_ROOT adjust accordingly.                       |
+-----------------------------------------------------------------------+

**3. Configuration**

All configuration is driven by environment variables, typically stored
in a .env file. python-dotenv loads them automatically on startup.

**3.1 Core Settings**

  ---------------------------------------------------------------------------------------
  **Variable**                      **Default**              **Description**
  --------------------------------- ------------------------ ----------------------------
  SESSION_SECRET                    (insecure dev key)       Django SECRET_KEY. Always
                                                             set a strong random value in
                                                             production.

  DJANGO_DEBUG                      1                        Set to 0 in production.

  FILEFORGE_DEFAULT_OWNER           default                  Owner value used when no API
                                                             key is present and no
                                                             X-App-Owner header is sent
                                                             (legacy fallback only).

  FILEFORGE_MAX_UPLOAD_SIZE         104857600 (100 MB)       Hard limit on file size
                                                             accepted by POST
                                                             /api/files/.

  FILEFORGE_DEFAULT_MAX_SYNC_SIZE   5242880 (5 MB)           Files larger than this
                                                             threshold are redirected to
                                                             the direct-upload flow.

  FILEFORGE_TEMP_DIR                {BASE_DIR}/tmp_uploads   Directory where incoming
                                                             files are buffered to disk
                                                             before provider upload.

  FILEFORGE_Q\_WORKERS              2                        Number of Django-Q2
                                                             background worker threads.

  FILEFORGE_Q\_SYNC                 0                        Set to 1 to run background
                                                             tasks synchronously ---
                                                             useful in tests.
  ---------------------------------------------------------------------------------------

**3.2 JWT Settings**

+-----------------------------------------------------------------------+
| **New in v2.0**                                                       |
|                                                                       |
| These settings control the SimpleJWT token lifetimes for the          |
| developer management API.                                             |
+-----------------------------------------------------------------------+

  ----------------------------------------------------------------------------
  **Variable**          **Default**   **Description**
  --------------------- ------------- ----------------------------------------
  JWT_ACCESS_MINUTES    30            Lifetime of an access token in minutes.

  JWT_REFRESH_DAYS      7             Lifetime of a refresh token in days.
                                      Rotation is enabled --- each refresh
                                      issues a new pair and blacklists the old
                                      refresh token.
  ----------------------------------------------------------------------------

**3.3 Google Drive Credentials**

  ------------------------------------------------------------------------------
  **Variable**                  **Required**   **Description**
  ----------------------------- -------------- ---------------------------------
  GOOGLE_SERVICE_ACCOUNT_JSON   One of the two Full service account key JSON as
                                               a single-line string.

  GOOGLE_SERVICE_ACCOUNT_FILE   One of the two Filesystem path to the service
                                               account key JSON file.

  GOOGLE_DRIVE_FOLDER_ID        No             Parent folder ID where uploaded
                                               files will be placed.
  ------------------------------------------------------------------------------

**3.4 Cloudinary Credentials**

  ------------------------------------------------------------------------------------
  **Variable**            **Required**   **Description**
  ----------------------- -------------- ---------------------------------------------
  CLOUDINARY_URL          One option     Full Cloudinary URL:
                                         cloudinary://api_key:api_secret@cloud_name.

  CLOUDINARY_CLOUD_NAME   Or these three Your Cloudinary cloud name.

  CLOUDINARY_API_KEY      Or these three Cloudinary API key.

  CLOUDINARY_API_SECRET   Or these three Cloudinary API secret.
  ------------------------------------------------------------------------------------

**3.5 Per-Provider Sync Size Overrides**

  -----------------------------------------------------------------------
  FILEFORGE_GOOGLE_DRIVE_MAX_SYNC_SIZE=5242880 \# 5 MB

  FILEFORGE_CLOUDINARY_MAX_SYNC_SIZE=10485760 \# 10 MB
  -----------------------------------------------------------------------

**3.6 Per-Owner Credential Overrides**

Environment variables provide system-wide defaults. To use different
credentials for a specific App (e.g. a customer\'s own Cloudinary
account), store them via POST /api/credentials/ using that App\'s API
key. Per-owner credentials win over environment defaults at request
time.

**4. Authentication & Ownership**

+-----------------------------------------------------------------------+
| **Changed in v2.0**                                                   |
|                                                                       |
| The honour-system X-App-Owner header has been replaced by             |
| cryptographic API keys. The header is still read as a fallback for    |
| backward compatibility during a migration period, but new             |
| integrations must use API keys.                                       |
+-----------------------------------------------------------------------+

**4.1 Developer Accounts (JWT)**

Developers who manage Apps and API keys authenticate using JSON Web
Tokens issued by SimpleJWT. The typical flow is:

15. Register: POST /auth/register/

16. Obtain tokens: POST /auth/token/ --- returns access (30 min) and
    refresh (7 days) tokens.

17. Use: include Authorization: Bearer \<access_token\> on all /auth/
    management requests.

18. Refresh: POST /auth/token/refresh/ --- returns a new pair and
    blacklists the old refresh token.

The token response includes email and full_name fields alongside the
standard access and refresh tokens for frontend convenience.

**4.2 App API Keys (Storage API)**

External servers that call the storage API (/api/\...) authenticate with
API keys. Key properties:

-   **Format:** ffk\_\<40 random chars\> --- the ffk\_ prefix makes keys
    identifiable in logs and code.

-   **Storage:** Only the SHA-256 hash is stored. The raw key is shown
    exactly once on creation and cannot be recovered.

-   **Header:** Authorization: Bearer ffk\_\<token\>

-   **Rotation:** Create a new key, deploy it, then revoke the old one.
    No downtime required.

-   **Expiry:** Optional. Set expires_at on creation for time-limited
    keys.

-   **Tracking:** last_used_at is updated on every successful
    authentication.

+-----------------------------------------------------------------------+
| **Security**                                                          |
|                                                                       |
| Never expose FileForge API keys to browsers or end users. Always make |
| storage API calls server-side from your backend and inject the key    |
| there. An API key grants full read/write access to its App\'s data.   |
+-----------------------------------------------------------------------+

**4.3 Owner Scoping**

Every File and StorageCredential row has an owner column. For
API-key-authenticated requests, this is automatically set to the
owner_slug of the API key\'s App --- a stable random string generated
when the App was created. There is no way for one App to read or write
another App\'s data.

The owner_slug is intentionally opaque and immutable. It is not the
App\'s name or ID --- renaming an App does not affect its slug, so
existing file records always resolve correctly.

**4.4 Multi-Tenant Usage**

Multiple independent applications can share a single FileForge instance.
Each registers its own developer account, creates its own App, and uses
its own API keys. Isolation is enforced at the database layer --- all
queries include a WHERE owner = \<slug\> filter derived from the
authenticated API key.

**4.5 Permission Classes**

  ------------------------------------------------------------------------------
  **Class**                  **Used on**         **Requirement**
  -------------------------- ------------------- -------------------------------
  IsAuthenticatedApp         /api/ storage       Request authenticated by
                             endpoints           ApiKeyAuthentication
                                                 (request.auth is an ApiKey
                                                 instance).

  IsAuthenticatedDeveloper   /auth/ management   Request authenticated by
                             endpoints           JWTAuthentication (request.auth
                                                 is a JWT token, not an ApiKey).

  IsAppOwner                 Object-level checks The ApiKey\'s App owner_slug
                                                 matches the object\'s owner
                                                 field. Used to prevent
                                                 cross-app data access.
  ------------------------------------------------------------------------------

**5. Management API Reference (/auth/)**

All management endpoints are authenticated with JWT. Include
Authorization: Bearer \<access_token\> on every request. The
registration and token endpoints are public.

**5.1 Registration**

**POST /auth/register/**

Creates a new developer account. Public --- no authentication required.

  ---------------------------------------------------------------------------------
  **Field**          **Type**   **Required**   **Notes**
  ------------------ ---------- -------------- ------------------------------------
  email              string     Yes            Must be unique across all developer
                                               accounts.

  password           string     Yes            Minimum 8 characters. Validated
                                               against Django\'s password
                                               validators.

  password_confirm   string     Yes            Must match password.

  full_name          string     No             Display name. Can be updated later
                                               via PATCH /auth/me/.
  ---------------------------------------------------------------------------------

***Request***

  -----------------------------------------------------------------------
  POST /auth/register/ HTTP/1.1

  Content-Type: application/json

  {

  \"email\": \"alice@example.com\",

  \"full_name\": \"Alice Dev\",

  \"password\": \"StrongPass123!\",

  \"password_confirm\": \"StrongPass123!\"

  }
  -----------------------------------------------------------------------

***Response --- 201 Created***

  -----------------------------------------------------------------------
  {

  \"id\": 1,

  \"email\": \"alice@example.com\",

  \"full_name\": \"Alice Dev\",

  \"date_joined\": \"2026-04-27T09:00:00Z\"

  }
  -----------------------------------------------------------------------

**5.2 Tokens**

**POST /auth/token/**

Obtain a JWT access/refresh pair. Public.

***Request***

  -----------------------------------------------------------------------
  POST /auth/token/ HTTP/1.1

  Content-Type: application/json

  { \"email\": \"alice@example.com\", \"password\": \"StrongPass123!\" }
  -----------------------------------------------------------------------

***Response --- 200 OK***

  -----------------------------------------------------------------------
  {

  \"access\": \"\<short-lived JWT\>\",

  \"refresh\": \"\<long-lived JWT\>\",

  \"email\": \"alice@example.com\",

  \"full_name\": \"Alice Dev\"

  }
  -----------------------------------------------------------------------

**POST /auth/token/refresh/**

Exchange a refresh token for a new access/refresh pair. The old refresh
token is blacklisted immediately.

***Request***

  -----------------------------------------------------------------------
  POST /auth/token/refresh/ HTTP/1.1

  Content-Type: application/json

  { \"refresh\": \"\<refresh_token\>\" }
  -----------------------------------------------------------------------

***Response --- 200 OK***

  -----------------------------------------------------------------------
  { \"access\": \"\<new_access_token\>\", \"refresh\":
  \"\<new_refresh_token\>\" }

  -----------------------------------------------------------------------

**5.3 Developer Profile**

**GET /auth/me/**

Returns the authenticated developer\'s profile.

***Request***

  -----------------------------------------------------------------------
  GET /auth/me/ HTTP/1.1

  Authorization: Bearer \<access_token\>
  -----------------------------------------------------------------------

***Response --- 200 OK***

  -----------------------------------------------------------------------
  {

  \"id\": 1,

  \"email\": \"alice@example.com\",

  \"full_name\": \"Alice Dev\",

  \"date_joined\": \"2026-04-27T09:00:00Z\"

  }
  -----------------------------------------------------------------------

**PATCH /auth/me/**

Update full_name. Email cannot be changed.

***Request***

  -----------------------------------------------------------------------
  PATCH /auth/me/ HTTP/1.1

  Authorization: Bearer \<access_token\>

  Content-Type: application/json

  { \"full_name\": \"Alice Smith\" }
  -----------------------------------------------------------------------

**POST /auth/me/change-password/**

***Request***

  -----------------------------------------------------------------------
  POST /auth/me/change-password/ HTTP/1.1

  Authorization: Bearer \<access_token\>

  Content-Type: application/json

  { \"current_password\": \"StrongPass123!\", \"new_password\":
  \"NewStrong456!\" }
  -----------------------------------------------------------------------

***Response --- 200 OK***

  -----------------------------------------------------------------------
  { \"detail\": \"Password updated.\" }

  -----------------------------------------------------------------------

**5.4 Apps**

**GET /auth/apps/**

Lists all Apps owned by the authenticated developer.

***Response --- 200 OK***

  -----------------------------------------------------------------------
  \[

  {

  \"id\": 1,

  \"name\": \"My SaaS App\",

  \"description\": \"Production integration\",

  \"owner_slug\": \"app_xk3m9pq7rz1c\",

  \"is_active\": true,

  \"api_key_count\": 2,

  \"created_at\": \"2026-04-27T09:00:00Z\",

  \"updated_at\": \"2026-04-27T09:00:00Z\"

  }

  \]
  -----------------------------------------------------------------------

**POST /auth/apps/**

Creates a new App. The owner_slug is auto-generated and immutable.

***Request***

  -----------------------------------------------------------------------
  POST /auth/apps/ HTTP/1.1

  Authorization: Bearer \<access_token\>

  Content-Type: application/json

  {

  \"name\": \"My SaaS App\",

  \"description\": \"Production integration\"

  }
  -----------------------------------------------------------------------

***Response --- 201 Created***

  -----------------------------------------------------------------------
  {

  \"id\": 1,

  \"name\": \"My SaaS App\",

  \"owner_slug\": \"app_xk3m9pq7rz1c\",

  \"is_active\": true,

  \"api_key_count\": 0,

  \...

  }
  -----------------------------------------------------------------------

**GET /auth/apps/{id}/**

Retrieves a single App. Returns 404 if the App belongs to a different
developer.

**PATCH /auth/apps/{id}/**

Updates name, description, or is_active. The owner_slug field is
read-only and ignored if submitted.

**DELETE /auth/apps/{id}/**

Deletes the App and all its API keys. Returns 204 No Content. Note: File
and StorageCredential rows are NOT deleted --- historical data is
preserved with its owner_slug.

**5.5 API Keys**

**GET /auth/apps/{id}/keys/**

Lists all API keys for an App. The raw key is never included in list
responses --- only the key_prefix (first 8 characters) is shown for
identification.

***Response --- 200 OK***

  -----------------------------------------------------------------------
  \[

  {

  \"id\": 1,

  \"app\": 1,

  \"app_name\": \"My SaaS App\",

  \"name\": \"production server\",

  \"key_prefix\": \"ffk_xK3m\",

  \"is_active\": true,

  \"last_used_at\": \"2026-04-28T07:30:00Z\",

  \"expires_at\": null,

  \"created_at\": \"2026-04-27T09:00:00Z\"

  }

  \]
  -----------------------------------------------------------------------

**POST /auth/apps/{id}/keys/**

Creates a new API key. The raw_key field is present in this response
only --- it cannot be retrieved afterwards. Copy it immediately.

***Request***

  -----------------------------------------------------------------------
  POST /auth/apps/1/keys/ HTTP/1.1

  Authorization: Bearer \<access_token\>

  Content-Type: application/json

  {

  \"name\": \"production server\",

  \"expires_at\": null

  }
  -----------------------------------------------------------------------

***Response --- 201 Created***

  -----------------------------------------------------------------------
  {

  \"id\": 1,

  \"name\": \"production server\",

  \"key_prefix\": \"ffk_xK3m\",

  \"raw_key\": \"ffk_xK3mAbc123\... ← shown ONCE, copy now\",

  \"expires_at\": null,

  \"created_at\": \"2026-04-27T09:00:00Z\"

  }
  -----------------------------------------------------------------------

+-----------------------------------------------------------------------+
| **raw_key is shown once**                                             |
|                                                                       |
| After this response, the raw key cannot be recovered. Only the        |
| SHA-256 hash is stored in the database. If a key is lost, revoke it   |
| and create a new one.                                                 |
+-----------------------------------------------------------------------+

**POST /auth/apps/{id}/keys/{key_id}/revoke/**

Marks a key as inactive. The key immediately stops authenticating.
Returns 200 with a confirmation message.

***Response --- 200 OK***

  -----------------------------------------------------------------------
  { \"detail\": \"API key revoked.\" }

  -----------------------------------------------------------------------

**6. Storage API Reference (/api/)**

All storage endpoints require a valid API key in the Authorization
header:

  -----------------------------------------------------------------------
  Authorization: Bearer ffk\_\<your_api_key\>

  -----------------------------------------------------------------------

The owner is resolved automatically from the API key\'s App. Do not send
an X-App-Owner header --- it is ignored when a valid API key is present.

**6.1 Health Check**

**GET /api/health/**

Public --- no authentication required. Returns liveness status and
registered providers.

***Response --- 200 OK***

  -----------------------------------------------------------------------
  { \"status\": \"ok\", \"providers\": \[\"cloudinary\",
  \"google_drive\"\] }

  -----------------------------------------------------------------------

**6.2 Providers**

**GET /api/providers/**

***Response --- 200 OK***

  -----------------------------------------------------------------------
  { \"providers\": \[

  { \"name\": \"cloudinary\", \"supports_direct_upload\": true },

  { \"name\": \"google_drive\", \"supports_direct_upload\": true }

  \]

  }
  -----------------------------------------------------------------------

**6.3 Credentials**

**GET /api/credentials/**

Lists credentials stored for the App whose API key was used.

***Request***

  -----------------------------------------------------------------------
  GET /api/credentials/ HTTP/1.1

  Authorization: Bearer ffk_xK3mAbc123\...
  -----------------------------------------------------------------------

***Response --- 200 OK***

  -----------------------------------------------------------------------
  \[{ \"id\": 1, \"owner\": \"app_xk3m9pq7rz1c\", \"provider\":
  \"cloudinary\", \"credentials\": { \... }, \... }\]

  -----------------------------------------------------------------------

**POST /api/credentials/**

Creates or upserts (updates on conflict) credentials for a provider,
scoped to the calling App.

***Request***

  -----------------------------------------------------------------------
  POST /api/credentials/ HTTP/1.1

  Authorization: Bearer ffk_xK3mAbc123\...

  Content-Type: application/json

  {

  \"provider\": \"cloudinary\",

  \"credentials\": { \"cloud_name\": \"my-cloud\", \"api_key\": \"123\",
  \"api_secret\": \"secret\" },

  \"is_default\": true

  }
  -----------------------------------------------------------------------

**GET /api/credentials/{id}/**

Retrieves a single credential. Returns 404 if owned by a different App.

**PATCH / PUT /api/credentials/{id}/**

Updates a credential. PATCH is partial; PUT replaces all fields.

**DELETE /api/credentials/{id}/**

Deletes a credential record. Returns 204 No Content.

**6.4 Files --- List & Upload**

**GET /api/files/**

Lists all file records for the calling App. Accepts an optional
?provider= query parameter.

***Request***

  -----------------------------------------------------------------------
  GET /api/files/?provider=cloudinary HTTP/1.1

  Authorization: Bearer ffk_xK3mAbc123\...
  -----------------------------------------------------------------------

***Response --- 200 OK***

  -----------------------------------------------------------------------
  \[

  {

  \"id\": 42,

  \"name\": \"photo.jpg\",

  \"size\": 204800,

  \"content_type\": \"image/jpeg\",

  \"provider\": \"cloudinary\",

  \"provider_file_id\": \"photo\",

  \"url\":
  \"https://res.cloudinary.com/my-cloud/image/upload/photo.jpg\",

  \"status\": \"completed\",

  \"error_message\": \"\",

  \"owner\": \"app_xk3m9pq7rz1c\",

  \"metadata\": { \"resource_type\": \"image\", \"bytes\": 204800 },

  \"upload_strategy\": \"async\",

  \"created_at\": \"2026-04-27T12:00:00Z\",

  \"updated_at\": \"2026-04-27T12:00:05Z\"

  }

  \]
  -----------------------------------------------------------------------

**POST /api/files/ --- Upload**

Accepts a multipart upload for files at or below the provider's sync
threshold (default 5 MB). The optional mode field controls whether the
response is returned immediately (async, default) or only after the
upload completes (sync).

  ----------------------------------------------------------------------------
  **Field**    **Type**      **Required**   **Description**
  ------------ ------------- -------------- ----------------------------------
  file         File          Yes            The file to upload.
               (multipart)

  provider     string        Yes            \"cloudinary\" or \"google_drive\"
                                            (or any registered provider).

  name         string        No             Override filename. Defaults to the
                                            original filename.

  mode         string        No             Upload execution mode. "async"
                                            (default): queue the upload and
                                            return 202 immediately with status
                                            "pending"; poll GET
                                            /api/files/{id}/ for the final
                                            result. "sync": block until the
                                            provider upload finishes and
                                            return 200 with the completed File
                                            in a single response. Only valid
                                            for files at or below the
                                            provider's sync size threshold.
  ----------------------------------------------------------------------------

***Request***

  -----------------------------------------------------------------------
  POST /api/files/ HTTP/1.1

  Authorization: Bearer ffk_xK3mAbc123\...

  Content-Type: multipart/form-data; boundary=\-\-\--B

  \-\-\-\-\--B

  Content-Disposition: form-data; name=\"file\"; filename=\"report.pdf\"

  Content-Type: application/pdf

  \<binary data\>

  \-\-\-\-\--B

  Content-Disposition: form-data; name=\"provider\"

  cloudinary

  \-\-\-\-\--B\--
  -----------------------------------------------------------------------

***Response --- 202 Accepted***

  -----------------------------------------------------------------------
  { \"id\": 43, \"status\": \"pending\", \"owner\": \"app_xk3m9pq7rz1c\",
  \... }

  -----------------------------------------------------------------------

When mode is "async" (default), poll GET /api/files/{id}/ until status
is "completed" or "failed". When mode is "sync", the response below is
returned directly with status "completed" and HTTP 200, or HTTP 502 if
the provider upload failed.

***Response --- 200 OK (mode: "sync", upload succeeded)***

+-----------------------------------------------------------------------+
| {                                                                     |
|                                                                       |
| \"id\": 43,                                                           |
|                                                                       |
| \"name\": \"report.pdf\",                                             |
|                                                                       |
| \"status\": \"completed\",                                            |
|                                                                       |
| \"provider_file_id\": \"report\",                                     |
|                                                                       |
| \"url\":                                                              |
| \"https://res.cloudinary.com/my-cloud/raw/upload/report.pdf\",        |
|                                                                       |
| \"upload_strategy\": \"sync\",                                        |
|                                                                       |
| \...                                                                  |
|                                                                       |
| }                                                                     |
+-----------------------------------------------------------------------+

***Response --- 502 Bad Gateway (mode: "sync", provider upload
failed)***

  -----------------------------------------------------------------------
  { \"detail\": \"Cloudinary credentials invalid.\", \"file\": { \"id\":
  43, \"status\": \"failed\", \... } }

  -----------------------------------------------------------------------

***Error --- 413 file exceeds hard limit***

  -----------------------------------------------------------------------
  { \"detail\": \"File exceeds maximum upload size of 104857600 bytes.\"
  }

  -----------------------------------------------------------------------

***Error --- 413 file too large for sync flow***

  -----------------------------------------------------------------------
  { \"detail\": \"File is too large for sync upload on this provider; use
  POST /api/files/direct-upload/ instead.\", \"provider\":
  \"cloudinary\", \"size\": 12582912 }

  -----------------------------------------------------------------------

**6.5 Files --- Detail, Rename, Delete**

**GET /api/files/{id}/**

Poll this endpoint after a 202 response to check upload status. Returns
404 if the file belongs to a different App.

***File status lifecycle***

  -----------------------------------------------------------------------
  pending → uploading → completed

  ↘ failed (check error_message)
  -----------------------------------------------------------------------

**PATCH /api/files/{id}/**

Renames a file. FileForge updates both the database record and the
file\'s name/public_id on the provider.

***Request***

  -----------------------------------------------------------------------
  PATCH /api/files/43/ HTTP/1.1

  Authorization: Bearer ffk_xK3mAbc123\...

  Content-Type: application/json

  { \"name\": \"q1-report-final.pdf\" }
  -----------------------------------------------------------------------

**DELETE /api/files/{id}/**

Deletes the database record and the underlying object from the provider.
Returns 204 No Content.

**6.6 Direct Upload**

Use for files above the provider\'s sync threshold. The file bytes never
touch the FileForge server.

**Step 1 --- POST /api/files/direct-upload/**

  -----------------------------------------------------------------------------
  **Field**      **Type**   **Required**   **Description**
  -------------- ---------- -------------- ------------------------------------
  name           string     Yes            Filename on the provider.

  provider       string     Yes            Provider name.

  size           integer    Yes            File size in bytes.

  content_type   string     No             MIME type.
  -----------------------------------------------------------------------------

***Request***

  -----------------------------------------------------------------------
  POST /api/files/direct-upload/ HTTP/1.1

  Authorization: Bearer ffk_xK3mAbc123\...

  Content-Type: application/json

  { \"name\": \"large-video.mp4\", \"provider\": \"cloudinary\",
  \"size\": 52428800, \"content_type\": \"video/mp4\" }
  -----------------------------------------------------------------------

***Response --- 201 Created (Cloudinary)***

  -----------------------------------------------------------------------
  {

  \"file_id\": 44,

  \"upload_url\":
  \"https://api.cloudinary.com/v1_1/my-cloud/video/upload\",

  \"method\": \"POST\",

  \"fields\": { \"timestamp\": \"\...\", \"public_id\": \"large-video\",
  \"api_key\": \"\...\", \"signature\": \"\...\" },

  \"headers\": {},

  \"expires_in\": null,

  \"provider_ref\": { \"public_id\": \"large-video\", \"resource_type\":
  \"video\" }

  }
  -----------------------------------------------------------------------

***Response --- 201 Created (Google Drive)***

  ------------------------------------------------------------------------------------------
  {

  \"file_id\": 45,

  \"upload_url\":
  \"https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable&upload_id=xyz\",

  \"method\": \"PUT\",

  \"fields\": {},

  \"headers\": { \"Content-Type\": \"video/mp4\" },

  \"provider_ref\": { \"path\": \"large-video.mp4\" }

  }
  ------------------------------------------------------------------------------------------

**Step 2 --- Client uploads to provider**

Upload directly using the ticket values. For Cloudinary: multipart POST
with fields as form data. For Google Drive: PUT with the file body.

  -----------------------------------------------------------------------
  // Cloudinary

  const form = new FormData();

  Object.entries(ticket.fields).forEach((\[k,v\]) =\> form.append(k, v));

  form.append(\'file\', fileBlob);

  await fetch(ticket.upload_url, { method: \'POST\', body: form });

  // Google Drive

  await fetch(ticket.upload_url, { method: \'PUT\', headers:
  ticket.headers, body: fileBlob });
  -----------------------------------------------------------------------

**Step 3 --- POST /api/files/direct-upload/complete/**

***Request***

  -----------------------------------------------------------------------
  POST /api/files/direct-upload/complete/ HTTP/1.1

  Authorization: Bearer ffk_xK3mAbc123\...

  Content-Type: application/json

  {

  \"file_id\": 44,

  \"provider_file_id\": \"large-video\",

  \"provider_response\": { \"public_id\": \"large-video\",
  \"secure_url\": \"https://\...\", \"resource_type\": \"video\",
  \"bytes\": 52428800 }

  }
  -----------------------------------------------------------------------

***Response --- 200 OK***

  -----------------------------------------------------------------------
  { \"id\": 44, \"status\": \"completed\", \"url\":
  \"https://res.cloudinary.com/\...\", \... }

  -----------------------------------------------------------------------

**7. Upload Flow Guide**

**7.1 Choosing the Right Flow**

  ------------------------------------------------------------------------
  **File size**         **Flow**           **Endpoints**
  --------------------- ------------------ -------------------------------
  ≤ provider sync       Async upload       POST /api/files/ (mode:
  threshold (default 5  (queue, poll)      "async", default)
  MB)

  ≤ provider sync       Sync upload        POST /api/files/ (mode: "sync")
  threshold, want       (block, no
  single round-trip     polling)

  \> provider sync      Direct upload      POST /api/files/direct-upload/
  threshold                                then /complete/

  Unknown at call time  Check 413 response If 413 returned with
                                           direct-upload hint, switch
                                           flows
  ------------------------------------------------------------------------

**7.2 Async Upload --- Full Flow**

19. POST /api/files/ with file as multipart form data and mode: "async"
    (or omit --- async is the default).

20. Receive 202 Accepted with the File record (status: \"pending\").

21. Poll GET /api/files/{id}/ at intervals (e.g. every 2 seconds with
    exponential back-off).

22. When status becomes \"completed\", use the url field. If \"failed\",
    read error_message.

**7.3 Sync Upload --- Full Flow**

Use this flow when you want a single round-trip with no polling. The web
worker blocks until the provider upload completes, then returns the
final File state. Only valid for files at or below the provider's sync
size threshold.

23. POST /api/files/ with file as multipart form data and mode: "sync".

24. Receive 200 OK with the File record already at status: "completed"
    and a populated url. No polling required.

25. If the provider rejects the upload, the response is 502 Bad Gateway
    with a detail message and the failed File record embedded in the
    body. The File row is still persisted and queryable via GET
    /api/files/{id}/.

**7.4 Direct Upload --- Full Flow**

26. POST /api/files/direct-upload/ with name, provider, size,
    content_type.

27. Receive 201 Created with file_id, upload_url, method, fields,
    headers.

28. Upload directly to upload_url using the returned credentials.

29. POST /api/files/direct-upload/complete/ with file_id and provider
    response data.

30. Receive completed File record with status: \"completed\".

**7.5 File Status Reference**

  -----------------------------------------------------------------------
  **Status**    **Meaning**
  ------------- ---------------------------------------------------------
  pending       File record created; background upload queued.

  uploading     Background worker is transferring bytes to the provider.

  completed     Upload succeeded. provider_file_id and url are populated.

  failed        Upload failed. Check error_message. The temp file has
                been deleted.
  -----------------------------------------------------------------------

**8. Provider Guide**

**8.1 Cloudinary**

**Credentials**

  -----------------------------------------------------------------------
  \# Option A --- URL string

  CLOUDINARY_URL=cloudinary://api_key:api_secret@cloud_name

  \# Option B --- individual values

  CLOUDINARY_CLOUD_NAME=my-cloud

  CLOUDINARY_API_KEY=123456789012345

  CLOUDINARY_API_SECRET=my-api-secret
  -----------------------------------------------------------------------

**Optional credential fields**

  -----------------------------------------------------------------------
  **Field**       **Description**
  --------------- -------------------------------------------------------
  folder          Folder prefix prepended to all uploads (e.g.
                  \"uploads/avatars\").

  resource_type   \"auto\" (default), \"image\", \"video\", or \"raw\".
  -----------------------------------------------------------------------

-   Cloudinary\'s destroy API does not accept resource_type: \"auto\"
    --- FileForge defaults to \"image\" for delete and rename. Set
    resource_type explicitly in credentials for non-image files.

-   The direct-upload ticket uses a signed form POST. Do not cache the
    ticket --- signatures expire.

**8.2 Google Drive**

**Service Account Setup**

31. In Google Cloud Console, create a service account.

32. Share the target Drive folder with the service account email
    address.

33. Download a JSON key file.

34. Set GOOGLE_SERVICE_ACCOUNT_JSON or GOOGLE_SERVICE_ACCOUNT_FILE.

35. Set GOOGLE_DRIVE_FOLDER_ID to the target folder\'s ID.

-   Files uploaded without folder_id go to the service account root ---
    not visible to humans in Drive.

-   For direct upload, the client PUTs the file body to the resumable
    session URL from the ticket. After upload, call /complete/ with the
    Drive file ID in provider_file_id.

**8.3 Adding a Custom Provider**

36. Create storage/providers/my_provider.py --- subclass
    BaseStorageProvider:

  -----------------------------------------------------------------------
  from .base import BaseStorageProvider, UploadResult

  class MyProvider(BaseStorageProvider):

  name = \"my_provider\"

  supports_direct_upload = False

  def upload(self, file, path, \*, content_type=None, size=None,
  \*\*kwargs):

  \# call your SDK here

  return UploadResult(provider_file_id=\'\...\', url=\'\...\')

  def download(self, file_id, \*\*kwargs): \...

  def delete(self, file_id, \*\*kwargs): \...

  def update(self, file_id, \*\*kwargs): \...

  def get_url(self, file_id, \*\*kwargs): \...
  -----------------------------------------------------------------------

37. Register it in storage/providers/registry.py inside
    register_default_providers():

  -----------------------------------------------------------------------
  from .my_provider import MyProvider

  if \"my_provider\" not in registry:

  registry.register(\"my_provider\", MyProvider)
  -----------------------------------------------------------------------

38. Add credential keys to FILEFORGE_PROVIDER_ENV_CREDENTIALS in
    settings.py.

No views, serializers, or services need to change.

**9. Data Models**

**9.1 DeveloperUser**

+-----------------------------------------------------------------------+
| **New in v2.0**                                                       |
|                                                                       |
| Custom user model (AUTH_USER_MODEL =                                  |
| \"fileforge_auth.DeveloperUser\"). Email is the login field --- no    |
| username.                                                             |
+-----------------------------------------------------------------------+

  ------------------------------------------------------------------------
  **Field**       **Type**        **Notes**
  --------------- --------------- ----------------------------------------
  id              BigAutoField    Primary key.

  email           EmailField      Unique login identifier.

  full_name       CharField       Display name. Optional.

  is_active       BooleanField    Inactive users cannot log in or use
                                  their apps\' API keys.

  is_staff        BooleanField    Grants Django admin access.

  date_joined     DateTimeField   Auto-set on registration.
  ------------------------------------------------------------------------

**9.2 App**

+-----------------------------------------------------------------------+
| **New in v2.0**                                                       |
|                                                                       |
| Replaces the X-App-Owner string header with a proper database entity. |
+-----------------------------------------------------------------------+

  ------------------------------------------------------------------------
  **Field**       **Type**        **Notes**
  --------------- --------------- ----------------------------------------
  id              BigAutoField    Primary key.

  developer       ForeignKey      Owning DeveloperUser. CASCADE on delete.

  name            CharField       Human name. Unique per developer.

  description     TextField       Optional notes.

  owner_slug      CharField       Stable random slug (app\_\<12 chars\>).
                                  Stored on all File/StorageCredential
                                  rows. Immutable after creation.

  is_active       BooleanField    Inactive apps\' API keys are rejected.

  created_at      DateTimeField   Auto-set on creation.

  updated_at      DateTimeField   Auto-updated on save.
  ------------------------------------------------------------------------

**9.3 ApiKey**

+-----------------------------------------------------------------------+
| **New in v2.0**                                                       |
|                                                                       |
| Only the SHA-256 hash is stored. Raw keys are generated once and      |
| never persisted.                                                      |
+-----------------------------------------------------------------------+

  ------------------------------------------------------------------------
  **Field**       **Type**        **Notes**
  --------------- --------------- ----------------------------------------
  id              BigAutoField    Primary key.

  app             ForeignKey      Owning App. CASCADE on delete.

  name            CharField       Human label, e.g. \"production server\".

  key_hash        CharField(64)   SHA-256 hex digest. Unique index. Never
                                  exposed in API responses.

  key_prefix      CharField(12)   First 8 characters of the raw key ---
                                  safe to show in the UI for
                                  identification.

  is_active       BooleanField    Revoked keys return 401.

  last_used_at    DateTimeField   Updated on every successful
                                  authentication.

  expires_at      DateTimeField   Optional expiry. Null means the key
                                  never expires.

  created_at      DateTimeField   Auto-set on creation.
  ------------------------------------------------------------------------

**9.4 File**

  --------------------------------------------------------------------------
  **Field**          **Type**          **Notes**
  ------------------ ----------------- -------------------------------------
  id                 BigAutoField      Primary key.

  name               CharField(512)    Filename on the provider.

  size               BigIntegerField   File size in bytes.

  content_type       CharField(255)    MIME type.

  provider           CharField(64)     Provider name.

  provider_file_id   CharField(512)    Provider\'s file ID. Null until
                                       upload completes.

  url                URLField          Viewable URL. Null until upload
                                       completes.

  status             CharField         pending, uploading, completed, or
                                       failed.

  error_message      TextField         Populated on failure.

  owner              CharField(255)    App\'s owner_slug. Scopes the file to
                                       an App.

  metadata           JSONField         Provider-specific metadata.

  temp_path          CharField         Path to temp file on disk. Cleared
                                       after upload.

  upload_strategy    CharField(16)     "async", "sync", or "direct".

  created_at         DateTimeField     Auto-set on creation.

  updated_at         DateTimeField     Auto-updated on save.
  --------------------------------------------------------------------------

**9.5 StorageCredential**

  ------------------------------------------------------------------------
  **Field**       **Type**        **Notes**
  --------------- --------------- ----------------------------------------
  id              BigAutoField    Primary key.

  owner           CharField       App\'s owner_slug. Unique constraint
                                  with provider.

  provider        CharField       Provider name.

  credentials     JSONField       Provider-specific credential blob.

  is_default      BooleanField    Informational.

  created_at      DateTimeField   Auto-set on creation.

  updated_at      DateTimeField   Auto-updated on save.
  ------------------------------------------------------------------------

**10. Migrating from v1**

+-----------------------------------------------------------------------+
| **New in v2.0**                                                       |
|                                                                       |
| If you are upgrading an existing FileForge instance, follow this      |
| section carefully.                                                    |
+-----------------------------------------------------------------------+

**10.1 What Changed**

  -----------------------------------------------------------------------
  **v1 behaviour**               **v2 behaviour**
  ------------------------------ ----------------------------------------
  X-App-Owner header identifies  API key (Bearer ffk\_\...) identifies
  the caller --- no              and authenticates the caller.
  verification.

  No developer accounts.         DeveloperUser model; register at POST
                                 /auth/register/.

  No App concept --- owner is a  App model with auto-generated
  free-form string.              owner_slug.

  All API endpoints were         Storage API requires API key. Management
  unauthenticated (AllowAny).    API requires JWT.

  X-App-Owner: default used when Missing API key returns 401/403. Legacy
  no header sent.                header fallback still active during
                                 transition.
  -----------------------------------------------------------------------

**10.2 Upgrade Steps**

39. Install the new dependency.

  -----------------------------------------------------------------------
  pip install -r requirements.txt \# adds djangorestframework-simplejwt

  -----------------------------------------------------------------------

40. Add fileforge_auth and rest_framework_simplejwt.token_blacklist to
    INSTALLED_APPS. Set AUTH_USER_MODEL =
    \"fileforge_auth.DeveloperUser\". Add SIMPLE_JWT config. (See
    updated settings.py.)

41. Run migrations.

  -----------------------------------------------------------------------
  python manage.py migrate

  -----------------------------------------------------------------------

42. Migrate legacy owner strings to App records.

  -----------------------------------------------------------------------
  python manage.py migrate_legacy_owners

  -----------------------------------------------------------------------

This command creates a placeholder DeveloperUser and an App with
owner_slug equal to each distinct owner string found in existing File
and StorageCredential rows. All historical data automatically resolves
to the correct App without any data transformation.

43. Register a real developer account and create a proper App with API
    keys for each integration.

  -----------------------------------------------------------------------------------------
  \# 1. Register

  curl -X POST /auth/register/ -d
  \'{\"email\":\"you@example.com\",\"password\":\"\...\",\"password_confirm\":\"\...\"}\'

  \# 2. Get token

  curl -X POST /auth/token/ -d \'{\"email\":\"you@example.com\",\"password\":\"\...\"}\'

  \# 3. Create app

  curl -X POST /auth/apps/ -H \"Authorization: Bearer \<token\>\" -d \'{\"name\":\"My
  App\"}\'

  \# 4. Create API key

  curl -X POST /auth/apps/1/keys/ -H \"Authorization: Bearer \<token\>\" -d
  \'{\"name\":\"prod\"}\'
  -----------------------------------------------------------------------------------------

44. Update all callers to use Authorization: Bearer ffk\_\... instead of
    X-App-Owner.

45. Once all callers are migrated, the X-App-Owner fallback can be
    disabled by removing the legacy branch from \_resolve_owner in
    storage/views.py.

**10.3 Legacy Header Fallback**

During migration, the X-App-Owner header still works for unauthenticated
requests. Priority order in \_resolve_owner:

46. API key present → owner_slug from ApiKey.app (authoritative).

47. No API key, X-App-Owner header present → use header value (legacy).

48. Neither present → FILEFORGE_DEFAULT_OWNER setting (\"default\").

**11. Error Handling**

**11.1 HTTP Status Codes**

  -----------------------------------------------------------------------
  **Code**              **Meaning**
  --------------------- -------------------------------------------------
  200 OK                Request succeeded.

  201 Created           Resource created.

  202 Accepted          File upload accepted; background task queued.

  204 No Content        Delete succeeded.

  400 Bad Request       Validation error, unsupported operation, or bad
                        credentials.

  401 Unauthorized      Missing, invalid, revoked, or expired API key or
                        JWT.

  403 Forbidden         Valid authentication but insufficient permission.

  404 Not Found         Resource not found or belongs to a different
                        App/Developer.

  413 Request Entity    File exceeds FILEFORGE_MAX_UPLOAD_SIZE or sync
  Too Large             threshold.

  502 Bad Gateway       The underlying provider returned an error.

  500 Internal Server   Unexpected server error.
  Error
  -----------------------------------------------------------------------

**11.2 Error Response Shape**

  -----------------------------------------------------------------------
  // Standard errors

  { \"detail\": \"API key is inactive or expired.\" }

  // Validation errors include per-field detail

  {

  \"password_confirm\": \[\"Passwords do not match.\"\],

  \"provider\": \[\"Unknown provider \\\"s3\\\". Available: cloudinary,
  google_drive\"\]

  }
  -----------------------------------------------------------------------

**11.3 Authentication Errors**

  -----------------------------------------------------------------------
  **Scenario**                    **Response**
  ------------------------------- ---------------------------------------
  No Authorization header on      401 --- A valid API key is required.
  /api/ endpoint

  Bearer token doesn\'t start     401 --- Invalid API key.
  with ffk\_

  Key hash not found in database  401 --- Invalid API key.

  Key is_active = false           401 --- API key is inactive or expired.

  Key expires_at in the past      401 --- API key is inactive or expired.

  App is_active = false           401 --- This app has been deactivated.

  Developer is_active = false     401 --- Developer account is
                                  deactivated.

  API key used on a /auth/        401/403 --- JWT required; API key auth
  endpoint                        rejected.

  JWT used on a /api/ endpoint    401/403 --- API key required; JWT auth
                                  rejected.
  -----------------------------------------------------------------------

**12. Background Tasks**

**12.1 Django-Q2 Configuration**

Django-Q2 uses an ORM broker --- no Redis required. The worker is
started in run.sh alongside the web server:

  -----------------------------------------------------------------------
  python manage.py qcluster &

  -----------------------------------------------------------------------

  ---------------------------------------------------------------------------
  **Setting**     **Default**   **Description**
  --------------- ------------- ---------------------------------------------
  workers         2             Parallel worker threads.

  timeout         600           Task timeout in seconds.

  retry           660           Seconds before a timed-out task is retried.

  queue_limit     50            Max queued tasks.

  sync            0             Set FILEFORGE_Q\_SYNC=1 for synchronous
                                execution (tests/dev).

  save_limit      250           Completed task records to retain in the DB.
  ---------------------------------------------------------------------------

**12.2 process_file_upload**

Transitions a File through pending → uploading → completed\|failed.
Deletes the temp file on completion or failure. If the temp file is
missing, the File immediately transitions to failed.

**12.3 cleanup_temp_files**

Removes orphaned temp files older than 24 hours. Run manually with:

  -----------------------------------------------------------------------
  python manage.py cleanup_temp \--max-age 86400

  -----------------------------------------------------------------------

**12.4 Synchronous Fallback**

If no Q2 cluster is running, FileForge falls back to executing
process_file_upload synchronously in-process. The 202 response is still
returned, but the file is already completed (or failed) by the time it
arrives. Set FILEFORGE_Q\_SYNC=1 to force this in tests.

**13. Integration Examples**

**13.1 Complete Onboarding --- Python**

  -----------------------------------------------------------------------
  import requests, time

  BASE = \'http://localhost:5000\'

  \# 1. Register developer account

  requests.post(f\'{BASE}/auth/register/\', json={

  \'email\': \'dev@example.com\',

  \'password\': \'StrongPass123!\',

  \'password_confirm\': \'StrongPass123!\'

  })

  \# 2. Obtain JWT

  r = requests.post(f\'{BASE}/auth/token/\',

  json={\'email\': \'dev@example.com\', \'password\':
  \'StrongPass123!\'})

  access_token = r.json()\[\'access\'\]

  mgmt = {\'Authorization\': f\'Bearer {access_token}\'}

  \# 3. Create an App

  app = requests.post(f\'{BASE}/auth/apps/\', json={\'name\': \'My
  App\'}, headers=mgmt).json()

  app_id = app\[\'id\'\]

  \# 4. Create an API key --- store raw_key immediately!

  key_resp = requests.post(f\'{BASE}/auth/apps/{app_id}/keys/\',

  json={\'name\': \'production\'}, headers=mgmt).json()

  api_key = key_resp\[\'raw_key\'\] \# e.g. ffk_xK3mAbc123\...

  storage = {\'Authorization\': f\'Bearer {api_key}\'}

  \# 5. Register provider credentials

  requests.post(f\'{BASE}/api/credentials/\', json={

  \'provider\': \'cloudinary\',

  \'credentials\': {\'cloud_name\': \'my-cloud\', \'api_key\': \'123\',
  \'api_secret\': \'secret\'}

  }, headers=storage)

  \# 6. Upload a file

  with open(\'photo.jpg\', \'rb\') as f:

  resp = requests.post(f\'{BASE}/api/files/\',

  data={\'provider\': \'cloudinary\'},

  files={\'file\': (\'photo.jpg\', f, \'image/jpeg\')},

  headers=storage).json()

  file_id = resp\[\'id\'\]

  \# 7. Poll until done

  while True:

  rec = requests.get(f\'{BASE}/api/files/{file_id}/\',
  headers=storage).json()

  if rec\[\'status\'\] in (\'completed\', \'failed\'): break

  time.sleep(2)

  print(rec\[\'url\'\] if rec\[\'status\'\] == \'completed\' else
  rec\[\'error_message\'\])
  -----------------------------------------------------------------------

**13.2 Complete Onboarding --- JavaScript**

  -----------------------------------------------------------------------
  const BASE = \'http://localhost:5000\';

  async function setup() {

  // Register

  await fetch(\`\${BASE}/auth/register/\`, {

  method: \'POST\',

  headers: { \'Content-Type\': \'application/json\' },

  body: JSON.stringify({ email: \'dev@example.com\', password:
  \'Pass123!\', password_confirm: \'Pass123!\' })

  });

  // Token

  const { access } = await fetch(\`\${BASE}/auth/token/\`, {

  method: \'POST\',

  headers: { \'Content-Type\': \'application/json\' },

  body: JSON.stringify({ email: \'dev@example.com\', password:
  \'Pass123!\' })

  }).then(r =\> r.json());

  const mgmt = { Authorization: \`Bearer \${access}\`, \'Content-Type\':
  \'application/json\' };

  // Create App

  const { id: appId } = await fetch(\`\${BASE}/auth/apps/\`, {

  method: \'POST\', headers: mgmt, body: JSON.stringify({ name: \'My
  App\' })

  }).then(r =\> r.json());

  // Create API key

  const { raw_key } = await fetch(\`\${BASE}/auth/apps/\${appId}/keys/\`,
  {

  method: \'POST\', headers: mgmt, body: JSON.stringify({ name: \'prod\'
  })

  }).then(r =\> r.json());

  return raw_key; // Store this securely!

  }
  -----------------------------------------------------------------------

**13.3 Direct Upload (Large File) --- JavaScript**

  -----------------------------------------------------------------------
  async function directUpload(file, apiKey) {

  const storage = { Authorization: \`Bearer \${apiKey}\`,
  \'Content-Type\': \'application/json\' };

  // Step 1: get ticket

  const ticket = await fetch(\`\${BASE}/api/files/direct-upload/\`, {

  method: \'POST\', headers: storage,

  body: JSON.stringify({ name: file.name, provider: \'cloudinary\', size:
  file.size, content_type: file.type })

  }).then(r =\> r.json());

  // Step 2: upload to provider

  const form = new FormData();

  Object.entries(ticket.fields).forEach((\[k, v\]) =\> form.append(k,
  v));

  form.append(\'file\', file);

  await fetch(ticket.upload_url, { method: ticket.method, body: form });

  // Step 3: notify FileForge

  return fetch(\`\${BASE}/api/files/direct-upload/complete/\`, {

  method: \'POST\', headers: storage,

  body: JSON.stringify({ file_id: ticket.file_id, provider_file_id:
  ticket.provider_ref.public_id })

  }).then(r =\> r.json());

  }
  -----------------------------------------------------------------------

**14. Security Considerations**

**14.1 API Key Handling**

-   Store API keys in environment variables or secrets managers ---
    never in source code or version control.

-   Treat an API key like a password. If a key is compromised, revoke it
    immediately via POST /auth/apps/{id}/keys/{key_id}/revoke/ and issue
    a replacement.

-   Use the key_prefix (visible in the key list) to identify which key
    is in use without exposing the full value.

-   Use expires_at for time-limited access scenarios such as CI/CD
    pipelines or contractor integrations.

**14.2 Never Expose FileForge Directly**

FileForge API keys grant full read/write access to the App\'s data.
Never expose them to browsers or end users. Always make storage API
calls from your own backend server and inject the API key server-side.

**14.3 JWT Token Security**

-   Access tokens expire after 30 minutes (configurable via
    JWT_ACCESS_MINUTES).

-   Refresh token rotation is enabled --- each refresh blacklists the
    old refresh token, limiting replay attacks.

-   Store JWTs in memory or secure httpOnly cookies. Never in
    localStorage for sensitive applications.

**14.4 Credential Storage**

Provider credentials stored in StorageCredential are saved as plaintext
JSON. For production, consider encrypting the credentials column (e.g.
with django-cryptography), or store credentials only as environment
variables.

**14.5 Temp File Security**

Incoming files are buffered to FILEFORGE_TEMP_DIR. Ensure this directory
is outside the web root and not accessible via MEDIA_URL or STATIC_URL.

**14.6 HTTPS & CSRF**

-   Run FileForge behind a TLS-terminating proxy in production. Provider
    credentials and API keys in transit must be protected.

-   CSRF_TRUSTED_ORIGINS in settings.py must include your frontend\'s
    origin.

-   Server-to-server API key calls are unaffected by CSRF (they use
    Authorization headers, not cookies).

**15. Troubleshooting**

  ------------------------------------------------------------------------------
  **Symptom**                **Likely cause**    **Fix**
  -------------------------- ------------------- -------------------------------
  401 on every /api/ request Missing or wrong    Ensure Authorization: Bearer
                             API key             ffk\_\... header is present.
                                                 Check the key is_active and not
                                                 expired.

  401 \"API key is inactive  Key was revoked or  Create a new key via POST
  or expired\"               has passed its      /auth/apps/{id}/keys/.
                             expires_at

  401 on /auth/me/ when      API key used on a   Obtain a JWT token via POST
  using an API key           JWT-only endpoint   /auth/token/ and use that for
                                                 /auth/ endpoints.

  403 on /auth/ endpoints    JWT missing or      Re-authenticate via POST
                             expired             /auth/token/ or refresh via
                                                 POST /auth/token/refresh/.

  File list returns empty    API key belongs to  Verify the API key\'s
  (files exist in DB)        a different App     owner_slug matches the owner
                             than the one that   column on the File rows.
                             uploaded the files

  File stays in \"pending\"  Django-Q2 cluster   Start with: python manage.py
  indefinitely               not running         qcluster. Or set
                                                 FILEFORGE_Q\_SYNC=1 for
                                                 synchronous execution.

  File enters \"failed\"     Missing or wrong    POST updated credentials to
  with credential error      provider            /api/credentials/ and
                             credentials         re-upload.

  400 \"Unknown provider\"   Provider not        Check GET /api/providers/ for
                             registered or       registered providers. Review
                             import failed at    startup logs for ImportError.
                             startup

  502 on                     Provider rejected   Inspect the detail field.
  /direct-upload/complete/   finalization (e.g.  Ensure provider_file_id is
                             missing             included in the complete
                             provider_file_id)   request.

  migrate_legacy_owners      No unmapped owner   Normal --- all owners are
  creates no Apps            strings in existing already mapped. Safe to run
                             data                multiple times.
  ------------------------------------------------------------------------------

**16. Testing**

**16.1 Running the Test Suite**

  -----------------------------------------------------------------------
  \# Run all tests

  python manage.py test fileforge_auth

  \# Run with verbose output

  python manage.py test fileforge_auth \--verbosity=2

  \# Run a specific test class

  python manage.py test fileforge_auth.tests.ApiKeyAuthenticationTests
  -----------------------------------------------------------------------

**16.2 Test Coverage**

  ----------------------------------------------------------------------------
  **Test class**              **What it covers**
  --------------------------- ------------------------------------------------
  ApiKeyModelTests            ApiKey.create_for_app, is_valid, touch, slug
                              generation, hash storage.

  ApiKeyAuthenticationTests   Valid key auth, invalid/revoked/expired keys,
                              inactive app/developer, last_used_at tracking.

  RegistrationTests           Register success/failure, duplicate email, token
                              obtain, wrong password.

  MeViewTests                 GET/PATCH me, change password, JWT-only access,
                              API key rejection.

  AppViewTests                App CRUD, developer scoping, duplicate name,
                              slug immutability.

  ApiKeyViewTests             Key create (raw_key once), list (no raw key),
                              revoke, expiry, cross-developer isolation.

  OwnerResolutionTests        Files/credentials scoped to owner_slug,
                              cross-app 404, two-app isolation.

  HealthViewTests             Health endpoint requires no auth.
  ----------------------------------------------------------------------------

**16.3 Useful Test Settings**

  -----------------------------------------------------------------------
  \# settings.py / .env for test runs

  FILEFORGE_Q\_SYNC=1 \# run upload tasks synchronously

  DJANGO_DEBUG=1 \# use in-memory SQLite
  -----------------------------------------------------------------------

**17. Quick Reference**

**17.1 Endpoint Summary**

  -------------------------------------------------------------------------------------------
  **Method**   **Endpoint**                            **Auth**   **Description**
  ------------ --------------------------------------- ---------- ---------------------------
  POST         /auth/register/                         Public     Create developer account

  POST         /auth/token/                            Public     Obtain JWT pair

  POST         /auth/token/refresh/                    Public     Refresh JWT pair

  GET          /auth/me/                               JWT        Get developer profile

  PATCH        /auth/me/                               JWT        Update profile

  POST         /auth/me/change-password/               JWT        Change password

  GET          /auth/apps/                             JWT        List apps

  POST         /auth/apps/                             JWT        Create app

  GET          /auth/apps/{id}/                        JWT        Get app

  PATCH        /auth/apps/{id}/                        JWT        Update app

  DELETE       /auth/apps/{id}/                        JWT        Delete app

  GET          /auth/apps/{id}/keys/                   JWT        List API keys

  POST         /auth/apps/{id}/keys/                   JWT        Create API key (returns
                                                                  raw_key once)

  POST         /auth/apps/{id}/keys/{key_id}/revoke/   JWT        Revoke API key

  GET          /api/health/                            Public     Liveness probe

  GET          /api/providers/                         API Key    List providers

  GET          /api/credentials/                       API Key    List credentials

  POST         /api/credentials/                       API Key    Create/upsert credential

  GET          /api/credentials/{id}/                  API Key    Get credential

  PATCH        /api/credentials/{id}/                  API Key    Update credential

  DELETE       /api/credentials/{id}/                  API Key    Delete credential

  GET          /api/files/                             API Key    List files

  POST         /api/files/                             API Key    Upload file (async)

  GET          /api/files/{id}/                        API Key    Get file

  PATCH        /api/files/{id}/                        API Key    Rename file

  DELETE       /api/files/{id}/                        API Key    Delete file

  POST         /api/files/direct-upload/               API Key    Initiate direct upload

  POST         /api/files/direct-upload/complete/      API Key    Finalize direct upload
  -------------------------------------------------------------------------------------------

**17.2 Authentication Header Cheatsheet**

  -----------------------------------------------------------------------
  \# Management API (register, login, apps, keys)

  Authorization: Bearer \<JWT access token\>

  \# Storage API (files, credentials, providers)

  Authorization: Bearer ffk\_\<api_key\>

  \# Health check --- no header needed

  GET /api/health/
  -----------------------------------------------------------------------

**17.3 File Status Lifecycle**

  -----------------------------------------------------------------------
  POST /api/files/

  │

  ▼

  pending ← File record created, task queued

  │

  ▼

  uploading ← Background worker transferring bytes

  │

  ┌────┴────┐

  ▼ ▼

  completed failed ← check error_message on failure
  -----------------------------------------------------------------------

**17.4 Provider Credential Fields**

  ------------------------------------------------------------------------
  **Provider**    **Required fields**               **Optional fields**
  --------------- --------------------------------- ----------------------
  cloudinary      url OR (cloud_name + api_key +    folder, resource_type
                  api_secret)

  google_drive    service_account_json OR           folder_id
                  service_account_file
  ------------------------------------------------------------------------

**17.5 Key Environment Variables**

  -----------------------------------------------------------------------------
  **Variable**                      **Purpose**
  --------------------------------- -------------------------------------------
  SESSION_SECRET                    Django secret key --- always set in
                                    production

  JWT_ACCESS_MINUTES                Access token lifetime (default: 30)

  JWT_REFRESH_DAYS                  Refresh token lifetime (default: 7)

  FILEFORGE_MAX_UPLOAD_SIZE         Hard file size limit (default: 100 MB)

  FILEFORGE_DEFAULT_MAX_SYNC_SIZE   Sync upload threshold (default: 5 MB)

  FILEFORGE_Q\_SYNC                 Set to 1 for synchronous background tasks

  CLOUDINARY_URL                    Full Cloudinary connection URL

  GOOGLE_SERVICE_ACCOUNT_JSON       Google service account key (JSON string)

  GOOGLE_DRIVE_FOLDER_ID            Target Drive folder ID
  -----------------------------------------------------------------------------