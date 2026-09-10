# Enterprise Search

Company-internal hybrid search (keyword + semantic) over uploaded files, with role- and group-based access control. v1 accepts local **PDF / TXT / CSV** uploads.

**Now:** Compose stack, Keycloak PKCE login, FastAPI JWT, OpenSearch 3.8 JWKS + `files_searcher` DLS, Postgres identity mirror + `files` / `file_acl` / `upload_sessions` / `search_query_metrics`, resumable ingest API, React multi-file `/upload`, **client-hybrid `POST /search`**, ACL-filtered **View files** + **Open** (MinIO stream), admin **Dashboard** (live stats + placeholders), **Access Control(Admin)** (Users / Roles / Groups / Access), **Configuration** placeholder.

**Not yet:** Check-access explorer / audit CSV, Task 7 SKIP LOCKED + dual-write repair, native OpenSearch `hybrid`+DLS (needs 3.9+; product path uses client-side merge on 3.8), connector ingestion pipeline (dashboard connector / rate / last-sync stay API placeholders).

## Stack

| Layer | Choice |
| --- | --- |
| Backend | FastAPI, SQLAlchemy, Alembic, uv |
| Frontend | React, Vite, Tailwind, Zustand, bun |
| Auth | Keycloak 26.2 (`web-client` PKCE, `api-client` for the API) |
| Search | OpenSearch 3.8.0 (ML Commons MiniLM ONNX embeddings; JWT via Keycloak JWKS) |
| Storage | PostgreSQL 16 (identity mirror, file metadata, ACL, upload sessions), MinIO (bytes) |

Request auth stays on the **JWT**. Postgres identity is a one-way Keycloak projection. File ACL lives only in Postgres (`viewer` / `editor` on a role or group). Uploads index chunks with **empty** ACL — searchable / listable only after an admin grant (Access tab / bulk APIs) or the optional seed script. Admin is the Keycloak realm role `admin` (does **not** bypass file ACL).

### Search on OpenSearch 3.8

Native `hybrid` + DLS hits a ClassCast bug on 3.8. Product `POST /search` runs **client-side hybrid**: parallel match + neural queries with the **user JWT**, then FastAPI min_max + weights `[0.3, 0.7]`. OpenSearch DLS still applies on each subquery. Native hybrid stays off the hot path until 3.9 proofs.

### Access control split

| Concern | Source of truth |
| --- | --- |
| Search hits | OpenSearch DLS on chunk `allowed_roles` / `allowed_groups` |
| View files / Open download | Postgres `file_acl` (JWT role/group **names**; `editor` ⇒ view) |
| File bytes | MinIO path from `files.object_store_path` only (never a client-supplied key) |

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

Primary path — one command from the repo root ([setup/README.md](setup/README.md)):

```bash
./setup/setup.sh
# optional ACL seed + start API/UI:
./setup/setup.sh --with-seed --start
```

This checks prereqs, copies env samples if missing, brings Compose up, waits for services, runs Alembic + `init_services`, installs frontend deps, and prints URLs / seed users. Re-runs are idempotent; existing `.env` files are not overwritten unless `--force-env`.

### Manual fallback

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

Vite proxies `/api` → FastAPI. Sign in, then:

- **Upload** (`/upload`) — PDF/TXT/CSV (25 MiB max each)
- **Search** (`/`) — hybrid search + Open download
- **View files** (`/files`) — ACL-filtered list + Open
- **Dashboard** (`/dashboard`, realm `admin`) — six KPIs from `GET /admin/stats`
- **Access Control(Admin)** (`/admin`, realm `admin`) — Users / Roles / Groups / Access (file grants + members)
- **Configuration** (`/configuration`, realm `admin`) — placeholder copy

`GET /health` is public. Product routes (`/auth/me`, `/search`, `/files*`, `/files/uploads*`) require a Bearer token. Admin identity/ACL routes and `GET /admin/stats` require realm role `admin`.

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

### Admin Dashboard, Access Control, Configuration

Navbar (realm `admin` only): Search | Upload | View files | **Dashboard** | **Access Control(Admin)** | **Configuration**. Non-admin users do not see those three links; deep-links show Forbidden.

| Page | Path | What it does |
| --- | --- | --- |
| **Dashboard** | `/dashboard` | Six cards from `GET /admin/stats`. Live: avg query time (**last 24 hours** of successful `POST /search`; `—` if none), MinIO bucket size, `COUNT(*)` of `files`. Placeholders until the connector pipeline: active connectors `8`, ingest rate `12,400 docs/hr`, last sync `"2 min ago"`. MinIO list failure → **502**. |
| **Access Control(Admin)** | `/admin` | Identity + file ACL (tabs unchanged). Label only — URL, `Admin.tsx`, and `/admin/*` APIs stay. |
| **Configuration** | `/configuration` | Body text `this is configuration.` (no settings API yet). |

Successful searches persist `took_ms` (no query text) into `search_query_metrics`. Migrate with `uv run alembic upgrade head` (`c3d4e5f6a7b8`). Proof: `uv run python -m scripts.admin_stats_proof`.

### Admin file access + members

As `realm-admin` open `/admin`:

| Tab | What it does |
| --- | --- |
| **Users** | Create/edit users; chip role/group pickers; multi-select → Add to role/group |
| **Roles** / **Groups** | CRUD + **Members** (add/remove users) + **File access** (list grants, Grant files…) |
| **Access** | Browse all files; Manage access (PUT replace-all); multi-select Grant/Revoke → sync job tray |

File grants target **roles/groups** only (Viewer/Editor). Membership changes: Keycloak first, then Postgres; users must **re-login** before search JWT roles/groups update. Bulk file ACL: max 100 files; upsert / replace (`confirm_replace`) / revoke; partial `results[]` / `failed[]`.

### Optional: ACL seed for list / search proofs

Uploads have **no** `file_acl` until an admin grant. For local demos without the Access UI, seed one/two recent files:

```bash
cd backend
uv run python -m scripts.seed_file_acl_for_proofs
uv run python -m scripts.search_view_proof
```

File A gets role `search-user` viewer; file B gets group `engineering` viewer (and matching OpenSearch `allowed_*`). Never grants `_empty`.

## Postgres (`app`)

| Tables | Purpose |
| --- | --- |
| `users`, `roles`, `groups`, `user_roles`, `user_groups` | Complete realm identity mirror (Keycloak UUID PKs; `users.id` = JWT `sub`) |
| `files` | File metadata only (`object_store_path`, `file_type`, `size_bytes`, `ingestion_type`, `original_source`, timestamps). No chunks, filename, or uploader. |
| `file_acl` | One principal per row (`user_id` **or** `role_id` **or** `group_id`). Permission `viewer` \| `editor`. v1 product grants target roles and groups; `user_id` is reserved for later connectors. |
| `upload_sessions` | Resumable upload state (local staging path, bytes received, status). TTL 24h. |
| `search_query_metrics` | Successful `POST /search` latency (`took_ms`, `created_at`). Unbounded; dashboard averages the last 24 hours. No query text. |

A file with no role/group grant is not searchable or listable. There is no automatic ACL on upload.

## Package docs

- [backend/README.md](backend/README.md) — API (incl. `/admin/*` + `/admin/stats`), ingest, search, `init_services`, proofs
- [frontend/README.md](frontend/README.md) — SPA routes, auth, search/files/upload/admin clients

## Repo layout

```
backend/                 FastAPI app, Alembic, init_services, ingest + search scripts
frontend/                React SPA (PKCE login, search, upload, files)
setup/                   One-command local bootstrap (./setup/setup.sh)
start-dev.sh             Local API + UI (uvicorn + Vite)
docker-compose.yml
docker_service_configs/  Keycloak realm, OpenSearch mappings/pipelines/security, Postgres init
prompts/                 Setup notes and task plan
```
