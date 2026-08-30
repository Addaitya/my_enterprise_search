# A–Z project setup script

Working plan to build a **one-command local bootstrap** for Enterprise Search. Sources: `prompts/summary/*` (product reality), root `README.md`, `backend/README.md`, `start-dev.sh`, and `backend/init_services/`.

**Agent rules while implementing**
- Run and execute code to confirm it works before moving on.
- Do not proceed past a broken step; fix it first.
- Where something cannot be verified in this environment (RAM, `vm.max_map_count`, Docker Desktop quirks), leave a clear human check and wait for feedback.
- Reuse existing bootstrap (`init_services`, Alembic, env samples). Do **not** reimplement Keycloak/OpenSearch/MinIO configure logic inside `setup/` — call them.
- Treat **Locked decisions** in this file as law.

---

## What “done” means

From a **fresh clone** (or a machine that already has Docker volumes), a developer can:

```bash
./setup/setup.sh                 # or: ./setup/setup.sh --with-seed --start
```

and end with:

1. Prerequisites checked (Docker, Compose, Python 3.12+, uv, bun; Linux mmap hint).
2. Root `.env` and `frontend/.env` present (copied from samples if missing; never overwrite without `--force-env`).
3. Compose stack up and healthy: Postgres, Keycloak, OpenSearch, MinIO (Dashboards / pgAdmin optional).
4. Backend deps synced (`uv sync`), Alembic at `head` (all migrations including `acl_sync_jobs`).
5. `python -m init_services` succeeded (Keycloak clients/users, identity mirror, OS JWT+DLS+ML+index, MinIO bucket).
6. Frontend deps installed (`bun install`).
7. Optional: ACL demo seed + smoke proofs.
8. Optional: `./start-dev.sh` (API :8000 + UI :5173).
9. Print a short “you are ready” summary (URLs, seed users, next commands).

| Actor | Responsibility after setup |
| --- | --- |
| `setup/` | Orchestrate checks → env → compose → migrate → init_services → frontend → optional seed/start |
| `init_services` | Idempotent service bootstrap (unchanged contract) |
| Alembic | Schema only (still **not** inside `init_services`) |
| `start-dev.sh` | Dev process supervisor (optional invoke from setup) |
| Human | Approve sudo for `vm.max_map_count`; first OS model download time/RAM |

**Not done by this task:** production deploy, CI image builds, secret rotation for shared hosts, rewriting Compose, moving app code.

---

## Current state (manual path to automate)

Root `README.md` today:

```text
cp backend/.env.sample .env
cp frontend/.env.sample frontend/.env
docker compose up -d
cd backend && uv sync && uv run alembic upgrade head
cd backend && uv run python -m init_services
cd frontend && bun install
./start-dev.sh
```

Gaps the script must close:

| Gap | Why it hurts |
| --- | --- |
| No prereq check | Failures look like “OpenSearch won’t start” instead of missing uv/bun/mmap |
| No wait/retry around compose + init | `init_services` has short waits (8s); cold Keycloak/OS often need longer |
| Alembic separate from init | Easy to forget → identity mirror errors with “identity tables missing” |
| No single entrypoint | Docs drift; new contributors miss admin re-init after 6a service-account roles |
| Seed/proofs optional but undocumented in one place | Uploads stay invisible until ACL grants |

---

## Target filesystem

Create **`setup/`** at the **repo root** (sibling of `backend/`, `frontend/`, `docker-compose.yml`).

```
my_enterprise_search/
├── setup/
│   ├── setup.sh                 # main entry (bash orchestrator; chmod +x)
│   ├── lib/
│   │   ├── common.sh            # colors, die(), root detect, logging
│   │   ├── check_prereqs.sh     # docker, compose, python, uv, bun, mmap, RAM hint
│   │   ├── env.sh               # copy .env samples; validate required keys
│   │   ├── compose.sh           # up -d, wait for health / ports
│   │   ├── backend.sh           # uv sync, alembic upgrade head
│   │   ├── init_services.sh     # invoke python -m init_services with longer wait policy
│   │   ├── frontend.sh          # bun install
│   │   └── seed.sh              # optional ACL seed (+ optional proofs)
│   ├── python/
│   │   ├── wait_ready.py        # poll Postgres/Keycloak/OS/MinIO until ready (longer timeouts)
│   │   ├── verify_stack.py      # post-bootstrap smoke: health, realm, OS cluster, bucket, model id
│   │   └── print_summary.py     # final URLs / users / next steps
│   └── README.md                # how to run flags (short; root README links here)
├── start-dev.sh                 # unchanged; setup may exec it with --start
├── docker-compose.yml
├── backend/
└── frontend/
```

**Language split (locked intent):**

| Layer | Language | Why |
| --- | --- | --- |
| Orchestration, CLI flags, calling tools | **Bash** | Matches `start-dev.sh`; easy chmod +x entry |
| Waits, HTTP/DB probes, JSON summary | **Python** | Reuse settings/`httpx`/SQLAlchemy patterns; richer than curl loops |
| Service configure | Existing **`init_services`** | Do not duplicate |

Prefer thin bash that `cd`s to repo root and calls `uv run python setup/python/...` or `uv run python -m init_services` from `backend/`.

---

## Dependency map

```
prereqs → env files → docker compose up
                           │
                           ▼
                    wait_ready.py (ports/health)
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
         uv sync      alembic head   (compose healthy)
              │            │
              └─────┬──────┘
                    ▼
            python -m init_services
                    │
                    ▼
            verify_stack.py
                    │
         bun install (frontend)
                    │
         [--with-seed] seed_file_acl_for_proofs (+ optional proofs)
                    │
         [--start] ./start-dev.sh
                    │
            print_summary.py
```

Order is strict: **never** run Alembic before Postgres accepts connections; **never** run `init_services` identity sync before Alembic head; **never** treat setup as success if OpenSearch model id is missing after init (unless `--skip-opensearch-ml` — see open questions).

---

## Locked decisions

### G1. Location and entrypoint

| | |
| --- | --- |
| Status | **LOCKED** |
| Decision | All new setup code lives under repo-root **`setup/`**. Single public entry: **`./setup/setup.sh`**. |

### G2. Reuse, don’t rewrite bootstrap

| | |
| --- | --- |
| Status | **LOCKED** |
| Decision | Call `uv run python -m init_services` and `uv run alembic upgrade head`. Do not fork Keycloak/OS/MinIO configure into `setup/python`. Waits/verify may be new. |

### G3. Env files are copy-once by default

| | |
| --- | --- |
| Status | **LOCKED** |
| Decision | If root `.env` missing → `cp backend/.env.sample .env`. If `frontend/.env` missing → `cp frontend/.env.sample frontend/.env` (`.env.example` is equivalent content; prefer `.env.sample` for symmetry). **Never** overwrite existing `.env` unless `--force-env`. Never commit real `.env`. |

### G4. Idempotent re-runs

| | |
| --- | --- |
| Status | **LOCKED** |
| Decision | Re-running `./setup/setup.sh` on an already-bootstrapped machine is safe: compose up is no-op-ish, Alembic no-op at head, `init_services` idempotent, `bun install` / `uv sync` refresh locks. |

### G5. Fail fast with actionable errors

| | |
| --- | --- |
| Status | **LOCKED** |
| Decision | Missing Docker/uv/bun → exit non-zero with install hint. OpenSearch mmap too low → print exact `sysctl` command and exit (do not silently continue). Identity tables missing → tell user Alembic step failed (should not happen if order is correct). |

### G6. Optional seed and start are flags

| | |
| --- | --- |
| Status | **LOCKED** |
| Decision | Default setup does **not** seed ACL and does **not** start dev servers. `--with-seed` runs `scripts.seed_file_acl_for_proofs` (requires prior uploads or documents that none were seeded). `--start` execs/invokes `./start-dev.sh` after success. `--verify-proofs` (optional, slower) may run selected proof modules after seed. |

### G7. Mix bash + Python is intentional

| | |
| --- | --- |
| Status | **LOCKED** |
| Decision | Bash orchestrates; Python probes and summarizes. No requirement for a pure-Python CLI (Click/Typer) in v1 of this script. |

---

## Open questions (resolve before or during implementation)

| ID | Question | Default if unanswered |
| --- | --- | --- |
| C1 | Should setup auto-attempt `sudo sysctl -w vm.max_map_count=262144` or only print instructions? | **Print only** (safer; no surprise sudo). |
| C2 | Include pgAdmin + OpenSearch Dashboards in “required healthy” wait? | **No** — only postgres, keycloak, opensearch, minio. |
| C3 | `--with-seed` when zero files exist? | Exit 0 with message “no files to seed”; do not fail whole setup. |
| C4 | Longer wait timeouts? | Keycloak/OS: **180s** total; Postgres/MinIO: **60s**. Override via `SETUP_WAIT_TIMEOUT_S`. |
| C5 | Wire root README “Setup” section to `./setup/setup.sh`? | **Yes** — small README edit in same PR/task as script. |
| C6 | Reset / wipe mode (`--destroy-volumes`)? | **Out of scope** for v1 (document manual volume wipe from README). |

---

## CLI contract

```bash
./setup/setup.sh [options]

Options:
  --help              Show usage
  --check-only        Prereqs + env presence only; no compose/migrate
  --force-env         Overwrite .env files from samples (destructive to local secrets)
  --skip-compose      Assume stack already up; still wait_ready + migrate + init
  --skip-init         Skip python -m init_services (migrate + deps only)
  --skip-frontend     Skip bun install
  --with-seed         Run seed_file_acl_for_proofs after init
  --verify-proofs     After seed, run search_view_proof (and/or admin proofs if flagged later)
  --start             Start ./start-dev.sh after success (foreground)
  --no-verify         Skip verify_stack.py (not recommended)
  -v, --verbose       Extra logs
```

Exit codes:

| Code | Meaning |
| --- | --- |
| 0 | Success |
| 1 | Generic / step failure |
| 2 | Prereq missing |
| 3 | Env/config invalid |
| 4 | Compose / wait timeout |
| 5 | Migrate or init_services failed |

---

## Phase tasks (implementation checklist)

Check a box only after the step has been run and verified.

### Phase A — Scaffold

- [x] Create `setup/` tree as in **Target filesystem**
- [x] `setup/setup.sh` parses flags, sources `lib/*.sh`, resolves `REPO_ROOT`
- [x] `lib/common.sh`: logging (`info`/`warn`/`error`), `die`, `REPO_ROOT`
- [x] Short `setup/README.md` (flags + examples)
- [x] Ensure scripts are executable (`chmod +x setup/setup.sh`)

### Phase B — Prerequisites & env

- [x] `check_prereqs.sh`: `docker`, `docker compose` (or `docker-compose`), `python3` ≥ 3.12, `uv`, `bun`
- [x] Detect Linux `vm.max_map_count`; if `< 262144`, warn/fail with sysctl hint (C1)
- [x] Optional RAM hint if free memory ≪ 4 GB (warn only)
- [x] `env.sh`: copy samples per G3; assert required keys exist (at least those in `backend/.env.sample` + frontend Vite keys)

### Phase C — Compose & wait

- [x] `compose.sh`: `docker compose up -d` from repo root (uses root `.env`)
- [x] `python/wait_ready.py`: poll until Postgres (`SELECT 1` via app DSN or admin), Keycloak realm URL, OpenSearch `_cluster/health` (basic admin), MinIO `/minio/health/live`
- [x] Timeouts per C4; clear error naming which service timed out
- [x] Do not require Dashboards/pgAdmin healthy (C2)

### Phase D — Backend

- [x] `backend.sh`: `cd backend && uv sync`
- [x] `uv run alembic upgrade head` (must apply through latest, including ACL jobs migration when present)
- [x] Confirm failure surfaces Alembic stderr (no silent skip)

### Phase E — init_services

- [x] `init_services.sh`: from `backend/`, `uv run python -m init_services`
- [x] Prefer running **after** `wait_ready.py` so init’s short internal waits are not the only gate
- [x] On failure, print pointer to `backend/README.md` `init_services` section

### Phase F — Verify

- [x] `verify_stack.py`:
  - Root `.env` readable by Settings
  - `GET` FastAPI not required yet (API may be down) — prefer infra checks:
    - Postgres: identity tables exist (`users` or alembic_version at head)
    - Keycloak: realm `enterprise-search-realm` reachable
    - OpenSearch: cluster not red; index `enterprise-search-chunks` exists **or** will after init (run verify **after** init)
    - `runtime_config.json` contains `opensearch_model_id` after successful ML bootstrap
    - MinIO bucket exists (name from settings)
  - Optional: if API already running, `GET /health`
- [x] Fail setup if model id missing after init (unless open question exception)

### Phase G — Frontend

- [x] `frontend.sh`: `cd frontend && bun install`
- [x] Confirm `frontend/.env` present

### Phase H — Optional seed / proofs / start

- [x] `seed.sh --with-seed` → `uv run python -m scripts.seed_file_acl_for_proofs` (C3 soft-pass if no files)
- [x] `--verify-proofs` → at least `scripts.search_view_proof` when seed likely meaningful; document that upload+admin flows need a running API
- [x] `--start` → `exec` or invoke repo `./start-dev.sh` (preserve Ctrl+C behavior)

### Phase I — Summary & docs

- [x] `print_summary.py` prints:
  - UI http://localhost:5173 · API http://localhost:8000 · Keycloak :8080 · OS :9200 · MinIO :9000/:9001
  - Users: `realm-admin` / `adminpass`, `searcher` / `searcherpass`
  - Next: open UI, upload, Admin ACL if needed, or `--with-seed` after upload
- [x] Update root `README.md` Setup section to lead with `./setup/setup.sh` (keep manual steps as fallback)
- [x] Link from `backend/README.md` / `frontend/README.md` one-liner if useful

### Phase J — Human verification

- [ ] **Human:** cold path — `docker compose down`, fresh `.env` from samples, `./setup/setup.sh` end-to-end
- [x] **Human:** warm path — re-run `./setup/setup.sh` (idempotent)
- [ ] **Human:** `--check-only` on a machine missing bun (expect exit 2)
- [ ] **Human:** login as `realm-admin`, hit `/admin`, upload + ACL or seed, search returns hits
- [x] **Human:** OpenSearch first boot (model download) completes; `opensearch_model_id` persisted

---

## What the script must NOT do

- Commit or print secrets from `.env` into logs (redact passwords).
- Run `docker compose down -v` or delete volumes (C6).
- Start Celery/Redis (project has none; admin ACL uses BackgroundTasks).
- Bypass JWT/ACL for “easier local demo” (no auto `all_access` for searcher).
- Auto-grant ACL on upload (product law G3 from ingest summary).
- Replace `init_services` identity mirror or Keycloak Admin product paths.

---

## Relation to product slices (`prompts/summary`)

| Summary | Setup implication |
| --- | --- |
| `1_high_level_project_info.md` | Full stack: KC + PG + OS + MinIO + React |
| `2_auth_layer.md` | After init: seed users + JWT domain must exist |
| `3_data_modeling.md` | Alembic before identity mirror |
| `4_search_layer.md` / OS 3.8 notes | Model register needs RAM + time; persist model id |
| `5_local_ingestion_setup.md` | Upload needs running API; seed optional after files exist |
| `6` / `7` search view | Proofs need ACL + JWT; wire optional `--verify-proofs` |
| `8a` / `8b` admin | Re-run init so `api-client` service-account roles exist for Admin API |

---

## Suggested implementation order for the coding agent

1. Scaffold `setup/` + `setup.sh` flag parsing + `common.sh`.
2. Prereqs + env copy.
3. Compose up + `wait_ready.py`.
4. `uv sync` + Alembic + `init_services`.
5. `verify_stack.py` + summary.
6. Frontend install + optional seed/start flags.
7. README updates + human cold/warm runs.

---

## Acceptance criteria (v1)

1. `./setup/setup.sh --help` documents flags above.
2. On a machine with prereqs, `./setup/setup.sh` brings stack from “compose may be down” to “init_services finished + frontend installed” without further manual steps.
3. Second run does not destroy data or rewrite `.env` (without `--force-env`).
4. Failure modes name the failing stage and suggest the next fix.
5. Root README documents the script as the primary local path.

---

## Changelog

| Date | Change |
| --- | --- |
| 30 Aug 2026 | Initial plan: `setup/` bash+Python A–Z bootstrap; G1–G7 locked; phases A–J. |
| 30 Aug 2026 | Implemented `setup/`; warm path + `--check-only` + full setup verified on this machine. Phase J cold/missing-bun/login still human. |
