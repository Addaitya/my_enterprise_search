---
status: reference
title: Pipeline contract with this backend
date: 2026-09-30
notes: Interface for the external ingestion pipeline. Not product truth. Product truth is prompt_2/current.md. The pipeline service is not in this repo.
---

# Pipeline contract with this backend

HTTP contract for the service at `INGESTION_PIPELINE_URL`. That service is not in this repo. Admins talk only to this API, which mirrors connectors and forwards connection fields. An empty pipeline URL returns 503 to the admin and never calls you.

## Contents

- [Endpoints the pipeline serves](#endpoints-the-pipeline-serves)
- [Calling this API](#calling-this-api)
- [Reserve](#reserve)
- [Complete](#complete)
- [Delete](#delete)
- [Sync status](#sync-status)
- [Sequence and gap](#sequence-and-gap)

| Direction | Auth |
| --- | --- |
| This API calls the pipeline (create, update, sync) | No `Authorization` header. |
| The pipeline calls this API (files, sync status) | Client-credentials token, realm role `ingest-service`. |

The pipeline owns credentials, scheduling, extraction, and chunk text. Bytes move only through the presigned URL from reserve. This API assigns the object key, records the file, and indexes chunks. Search hides the file until an admin grants access. It still appears in Access Control. A later reserve of the same source reloads role and group names onto the chunks.

## Endpoints the pipeline serves

One attempt, timeout 10 seconds (`INGESTION_PIPELINE_TIMEOUT_SECONDS`). No retries. A non-2xx body is discarded. There is no list, get, or delete. Keep the `id` you return stable: update and sync call that same id.

| Call | Body | Success |
| --- | --- | --- |
| `POST /connectors` | `type`, `name`, `enabled`, `schedule`, `config`, `callback_connector_id` | JSON object with a non-empty string `id` (your connector id). A bare string, an empty `id`, or any other 2xx stores nothing. |
| `PATCH /connectors/{pipeline_id}` | Same fields, only those that changed | Any 2xx. Body ignored. |
| `POST /connectors/{pipeline_id}/sync` | `{}` | Any 2xx. Body ignored. Return quickly; the sync stays open until the status callback. A failed call is already marked failed, so no callback is expected. |

Create always includes all six keys. `enabled` is a boolean (default false). `schedule` may be JSON `null`. `config` may be `{}`. `callback_connector_id` is this API’s connector UUID as a string. Store it. Status callbacks use that value, not the `id` you return. Sync does not repeat it. If the mirror insert fails after a successful create, you may keep an orphan connector. A later status call for that UUID is 404.

`config` is string-keyed, secrets included, and is not stored here. Create sends every catalog field (`""` if blank). Toggles and `cdc` are `"true"` or `"false"`. Update sends only filled fields: a missing secret stays, a present key replaces it. `schedule` is opaque text, or `null`. `enabled: false` still receives Sync Now.

Catalog types: `postgresql`, `oracle`, `sqlserver`, `sharepoint`, `salesforce`, `s3`, `azure`, `gcs`, `email`, `box`, `sap`. `config` keys match that form. Unknown types are forwarded if you accept them. `google_drive` is a legal file `ingestion_type` and is not a catalog type.

## Calling this API

```http
POST {KEYCLOAK_URL}/realms/enterprise-search-realm/protocol/openid-connect/token
grant_type=client_credentials
client_id=ingest-client
client_secret={KEYCLOAK_INGEST_SECRET}
```

Audience must be `api-client`, role `ingest-service`. Request a new token when it expires. Missing bearer is 401. Any other role, including realm `admin`, is 403. Demo secret: `ingest-client-secret`. Base URL has no `/api` prefix (`http://localhost:8000` on the host). No object-store, database, or search credentials are issued.

### Reserve

`POST /internal/ingest/files` with `Content-Type: application/json` → 201. Extra fields are 422, including `file_id`, `allowed_roles`, `allowed_groups`, `embedding`, and `object_store_path`.

| Field | Rule |
| --- | --- |
| `filename` | Stored as the basename. `reports/q1.pdf` becomes `q1.pdf`. Empty, `.`, and `..` are 422. |
| `size_bytes` | At least 1. Above 100 MiB (`104857600`) is 413. |
| `ingestion_type` | `local`, `sharepoint`, `google_drive`, `s3`, `postgresql`, `oracle`, `sqlserver`, `salesforce`, `azure`, `gcs`, `email`, `box`, `sap`, or `pipeline`. Use the connector type when it is in this list. |
| `original_source` | Required stable source URI. Leading and trailing space is stripped. With `ingestion_type`, this is the file identity. A new URI is a new file with no grants. |
| `content_type` | Optional. Ignored. |

201 body: `file_id`, `object_store_path` (`files/{ingestion_type}/{file_id}/{name}`), `upload_url`, `expires_at` (UTC, default 1 hour). Each call adds a job and reuses `file_id` when a file exists or the newest job is `reserved` or `failed`. Complete uses that newest job only. A second reserve before complete replaces the path and size you must PUT. A new filename changes that job’s path. The stored path updates only after complete succeeds.

PUT the raw bytes to `upload_url` before expiry. Send exactly `size_bytes` bytes and no `Authorization` header; an extra header breaks the signature. `Content-Type: application/octet-stream` is enough. Host is `MINIO_PRESIGN_ENDPOINT` (default `minio:9000`). If that name does not resolve, start this API with `MINIO_PRESIGN_ENDPOINT=localhost:9000`. After expiry, reserve again and PUT the new URL.

### Complete

`POST /internal/ingest/files/{file_id}/complete`. You send the chunk text. JSON body.

| Field | Rule |
| --- | --- |
| `size_bytes` | Must match the stored object and the newest reserved size. |
| `file_type` | Extension, 1–32 characters, no dot or slash. Any extension is allowed. |
| `chunks` | Non-empty `{ "seq": int >= 0, "content": non-empty string }`. `seq` unique. |

201 returns `file_id`, `status` `completed`, `object_store_path`, `file_type`, `size_bytes`, `ingestion_type`, `chunk_count`. Chunk id is `{file_id}:{seq:06d}`. The same id is overwritten on a later complete. Any chunk for that file whose seq is not in this body is deleted, so a shorter re-sync does not leave stale hits. Seqs may be non-contiguous (`0,1,2` then `0,2` removes seq `1`). This API fills the vector. Omit `embedding`.

| Result | Next step |
| --- | --- |
| 201 | Done. |
| 409 `already completed` (same size) | Already indexed. Stop. |
| 409 different size, or job `failed` / `expired` | Reserve again, PUT the new URL, complete. |
| 404 | Reserve first. |
| 409 `object not found` | Newest job stays `reserved`. PUT that job’s URL, then complete. |
| 422 size mismatch | Job stays `reserved`. PUT the reserved size, or reserve again with the real size. |
| 502 | Object store error. Complete again later. |
| 500 | Save failed, including a failure while removing omitted chunks. Job is `failed`. Reserve again. Grants on that file can be dropped. The object remains. |

### Delete

`DELETE /internal/ingest/files/{file_id}`. No body. `file_id` is the id from reserve. That id is the one file for `(ingestion_type, original_source)`.

| Result | Meaning |
| --- | --- |
| 204 | The file is gone. Empty body. A repeat, while an ingest job for that id remains, is also 204. |
| 404 `Ingest job not found` | No ingest job for that id. Local uploads and the folder CLI are not deleted. |
| 502 | Search-index delete failed. The `files` row is unchanged. Retry. |
| 500 | The database write failed after the index delete. The `files` row is unchanged. Chunks may already be gone. Retry. |
| 401 / 403 | Same auth as reserve and complete. |

204 removes OpenSearch chunks for that `file_id`, the MinIO object at the stored `files` path, and each distinct job object path. The `files` row is deleted. `file_acl` and ACL sync jobs go with it. `reserved` and `failed` jobs for that id become `expired`, so a later complete is 409 and cannot recreate the file. `completed` jobs stay, so the ingest-rate count is unchanged.

A later reserve of the same `(ingestion_type, original_source)` returns a new `file_id` with no grants. Do not complete the deleted id afterward.

### Sync status

`POST /internal/connectors/{connector_id}/status`. `connector_id` is the `callback_connector_id` from create, which is this API’s connector UUID, not your `pipeline_id`.

Body: `status` (`success` or `failed`), optional `files_count` (zero is allowed), `error`, `finished_at`, `started_at`. Extra fields are 422. `finished_at` is last sync (now, if omitted). `started_at` is ignored. `success` clears the stored error. On `failed`, send `error` or the admin sees a blank failure. Unknown UUID is 404. 200 returns the connector without `config`.

This closes only the newest open sync. A second Sync Now leaves the older row `syncing`. If none is open, the connector still updates and the response is 200. One file failure does not close the sync. Call this when the run finishes. It sets last sync. Completes in the past hour count toward ingest rate. Enabled connectors count as active. `files_count` is whatever count you choose to report.

## Sequence and gap

1. `POST /connectors`, including `callback_connector_id`, and return `{ "id": "<yours>" }`. Store `callback_connector_id`.
2. `POST /connectors/{your id}/sync` with `{}` and return 2xx. The body does not repeat the UUID.
3. Per object: reserve, PUT, complete.
4. `POST /internal/connectors/{callback_connector_id}/status`.

When that source is removed, `DELETE /internal/ingest/files/{file_id}` and do not complete afterward.

Create sends this API’s connector UUID as `callback_connector_id`. Sync does not repeat it, and the sync response is ignored. Do not read this API’s database to find the id. Also absent: connector delete and content-hash identity.

Check: reserve `pipeline` with a new `original_source`, PUT, complete with `file_type` `log` and one chunk. A second reserve returns the same `file_id`. Another complete is 409 `already completed`.

Callback id: a create stub must see `callback_connector_id` on `POST /connectors` and `{}` on sync. The admin **201** `id` equals that value. `POST /internal/connectors/{callback_connector_id}/status` with the ingest token returns **200**. The same path with your pipeline `id` does not. Unit check, no Compose: `cd backend && uv run python -m unittest tests.test_pipeline_callback_id -v`.

Shorter re-sync and source delete, unit check, no Compose: `cd backend && uv run python -m unittest tests.test_internal_ingest_stale_chunks tests.test_internal_ingest_delete -v`.
