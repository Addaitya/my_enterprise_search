# Current product

Agent source of truth. Humans use the root `README.md` for clone and setup. When product behavior changes, update both. Do not edit `prompts/`.

## What this is

Company-internal hybrid search (keyword + semantic) over files, with role- and group-based access control (RACL). v1 accepts local PDF, TXT, and CSV uploads.

## Now

- Compose stack
- Keycloak PKCE login
- FastAPI JWT
- OpenSearch 3.8 JWKS + `files_searcher` document-level security
- Postgres identity mirror and `files`, `file_acl`, `upload_sessions`, `search_query_metrics`
- Resumable HTTP ingest API
- Ops folder ingest CLI
- React multi-file `/upload`
- Client-hybrid `POST /search`
- ACL-filtered View files and Open (MinIO stream)
- Admin Dashboard (live stats and placeholders)
- Access Control (Users / Roles / Groups / Access)
- Configuration placeholder

## Not yet

- Check-access explorer and audit CSV
- Task 7 `SKIP LOCKED` and dual-write repair. Do not invent a Task 7 plan.
- Native OpenSearch `hybrid` plus document-level security (needs 3.9+; the product path is client-side merge on 3.8)
- Connector ingestion pipeline (dashboard connector, rate, and last-sync stay API placeholders)
- Content-hash dedup
- Auto-ACL after ingest

## Invariants

- Search uses the user JWT. Never basic `admin`.
- HTTP ingest and the folder CLI do not auto-grant `file_acl`. Chunks are indexed with an empty ACL and become searchable or listable only after an admin grant or the optional seed script.
- Indexed chunks omit `embedding`.
- View and Open check Postgres ACL, then stream bytes from MinIO using `files.object_store_path` only. Never a client-supplied key.
- The Keycloak realm role `admin` does not bypass file ACL.
- ACL split: search hits use OpenSearch document-level security on chunk `allowed_roles` and `allowed_groups`; View files and Open use Postgres `file_acl` (JWT role and group names; `editor` implies view); file bytes use the MinIO path from `files.object_store_path`.

## Search on 3.8

Native `hybrid` plus document-level security hits a ClassCast bug on OpenSearch 3.8. Product `POST /search` runs client-side hybrid: parallel match and neural queries with the user JWT, then FastAPI min-max normalization and weights `[0.3, 0.7]`. OpenSearch document-level security still applies on each subquery. Native hybrid stays off the hot path until 3.9 proofs.

## Unfinished work

These two archive files are the only unfinished product work:

- `prompts/cursor_summary/12_ingestion_pipeline_proposal.md`
- `prompts/instructions/2_Ingestion_pipeline.md`
