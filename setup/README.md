# Local setup

One-command bootstrap from the repo root:

```bash
./setup/setup.sh
# optional:
./setup/setup.sh --with-seed --start
```

## What it does

1. Checks Docker, Compose, Python 3.12+, uv, bun (and Linux `vm.max_map_count`)
2. Copies `backend/.env.sample` → root `.env` and `frontend/.env.sample` → `frontend/.env` if missing
3. `docker compose up -d` and waits for Postgres / Keycloak / OpenSearch / MinIO
4. `uv sync` + `alembic upgrade head`
5. `python -m init_services` (existing bootstrap; not duplicated here)
6. Verifies realm, index, MinIO bucket, and `opensearch_model_id`
7. `bun install`
8. Optional ACL seed / proofs / `./start-dev.sh`

Re-runs are safe (idempotent). Existing `.env` files are **not** overwritten unless `--force-env`. A root `.env` created before internal ingest is missing `KEYCLOAK_INGEST_SECRET`; setup appends that one key from the sample and leaves every other key as it is.

## Flags

| Flag | Meaning |
| --- | --- |
| `--help` | Usage |
| `--check-only` | Prereqs + env only |
| `--force-env` | Overwrite `.env` from samples |
| `--skip-compose` | Stack already up |
| `--skip-init` | Skip `init_services` |
| `--skip-frontend` | Skip `bun install` |
| `--with-seed` | `scripts.seed_file_acl_for_proofs` (soft-ok if no files) |
| `--verify-proofs` | Run `scripts.search_view_proof` after seed |
| `--start` | Exec `./start-dev.sh` |
| `--no-verify` | Skip `verify_stack.py` |
| `--skip-opensearch-ml` | Allow missing model id |
| `-v` / `--verbose` | Extra logs |

Wait timeouts: Keycloak/OpenSearch **180s**, Postgres/MinIO **60s**. Override with `SETUP_WAIT_TIMEOUT_S` or `SETUP_WAIT_*_S`.

## Internal ingest interface

For a stack that is already up, apply the machine-ingest client, schema, and Keycloak client without a full bootstrap:

```bash
./setup/internal_ingest.sh
```

This starts the existing Compose services, runs `alembic upgrade head`, and runs `init_services` so an already-imported realm gets `ingest-client`. A Keycloak restart does not reimport `realm.json`. It does not start a pipeline container, does not set `INGESTION_PIPELINE_URL` (empty stays 503), and does not rotate a secret that is already set. `--skip-compose` assumes the stack is up. `--no-verify` skips the schema and token check.

Restart `./start-dev.sh` afterward so the API reloads `.env`.

## Manual fallback

See the root [README.md](../README.md) Setup section for step-by-step commands if you prefer not to use this script.

## Not in scope

- Volume wipe / `docker compose down -v` (destroy volumes manually)
- Production deploy or secret rotation
- Auto ACL on upload (product law)
