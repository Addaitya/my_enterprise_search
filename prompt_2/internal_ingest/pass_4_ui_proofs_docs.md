---
status: implemented
title: Pass 4 — Configuration UI, proofs, and product truth
date: 2026-09-28
notes: Implemented 28 Sep 2026. Browser steps 1–4 and both proof scripts passed. Product truth is prompt_2/current.md. Retest guide is pass_4_reference.md. Do not edit prompts/.
---

# Pass 4 — Configuration UI, proofs, and product truth

Parent: `prompt_2/internal_ingest_plan.md` (T7, T8, T9). Previous: `pass_3_connectors_stats.md`.

This is the last pass. The test gate passed and the product-truth edits landed. `prompt_2/current.md` is the live description.

## Goal

The Configuration ingestion section lists, creates, updates, and syncs connectors through `/admin/connectors`. Proof scripts cover reserve → PUT → complete and the connector 502/503 paths. Product docs match the new behavior. A human test guide is written down.

## Do not

- Add a pipeline service, Airbyte, Kafka, Tika, or Spark.
- Let the browser call `INGESTION_PIPELINE_URL`.
- Round-trip `config` into React state from GET. The API does not return it.
- Remove `CONNECTOR_CATALOG`. It stays the form schema.
- Remove the static Dashboard cards for p99, searches today, and total sources, or the static connector table and index bars. Those are still placeholders. Only the three API-backed cards (active connectors, ingest rate, last sync) lose their Placeholder badge.
- Invent a Task 7 plan. Do not map `files_writer`.
- Edit `prompts/`.

## Frontend

### API helper

Add `frontend/src/api/connectors.ts`. Use `apiGet`, `apiPostJson`, and `apiPatchJson` from `frontend/src/api/client.ts`.

```ts
type Connector = {
  id: string
  type: string
  name: string
  enabled: boolean
  schedule: string | null
  pipeline_connector_id: string | null
  status: 'pending' | 'idle' | 'syncing' | 'success' | 'failed'
  last_sync_at: string | null
  last_error: string | null
  created_at: string
  updated_at: string
}

type ConnectorWrite = {
  type: string
  name: string
  enabled: boolean
  schedule: string | null
  config: Record<string, string>
}
```

| Function | Call |
| --- | --- |
| `listConnectors` | `GET /admin/connectors` |
| `createConnector` | `POST /admin/connectors` |
| `updateConnector` | `PATCH /admin/connectors/{id}` |
| `syncConnector` | `POST /admin/connectors/{id}/sync` |

Surface `ApiError.status` so the page can tell 502 from 503.

### Ingestion section

Replace the fixture state in `frontend/src/components/config/IngestionSection.tsx`.

- On mount, `listConnectors`. Show a loading row and an error banner. Do not fall back to `CONNECTOR_FIXTURES`.
- Remove the header sentence "Local placeholders. None of these are connected." and the section Placeholder badge.
- Status column shows `status`. When `last_error` is set, show it as secondary text.
- Enabled toggle calls `updateConnector` with `{ enabled }`. On failure, put the toggle back and show the error.
- Sync Now calls `syncConnector`. 503 copy: pipeline URL is not configured. 502 copy: pipeline is unreachable. Do not pretend the sync started.
- Add connector still opens the catalog picker (`CONNECTOR_CATALOG` only). Save on a new draft calls `createConnector` with `config` set from the field values, including toggles as `"true"` / `"false"`. Schedule is the `schedule` field, not inside `config`.
- The fixture `cdc` toggle is not a column. Send it inside `config` as `cdc` when the form still shows it. Do not add a database column.
- Editing an existing row: name, enabled, and schedule load from the API. Catalog fields start empty. Helper text: saved connection fields are not shown again; leave a field blank to keep the pipeline's current value, or fill it to replace it. PATCH sends only the fields the human changed. Omit empty secret fields so a blank password is not forwarded.
- `isSensitiveField` in `frontend/src/config/placeholders.ts` stays. Keep using it for password inputs.
- Delete the unused `CONNECTOR_FIXTURES` export only if nothing else imports it. `CONFIG_SECTIONS` and the other Configuration sections stay local placeholders.
- Drop the local Save bar for this section. Each toggle, save, and sync is its own request. A "Saved" flash after a 2xx is enough.

`frontend/src/pages/Dashboard.tsx` needs no data change if pass 3 returns `last_sync` as a string. Confirm the three cards render without Placeholder badges. Leave `CONNECTOR_ROWS` and `INDEX_BARS` in place.

## Proofs

Finish `backend/scripts/internal_ingest_proof.py` so one command covers pass 2 and pass 3:

```text
cd backend && uv run python -m scripts.internal_ingest_proof
```

Header docstring states the stack requirements: API on `:8000`, Keycloak, Postgres, MinIO, OpenSearch, `KEYCLOAK_INGEST_SECRET`, and how the presigned PUT is reached (`MINIO_PRESIGN_ENDPOINT=localhost:9000` on the host, or a PUT from the compose network).

Required cases:

1. Ingest token reserve → PUT → complete. `files` row, MinIO object, OpenSearch chunk, `allowed_*` empty, no `file_acl`.
2. Second reserve of the same `(ingestion_type, original_source)` returns the same `file_id`. After an ACL grant and complete, the chunk reloads role or group names from `file_acl`.
3. `realm-admin` on `/internal/ingest/files` → 403.
4. Admin create connector with an empty pipeline URL → 503 and no row.
5. Admin create with an unreachable URL → 502 and no row.
6. Ingest token `POST /internal/connectors/{id}/status` updates `connectors` and the open `connector_syncs` row. Admin token on that route → 403.

`uv run python -m scripts.admin_stats_proof` still passes (pass 3 assertions).

## Docs (only after the proofs pass)

These edits are the ship record. Do them in the same pass, after the scripts are green.

### `prompt_2/current.md`

Now:

- Internal ingest API (`ingest-client`, presigned PUT, complete indexes chunks).
- Admin connector control plane (BFF + Postgres mirror). Pipeline service is not in this repo.
- Dashboard connector count, ingest rate, and last sync are live. Other dashboard cards stay placeholders.
- Configuration ingestion talks to `/admin/connectors`. Other Configuration sections stay local placeholders.

Not yet: remove "Connector ingestion pipeline (dashboard connector, rate, and last-sync stay API placeholders)". Keep content-hash dedup, auto-ACL, Task 7, and native hybrid.

Invariants: add that `/internal/*` requires realm role `ingest-service`, OpenSearch writes on that path stay basic `admin`, and connector secrets are not stored in Postgres.

Unfinished work: `prompts/instructions/2_Ingestion_pipeline.md` and `prompts/cursor_summary/12_ingestion_pipeline_proposal.md` stay unfinished. This slice did not build that pipeline. Say so in one sentence. Do not mark those archive files done. Do not edit them.

### Root `README.md`

Match the Now / Not yet / Dashboard / Configuration sentences in `current.md`. Document:

- `KEYCLOAK_INGEST_SECRET` and client `ingest-client`.
- `INGESTION_PIPELINE_URL` empty means connector create and sync return 503.
- `MINIO_PRESIGN_ENDPOINT` default `minio:9000`.
- Human test section copied from the guide below, shortened to the click path.

### `backend/README.md`

Replace the stats table rows that say constants `8`, `12400`, and `"2 min ago"`. Add the `/internal` and `/admin/connectors` routes.

### Context notes

| File | Change |
| --- | --- |
| `prompt_2/context/auth.md` | Client `ingest-client`, role `ingest-service`, audience `api-client`, no product roles, no OpenSearch mapping. |
| `prompt_2/context/ingest.md` | Add the two `/internal` routes beside HTTP upload. State path prefix `files/{type}/{file_id}/...`, presigned PUT, no auto ACL, re-sync reuses `file_id`. HTTP and folder CLI paragraphs stay. |
| `prompt_2/context/dashboard.md` | The three former placeholders are live. Say what each query counts. Static page cards stay placeholders. |
| `prompt_2/context/connectors.md` | Split shipped control plane from the frozen Airbyte proposal. The proposal is still unfinished. This repo stores no source passwords. |
| `prompt_2/context/data_model.md` | New tables and the widened `ingestion_type` CHECK. Partial unique `(ingestion_type, original_source)`. |

### Plan status

- Set `status: implemented` in the front matter of `prompt_2/internal_ingest_plan.md`.
- Check T1–T9 in that file.
- Set this pass file and the three earlier pass files to `status: implemented` only after their gates were actually run.
- In `prompt_2/index.md`, move the internal ingest rows from active plans to shipped, and point the topic sentence at the log below. Leave the frozen proposal row active.

### Implementation log

Write `prompt_2/internal_ingest_log.md`. This is the ship dump, same role as `prompt_2/frontend_ui_log.md`. It is not product truth. Include:

- What changed, by pass.
- Routes, tables, and settings actually added.
- Proof commands and the result.
- The human test guide below.
- Anything deferred (pipeline service, auto-ACL, content-hash, Task 7, static dashboard cards).

## Human test guide

Write this into the log and a short form into the root README.

Preconditions: stack up, `uv run alembic upgrade head`, `uv run python -m init_services`, root `.env` contains `KEYCLOAK_INGEST_SECRET`. Sign in as `realm-admin` / `adminpass`.

1. Open `/dashboard`. Active connectors, ingestion rate, and last sync have no Placeholder badge. With no connectors, the count is 0 and last sync is `—`. p99, searches today, and total sources still show Placeholder.
2. Open `/configuration`, Ingestion. The list comes from the API. It is empty, not the old eight fixtures. The section has no Placeholder badge.
3. Leave `INGESTION_PIPELINE_URL` empty. Add a connector, fill a name, save. The page shows an error that the pipeline is not configured (503). The list stays empty after refresh.
4. Set `INGESTION_PIPELINE_URL=http://127.0.0.1:9` and restart the API. Add again. The page shows that the pipeline is unreachable (502). Refresh. The connector is not listed.
5. Sync Now on a connector, if one exists from a later pipeline test, shows the same class of error while the URL is down. Do not expect a real sync in this repo.
6. Optional API check, not the SPA. With the ingest token, reserve a file, PUT bytes to the presigned URL, complete. In Access Control the file appears with no grants. Search as `searcher` does not return it until an admin grants a role or group. After a grant, a second reserve of the same source URI keeps the same file id.

## Tasks

- [x] Add `frontend/src/api/connectors.ts`.
- [x] Rewire `IngestionSection.tsx` to the admin API. Catalog stays the form schema. Secrets are not reloaded from GET.
- [x] Browser pass of the human test guide steps 1–4. Fix UI bugs before docs.
- [x] `internal_ingest_proof.py` green, including connector cases. `admin_stats_proof.py` green.
- [x] Update `prompt_2/current.md`, root `README.md`, `backend/README.md`, and context notes `auth.md`, `ingest.md`, `dashboard.md`, `connectors.md`, `data_model.md`.
- [x] Write `prompt_2/internal_ingest_log.md` with the human test guide.
- [x] Mark `prompt_2/internal_ingest_plan.md` and these pass files implemented. Update `prompt_2/index.md`.

## Test gate

The pass is done when all of the following are true:

1. Steps 1–4 of the human test guide, exercised in the browser while signed in as `realm-admin`.
2. `uv run python -m scripts.internal_ingest_proof` exits 0.
3. `uv run python -m scripts.admin_stats_proof` exits 0.
4. `prompt_2/current.md` and root `README.md` describe the shipped control plane, and they no longer say connector count, rate, and last sync are API placeholders.
5. `prompts/` has no edits.
