# Connectors (not built)

Active unfinished work. Brief: `prompts/instructions/2_Ingestion_pipeline.md`. Proposal: `prompts/cursor_summary/12_ingestion_pipeline_proposal.md`. Do not treat the proposal checkboxes as shipped work. Do not invent a Task 7 plan.

The brief asks for SharePoint, Google Drive, and S3/MinIO, with Airbyte dumping into a lake, Kafka events, and Spark plus Tika for processing. The proposal treats Spark as deferred and keeps chunking on the existing 600/75 chunker.

Proposed shape, not implemented:

- Airbyte syncs sources into MinIO `lake/raw/...` (not the user-facing prefix).
- A worker consumes `ingest.raw.created`, extracts with Tika, chunks, copies bytes to a user-facing prefix (`files/sharepoint|google_drive|s3/{file_id}/...`), upserts `files`, and bulk-indexes OpenSearch with empty ACL.
- User-facing Open still uses Postgres ACL then MinIO. Lake objects are not served to end users.
- `allowed_roles` and `allowed_groups` stay empty until an admin grant. No auto ACL.
- Local `/upload` and `local/{file_id}/...` stay as they are.

Still open in the proposal: event-based vs scheduled Airbyte, dedup and re-update, source deletes, connector credentials, and whether the worker is a separate process. Dashboard connector count, ingest rate, and last-sync stay API placeholders.
