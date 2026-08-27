# Project Setup Summary

Working notes for scaffolding this repo. Source: `prompts/instructions/1_setup_project.md` and existing `.env`.

**Agent rules while implementing setup**
- Run and execute code to confirm it works before moving on.
- Do not proceed past a broken step; fix it first.
- Where something cannot be verified in this environment, leave a clear human check and wait for feedback.

---

## Tech stack

| Layer | Choice |
|---|---|
| Backend | FastAPI |
| ORM | SQLAlchemy |
| Schema migrations | Alembic |
| Python packages | uv |
| Database | PostgreSQL |
| Search | OpenSearch (embeddings via HuggingFace `sentence-transformers/all-MiniLM-L6-v2` downloaded directly in opensearch). |
| Auth | Keycloak |
| Object storage | MinIO |
| Frontend | React |
| CSS | Tailwind |
| Client state | Zustand |
| JS packages | bun |

---

## Target filesystem

Create two top-level app folders: `backend/` and `frontend/`. Keep docker service config in a dedicated directory (name TBD; instruction draft: `docker_service_configs/`).

```
my_enterprise_search/
├── backend/
│   ├── app/                          # FastAPI application package
│   │   ├── __init__.py
│   │   ├── main.py                   # app factory / entry
│   │   ├── api/                      # routers
│   │   ├── core/                     # config, security helpers
│   │   ├── models/                   # SQLAlchemy models
│   │   ├── schemas/                  # Pydantic request/response
│   │   ├── services/                 # domain logic
│   │   └── db/                       # session, engine
│   ├── init_services/                # bootstrap docker services via API calls
│   ├── alembic/                      # migrations
│   ├── alembic.ini
│   ├── pyproject.toml                # uv project
│   ├── uv.lock
│   ├── .env                          # sensitive values (do not commit secrets)
│   └── runtime_config.json           # generated-at-runtime values cached in dev
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── ui/                   # primitive UI
│   │   │   └── layout/               # shells, navbar, admin layout
│   │   ├── hooks/
│   │   ├── store/                    # Zustand
│   │   ├── api/                      # external HTTP calls
│   │   ├── config/                   # frontend config values
│   │   └── App.tsx
│   ├── package.json                  # bun
│   └── tailwind config
├── docker_service_configs/           # per-service docker config
│   └── keycloak/
│       └── realm.json
├── docker-compose.yml                # (implied by Step 2)
└── prompts/
```

Exact backend/frontend internals can follow common FastAPI + Vite/React conventions; the folders above are the required surfaces.

---

## Backend config management

Three sources, one Settings object:

1. **pydantic-settings** — non-sensitive config (host, ports, index names, feature flags, etc.).
2. **`.env`** — secrets only (DB passwords, Keycloak client secret, MinIO keys, etc.).
3. **Runtime-generated values** — produced at process start (tokens, discovered URLs, bootstrap IDs, etc.).
   - In development, **do not regenerate on every restart**. Persist them in a JSON file (e.g. `runtime_config.json`) and load into the pydantic Settings object.

`.env` already present at repo root (move or duplicate into backend as needed):

| Key | Purpose |
|---|---|
| `POSTGRES_ADMIN_USER` / `POSTGRES_ADMIN_PASSWORD` | Postgres superuser |
| `KEYCLOAK_DB` / `KEYCLOAK_USER` / `KEYCLOAK_PASSWORD` | Keycloak DB + admin user |
| `APP_DB` / `APP_USER` / `APP_PASSWORD` | Application database |
| `KEYCLOAK_API_SECRET` | `api-client` secret (`api-client-secret`) |

---

## `init_services/`

Directory for **initializing docker services through API calls**, not only compose `depends_on`. Typical uses:

- Wait until Keycloak / OpenSearch / MinIO / Postgres are healthy.
- Import or verify the Keycloak realm and client.
- Create OpenSearch index + DLS settings.
- Create MinIO buckets.
- Create app DB user/schema if not handled by compose.

Keep these as idempotent scripts/modules invoked from a one-shot command or compose `init` service.

---

## Frontend setup

Ideal React app with:

- Tailwind CSS
- Zustand for state
- `components/ui` and `components/layout`
- Dedicated module for backend API calls
- Custom hooks
- Config value storage (env-based public config, not secrets)

Package manager: **bun**.

---

## Docker Compose (Step 2)

Create a directory for per-service config. Instruction name: `docker_service_configs/` (use a clearer name if preferred, e.g. `deploy/services/` — pick one and stick to it).

### Specified so far

**Keycloak**
- Config path: `docker_service_configs/keycloak/realm.json`
- Realm: `enterprise-search-realm`
- Client: `api-client` (secret already in `.env` as `KEYCLOAK_API_SECRET`)

### Implied but not specified in the setup prompt

Compose will also need Postgres, OpenSearch, and MinIO to match the product. Those service configs, images, ports, volumes, and networks are **not yet written** in the instruction file — define them when implementing Step 2, aligned with `.env` and the search/ACL design.

---

## Setup task checklist

- [x] Create `backend/` with FastAPI + uv + SQLAlchemy + Alembic
- [x] Wire pydantic-settings + `.env` + runtime JSON cache
- [x] Create `init_services/` bootstrap flow
- [x] Create `frontend/` with React + bun + Tailwind + Zustand + ui/layout/hooks/api/config
- [x] Create `docker_service_configs/`
- [x] Keycloak `realm.json`: realm `enterprise-search-realm`, client `api-client`
- [x] Docker Compose for Keycloak, Postgres, OpenSearch, MinIO
- [ ] Verify stack with `docker compose up` (human; RAM / `vm.max_map_count`)
- [x] Verify backend `/health` and frontend production build locally
