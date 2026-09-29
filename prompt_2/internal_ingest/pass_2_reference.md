---
status: implemented
title: Pass 2 reference — file reserve and complete
date: 2026-09-28
notes: Implementation record and retest guide. Not product truth. Product truth is prompt_2/current.md.
---

# Pass 2 reference — file reserve and complete

Parent plan: `prompt_2/internal_ingest_plan.md` (T3, T4). Spec: `prompt_2/internal_ingest/pass_2_file_ingest.md`.

Gate passed 28 Sep 2026 on the running Compose stack. `cd backend && uv run python -m scripts.internal_ingest_proof` printed `PASS file ingest`.

This pass adds the two machine file routes. It does not add connector routes, live dashboard stats, or Configuration UI. Product truth was updated in pass 4 (`prompt_2/current.md`).

## What the routes do

`POST /internal/ingest/files` reserves a `file_id` and a presigned PUT. The pipeline writes the bytes to MinIO. This API never accepts the file body.

`POST /internal/ingest/files/{file_id}/complete` HEADs that object, upserts `files`, and bulk-indexes the chunks the caller sends. Re-sync of the same `(ingestion_type, original_source)` keeps `file_id`, so `file_acl` survives a successful complete.

`/files/uploads` and the folder CLI are unchanged. Nothing on this path calls `detect_file_type`, the 600/75 chunker, or `UploadService`. Nothing auto-grants `file_acl`. OpenSearch writes stay basic `admin` inside `backend/app/services/opensearch_ingest.py`. The ingest JWT is not forwarded.

## Settings

In `backend/app/core/config.py`:

| Setting | Env | Default |
| --- | --- | --- |
| `minio_presign_endpoint` | `MINIO_PRESIGN_ENDPOINT` | `minio:9000` |
| `minio_presign_expiry_seconds` | `MINIO_PRESIGN_EXPIRY_SECONDS` | `3600` |
| `pipeline_max_upload_bytes` | `PIPELINE_MAX_UPLOAD_BYTES` | `104857600` (100 MiB) |

`minio_endpoint` stays `localhost:9000`. HEAD and GET use that client. The presigned URL is signed for `minio_presign_endpoint` so a container on the compose network can PUT.

The three keys are comments in `backend/.env.sample`. They are not required keys in `setup/lib/env.sh`. Defaults are enough. The live root `.env` was not changed.

Human uploads still use `ingest_max_upload_bytes` (25 MiB).

## MinIO

`MinioStore` in `backend/app/services/minio_store.py`:

- `presigned_put_url(object_store_path, *, expires_seconds) -> str` builds a second `Minio` client on `minio_presign_endpoint`. It does not replace `minio_client()`.
- minio-py calls GetBucketLocation before signing unless a region is set. That call would dial `minio:9000` from the host, which cannot resolve it. The presign client is given the region already known to the host client (`us-east-1` on this stack), so signing stays local.
- `stat_object_size(object_store_path) -> int | None` is the HEAD used on complete. A missing key (`NoSuchKey` / `NoSuchObject`) returns `None`. It does not return `0`. Other S3 errors propagate.

## Reserve

`POST /internal/ingest/files`. Router `backend/app/api/routes/internal_ingest.py`, prefix `/internal`, tag `internal-ingest`, dependency `require_ingest_service` only. Registered from `backend/app/api/router.py`.

Body (`backend/app/schemas/internal_ingest.py`, extra fields forbidden):

| Field | Required | Notes |
| --- | --- | --- |
| `filename` | yes | Passed through `safe_filename`. Basename only. |
| `size_bytes` | yes | Below 1 or above `pipeline_max_upload_bytes` is 413. |
| `ingestion_type` | yes | Must be one of `FILE_INGESTION_TYPES` from pass 1. |
| `original_source` | yes | Stable source URI. Stripped. Empty is 422. |
| `content_type` | no | Accepted and ignored. `files` has no MIME column. |

`file_id`, `allowed_roles`, `allowed_groups`, `embedding`, and `object_store_path` are extra fields, so they are 422.

Upsert key is `(ingestion_type, original_source)`:

1. If a `files` row exists for that pair, reuse its `id`.
2. Else if the newest `ingest_jobs` row for that pair is `reserved` or `failed`, reuse that `file_id`.
3. Else allocate a new UUID.

The new job's path is `files/{ingestion_type}/{file_id}/{safe_name}`. A changed safe name changes that job's path. A completed `files.object_store_path` is not updated until complete succeeds. Each reserve inserts a new `ingest_jobs` row with status `reserved`. No `files` row is inserted.

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

## Complete

`POST /internal/ingest/files/{file_id}/complete`. 404 when no `ingest_jobs` row exists for that id. The latest job wins.

Body (extra forbidden):

| Field | Required | Notes |
| --- | --- | --- |
| `size_bytes` | yes | Must match the object size from HEAD and the job's declared size. |
| `file_type` | yes | 1–32 characters, no dot, no slash. Not passed through `detect_file_type`. |
| `chunks` | yes | Non-empty `{seq: int >= 0, content: non-empty str}`. `seq` unique. |

| Latest job status | Behavior |
| --- | --- |
| `completed` and `size_bytes` equals the body | 409, detail `already completed`. No re-index. |
| `completed` and size differs | 409, detail says reserve again. |
| `failed` or `expired` | 409, detail says reserve again. |
| `reserved` | Continue. |

HEAD via `stat_object_size`:

- Missing object → 409 `object not found`. The job stays `reserved`.
- Present, but size differs from the body or from the job → 422 `object size does not match size_bytes`. The job stays `reserved`.
- MinIO error other than a missing key → 502 `object store unavailable`.

Then upsert `files` with that `file_id`, the job path, `file_type`, `size_bytes`, `ingestion_type`, and `original_source`. `updated_at` is now. The first insert sets `uploaded_at` to now. A reuse keeps `uploaded_at`.

### Chunk documents

`build_chunk_document` in `backend/app/services/opensearch_ingest.py` takes `ingestion_type: str = "local"`, plus optional `allowed_roles` and `allowed_groups`. HTTP upload and the folder CLI still use the defaults, so their documents stay `ingestion_type: "local"` and empty ACL lists.

`chunk_id` is `{file_id}:{seq:06d}`. The bulk `_id` is that same value. The document omits `embedding`. `_empty` is stripped if a caller passes it.

Allowed names come from `recompute_allowed_names` in `backend/app/services/file_acl_admin.py`:

- No role or group grants → `allowed_roles` and `allowed_groups` are `[]`.
- Role or group grants → those names. User-principal grants are ignored. `_empty` is never written.

Bulk uses the existing `bulk_index_chunks` (basic `admin`, `refresh=wait_for`). The same `_id` overwrites on re-sync, so ACL names reload without a separate update-by-query.

The ingest pipeline may still store a vector on the indexed hit. That vector is not in the document this API sends.

### Failure after the files upsert

`InternalIngestService._compensate` follows `compensate_local_ingest` with one difference: it does not delete the MinIO object.

- Roll back the session.
- `delete_chunks_by_file_id`.
- Delete the `files` row when this attempt inserted or updated it. `file_acl` is ON DELETE CASCADE, so a failed re-complete drops grants. The success path is what keeps them.
- Set the job to `failed` and store `error` (truncated to 4000 characters).
- Leave the object for retry.

The job is marked `completed` and `completed_at` is set only after bulk index and commit succeed. The proof covers the success path. It does not force an OpenSearch failure.

A validation failure before the upsert (409 already completed, 409 missing object, 422 size mismatch) does not compensate and does not mark the job failed.

## Files touched

| Path | Change |
| --- | --- |
| `backend/app/core/config.py` | Three settings above. |
| `backend/.env.sample` | Commented defaults. Not required by setup. |
| `backend/app/services/minio_store.py` | `presigned_put_url`, `stat_object_size`. |
| `backend/app/services/opensearch_ingest.py` | `ingestion_type` and allowed-name arguments on `build_chunk_document`. Still omits `embedding`. |
| `backend/app/schemas/internal_ingest.py` | Reserve and complete models. `extra=forbid`. |
| `backend/app/services/internal_ingest.py` | Reserve, complete, compensate. |
| `backend/app/api/routes/internal_ingest.py` | The two routes. |
| `backend/app/api/router.py` | Registers that router. |
| `backend/app/api/deps.py` | Comment only. `require_ingest_service` was already the gate. |
| `backend/scripts/internal_ingest_proof.py` | File-half proof. `main()` is where pass 3 and pass 4 append connector cases. |

Not changed: `backend/app/api/routes/files.py`, `backend/app/services/upload.py`, `backend/scripts/ingest_folder.py`, `ingest_local_bytes`, `prompt_2/current.md`, root `README.md`, `prompts/`.

## Proof result

Command, from `backend/`, with the stack and `./start-dev.sh` already up:

```text
[ok] 1 no token 401; realm-admin and searcher 403 on reserve and complete
[ok] 2 reserved <file_id> path=files/pipeline/<file_id>/pass2-note.md with no files row
[ok] 3 PUT 29 bytes via compose network curl from the opensearch container (presign host minio)
[ok] 4 complete indexed <file_id>:000000 ingestion_type=pipeline allowed_*=[] file_acl=0
[ok] 5 re-reserve kept file_id; chunk allowed_roles includes search-user; file_acl kept
[ok] 6 complete without a new reserve is 409, including a different size
[ok] 7 over 100 MiB or below 1 is 413; file_id, embedding, bad type, and bad name are 422; size mismatch is 422
[ok] 8 missing object is 409; human upload still rejects a non-pdf/txt/csv file
PASS file ingest
```

Step 4 uses `file_type` `log`, which is outside the pdf/txt/csv allowlist, so complete is not calling `detect.py`. The human route still returns 415 for `pass2-reject.log`.

Step 5 grants `search-user` viewer through `POST /admin/files/{id}/acl`, waits until that ACL sync job is `succeeded`, then reserves the same source, PUTs again, and completes. `uploaded_at` stays the same. `file_id` stays the same. The chunk's `allowed_roles` includes `search-user`.

Each run uses a fresh `original_source`, so it does not collide with a previous proof file. It leaves the new `files` row, the MinIO object, the OpenSearch chunk, and the one `file_acl` grant in place.

The first proof run granted ACL and completed in the same window, and the background update-by-query logged a version conflict. The chunk names still came from complete. The script now waits for that job before the second complete so the log stays quiet. Complete is still what reloads `allowed_roles`.

# Test guide

Use this when you need to re-check pass 2 later. Do not start pass 3 if the script fails.

## What must already be running

- Compose: Postgres, Keycloak, MinIO, OpenSearch (`docker compose up -d`).
- API on `http://localhost:8000` (`./start-dev.sh` or `cd backend && uv run enterprise-search-api`). Code changes reload under `start-dev.sh`.
- Root `.env` with `KEYCLOAK_INGEST_SECRET` (pass 1). Demo value `ingest-client-secret`.
- Pass 1 migration `d4e5f6a7b8c9` applied (`cd backend && uv run alembic upgrade head`).
- Docker available to the proof process. The default presign host is `minio:9000`, which the host cannot resolve.

The proof chooses the PUT path itself:

- URL host `localhost` or `127.0.0.1`: httpx from the host. Use this only after you set `MINIO_PRESIGN_ENDPOINT=localhost:9000` and restart the API.
- Any other host, including the default `minio`: `docker compose exec` curl from the `opensearch` container, which is on the compose network and can resolve `minio`.

The gate run used the compose curl. Say which line the script prints under step 3 if you change the endpoint.

## Automated gate

```bash
cd /home/aditya/repos/my_enterprise_search/backend
uv run python -m scripts.internal_ingest_proof
```

Expect `PASS file ingest` and exit code 0. A Postgres collation warning is harmless. Connector cases are not in this script yet. `main()` is the append point.

What it checks:

1. No bearer → 401 on both routes. `realm-admin` and `searcher` bearers → 403 on both routes.
2. Ingest token reserves `ingestion_type=pipeline`. Path is `files/pipeline/{file_id}/pass2-note.md`. No `files` row. Latest job is `reserved`.
3. PUT the reserved bytes to `upload_url`.
4. Complete with matching `size_bytes`, `file_type` `log`, and one chunk. 201. `files` row exists. MinIO size matches. OpenSearch `_id` is `{file_id}:000000`. `allowed_roles` and `allowed_groups` are `[]`. `ingestion_type` is `pipeline`. `file_acl` count is 0. `build_chunk_document` has no `embedding` key.
5. Admin grant of role `search-user` viewer. Second reserve of the same source returns the same `file_id`. PUT again. Complete. Chunk `allowed_roles` includes `search-user`. The `file_acl` row is still there. `uploaded_at` is unchanged.
6. Complete again with the same size → 409 `already completed`. Complete with a different size → 409 telling the caller to reserve again.
7. `size_bytes` of `104857601` or `0` → 413. Body fields `file_id` or `embedding`, ingestion type `not-a-type`, or filename `..` → 422. A PUT whose object size does not match the complete body → 422.
8. Complete with no object → 409. `POST /files/uploads` as `searcher` with `pass2-reject.log` → 415.

## Manual walkthrough

From the repo root, with `.env` loaded:

```bash
set -a
source .env
set +a
KC="${KEYCLOAK_URL:-http://localhost:8080}/realms/enterprise-search-realm/protocol/openid-connect/token"

ingest=$(curl -fsS -X POST "$KC" \
  -d grant_type=client_credentials \
  -d client_id=ingest-client \
  -d client_secret="$KEYCLOAK_INGEST_SECRET" | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')

admin=$(curl -fsS -X POST "$KC" \
  -d grant_type=password \
  -d client_id=api-client \
  -d client_secret="$KEYCLOAK_API_SECRET" \
  -d username=realm-admin \
  -d password=adminpass | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')

searcher=$(curl -fsS -X POST "$KC" \
  -d grant_type=password \
  -d client_id=api-client \
  -d client_secret="$KEYCLOAK_API_SECRET" \
  -d username=searcher \
  -d password=searcherpass | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')
```

Auth:

```bash
# 401
curl -sS -o /dev/null -w "%{http_code}\n" -X POST http://localhost:8000/internal/ingest/files \
  -H 'Content-Type: application/json' \
  -d '{"filename":"note.md","size_bytes":4,"ingestion_type":"pipeline","original_source":"manual://auth"}'

# 403
curl -sS -o /dev/null -w "%{http_code}\n" -X POST http://localhost:8000/internal/ingest/files \
  -H "Authorization: Bearer $admin" -H 'Content-Type: application/json' \
  -d '{"filename":"note.md","size_bytes":4,"ingestion_type":"pipeline","original_source":"manual://auth"}'
```

Reserve, PUT, complete. Pick a new `original_source` each time you want a new file. Reuse it when you want the same `file_id`.

```bash
SRC="manual://$(uuidgen)"
RESERVE=$(curl -fsS -X POST http://localhost:8000/internal/ingest/files \
  -H "Authorization: Bearer $ingest" -H 'Content-Type: application/json' \
  -d "{\"filename\":\"note.md\",\"size_bytes\":5,\"ingestion_type\":\"pipeline\",\"original_source\":\"$SRC\",\"content_type\":\"text/plain\"}")
echo "$RESERVE" | python3 -m json.tool

FILE_ID=$(echo "$RESERVE" | python3 -c 'import json,sys; print(json.load(sys.stdin)["file_id"])')
URL=$(echo "$RESERVE" | python3 -c 'import json,sys; print(json.load(sys.stdin)["upload_url"])')
printf 'hello' | docker compose exec -T opensearch \
  curl -sS -X PUT -H 'Content-Type: application/octet-stream' --data-binary @- -o /dev/null -w "%{http_code}\n" "$URL"

curl -sS -X POST "http://localhost:8000/internal/ingest/files/$FILE_ID/complete" \
  -H "Authorization: Bearer $ingest" -H 'Content-Type: application/json' \
  -d '{"size_bytes":5,"file_type":"log","chunks":[{"seq":0,"content":"hello"}]}' | python3 -m json.tool
```

Expect the PUT to print `200` and complete to return 201 with `ingestion_type` `pipeline` and `file_type` `log`. If you set `MINIO_PRESIGN_ENDPOINT=localhost:9000` and restarted the API, PUT with curl on the host instead of `docker compose exec`.

Then confirm Postgres, MinIO, and OpenSearch. `APP_USER` and `APP_DB` come from `.env`.

```bash
docker compose exec -T postgres psql -U "$APP_USER" -d "$APP_DB" -c \
  "SELECT id, object_store_path, file_type, ingestion_type, original_source FROM files WHERE id = '$FILE_ID';"

docker compose exec -T postgres psql -U "$APP_USER" -d "$APP_DB" -c \
  "SELECT status, object_store_path, size_bytes FROM ingest_jobs WHERE file_id = '$FILE_ID' ORDER BY created_at DESC LIMIT 1;"
```

OpenSearch, as basic `admin` (this is a proof read, not the product search path):

```bash
curl -sS -u "admin:$OPENSEARCH_INITIAL_ADMIN_PASSWORD" \
  "http://localhost:9200/enterprise-search-chunks/_doc/${FILE_ID}:000000" | python3 -m json.tool
```

Expect `_id` `{file_id}:000000`, `ingestion_type` `pipeline`, `allowed_roles` `[]`, `allowed_groups` `[]`. `embedding` may be present on the stored hit because the ingest pipeline fills it. It is not part of the JSON this API sent.

Repeat the reserve with the same `SRC`. `file_id` must match. PUT the same five bytes to the new `upload_url`, then complete again. A third complete without a new reserve must be 409 with detail `already completed`.

Rejects worth re-checking by hand:

```bash
# 413
curl -sS -o /dev/null -w "%{http_code}\n" -X POST http://localhost:8000/internal/ingest/files \
  -H "Authorization: Bearer $ingest" -H 'Content-Type: application/json' \
  -d '{"filename":"big.bin","size_bytes":104857601,"ingestion_type":"pipeline","original_source":"manual://big"}'

# 422
curl -sS -o /dev/null -w "%{http_code}\n" -X POST http://localhost:8000/internal/ingest/files \
  -H "Authorization: Bearer $ingest" -H 'Content-Type: application/json' \
  -d '{"filename":"a.txt","size_bytes":4,"ingestion_type":"pipeline","original_source":"manual://extra","file_id":"00000000-0000-0000-0000-000000000001"}'

# 415 — human upload allowlist is unchanged
curl -sS -o /dev/null -w "%{http_code}\n" -X POST http://localhost:8000/files/uploads \
  -H "Authorization: Bearer $searcher" -H 'Content-Type: application/json' \
  -d '{"filename":"pass2-reject.log","size_bytes":4,"content_type":"text/plain"}'
```

## Not covered here

- Forced OpenSearch or database failure during complete. Compensation is implemented and unproven. A failed re-complete deletes the `files` row and therefore `file_acl`. The MinIO object stays.
- Connector admin routes, `POST /internal/connectors/{id}/status`, and live `GET /admin/stats`. Those are pass 3.
- Configuration UI and edits to `prompt_2/current.md` / root `README.md`. Those are pass 4.
