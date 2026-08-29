# Enterprise Search

Company-internal hybrid search (keyword + semantic) over uploaded files, with role- and group-based access control. v1 is local PDF/TXT upload only.

**Now:** Compose stack, Keycloak PKCE login, FastAPI JWT, OpenSearch `files_searcher` DLS mapping, and a Postgres identity mirror plus `files` / `file_acl` schema.

**Not yet:** upload, chunking, search UI, or admin CRUD.

## Stack

| Layer | Choice |
| --- | --- |
| Backend | FastAPI, SQLAlchemy, Alembic, uv |
| Frontend | React, Vite, Tailwind, Zustand, bun |
| Auth | Keycloak 26.2 (`web-client` PKCE, `api-client` for the API) |
| Search | OpenSearch 3.8.0 (ML Commons MiniLM embeddings; JWT via Keycloak JWKS) |
| Storage | PostgreSQL 16 (identity mirror, file metadata, ACL), MinIO (bytes) |

Request auth stays on the **JWT**. Postgres identity is a one-way Keycloak projection. File ACL lives only in Postgres (`viewer` / `editor` on a role or group). Admin is the Keycloak realm role `admin`.

## Prerequisites

- Docker Compose
- Python 3.12+ and [uv](https://docs.astral.sh/uv/)
- [bun](https://bun.sh)
- ~4 GB RAM for OpenSearch (heap is 2g)
- Linux: `vm.max_map_count` ≥ 262144 if OpenSearch will not start

```bash
sudo sysctl -w vm.max_map_count=262144
```

## Setup

1. Copy env samples. Values are local demo defaults; do not commit real `.env` files.

```bash
cp backend/.env.sample .env
cp frontend/.env.sample frontend/.env
```

2. Start services:

```bash
docker compose up -d
```

3. Create the `app` schema (Alembic is **not** run by `init_services`):

```bash
cd backend && uv sync && uv run alembic upgrade head
```

4. Bootstrap Keycloak, the identity mirror, OpenSearch (JWT + index/model), and MinIO:

```bash
cd backend && uv run python -m init_services
```

If tables are missing, the mirror exits with `[error] identity tables missing`. Re-run the mirror after Keycloak changes; Keycloak wins if the two disagree.

5. API (http://localhost:8000) and UI (http://localhost:5173):

```bash
cd frontend && bun install
./start-dev.sh
```

Ctrl+C stops both. To run them separately:

```bash
cd backend && uv run python -c "from app.main import run; run()"
cd frontend && bun run dev
```

`GET /health` is public. `GET /auth/me` and `/auth/admin-ping` require a Bearer token.

OpenSearch verifies JWTs via Keycloak JWKS (`http://keycloak:8080/.../certs` from inside the container). Token `iss` stays `http://localhost:8080/realms/enterprise-search-realm`.

To wipe **only** the OpenSearch data volume (fresh cluster after a 2.x→3.x bump; does **not** touch Postgres or MinIO):

```bash
docker compose stop opensearch opensearch-dashboard
docker compose rm -f opensearch opensearch-dashboard
docker volume rm my_enterprise_search_opensearch_data
# then clear opensearch_model_id from backend/runtime_config.json if present
docker compose up -d opensearch opensearch-dashboard
cd backend && uv run python -m init_services
```

## Seed users (local)

| User | Password | Access |
| --- | --- | --- |
| `realm-admin` | `adminpass` | Search + Admin |
| `searcher` | `searcherpass` | Search only |

SPA client: `web-client`. API and OpenSearch audience: `api-client`.

After a successful mirror you should see seed users plus Keycloak built-ins and the `api-client` service account (typically users=3, roles=5, groups=`engineering` + `_empty`).

## Postgres (`app`)

| Tables | Purpose |
| --- | --- |
| `users`, `roles`, `groups`, `user_roles`, `user_groups` | Complete realm identity mirror (Keycloak UUID PKs; `users.id` = JWT `sub`) |
| `files` | File metadata only (`object_store_path`, `file_type`, `size_bytes`, `ingestion_type`, `original_source`, timestamps). No chunks, filename, or uploader. |
| `file_acl` | One principal per row (`user_id` **or** `role_id` **or** `group_id`). Permission `viewer` \| `editor`. v1 product grants target roles and groups; `user_id` is reserved for later connectors. |

A file with no role/group grant is not searchable. There is no automatic ACL on upload.

## Repo layout

```
backend/                 FastAPI app, Alembic, init_services
frontend/                React SPA
start-dev.sh             Local API + UI (uvicorn + Vite)
docker-compose.yml
docker_service_configs/  Keycloak realm, OpenSearch mappings, Postgres init
prompts/                 Setup notes and task plan
```
