#!/usr/bin/env bash
# Apply the internal ingest interface to the Compose stack and the backend.
#
# Idempotent. Safe to re-run.
# - Appends KEYCLOAK_INGEST_SECRET to an existing root .env when the key is missing.
#   Does not overwrite a secret that is already set, and does not rotate the
#   Keycloak client secret if ingest-client already exists.
# - Starts the existing Compose services (postgres, keycloak, opensearch, minio).
#   Does not add a pipeline container. That service is not in this repo.
# - Runs Alembic (ingest_jobs, connectors, connector_syncs) and init_services
#   so an already-imported realm gets ingest-client. A Keycloak restart does
#   not reimport realm.json.
# - Leaves INGESTION_PIPELINE_URL unset. An empty URL makes admin connector
#   create and sync return 503.
#
# Usage: ./setup/internal_ingest.sh [--skip-compose] [--no-verify] [-v]
set -euo pipefail

SETUP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SETUP_DIR}/lib/common.sh"
# shellcheck source=lib/env.sh
source "${SETUP_DIR}/lib/env.sh"
# shellcheck source=lib/compose.sh
source "${SETUP_DIR}/lib/compose.sh"
# shellcheck source=lib/backend.sh
source "${SETUP_DIR}/lib/backend.sh"
# shellcheck source=lib/init_services.sh
source "${SETUP_DIR}/lib/init_services.sh"

FLAG_SKIP_COMPOSE=0
FLAG_NO_VERIFY=0

usage() {
  cat <<'EOF'
Usage: ./setup/internal_ingest.sh [options]

Prepare a local stack for the internal ingestion pipeline interface:
env → compose → alembic upgrade head → init_services → verify.

Does not start a pipeline service. Does not set INGESTION_PIPELINE_URL.
Does not wipe volumes or rotate an existing ingest-client secret.

Options:
  --help           Show this help
  --skip-compose   Stack already up; still wait, migrate, and init
  --no-verify      Skip the schema and ingest-client token check
  -v, --verbose    Extra logs

Environment:
  SETUP_WAIT_TIMEOUT_S     Cap all wait timeouts (seconds)
  SETUP_WAIT_POSTGRES_S    Postgres wait (default 60)
  SETUP_WAIT_KEYCLOAK_S    Keycloak wait (default 180)
  SETUP_WAIT_OPENSEARCH_S  OpenSearch wait (default 180)
  SETUP_WAIT_MINIO_S       MinIO wait (default 60)

Exit codes: 0 ok · 1 fail · 3 env · 4 compose/wait · 5 migrate/init
EOF
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --help|-h) usage; exit 0 ;;
      --skip-compose) FLAG_SKIP_COMPOSE=1 ;;
      --no-verify) FLAG_NO_VERIFY=1 ;;
      -v|--verbose) SETUP_VERBOSE=1; export SETUP_VERBOSE ;;
      *)
        error "unknown option: $1"
        usage
        exit "${EXIT_FAIL}"
        ;;
    esac
    shift
  done
}

print_next() {
  cat <<'EOF'

Internal ingest interface is ready.

  Token     POST http://localhost:8080/realms/enterprise-search-realm/protocol/openid-connect/token
            grant_type=client_credentials  client_id=ingest-client
            client_secret=$KEYCLOAK_INGEST_SECRET
  Reserve   POST http://localhost:8000/internal/ingest/files
  Complete  POST http://localhost:8000/internal/ingest/files/{file_id}/complete
  Status    POST http://localhost:8000/internal/connectors/{connector_id}/status

  Presigned PUT host defaults to minio:9000 (reachable on the Compose network).
  Set MINIO_PRESIGN_ENDPOINT=localhost:9000 in the root .env only when a process
  on the host must PUT that URL, then restart the API.

  INGESTION_PIPELINE_URL is left empty. Connector create and sync return 503
  until that URL is set and the API is restarted. This repo does not run the pipeline.

  Restart the API (./start-dev.sh) so it reloads .env.
EOF
}

main() {
  parse_args "$@"
  require_repo_root
  cd "${REPO_ROOT}"

  info "internal ingest interface setup (repo: ${REPO_ROOT})"
  ensure_internal_ingest_env

  if (( FLAG_SKIP_COMPOSE == 0 )); then
    compose_up
  else
    info "skipping compose up (--skip-compose)"
  fi

  backend_uv_sync
  wait_stack_ready
  backend_migrate
  run_init_services

  if (( FLAG_NO_VERIFY == 0 )); then
    info "verifying ingest schema and ingest-client token..."
    if ! run_setup_python verify_internal_ingest.py; then
      die "internal ingest verify failed" "${EXIT_FAIL}"
    fi
    ok "internal ingest verify"
  else
    warn "skipping verify (--no-verify)"
  fi

  if curl -fsS -o /dev/null --max-time 2 http://127.0.0.1:8000/health 2>/dev/null; then
    warn "API is already listening on :8000. Restart it so the new settings load."
  fi

  print_next
  ok "internal ingest setup finished"
}

main "$@"
