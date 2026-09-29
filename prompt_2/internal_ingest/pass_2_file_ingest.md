---
status: implemented
title: Pass 2 — internal file reserve and complete
date: 2026-09-28
notes: Implemented with the internal ingest slice. Detail and the retest guide are in pass_2_reference.md. Product truth is prompt_2/current.md. Do not edit prompts/.
---

# Pass 2 — internal file reserve and complete

Parent: `prompt_2/internal_ingest_plan.md` (T3, T4). Previous: `pass_1_auth_schema.md`. Next: `pass_3_connectors_stats.md`.

Two routes. The pipeline writes bytes to MinIO. This backend never accepts the file body.

## Goal

`POST /internal/ingest/files` reserves a `file_id` and a presigned PUT. `POST /internal/ingest/files/{id}/complete` checks the object, upserts `files`, and bulk-indexes chunks. Re-sync keeps `file_id` so `file_acl` survives. `/files/uploads` and the folder CLI stay as they are.

## Do not

- Insert a `files` row on reserve. `object_store_path` is `NOT NULL` unique; View and Open would 404 on a row with no object, and a reserved path must not be listable.
- Add a backend byte-upload route. No reuse of `UploadService` or `api-client`.
- Auto-grant `file_acl`.
- Forward the ingest JWT to OpenSearch. Bulk index stays basic `admin` inside `backend/app/services/opensearch_ingest.py`.
- Call `detect.py` to allowlist `pdf` / `txt` / `csv`. The pipeline owns extraction. `file_type` on complete is the extension string the pipeline sends.
- Accept client `file_id`, `allowed_roles`, `allowed_groups`, `embedding`, an `object_store_path` override, or a `lake/` prefix.
- Delete the MinIO object on compensate. Leave it for retry.
- Change chunking of human uploads. Do not run the 600/75 chunker on this path. Chunks arrive in the complete body.

## Settings

In `backend/app/core/config.py`:

| Setting | Env | Default |
| --- | --- | --- |
| `minio_presign_endpoint` | `MINIO_PRESIGN_ENDPOINT` | `minio:9000` |
| `minio_presign_expiry_seconds` | `MINIO_PRESIGN_EXPIRY_SECONDS` | `3600` |
| `pipeline_max_upload_bytes` | `PIPELINE_MAX_UPLOAD_BYTES` | `104857600` (100 MiB) |

FastAPI keeps talking to MinIO at `minio_endpoint` (`localhost:9000` on the host). The presigned URL is signed with `minio_presign_endpoint` so a pipeline on the compose network can PUT to `minio:9000`. Add the two non-secret defaults to `backend/.env.sample` as comments or real keys. Do not put them in `setup/lib/env.sh` required keys; defaults are enough.

## Presign

Add `presigned_put_url(object_store_path, *, expires_seconds) -> str` on `MinioStore` in `backend/app/services/minio_store.py`.

Build a second `Minio` client with `settings.minio_presign_endpoint` and the same access key, secret, and `minio_secure`. Call `presigned_put_object`. Do not point the existing `minio_client()` at the compose hostname; host-side HEAD and GET must keep using `minio_endpoint`.

`stat_object` is the HEAD used on complete. Add `stat_object_size(object_store_path) -> int | None` (None when the key is missing). Do not treat a missing key as size 0.

## Path

`files/{ingestion_type}/{file_id}/{safe_name}`

`safe_name` is `safe_filename` from `backend/app/services/ingest/detect.py` (basename only). HTTP upload stays on `final_object_path` → `local/{file_id}/{safe_name}`. Do not send internal objects through `final_object_path`.

Reject `ingestion_type` outside the CHECK from pass 1. Reject `filename` that fails `safe_filename`. Reject `size_bytes` below 1 or above `pipeline_max_upload_bytes` with 413.

## `POST /internal/ingest/files`

Router `backend/app/api/routes/internal_ingest.py`, prefix `/internal`, tag `internal-ingest`. Dependency `require_ingest_service` only. Register it in `backend/app/api/router.py`.

Body (Pydantic, extra fields forbidden):

| Field | Required | Notes |
| --- | --- | --- |
| `filename` | yes | Safe basename. Not a path. |
| `size_bytes` | yes | Declared size. Checked again on complete. |
| `ingestion_type` | yes | One of the widened CHECK values. |
| `original_source` | yes | Stable source URI. Non-empty. |
| `content_type` | no | Not stored. `files` has no MIME column. |

Reject if the body contains `file_id`, `allowed_roles`, `allowed_groups`, `embedding`, or `object_store_path` (extra=forbid covers this).

Upsert key is `(ingestion_type, original_source)`:

1. If a `files` row exists for that pair, reuse its `id`.
2. Else if the newest `ingest_jobs` row for that pair is `reserved` or `failed`, reuse that `file_id` and its path.
3. Else allocate a new UUID.

Set `object_store_path` to `files/{ingestion_type}/{file_id}/{safe_name}`. On reuse, if the safe name changed, update the reserved path. Do not update a completed `files.object_store_path` until complete succeeds. The job stores the path that the PUT must use.

Insert a new `ingest_jobs` row with status `reserved`. Do not insert `files`.

Response 201:

```json
{
  "file_id": "<uuid>",
  "object_store_path": "files/<type>/<file_id>/<safe_name>",
  "upload_url": "<presigned PUT>",
  "expires_at": "<ISO-8601 UTC>"
}
```

`expires_at` is now plus `minio_presign_expiry_seconds`.

## `POST /internal/ingest/files/{id}/complete`

`id` is `file_id`. 404 when no `ingest_jobs` row exists for it.

Body (extra forbidden):

| Field | Required | Notes |
| --- | --- | --- |
| `size_bytes` | yes | Must match the object size from HEAD. |
| `file_type` | yes | Extension string, 1–32 chars, no dot, no slash. Not passed through `detect_file_type`. |
| `chunks` | yes | Non-empty list of `{seq: int >= 0, content: non-empty str}`. `seq` unique. |

Load the latest job for that `file_id`.

| Job status | Behavior |
| --- | --- |
| `completed` and `size_bytes` equals the body | 409. Do not re-index. Response detail says already completed. |
| `completed` and size differs | 409. Caller must reserve again, then complete. |
| `failed` or `expired` | 409. Reserve again. |
| `reserved` | Continue. |

HEAD the job's `object_store_path` via `stat_object_size`:

- Missing → 409.
- Present but size ≠ body `size_bytes` or ≠ job `size_bytes` → 422.

Then upsert `files` with that `file_id`, path, `file_type`, `size_bytes`, `ingestion_type`, `original_source`. Set `updated_at` to now. On first insert set `uploaded_at` to now. On reuse keep `uploaded_at`.

### Chunk documents

Add `ingestion_type: str = "local"` to `build_chunk_document` in `backend/app/services/opensearch_ingest.py`. Existing HTTP and CLI callers stay on the default.

`chunk_id` stays `{file_id}:{seq:06d}`.

Allowed names:

- No `file_acl` rows for this `file_id` → `allowed_roles` and `allowed_groups` are `[]`.
- Any role or group grants → `recompute_allowed_names` in `backend/app/services/file_acl_admin.py`. Never write `_empty`. User-principal grants stay out of the name lists (that function already ignores them).

Omit `embedding`. Bulk through the existing `bulk_index_chunks` (basic `admin`, `refresh=wait_for`). Same `_id` overwrites on re-sync, so ACL names reload without a separate update-by-query.

### Failure

On OpenSearch or database failure after the `files` upsert, compensate like `compensate_local_ingest` with one difference: do not delete the MinIO object.

- Roll back the session.
- `delete_chunks_by_file_id`.
- Delete the `files` row if this attempt inserted or updated it.
- Set the job to `failed` and store `error`.
- Leave the object.

`file_acl.file_id` is ON DELETE CASCADE. A failed re-complete that deletes the `files` row deletes grants. That matches the parent plan. The success path is the one that keeps grants. The proof below covers success, not a forced OS failure.

Mark the job `completed` and set `completed_at` only after bulk index and commit succeed.

## Leave unchanged

- `backend/app/api/routes/files.py` and `backend/app/services/upload.py`
- `backend/scripts/ingest_folder.py` and `ingest_local_bytes`
- 25 MiB human cap (`ingest_max_upload_bytes`)

## Tasks

- [x] Settings `minio_presign_endpoint`, expiry, and `pipeline_max_upload_bytes`.
- [x] `MinioStore.presigned_put_url` and `stat_object_size`. Presign host is the compose endpoint. HEAD host stays `minio_endpoint`.
- [x] `build_chunk_document(..., ingestion_type="local")`.
- [x] Schemas in `backend/app/schemas/internal_ingest.py`. Extra fields forbidden.
- [x] Service module `backend/app/services/internal_ingest.py` for reserve, complete, and compensate.
- [x] Routes under `/internal/ingest/files`. `require_ingest_service`. Register the router.
- [x] File-half of `backend/scripts/internal_ingest_proof.py` (connector cases wait for pass 3 and pass 4).
- [x] Run the test gate. Do not start pass 3 if any step fails.

## Test gate

Use the `ingest-client` client-credentials token from pass 1. API on port 8000.

1. No token → 401. `realm-admin` Bearer and `searcher` Bearer → 403 on both routes.
2. Reserve a small text object (`ingestion_type=pipeline`, a stable `original_source`). Response path matches `files/pipeline/{file_id}/{name}`. No `files` row yet. Job status `reserved`.
3. PUT the bytes to `upload_url` from the host. If the URL host is `minio:9000`, the host cannot resolve it. For this proof, either run the PUT from a compose network container or override `MINIO_PRESIGN_ENDPOINT=localhost:9000` for the API process under test. Say which one the proof used.
4. Complete with matching `size_bytes`, `file_type` `txt` (or any extension outside pdf/txt/csv, to prove `detect.py` is not the allowlist), and one chunk. Expect 201. `files` row exists. MinIO object size matches. OpenSearch chunk `_id` is `{file_id}:{seq:06d}`, `embedding` is absent from the document we sent, `allowed_*` are `[]`, `ingestion_type` is `pipeline`. `file_acl` count is 0.
5. Grant one role `file_acl` row (viewer, role `search-user`) with the existing admin ACL API or a direct insert plus the names you expect. Reserve the same `(ingestion_type, original_source)`. `file_id` is unchanged. PUT again. Complete. Chunk `allowed_roles` includes `search-user`. The `file_acl` row is still there.
6. Complete again without a new reserve → 409.
7. Reserve with `size_bytes` over 100 MiB → 413. Body field `file_id` or `embedding` → 422.
8. A missing object on complete → 409. The human upload route `POST /files/uploads` still rejects a non-pdf/txt/csv file.

Script the steps in `backend/scripts/internal_ingest_proof.py` so pass 4 can append connector cases to the same file.

## Shipped

Gate passed 28 Sep 2026. `uv run python -m scripts.internal_ingest_proof` printed `PASS file ingest`. The presigned PUT went through curl in the `opensearch` container, because the default URL host is `minio:9000`. Product truth is unchanged: do not edit `prompt_2/current.md` or the root `README.md` until pass 4.

File-by-file notes and a manual retest are in `prompt_2/internal_ingest/pass_2_reference.md`.
