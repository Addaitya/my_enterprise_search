# Backend

FastAPI service for Enterprise Search: JWT auth against Keycloak, Postgres identity/files metadata + ACL, resumable local ingest into MinIO + OpenSearch, **client-hybrid search**, file list/open streams, and bootstrap via `init_services`.

Managed with [uv](https://docs.astral.sh/uv/). Python **3.12+**.

## Layout

```
app/
  api/routes/     health, auth, files (list/open + upload), search
  core/           settings, JWT verification
  models/         identity, files, file_acl, upload_sessions
  services/       file_access, opensearch_search, upload, staging, MinIO, OpenSearch bulk, ingest/*
  schemas/        request/response models (files, search, uploads)
alembic/          migrations (run manually; not part of init_services)
init_services/    Keycloak, identity mirror, OpenSearch security/ML/index, MinIO bucket
scripts/          ingest_*, search_unit_checks, search_view_proof, seed_file_acl_for_proofs
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
- Uploads start with **empty** ACL — list/search stay empty until grants (seed script or Task 6).

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
```

`seed_file_acl_for_proofs` grants role `search-user` on file A and group `engineering` on file B (idempotent; never `_empty`), then `update_by_query` copies names into chunk `allowed_*`.

## Notes

- `backend/runtime_config.json` and `backend/data/upload-staging/` are gitignored.
- Do **not** use `securityadmin.sh` for JWT/DLS edits — re-run `init_services`.
- See root [README.md](../README.md) for Compose, seed users, and OpenSearch volume wipe.
