---
status: implemented
title: Internal ingest log
date: 2026-09-28
notes: Ship dump. Not product truth. Product truth is prompt_2/current.md.
---

# Internal ingest log

Not product truth. Same role as `prompt_2/frontend_ui_log.md`. What shipped is in `prompt_2/current.md` and the root `README.md`.

This slice is the admin control plane and the machine ingest API. It is not the Airbyte, Kafka, Tika, or Spark pipeline in `prompts/instructions/2_Ingestion_pipeline.md` and `prompts/cursor_summary/12_ingestion_pipeline_proposal.md`. Those archive files stay unfinished. Do not edit `prompts/`.

## By pass

### Pass 1 — auth and schema

Keycloak confidential client `ingest-client` (service accounts on, direct access grants off). Realm role `ingest-service` only. Audience mapper `aud=api-client`. No product roles. No OpenSearch role mapping. Setting `KEYCLOAK_INGEST_SECRET`.

Alembic `d4e5f6a7b8c9`: widened `files.ingestion_type` CHECK, partial unique `(ingestion_type, original_source)` where `original_source` is not null, tables `ingest_jobs`, `connectors`, `connector_syncs`. Connector rows have no config or password column.

### Pass 2 — file reserve and complete

`POST /internal/ingest/files` reserves an `ingest_jobs` row and a presigned PUT. Path prefix `files/{type}/{file_id}/{name}`. `POST /internal/ingest/files/{id}/complete` checks the object, upserts `files`, bulk-indexes chunks as basic `admin`, and does not write `file_acl`. A second reserve of the same `(ingestion_type, original_source)` returns the same `file_id`. Re-complete reloads `allowed_*` from `file_acl`.

### Pass 3 — connector control plane and live stats

Admin routes under `/admin/connectors`. FastAPI calls `INGESTION_PIPELINE_URL`. `config` is forwarded and never stored or returned. Empty URL is 503 and inserts nothing. Unreachable URL is 502 and inserts nothing. `POST /internal/connectors/{id}/status` is `ingest-service` only and closes the open `connector_syncs` row.

`GET /admin/stats` reads Postgres: enabled connector count, completed `ingest_jobs` in the last hour, latest `connectors.last_sync_at` or `—`. The three `placeholders` flags are false. Stats do not query OpenSearch.

### Pass 4 — Configuration UI and docs

`frontend/src/api/connectors.ts` and `IngestionSection.tsx` talk to `/admin/connectors`. The catalog stays the form schema. Saved connection fields are not reloaded from GET. Dashboard cards were already bound to `placeholders.*`; they lose the badge without a data change. Static p99, searches today, total sources, connector table, and index bars stay.

Product truth and context notes were updated after the proofs below exited 0. Retest detail: `prompt_2/internal_ingest/pass_4_reference.md`.

## Routes

| Method | Path | Caller |
| --- | --- | --- |
| POST | `/internal/ingest/files` | `ingest-service` |
| POST | `/internal/ingest/files/{id}/complete` | `ingest-service` |
| POST | `/internal/connectors/{id}/status` | `ingest-service` |
| GET | `/admin/connectors` | `admin` |
| POST | `/admin/connectors` | `admin` |
| GET | `/admin/connectors/{id}` | `admin` |
| PATCH | `/admin/connectors/{id}` | `admin` |
| POST | `/admin/connectors/{id}/sync` | `admin` |
| GET | `/admin/connectors/{id}/syncs` | `admin` |

## Tables

| Table | Notes |
| --- | --- |
| `ingest_jobs` | Reserved before a `files` row. Status `reserved`, `completed`, `failed`, `expired`. |
| `connectors` | Mirror only. No source secrets. Status `pending`, `idle`, `syncing`, `success`, `failed`. |
| `connector_syncs` | History. Cascades on connector delete. Status `syncing`, `success`, `failed`. |
| `files` | `ingestion_type` CHECK includes connector types plus `local` and `pipeline`. Partial unique `(ingestion_type, original_source)`. |

## Settings

| Env | Default | Effect |
| --- | --- | --- |
| `KEYCLOAK_INGEST_SECRET` | empty in code; sample `ingest-client-secret` | Client-credentials secret for `ingest-client` |
| `INGESTION_PIPELINE_URL` | empty | Empty create and sync return 503 |
| `INGESTION_PIPELINE_TIMEOUT_SECONDS` | `10` | One httpx attempt, no retries |
| `MINIO_PRESIGN_ENDPOINT` | `minio:9000` | Host used in the presigned PUT URL |

## Proofs

28 Sep 2026, stack up, API on `:8000` with `INGESTION_PIPELINE_URL` unset:

```text
cd backend && uv run python -m scripts.internal_ingest_proof
cd backend && uv run python -m scripts.admin_stats_proof
```

`internal_ingest_proof` exited 0 (`PASS file ingest`, `PASS connectors`). `admin_stats_proof` exited 0 (`=== all admin stats proofs passed ===`, `connectors=0`, `last_sync='—'`).

Browser, signed in as `realm-admin`: dashboard cards for active connectors (0), ingestion rate, and last sync (`—`) had no Placeholder badge. p99, searches today, and total sources still did. Configuration ingestion listed no fixtures. Create with an empty pipeline URL showed “The pipeline URL is not configured.” Create with `INGESTION_PIPELINE_URL=http://127.0.0.1:9` showed “The pipeline is unreachable.” Refresh left the list empty both times. The API was then restarted with the URL unset.

## Human test

Preconditions: stack up, `cd backend && uv run alembic upgrade head`, `uv run python -m init_services`, root `.env` contains `KEYCLOAK_INGEST_SECRET`. Sign in as `realm-admin` / `adminpass`.

1. Open `/dashboard`. Active connectors, ingestion rate, and last sync have no Placeholder badge. With no connectors, the count is 0 and last sync is `—`. p99, searches today, and total sources still show Placeholder.
2. Open `/configuration`, Ingestion. The list comes from the API. It is empty, not the old eight fixtures. The section has no Placeholder badge.
3. Leave `INGESTION_PIPELINE_URL` empty. Add a connector, fill a name, save. The page shows an error that the pipeline is not configured. The list stays empty after refresh.
4. Set `INGESTION_PIPELINE_URL=http://127.0.0.1:9` and restart the API. Add again. The page shows that the pipeline is unreachable. Refresh. The connector is not listed.
5. Sync Now on a connector, if one exists from a later pipeline test, shows the same class of error while the URL is down. Do not expect a real sync in this repo.
6. Optional API check, not the SPA. With the ingest token, reserve a file, PUT bytes to the presigned URL, complete. In Access Control the file appears with no grants. Search as `searcher` does not return it until an admin grants a role or group. After a grant, a second reserve of the same source URI keeps the same file id.

## Deferred

Pipeline service, Airbyte, Kafka, Tika, Spark, source OAuth, auto-ACL, content-hash dedup, Task 7 `SKIP LOCKED` and `files_writer`. Static dashboard cards, connector table, and index bars. Other Configuration sections stay local placeholders.
