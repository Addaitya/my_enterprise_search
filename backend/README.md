# Backend

FastAPI service for Enterprise Search: JWT auth against Keycloak, Postgres identity/files metadata, resumable local ingest into MinIO + OpenSearch, and bootstrap via `init_services`.

Managed with [uv](https://docs.astral.sh/uv/). Python **3.12+**.

## Layout

```
app/
  api/routes/     health, auth, files (upload)
  core/           settings, JWT verification
  models/         identity, files, file_acl, upload_sessions
  services/       upload orchestrator, staging, MinIO, OpenSearch bulk, ingest/*
  schemas/        request/response models
alembic/          migrations (run manually; not part of init_services)
init_services/    Keycloak, identity mirror, OpenSearch security/ML/index, MinIO bucket
scripts/          ingest_unit_checks, ingest_proof
```

## Setup

From the **repo root**, env lives in `.env` (Compose + FastAPI):

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
| `POST` | `/files/uploads` | `search-user` \| `admin` | Initiate resumable upload (201) |
| `PUT` | `/files/uploads/{id}` | owner (`sub`) | `Content-Range` byte parts; incomplete → 308 |
| `GET` | `/files/uploads/{id}` | owner | Status / progress |
| `POST` | `/files/uploads/{id}/complete` | owner | Parse → MinIO put → `files` row → OS bulk |
| `DELETE` | `/files/uploads/{id}` | owner | Cancel; drop local staging |

Vite proxies `/api/*` to these paths (no `/api` prefix on FastAPI itself).

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

On OpenSearch **3.8**, hybrid+DLS is blocked (Landmine 13); proofs fall back to match/neural DLS while keeping hybrid as the product contract.

## Proofs / checks

```bash
uv run python -m scripts.ingest_unit_checks   # offline chunker/CSV
uv run python -m scripts.ingest_proof         # live JWT upload → PG/MinIO/OS
```

## Notes

- `backend/runtime_config.json` and `backend/data/upload-staging/` are gitignored.
- Do **not** use `securityadmin.sh` for JWT/DLS edits — re-run `init_services`.
- See root [README.md](../README.md) for Compose, seed users, and OpenSearch volume wipe.
