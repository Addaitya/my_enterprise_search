# Connectors

The control plane in this repo is shipped. The pipeline service is not. Brief: `prompts/instructions/2_Ingestion_pipeline.md`. Proposal: `prompts/cursor_summary/12_ingestion_pipeline_proposal.md`. Those archive files stay unfinished. Do not treat their checkboxes as shipped work. Do not invent a Task 7 plan. Do not edit `prompts/`.

## Shipped control plane

Admins list, create, update, and sync connectors through `/admin/connectors`. FastAPI calls `INGESTION_PIPELINE_URL` and stores a Postgres mirror (`connectors`, `connector_syncs`). `config` is forwarded on create and update and is not a column. GET never returns it. This repo stores no source passwords.

Empty `INGESTION_PIPELINE_URL` → 503 and no row. Unreachable pipeline → 502 and no row. Create forwards `callback_connector_id`, this API’s connector UUID, minted before the pipeline call. The pipeline reports status to `POST /internal/connectors/{id}/status` with that same id and realm role `ingest-service`. Sync does not repeat the UUID.

Configuration → Ingestion uses that admin API. `CONNECTOR_CATALOG` is the form schema only. Saved connection fields are not loaded back into the form. Dashboard connector count, ingest rate, and last sync read the mirror. Other dashboard cards stay static placeholders.

File bytes from a pipeline still arrive through `POST /internal/ingest/files` (presigned PUT, then complete). See `prompt_2/context/ingest.md`. No auto ACL.

## Frozen proposal (not this repo)

The brief asks for SharePoint, Google Drive, and S3/MinIO, with Airbyte dumping into a lake, Kafka events, and Spark plus Tika for processing. The proposal treats Spark as deferred and keeps chunking on the existing 600/75 chunker. None of that service is implemented here.

Proposed shape, not implemented:

- Airbyte syncs sources into MinIO `lake/raw/...` (not the user-facing prefix).
- A worker consumes `ingest.raw.created`, extracts with Tika, chunks, copies bytes to a user-facing prefix (`files/sharepoint|google_drive|s3/{file_id}/...`), upserts `files`, and bulk-indexes OpenSearch with empty ACL.
- User-facing Open still uses Postgres ACL then MinIO. Lake objects are not served to end users.
- `allowed_roles` and `allowed_groups` stay empty until an admin grant. No auto ACL.
- Local `/upload` and `local/{file_id}/...` stay as they are.

Still open in the proposal: event-based vs scheduled Airbyte, dedup and re-update, source deletes, connector credentials inside the pipeline, and whether the worker is a separate process.
