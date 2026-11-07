# Video upload/download/encryption flow

## Upload (admin)

1. Admin calls `POST /api/courses/admin/<course_id>/videos/` (multipart: `title`, `order`, `file`) with an admin JWT.
2. `AdminVideoListUploadApi.post` (`courses/apis.py`) validates input, calls `courses.services.create_video_upload`.
3. `create_video_upload` (`courses/services.py`):
   - creates a `Video` row, status `pending`
   - streams the uploaded file to a local tmp path (`VIDEO_UPLOAD_TMP_DIR`)
   - hands off to the Celery task `encrypt_and_upload_video` (`courses/tasks.py`) and returns
4. `encrypt_and_upload_video` (async, off the request):
   - generates a random 256-bit **data key (DEK)** — one per video
   - `encription_methods.encrypt_file`: AES-256-GCM encrypts the whole file with the DEK + a random 12-byte nonce (`content_nonce`) → ciphertext written to a second tmp path
   - uploads the ciphertext to MinIO at `course_<id>/video_<id>.enc` (private bucket, `storage/minio_apis.py`)
   - `encription_methods.wrap_data_key`: encrypts the DEK itself with the server's `VIDEO_MASTER_KEY` (AES-GCM, its own nonce `key_wrap_nonce`) — this is what's actually persisted in Postgres (`wrapped_data_key`), never the raw DEK
   - marks the `Video` row `ready`, deletes both tmp files (plaintext never survives past this task)

So at rest: MinIO only ever holds ciphertext; Postgres only ever holds the DEK in wrapped (encrypted) form. The only place the raw DEK exists is in-process memory during encryption and during a key request (step below).

## Download (end user / Flutter app)

1. App calls `GET /api/courses/videos/<video_id>/key/` with the user's JWT.
2. `VideoKeyApi.get` → `courses.services.get_video_download_key`:
   - 404 if the video doesn't exist or isn't `ready`
   - **403 if the requesting user has no `Enrollment` for that video's course** — this is the actual access-control gate; nothing upstream of this matters if the user hasn't paid
   - logs a `VideoKeyIssuance` audit row (user, video, IP, `X-Device-Id` header) — every key handout is traceable
   - unwraps the DEK using `VIDEO_MASTER_KEY` (server-side only, app never touches this key)
   - asks MinIO for a **presigned GET URL**, valid 10 minutes (`MINIO_PRESIGNED_URL_TTL_SECONDS`)
3. Response: `{download_url, decryption_key, nonce, expires_in}` — `decryption_key` and `nonce` are base64, `download_url` is a normal HTTPS link straight to the MinIO object.
4. App downloads the ciphertext from `download_url` (plain HTTPS GET, no auth needed — the URL itself is the credential and it expires).
5. App decrypts locally: AES-256-GCM with `decryption_key` + `nonce` over the downloaded bytes → the original video. This must happen in app-private storage (Flutter `path_provider` app-support dir), never written to `Downloads/` or any externally-shareable location, and never re-encoded/exported.

## Why this stops casual sharing, and what it doesn't stop

- Stops: copying the file out to Telegram/Drive/another device — without hitting the API again (which re-checks enrollment), a copied ciphertext file is useless, and a copied decrypted file only exists briefly in app-private storage if the app is well-behaved.
- Revocation: delete the `Enrollment` row → next key request 403s. Already-downloaded ciphertext on a device is inert without a fresh key.
- Audit: `VideoKeyIssuance` lets you spot one account hammering key requests (screen-recording farms, credential sharing) and cut off their `Enrollment`.
- Does **not** stop: a rooted/jailbroken device, a hooked app process, or plain screen recording. That requires real DRM (Widevine L1 + ExoPlayer), which is an order of magnitude more infrastructure and is not what's built here. If that becomes a real threat model, the natural next step is Play Integrity API checks before issuing keys, not rebuilding this pipeline.

## Key files

- `courses/encription_methods.py` — AES-GCM primitives (generate/wrap/unwrap DEK, encrypt file)
- `courses/tasks.py` — `encrypt_and_upload_video` Celery task
- `courses/services.py` — `create_video_upload`, `get_video_download_key`
- `courses/models.py` — `Video` (`wrapped_data_key`, `key_wrap_nonce`, `content_nonce`, `status`), `Enrollment`, `VideoKeyIssuance`
- `storage/minio_apiclient.py` / `minio_apis.py` — MinIO upload/presign/delete
