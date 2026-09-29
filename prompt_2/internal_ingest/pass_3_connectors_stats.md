---
status: implemented
title: Pass 3 — connector control plane and live stats
date: 2026-09-28
notes: Implemented with the internal ingest slice. Detail and the retest guide are in pass_3_reference.md. Product truth is prompt_2/current.md. Do not edit prompts/.
---

# Pass 3 — connector control plane and live stats

Parent: `prompt_2/internal_ingest_plan.md` (T5, T6). Previous: `pass_2_file_ingest.md`. Next: `pass_4_ui_proofs_docs.md`.

This backend is the admin BFF and the Postgres mirror. The pipeline service is not in this repo. The SPA does not call the pipeline.

## Goal

Admins create, update, list, and sync connectors through FastAPI. FastAPI calls a base URL. The pipeline reports status to `/internal`. `GET /admin/stats` reads the new tables and sets `placeholders.*` to false.

## Do not

- Build Airbyte, Kafka, Tika, Spark, or a pipeline Dockerfile.
- Persist source passwords, tokens, keys, or a `config` JSON column. Pass 1's `connectors` table has no such column. Do not add one.
- Call the pipeline with the admin JWT or the ingest JWT.
- Search or index as basic `admin` from these routes. Stats do not query OpenSearch.
- Leave a local `connectors` row when pipeline create fails.
- Flip dashboard placeholder badges in React here. The API change is enough for the existing cards to drop the badge once `placeholders.*` is false. Formatting a null last-sync is not required if the API returns the string below.

## Pipeline client

New module `backend/app/services/ingestion_pipeline.py`.

Setting `ingestion_pipeline_url: str = ""` from `INGESTION_PIPELINE_URL`. Setting `ingestion_pipeline_timeout_seconds: float = 10`.

Document the contract in the module docstring. Do not implement the other side.

| Call | Request | Success body |
| --- | --- | --- |
| `POST {base}/connectors` | `{ "type", "name", "enabled", "schedule", "config" }` | JSON object with string `id` (the pipeline connector id) |
| `PATCH {base}/connectors/{pipeline_id}` | same fields, all optional | 2xx, body ignored |
| `POST {base}/connectors/{pipeline_id}/sync` | empty object | 2xx, body ignored |

`config` is a string-keyed object of catalog field values. It is not written to Postgres.

Errors:

| Condition | HTTP from FastAPI |
| --- | --- |
| `ingestion_pipeline_url` empty or whitespace | 503, detail that the pipeline URL is not configured |
| DNS, connect, timeout | 502 |
| Pipeline status not 2xx | 502, include the pipeline status code, not the response body if it may contain secrets |
| 2xx create body missing string `id` | 502, and do not keep a local row |

Timeout is the setting above. Use `httpx`. No retries.

## Admin routes

New router `backend/app/api/routes/admin_connectors.py`, prefix `/admin`, dependency `require_admin` on every route. Register in `backend/app/api/router.py`. Schemas in `backend/app/schemas/admin_connectors.py`.

`config` is write-only. It appears on POST and PATCH. It never appears on GET.

### `GET /admin/connectors`

List mirror rows. Each item: `id`, `type`, `name`, `enabled`, `schedule`, `pipeline_connector_id`, `status`, `last_sync_at` (ISO-8601 or null), `last_error`, `created_at`, `updated_at`. No `config`.

### `POST /admin/connectors`

Body: `type`, `name`, `enabled` (default false), `schedule` (optional), `config` (object, default `{}`). `type` is a non-empty string. Do not reject types missing from the React catalog; the catalog is a form schema, not the server allowlist. Known product types are the pass 1 CHECK list except `local` and `pipeline` (`sharepoint`, `google_drive`, `s3`, `postgresql`, `oracle`, `sqlserver`, `salesforce`, `azure`, `gcs`, `email`, `box`, `sap`). Unknown types are still stored if the pipeline accepts them. Reject empty `name` with 422.

Order:

1. If the pipeline URL is empty, 503 and insert nothing.
2. Call `POST /connectors`. On failure, insert nothing and return 502.
3. Insert `connectors` with `pipeline_connector_id` set, `status=idle` when `enabled` else `pending`, `last_sync_at` null, `last_error` null.
4. Return 201 and the GET shape.

If the insert fails after the pipeline accepted the create, return 502 and do not report success. The pipeline may keep an orphan connector. Say that in the error detail. Do not try to delete it; the contract has no delete.

### `GET /admin/connectors/{id}`

404 when missing. Same shape as a list item.

### `PATCH /admin/connectors/{id}`

Partial update of `name`, `enabled`, `schedule`, `config`. At least one field. 404 when missing.

If `pipeline_connector_id` is null, 409. Create should not have stored that state.

Call `PATCH` on the pipeline first. On 502/503, do not change the local row. On 2xx, apply the local column changes (`config` is not a column). Return the GET shape.

### `POST /admin/connectors/{id}/sync`

404 when missing. 409 when `pipeline_connector_id` is null.

1. Insert `connector_syncs` with `status=syncing`, `started_at=now`.
2. Set `connectors.status=syncing` and commit.
3. Call pipeline `POST .../sync`.
4. On 502/503, set that sync row to `failed`, `finished_at=now`, `error` to a short message, and `connectors.status=failed`, `last_error` the same message. Return the 502/503. The sync row remains as history.
5. On 2xx, leave the sync row `syncing`. The pipeline closes it with the status callback. Return 202 and `{ "sync_id", "status": "syncing" }`.

### `GET /admin/connectors/{id}/syncs`

Newest first. Fields: `id`, `connector_id`, `status`, `started_at`, `finished_at`, `files_count`, `error`.

## Internal callback

`POST /internal/connectors/{id}/status` on the internal router from pass 2. `require_ingest_service`. `id` is our connector UUID, not `pipeline_connector_id`.

Body: `status` (`success` or `failed`), `files_count` (int, optional), `error` (string, optional), `started_at` and `finished_at` (optional datetimes). Extra fields forbidden.

404 when the connector is missing.

Update `connectors.status`, `last_error` (null on success), and `last_sync_at` from `finished_at` or now.

Update the open sync row: newest `connector_syncs` row for this connector with `status=syncing`. Set `status`, `finished_at`, `files_count`, `error`. If none is open, still update the connector row and return 200. Do not insert a sync row from the callback.

Return 200 and the connector GET shape. Admin-only fields are fine on this response; the caller is the ingest service, not the SPA.

## Live stats

`backend/app/services/admin_stats.py` and `backend/app/schemas/admin_stats.py`.

| Field | Value |
| --- | --- |
| `active_connectors` | `COUNT(*)` from `connectors` where `enabled` is true. `0` when the table is empty. |
| `ingestion_rate_docs_per_hour` | `COUNT(*)` from `ingest_jobs` where `status=completed` and `completed_at` is in the last hour. Do not also count `files.updated_at`. |
| `last_sync` | Latest `connectors.last_sync_at` as ISO-8601 UTC. None → the string `—` (U+2014). Keep the field a string so `frontend/src/api/stats.ts` does not need a type change in this pass. |
| `placeholders.active_connectors` | false |
| `placeholders.ingestion_rate_docs_per_hour` | false |
| `placeholders.last_sync` | false |

Remove `PLACEHOLDER_ACTIVE_CONNECTORS`, `PLACEHOLDER_INGESTION_RATE_DOCS_PER_HOUR`, and `PLACEHOLDER_LAST_SYNC`.

Leave `avg_query_time_ms`, `total_data_ingested_bytes`, and `total_docs_indexed` as they are. MinIO failure stays 502.

`Dashboard.tsx` already sets `placeholder` from `stats.placeholders.*`. After this pass those three cards lose the Placeholder badge. The static p99, searches-today, and total-sources cards stay placeholders. Do not wire them.

## Proof updates

`backend/scripts/admin_stats_proof.py` currently asserts `8`, `12400`, and `"2 min ago"`, and `placeholders.* is True`. Change proof 3 to:

- `active_connectors` is an int and equals `SELECT count(*) FROM connectors WHERE enabled`.
- `ingestion_rate_docs_per_hour` is an int and equals completed `ingest_jobs` in the last hour.
- `last_sync` is `—` or a string that parses as ISO-8601.
- All three `placeholders` flags are false.
- Proofs 1, 2, and 4 stay (401, 403, avg after search).

Append connector cases to `backend/scripts/internal_ingest_proof.py`:

1. `INGESTION_PIPELINE_URL` empty → `POST /admin/connectors` returns 503 and `connectors` count is unchanged.
2. URL set to an unreachable host (for example `http://127.0.0.1:9`) → 502 and no new row.
3. Insert a connector row directly (pipeline id set) or, if a local stand-in is too heavy, call the status route against a row inserted in SQL. `POST /internal/connectors/{id}/status` with the ingest token sets `status`, `last_sync_at`, and closes the open `connector_syncs` row. `realm-admin` on that internal route → 403.

Do not require a real pipeline for the gate.

## Tasks

- [x] Settings `ingestion_pipeline_url` and timeout. Sample comment in `backend/.env.sample`. Empty default.
- [x] Typed client in `backend/app/services/ingestion_pipeline.py` with the contract docstring. 503 when the URL is empty. 502 on network errors and non-2xx.
- [x] Schemas and `admin_connectors` router. Write-only `config`. Create inserts only after the pipeline returns an id.
- [x] `POST /internal/connectors/{id}/status`.
- [x] Live stats. Delete the three placeholder constants. Flags false. `last_sync` is ISO-8601 or `—`.
- [x] Update `backend/scripts/admin_stats_proof.py`. Append connector cases to `backend/scripts/internal_ingest_proof.py`.
- [x] Run the test gate. Do not start pass 4 if any step fails.

## Test gate

1. `uv run python -m scripts.admin_stats_proof` passes with the new assertions.
2. Connector proof steps above pass.
3. `GET /admin/stats` as `realm-admin` shows `placeholders` all false. With no connectors, `active_connectors` is 0 and `last_sync` is `—`.
4. A completed `ingest_jobs` row with `completed_at` inside the last hour increases `ingestion_rate_docs_per_hour` by 1. A `local` HTTP upload does not, unless it also completed an `ingest_jobs` row (it must not).
5. `GET /admin/connectors` does not return any field named `config`, `password`, `secret`, or `token`.
