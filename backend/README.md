# Backend

FastAPI service for Enterprise Search: JWT auth against Keycloak, Postgres identity/files metadata + ACL, resumable local ingest into MinIO + OpenSearch, **ops folder ingest CLI**, **internal ingest API** (`ingest-service`, presigned PUT, complete), **admin connector control plane** (BFF + Postgres mirror; the pipeline service is not in this repo), **client-hybrid search**, file list/open streams, **admin identity + file ACL** (bulk grants, members, sync jobs), **admin dashboard stats**, and bootstrap via `init_services`.

Managed with [uv](https://docs.astral.sh/uv/). Python **3.12+**.

## Layout

```
app/
  api/routes/     health, auth, files, search, admin_identity, admin_acl, admin_stats, admin_connectors, internal_ingest
  core/           settings, JWT verification
  models/         identity, files, file_acl, upload_sessions, acl_sync_jobs, search_metrics, ingest_job, connector
  services/       ingest (csv_extract, local_file, folder_walk, …), file_access, file_acl_admin, acl_sync, identity_admin, keycloak_admin, opensearch_search, upload, admin_stats, admin_connectors, ingestion_pipeline, internal_ingest, search_metrics, …
  schemas/        request/response models (files, search, uploads, admin_*, internal_ingest)
alembic/          migrations (run manually; not part of init_services)
init_services/    Keycloak, identity mirror, OpenSearch security/ML/index, MinIO bucket
scripts/          ingest_folder, ingest_*, search_*, seed_file_acl_for_proofs, admin_*_proof, internal_ingest_proof
```

## Setup

Preferred: from the **repo root**, run `./setup/setup.sh` (see [setup/README.md](../setup/README.md)). An already-running stack can add the internal ingest client with `./setup/internal_ingest.sh`. That script does not start a pipeline container. An empty `INGESTION_PIPELINE_URL` makes connector create and sync return **503**.

Manual path — env lives in root `.env` (Compose + FastAPI):

```bash
cp backend/.env.sample .env
cd backend && uv sync
uv run alembic upgrade head
uv run python -m init_services
```

Run the API (http://localhost:8000):

```bash
uv run python -c "from app.main import run; run()"
# or from repo root: ./start-dev.sh
```

OpenAPI: http://localhost:8000/docs

## HTTP API

| Method | Path | Auth | Notes |
| --- | --- | --- | --- |
| `GET` | `/health` | public | Liveness |
| `GET` | `/auth/me` | Bearer | Current user claims |
| `GET` | `/auth/admin-ping` | Bearer + `admin` | Admin check |
| `GET` | `/admin/stats` | Bearer + `admin` | Dashboard KPIs (see Admin stats) |
| `POST` | `/search` | `search-user` \| `admin` | Client-hybrid search (user JWT → OpenSearch DLS); records OpenSearch `took` after success |
| `GET` | `/files` | `search-user` \| `admin` | ACL-filtered file list (Postgres `file_acl`) |
| `GET` | `/files/{id}` | product user + ACL | File metadata |
| `GET` | `/files/{id}/content` | product user + ACL | Stream original from MinIO |
| `POST` | `/files/uploads` | `search-user` \| `admin` | Initiate resumable upload (201) |
| `PUT` | `/files/uploads/{id}` | owner (`sub`) | `Content-Range` byte parts; incomplete → 308 |
| `GET` | `/files/uploads/{id}` | owner | Status / progress |
| `POST` | `/files/uploads/{id}/complete` | owner | Parse → MinIO put → `files` row → OS bulk |
| `DELETE` | `/files/uploads/{id}` | owner | Cancel; drop local staging |

### Admin identity (`require_admin`)

| Method | Path | Notes |
| --- | --- | --- |
| `GET/POST` | `/admin/users` | List (`q`, limit/offset) / create |
| `GET/PATCH` | `/admin/users/{id}` | Detail / update (roles+groups replace via Keycloak then PG) |
| `GET/POST` | `/admin/roles` | List (`include_system`) / create |
| `GET/PATCH/DELETE` | `/admin/roles/{id}` | Detail / update / delete (product roles) |
| `GET/POST` | `/admin/roles/{id}/members` | List members (`q`); add users (additive; max 100) |
| `POST` | `/admin/roles/{id}/members:remove` | Remove users; keep `search-user` and/or `admin` |
| `GET/POST` | `/admin/groups` | List / create |
| `GET/DELETE` | `/admin/groups/{id}` | Detail / delete |
| `GET/POST` | `/admin/groups/{id}/members` | List / add (rejects `_empty` / system) |
| `POST` | `/admin/groups/{id}/members:remove` | Remove; may mirror `_empty` when no product groups left |

Member mutations return `results[]` + `failed[]` (HTTP 200 on partial success). Keycloak first, then Postgres.

### Admin file ACL (`require_admin`)

| Method | Path | Notes |
| --- | --- | --- |
| `GET` | `/admin/files` | All files; optional `q`, `has_acl`; `access_total` / `access_preview` |
| `POST` | `/admin/files/acl:bulk` | upsert / replace / revoke; max 100 `file_ids`; per-file commit + enqueue |
| `GET/PUT/POST` | `/admin/files/{id}/acl` | List / replace-all / upsert one (+ `acl_job_id`) |
| `DELETE` | `/admin/files/{id}/acl/{acl_id}` | Revoke one + enqueue |
| `GET` | `/admin/roles/{id}/file-grants` | Files this role can access |
| `GET` | `/admin/groups/{id}/file-grants` | Files this group can access |
| `GET` | `/admin/acl-jobs` / `{id}` | Job list / detail |
| `POST` | `/admin/acl-jobs/{id}/retry` | failed → queued |

Grants are **role/group** only (`viewer` \| `editor`). System / `_empty` → **400**. Bulk `replace` needs `confirm_replace: true`. Flow: mutate Postgres → enqueue `acl_sync_jobs` → worker updates OpenSearch `allowed_*`.

### Admin stats (`GET /admin/stats`, `require_admin`)

One DTO for the Dashboard. OpenSearch is **not** queried at stats read time; avg samples were captured from each successful search response.

| Field | Source |
| --- | --- |
| `avg_query_time_ms` | `AVG(took_ms)` on `search_query_metrics` where `created_at` is in the last 24 hours (`null` if empty). Stored value is OpenSearch `took` (sum of subqueries in client-hybrid), not FastAPI wall-clock. |
| `total_data_ingested_bytes` | MinIO bucket `enterprise-search-files` recursive object-size sum (empty → `0`; list/sum failure → **502**) |
| `total_docs_indexed` | `COUNT(*) FROM files` (files, not OpenSearch chunks) |
| `active_connectors` | `COUNT(*)` of `connectors` where `enabled` is true (`placeholders.active_connectors: false`) |
| `ingestion_rate_docs_per_hour` | `COUNT(*)` of `ingest_jobs` with `status=completed` and `completed_at` in the last hour |
| `last_sync` | latest `connectors.last_sync_at` as ISO-8601, or `—` when none |

Unauthenticated → **401**; non-admin → **403**. Successful `POST /search` enqueues `record_search_metric(os_took_ms)` via `BackgroundTasks` (no query text; failures are not stored). `os_took_ms` is the OpenSearch response `took` (client_hybrid: match + neural; native_hybrid: one query). API `took_ms` stays wall-clock. Table is unbounded; the average still filters last 24 hours.

### Internal ingest (`require_ingest_service`)

Client `ingest-client`, realm role `ingest-service`, audience `api-client`. Not `admin` and not `search-user`. OpenSearch writes on this path use basic `admin`. No `file_acl` is created.

| Method | Path | Notes |
| --- | --- | --- |
| `POST` | `/internal/ingest/files` | Reserve. Presigned PUT at `files/{type}/{file_id}/{name}`. `MINIO_PRESIGN_ENDPOINT` default `minio:9000`. |
| `POST` | `/internal/ingest/files/{id}/complete` | HEAD the object, upsert `files`, bulk-index chunks. Same `(ingestion_type, original_source)` reuses `file_id` and reloads `allowed_*` from `file_acl`. |
| `POST` | `/internal/connectors/{id}/status` | Pipeline callback. Updates `connectors` and the open `connector_syncs` row. Admin token → **403**. |

### Admin connectors (`require_admin`)

Postgres mirror. `config` is write-only and is not a column. Empty `INGESTION_PIPELINE_URL` → **503** and no row. Unreachable pipeline → **502** and no row.

| Method | Path | Notes |
| --- | --- | --- |
| `GET` | `/admin/connectors` | List. No `config`. |
| `POST` | `/admin/connectors` | Create on the pipeline, then insert. **201**. |
| `GET` | `/admin/connectors/{id}` | One row. **404** when missing. |
| `PATCH` | `/admin/connectors/{id}` | Forwards set fields. Local row changes only after a 2xx. |
| `POST` | `/admin/connectors/{id}/sync` | **202** `{ sync_id, status: syncing }`. |
| `GET` | `/admin/connectors/{id}/syncs` | Newest first. |

Vite proxies `/api/*` to these paths (no `/api` prefix on FastAPI itself).

### Search (`POST /search`)

Body: `{ "q": "<string>", "size": 10 }` (`size` clamped 1..50; empty/`whitespace` `q` → **400**).

Default `search_mode=client_hybrid` (OpenSearch **3.8** workaround):

1. Forward the **caller JWT** (never basic `admin`).
2. Run match on `content` and neural on `embedding` in parallel (`k=50`).
3. Merge with min_max + arithmetic_mean weights `[0.3, 0.7]` in FastAPI.
4. Strip `embedding` from `_source` and the response DTO.

Hits are **chunk-grain** (snippet, `file_id`, `chunk_seq`, score, `display_name` = basename of `object_store_path`). OS failures → **502**; missing `opensearch_model_id` → **503**. Native `hybrid` + `search_pipeline` only when `search_mode=native_hybrid` after 3.9 proofs. After a successful search, OpenSearch `took` (`os_took_ms`) is persisted in the background for the dashboard average. Response `took_ms` remains wall-clock.

### View files / Open

- List/metadata/content use Postgres `file_acl` matched on JWT **role/group names** (`viewer` \| `editor`; ignore `_empty`). Realm `admin` does **not** bypass ACL.
- Content streams `files.object_store_path` from MinIO only after ACL pass (**403** deny, **404** missing). No client-supplied object keys.
- Uploads and folder-CLI files start with **empty** ACL — list/search stay empty until an admin grant (Access UI / bulk APIs) or the seed script.

### Ingest rules

Shared helper `ingest_local_bytes` (HTTP `complete()` and the folder CLI): parse/chunk → MinIO `put_object` → INSERT `files` → OpenSearch `_bulk` (`refresh=wait_for`) → `db.commit()`. C6 on failure: rollback `files`, delete OS docs if indexed, delete MinIO object if written. `_bulk` retries up to 5 times on transient `circuit_breaking_exception` and HTTP 429/503; mapping errors are not retried.

- Types: **pdf / txt / csv** only. HTTP: else **415**, cap **25 MiB**. Folder CLI: other extensions `[skip]`; **no** 25 MiB skip.
- Chunking: **600** tokens / **75** overlap (~4 chars/token). CSV packs rows by token budget; oversized rows still split via `chunk_text`. Parser raises `csv.field_size_limit` so a cell larger than the default 128 KiB can parse (do not routinely ingest multi-hundred-MiB CSVs — the process is in-memory).
- MinIO: **one** full object at `local/{file_id}/{safe_name}` (basename only — not a nested prefix). HTTP ranges assemble on local disk first.
- Postgres: one `files` row; **no** `file_acl`. HTTP also writes `upload_sessions`; the folder CLI does not.
- OpenSearch: bulk as basic **admin**, omit `embedding` (ingest pipeline fills 384-dim). Chunks get `allowed_roles: []`, `allowed_groups: []` (no auto ACL). HTTP `original_source` is `null`; folder CLI stores the POSIX path relative to the folder root.
- HTTP session ownership: `user_id == JWT sub` (admins do not hijack other sessions). Folder CLI uses **no JWT**.

### Folder ingest CLI

Ops script (stack up; API optional). Direct service call — not initiate / ranged PUT / JWT.

```bash
uv run python -m scripts.ingest_folder /path/to/folder
uv run python -m scripts.ingest_folder /path/to/folder --dry-run
uv run python -m scripts.ingest_folder /path/to/folder --fail-fast
```

| Flag / arg | Behavior |
| --- | --- |
| `folder` | Required; must exist and be a directory; else exit **1** |
| `--dry-run` | Print classification only; **no** store writes; exit **0** if the folder exists |
| `--fail-fast` | Stop after first ingest/parse/infra failure (type/hidden skips are not failures) |

Walk does **not** follow file or directory symlinks. Skip if any relative path component starts with `.`. Re-running the same folder creates **new** `file_id`s.

Stdout example:

```text
[skip]  ignored.bin  (unsupported extension)
[ok]    notes.txt  file_id=...  chunks=1
[fail]  empty.pdf  PDF has no extractable text (OCR not supported)

ingested=2  failed=1  skipped_type=1  skipped_hidden=0
```

`--dry-run` uses `[ingest]` for eligible files. Files ≥ 512 MiB get an optional `[warn]` then still ingest. Exit **0** if every *attempted* ingest succeeded; **1** if any attempted ingest failed or the folder is missing. React `/upload` is unchanged.

## `init_services`

Idempotent bootstrap (stack must be up):

```bash
uv run python -m init_services
```

Configures Keycloak realm clients/users, mirrors identity into Postgres, applies OpenSearch JWKS JWT + DLS roles, registers/deploys MiniLM (persists `opensearch_model_id` in `runtime_config.json`), creates ingest/search pipelines + `enterprise-search-chunks`, ensures the MinIO bucket.

Opt-in search DLS proofs:

```bash
SEARCH_PROOF=1 uv run python -m init_services
# or
uv run python -m init_services.search_proof
```

On OpenSearch **3.8**, hybrid+DLS is blocked (Landmine 13); platform proofs fall back to match/neural DLS. Product search uses client-hybrid instead.

## Proofs / checks

```bash
uv run python -m scripts.ingest_unit_checks      # offline chunker/CSV + bulk retry
uv run python -m scripts.ingest_folder_unit_checks  # offline walker / 25 MiB+ still eligible
uv run python -m scripts.ingest_proof            # live JWT upload → PG/MinIO/OS
uv run python -m scripts.ingest_folder_proof     # live folder CLI proofs 1–13 (writes sample files)
uv run python -m scripts.search_unit_checks      # offline merge / DTO strip
uv run python -m scripts.seed_file_acl_for_proofs  # optional G3 ACL + OS allowed_*
uv run python -m scripts.search_view_proof       # list/open + client-hybrid DLS
uv run python -m scripts.admin_identity_proof    # identity CRUD
uv run python -m scripts.admin_acl_proof         # single-file ACL + sync jobs
uv run python -m scripts.admin_file_access_proof # bulk ACL + file-grants filters
uv run python -m scripts.admin_member_assignment_proof  # role/group members
uv run python -m scripts.admin_stats_proof       # /admin/stats 401/403/200 + search avg
uv run python -m scripts.internal_ingest_proof   # reserve → PUT → complete, ACL reload, connector 502/503
```

`seed_file_acl_for_proofs` grants role `search-user` on file A and group `engineering` on file B (idempotent; never `_empty`), then `update_by_query` copies names into chunk `allowed_*`.

## Notes

- `backend/runtime_config.json` and `backend/data/upload-staging/` are gitignored.
- Do **not** use `securityadmin.sh` for JWT/DLS edits — re-run `init_services`.
- See root [README.md](../README.md) for Compose, seed users, and OpenSearch volume wipe.
