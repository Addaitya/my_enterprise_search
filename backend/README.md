# Backend

FastAPI service for Enterprise Search: JWT auth against Keycloak, Postgres identity/files metadata + ACL, resumable local ingest into MinIO + OpenSearch, **client-hybrid search**, file list/open streams, **admin identity + file ACL** (bulk grants, members, sync jobs), and bootstrap via `init_services`.

Managed with [uv](https://docs.astral.sh/uv/). Python **3.12+**.

## Layout

```
app/
  api/routes/     health, auth, files, search, admin_identity, admin_acl
  core/           settings, JWT verification
  models/         identity, files, file_acl, upload_sessions, acl_sync_jobs
  services/       file_access, file_acl_admin, acl_sync, identity_admin, keycloak_admin, opensearch_search, upload, …
  schemas/        request/response models (files, search, uploads, admin_*)
alembic/          migrations (run manually; not part of init_services)
init_services/    Keycloak, identity mirror, OpenSearch security/ML/index, MinIO bucket
scripts/          ingest_*, search_*, seed_file_acl_for_proofs, admin_*_proof
```

## Setup

Preferred: from the **repo root**, run `./setup/setup.sh` (see [setup/README.md](../setup/README.md)).

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
| `POST` | `/search` | `search-user` \| `admin` | Client-hybrid search (user JWT → OpenSearch DLS) |
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

Vite proxies `/api/*` to these paths (no `/api` prefix on FastAPI itself).

### Search (`POST /search`)

Body: `{ "q": "<string>", "size": 10 }` (`size` clamped 1..50; empty/`whitespace` `q` → **400**).

Default `search_mode=client_hybrid` (OpenSearch **3.8** workaround):

1. Forward the **caller JWT** (never basic `admin`).
2. Run match on `content` and neural on `embedding` in parallel (`k=50`).
3. Merge with min_max + arithmetic_mean weights `[0.3, 0.7]` in FastAPI.
4. Strip `embedding` from `_source` and the response DTO.

Hits are **chunk-grain** (snippet, `file_id`, `chunk_seq`, score, `display_name` = basename of `object_store_path`). OS failures → **502**; missing `opensearch_model_id` → **503**. Native `hybrid` + `search_pipeline` only when `search_mode=native_hybrid` after 3.9 proofs.

### View files / Open

- List/metadata/content use Postgres `file_acl` matched on JWT **role/group names** (`viewer` \| `editor`; ignore `_empty`). Realm `admin` does **not** bypass ACL.
- Content streams `files.object_store_path` from MinIO only after ACL pass (**403** deny, **404** missing). No client-supplied object keys.
- Uploads start with **empty** ACL — list/search stay empty until an admin grant (Access UI / bulk APIs) or the seed script.

### Ingest rules

- Types: **pdf / txt / csv** only (else 415). Cap **25 MiB**.
- Chunking: **600** tokens / **75** overlap (~4 chars/token). CSV packs rows by token budget.
- MinIO: **one** full object at `local/{file_id}/{safe_name}` on complete (ranges assemble on local disk).
- OpenSearch: bulk as basic **admin**, omit `embedding` (ingest pipeline fills 384-dim). Chunks get `allowed_roles: []`, `allowed_groups: []` (no auto ACL).
- Session ownership: `user_id == JWT sub` (admins do not hijack other sessions).

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
uv run python -m scripts.ingest_unit_checks      # offline chunker/CSV
uv run python -m scripts.ingest_proof            # live JWT upload → PG/MinIO/OS
uv run python -m scripts.search_unit_checks      # offline merge / DTO strip
uv run python -m scripts.seed_file_acl_for_proofs  # optional G3 ACL + OS allowed_*
uv run python -m scripts.search_view_proof       # list/open + client-hybrid DLS
uv run python -m scripts.admin_identity_proof    # identity CRUD
uv run python -m scripts.admin_acl_proof         # single-file ACL + sync jobs
uv run python -m scripts.admin_file_access_proof # bulk ACL + file-grants filters
uv run python -m scripts.admin_member_assignment_proof  # role/group members
```

`seed_file_acl_for_proofs` grants role `search-user` on file A and group `engineering` on file B (idempotent; never `_empty`), then `update_by_query` copies names into chunk `allowed_*`.

## Notes

- `backend/runtime_config.json` and `backend/data/upload-staging/` are gitignored.
- Do **not** use `securityadmin.sh` for JWT/DLS edits — re-run `init_services`.
- See root [README.md](../README.md) for Compose, seed users, and OpenSearch volume wipe.
