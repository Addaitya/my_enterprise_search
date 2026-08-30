# A–Z local setup script

**Implemented 30 August 2026.** Plan: `prompts/cursor_summary/10_setup.md`. One-command bootstrap under repo-root **`setup/`**. Does **not** rewrite Compose, `init_services`, or product ACL/upload rules.

Orchestration is **bash**; waits / verify / summary are **Python** via `uv run` from `backend/`. Service configure stays in existing `python -m init_services`.

---

## What shipped

### A. Entrypoint and layout

| Piece | Location |
| --- | --- |
| Public entry | `./setup/setup.sh` (`chmod +x`) |
| Shared helpers | `setup/lib/common.sh` — colors, `die`, exit codes, `REPO_ROOT`, `run_setup_python` |
| Docs | `setup/README.md`; root / backend / frontend READMEs point here |

```
setup/
├── setup.sh
├── lib/
│   ├── common.sh
│   ├── check_prereqs.sh
│   ├── env.sh
│   ├── compose.sh
│   ├── backend.sh
│   ├── init_services.sh
│   ├── frontend.sh
│   └── seed.sh
├── python/
│   ├── wait_ready.py
│   ├── verify_stack.py
│   └── print_summary.py
└── README.md
```

### B. Pipeline (strict order)

```
prereqs → env → compose up → uv sync → wait_ready → alembic head
       → init_services → verify_stack → bun install
       → [--with-seed] → [--verify-proofs] → [--start] → print_summary
```

| Step | Behavior |
| --- | --- |
| Prereqs | Docker + Compose, Python ≥3.12, `uv`, `bun`; Linux `vm.max_map_count` ≥262144 or **fail** with `sysctl` hint (print only, no sudo); RAM ≪4 GiB → **warn** |
| Env | Missing root `.env` ← `backend/.env.sample`; missing `frontend/.env` ← `.env.sample`. Never overwrite unless `--force-env`. Validate required keys |
| Compose | `docker compose up -d` from repo root; Dashboards/pgAdmin **not** required healthy |
| Wait | `wait_ready.py`: Postgres `SELECT 1`, Keycloak realm URL, OS `_cluster/health` (admin basic), MinIO `/minio/health/live`. Defaults: PG/MinIO **60s**, KC/OS **180s**; override `SETUP_WAIT_*_S` / `SETUP_WAIT_TIMEOUT_S` |
| Backend | `uv sync` then `alembic upgrade head` (includes `acl_sync_jobs` when present) |
| Init | `uv run python -m init_services` unchanged; longer wait already done upstream |
| Verify | Identity tables + alembic version; realm; OS not red + index; `opensearch_model_id` in `runtime_config.json`; MinIO bucket; optional `GET /health` if API up. Missing model id → fail unless `--skip-opensearch-ml` / `SETUP_SKIP_OPENSEARCH_ML=1` |
| Frontend | `bun install` |
| Seed | `--with-seed` → `scripts.seed_file_acl_for_proofs`; **soft-ok** if no files |
| Proofs | `--verify-proofs` → `scripts.search_view_proof` (needs API + ACL; documented) |
| Start | `--start` → `exec ./start-dev.sh` |

### C. CLI contract

```bash
./setup/setup.sh [options]
```

| Flag | Meaning |
| --- | --- |
| `--help` | Usage |
| `--check-only` | Prereqs + env only |
| `--force-env` | Overwrite `.env` from samples |
| `--skip-compose` | Stack already up; still wait + migrate + init |
| `--skip-init` | Skip `init_services` |
| `--skip-frontend` | Skip `bun install` |
| `--with-seed` | ACL seed after init |
| `--verify-proofs` | Run `search_view_proof` |
| `--start` | Foreground `start-dev.sh` |
| `--no-verify` | Skip `verify_stack.py` |
| `--skip-opensearch-ml` | Allow missing model id |
| `-v` / `--verbose` | Extra logs |

| Exit | Meaning |
| --- | --- |
| 0 | Success |
| 1 | Generic / step failure |
| 2 | Prereq missing |
| 3 | Env/config invalid |
| 4 | Compose / wait timeout |
| 5 | Migrate or `init_services` failed |

Re-runs are **idempotent** (G4): compose no-op-ish, Alembic at head, `init_services` idempotent, deps refresh.

### D. Docs

Root `README.md` Setup leads with `./setup/setup.sh`; manual steps kept as fallback. `backend/README.md` and `frontend/README.md` one-liner to `setup/README.md`. Repo layout lists `setup/`.

---

## Locked decisions (as shipped)

| ID | Decision |
| --- | --- |
| G1 | All setup code under `setup/`; entry `./setup/setup.sh` |
| G2 | Call `init_services` + Alembic; do not fork KC/OS/MinIO configure |
| G3 | Copy-once env; `--force-env` to overwrite |
| G4 | Safe re-runs |
| G5 | Fail fast with install / `sysctl` / Alembic hints |
| G6 | Seed and start are opt-in flags |
| G7 | Bash orchestrates; Python probes/summarizes (no Click/Typer v1) |
| C1 | mmap: print instructions only |
| C2 | Wait only postgres, keycloak, opensearch, minio |
| C3 | Zero files on `--with-seed` → exit 0 + message |
| C4 | Wait timeouts 60s / 180s as above |
| C5 | Root README wired to script |
| C6 | No `--destroy-volumes` in v1 |

---

## Verified (30 Aug 2026)

| Check | Result |
| --- | --- |
| `./setup/setup.sh --help` | Flags documented |
| `--check-only` | Prereqs + env OK; created missing `frontend/.env` |
| Full `./setup/setup.sh` (warm stack) | compose → wait → migrate → init → verify (model id + index + bucket) → bun install → summary |
| Idempotent re-run `--skip-compose` | OK |
| `--with-seed` | Seeded existing files (`opaque-redirect-fix.txt`, `longrow.csv`) |
| Cold `compose down` + fresh `.env` | **Human** (not run in agent session) |
| Missing bun → exit 2 | **Human** |
| Login / upload / search after setup | **Human** |

---

## Guide to use

```bash
# Primary
./setup/setup.sh

# After uploads, grant demo ACL
./setup/setup.sh --skip-compose --skip-init --with-seed

# Bootstrap + start API/UI
./setup/setup.sh --start
```

If OpenSearch will not start on Linux:

```bash
sudo sysctl -w vm.max_map_count=262144
```

Manual fallback remains in root README (copy env → compose → alembic → init_services → bun → `start-dev.sh`).

Wipe volumes manually if needed (`docker compose down -v` or OS volume rm); setup will not destroy data.

---

## Intentionally out of scope

- Production deploy, CI image builds, secret rotation
- `docker compose down -v` / `--destroy-volumes`
- Reimplementing Keycloak / OpenSearch / MinIO bootstrap inside `setup/python`
- Auto ACL on upload; bypass JWT/ACL for demos
- Celery/Redis (none in project)
- Printing secrets from `.env` into logs

---

## Relation to earlier summaries

| Summary | Setup implication |
| --- | --- |
| `1_high_level_project_info.md` | Full stack: KC + PG + OS + MinIO + React |
| `2_auth_layer.md` | After init: seed users + JWT domain |
| `3_data_modeling.md` | Alembic before identity mirror |
| `4_search_layer.md` / OS 3.8 | Model register needs RAM/time; persist model id |
| `5_local_ingestion_setup.md` | Upload needs running API; seed optional after files |
| `6` / `7` search view | Optional `--verify-proofs` needs ACL + JWT |
| `8a` / `8b` admin | Re-run init so `api-client` service-account roles exist |

---

## Files touched (reference)

```
setup/setup.sh
setup/lib/*.sh
setup/python/wait_ready.py
setup/python/verify_stack.py
setup/python/print_summary.py
setup/README.md
README.md
backend/README.md
frontend/README.md
prompts/cursor_summary/10_setup.md   # plan + checklist
prompts/summary/9_setup.md           # this file
```
