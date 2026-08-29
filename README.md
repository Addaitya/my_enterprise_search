# Enterprise Search

Company-internal hybrid search (keyword + semantic) over uploaded files, with role- and group-based access control. v1 is local PDF/TXT upload only.

## Stack

| Layer | Choice |
| --- | --- |
| Backend | FastAPI, SQLAlchemy, Alembic, uv |
| Frontend | React, Vite, Tailwind, Zustand, bun |
| Auth | Keycloak 26.2 (`web-client` PKCE, `api-client` for the API) |
| Search | OpenSearch 2.19.1 (ML Commons MiniLM embeddings) |
| Storage | PostgreSQL 16, MinIO |

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

3. Bootstrap Keycloak, OpenSearch (JWT + index/model), and MinIO:

```bash
cd backend && uv sync && uv run python -m init_services
```

4. API (http://localhost:8000) and UI (http://localhost:5173):

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

## Seed users (local)

| User | Password | Access |
| --- | --- | --- |
| `realm-admin` | `adminpass` | Search + Admin |
| `searcher` | `searcherpass` | Search only |

SPA client: `web-client`. API and OpenSearch audience: `api-client`.

## Repo layout

```
backend/                 FastAPI app, Alembic, init_services
frontend/                React SPA
start-dev.sh             Local API + UI (uvicorn + Vite)
docker-compose.yml
docker_service_configs/  Keycloak realm, OpenSearch mappings, Postgres init
prompts/                 Setup notes and task plan
```
