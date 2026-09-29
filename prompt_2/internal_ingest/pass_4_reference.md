---
status: implemented
title: Pass 4 reference — Configuration UI, proofs, and product truth
date: 2026-09-28
notes: Implementation record and retest guide. Not product truth. Product truth is prompt_2/current.md. The ship dump is prompt_2/internal_ingest_log.md.
---

# Pass 4 reference — Configuration UI, proofs, and product truth

Parent plan: `prompt_2/internal_ingest_plan.md` (T7, T9). Spec: `prompt_2/internal_ingest/pass_4_ui_proofs_docs.md`.

Gate passed 28 Sep 2026. Browser steps 1–4 were exercised as `realm-admin`. From `backend/`:

- `uv run python -m scripts.internal_ingest_proof` printed `PASS file ingest` and `PASS connectors`
- `uv run python -m scripts.admin_stats_proof` printed `=== all admin stats proofs passed ===`

This pass wires Configuration ingestion to `/admin/connectors` and records the slice in product docs. It does not add a pipeline service. The SPA does not call `INGESTION_PIPELINE_URL`.

## What the page does

`frontend/src/api/connectors.ts` lists, creates, patches, and syncs through the admin API. GET responses have no `config`. The form schema stays `CONNECTOR_CATALOG` in `frontend/src/config/placeholders.ts`. `CONNECTOR_FIXTURES` is gone.

On `/configuration`, Ingestion loads the connector list. A failure shows an error banner. There is no fixture fallback and no section Placeholder badge. The page intro says ingestion is saved through the admin API and the other sections stay local placeholders.

The status column shows `status`. `last_error` is secondary text. The enabled toggle sends `PATCH { enabled }` and restores the previous value if the request fails. Sync Now posts `/admin/connectors/{id}/sync`. HTTP 503 copy is “The pipeline URL is not configured.” HTTP 502 copy is “The pipeline is unreachable.” A 2xx shows a Saved flash. There is no section-level Save bar.

Add still opens the catalog picker. Save on a new draft calls `POST /admin/connectors`. Catalog toggles go in `config` as `"true"` / `"false"`. The CDC toggle is not a column; it is `config.cdc`. `schedule` is the top-level field.

Configure on an existing row loads name, enabled, and schedule from the API. Catalog fields start empty. Helper text says saved connection fields are not shown again: leave a field blank to keep the pipeline value, or fill it to replace it. PATCH sends only changed fields and omits empty secret fields.

`frontend/src/pages/Dashboard.tsx` was not changed. Active connectors, ingestion rate, and last sync already drop the Placeholder badge when `placeholders.*` is false. p99, searches today, total sources, the connector table, and the index bars stay placeholders.

## Proofs

```text
cd backend && uv run python -m scripts.internal_ingest_proof
cd backend && uv run python -m scripts.admin_stats_proof
```

Stack: API on `:8000`, Keycloak, Postgres, MinIO, OpenSearch, `KEYCLOAK_INGEST_SECRET`. Presigned PUT uses `MINIO_PRESIGN_ENDPOINT` (default `minio:9000`, reached with curl from the OpenSearch container, or `localhost:9000` for a host PUT). The live API must have an empty `INGESTION_PIPELINE_URL`. The 502 case starts its own API on `:8013`.

28 Sep 2026 results: file half `[ok] 1` through `[ok] 8` then `PASS file ingest`. Connector half: empty URL 503 with no new row, unreachable URL 502 with no new row, ingest-token status callback closes the open sync, realm-admin on that route is 403, then `PASS connectors`. Stats proof: admin stats 200 with `connectors=0`, `last_sync='—'`, and `=== all admin stats proofs passed ===`.

## Human test

Preconditions: stack up, `cd backend && uv run alembic upgrade head`, `uv run python -m init_services`, root `.env` contains `KEYCLOAK_INGEST_SECRET`. Sign in as `realm-admin` / `adminpass` at `http://localhost:5173`. Leave `INGESTION_PIPELINE_URL` empty for steps 1–3. For step 4, set `INGESTION_PIPELINE_URL=http://127.0.0.1:9`, restart only the API, then start it again with the URL unset so later 503 checks still match.

1. Open `/dashboard`. Active connectors, ingestion rate, and last sync have no Placeholder badge. With no connectors, the count is 0 and last sync is `—`. p99, searches today, and total sources still show Placeholder. The connector table and index bars stay placeholders.
2. Open `/configuration`, Ingestion. The list comes from the API. It is empty, not the old eight fixtures. The section has no Placeholder badge. Messaging still says it is not built.
3. Leave `INGESTION_PIPELINE_URL` empty. Add a connector, fill a name, save. The page shows that the pipeline URL is not configured. Refresh. The list stays empty.
4. Set `INGESTION_PIPELINE_URL=http://127.0.0.1:9` and restart the API. Add again. The page shows that the pipeline is unreachable. Refresh. The connector is not listed.
5. Sync Now on a connector, if one exists from a later pipeline test, shows the same class of error while the URL is down. Do not expect a real sync in this repo.
6. Optional API check, not the SPA. With the ingest token, reserve a file, PUT bytes to the presigned URL, complete. In Access Control the file appears with no grants. Search as `searcher` does not return it until an admin grants a role or group. After a grant, a second reserve of the same source URI keeps the same file id. `internal_ingest_proof` already covers this.

Steps 1–4 were run in the browser on 28 Sep 2026. Step 3 showed “The pipeline URL is not configured.” Step 4 showed “The pipeline is unreachable.” Both refreshes stayed on “No connectors.”

## Not covered here

- A real pipeline. Create and sync 2xx need a service this repo does not ship.
- Auto-ACL, content-hash dedup, and Task 7 `SKIP LOCKED` / `files_writer`.
- The static dashboard cards, connector table, and index bars.
