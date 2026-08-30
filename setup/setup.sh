#!/usr/bin/env bash
# A–Z local bootstrap for Enterprise Search.
# Usage: ./setup/setup.sh [options]
set -euo pipefail

SETUP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SETUP_DIR}/lib/common.sh"
# shellcheck source=lib/check_prereqs.sh
source "${SETUP_DIR}/lib/check_prereqs.sh"
# shellcheck source=lib/env.sh
source "${SETUP_DIR}/lib/env.sh"
# shellcheck source=lib/compose.sh
source "${SETUP_DIR}/lib/compose.sh"
# shellcheck source=lib/backend.sh
source "${SETUP_DIR}/lib/backend.sh"
# shellcheck source=lib/init_services.sh
source "${SETUP_DIR}/lib/init_services.sh"
# shellcheck source=lib/frontend.sh
source "${SETUP_DIR}/lib/frontend.sh"
# shellcheck source=lib/seed.sh
source "${SETUP_DIR}/lib/seed.sh"

FLAG_CHECK_ONLY=0
FLAG_FORCE_ENV=0
FLAG_SKIP_COMPOSE=0
FLAG_SKIP_INIT=0
FLAG_SKIP_FRONTEND=0
FLAG_WITH_SEED=0
FLAG_VERIFY_PROOFS=0
FLAG_START=0
FLAG_NO_VERIFY=0
FLAG_SKIP_OS_ML=0

usage() {
  cat <<'EOF'
Usage: ./setup/setup.sh [options]

One-command local bootstrap: prereqs → env → compose → migrate → init_services
→ frontend deps → optional seed/start.

Options:
  --help              Show this help
  --check-only        Prereqs + env presence only; no compose/migrate
  --force-env         Overwrite .env files from samples (destructive to local secrets)
  --skip-compose      Assume stack already up; still wait_ready + migrate + init
  --skip-init         Skip python -m init_services (migrate + deps only)
  --skip-frontend     Skip bun install
  --with-seed         Run seed_file_acl_for_proofs after init
  --verify-proofs     After seed, run search_view_proof
  --start             Start ./start-dev.sh after success (foreground)
  --no-verify         Skip verify_stack.py (not recommended)
  --skip-opensearch-ml  Do not fail verify if opensearch_model_id is missing
  -v, --verbose       Extra logs

Environment:
  SETUP_WAIT_TIMEOUT_S     Cap all wait timeouts (seconds)
  SETUP_WAIT_POSTGRES_S    Postgres wait (default 60)
  SETUP_WAIT_KEYCLOAK_S    Keycloak wait (default 180)
  SETUP_WAIT_OPENSEARCH_S  OpenSearch wait (default 180)
  SETUP_WAIT_MINIO_S       MinIO wait (default 60)
  SETUP_SKIP_OPENSEARCH_ML=1  Same as --skip-opensearch-ml

Exit codes: 0 ok · 1 fail · 2 prereq · 3 env · 4 compose/wait · 5 migrate/init
EOF
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --help|-h) usage; exit 0 ;;
      --check-only) FLAG_CHECK_ONLY=1 ;;
      --force-env) FLAG_FORCE_ENV=1 ;;
      --skip-compose) FLAG_SKIP_COMPOSE=1 ;;
      --skip-init) FLAG_SKIP_INIT=1 ;;
      --skip-frontend) FLAG_SKIP_FRONTEND=1 ;;
      --with-seed) FLAG_WITH_SEED=1 ;;
      --verify-proofs) FLAG_VERIFY_PROOFS=1 ;;
      --start) FLAG_START=1 ;;
      --no-verify) FLAG_NO_VERIFY=1 ;;
      --skip-opensearch-ml) FLAG_SKIP_OS_ML=1 ;;
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

main() {
  parse_args "$@"
  require_repo_root
  cd "${REPO_ROOT}"

  info "Enterprise Search setup (repo: ${REPO_ROOT})"

  check_prereqs
  prepare_env "${FLAG_FORCE_ENV}"

  if (( FLAG_CHECK_ONLY == 1 )); then
    ok "check-only complete"
    exit "${EXIT_OK}"
  fi

  if (( FLAG_SKIP_COMPOSE == 0 )); then
    compose_up
  else
    info "skipping compose up (--skip-compose)"
  fi

  # Sync before wait_ready so Python probes run under the backend uv env.
  backend_uv_sync
  wait_stack_ready
  backend_migrate

  if (( FLAG_SKIP_INIT == 0 )); then
    run_init_services
  else
    info "skipping init_services (--skip-init)"
  fi

  if (( FLAG_NO_VERIFY == 0 )); then
    info "verifying stack..."
    local verify_args=()
    if (( FLAG_SKIP_OS_ML == 1 )); then
      verify_args+=(--skip-opensearch-ml)
    fi
    if ! run_setup_python verify_stack.py "${verify_args[@]+"${verify_args[@]}"}"; then
      die "verify_stack failed" "${EXIT_FAIL}"
    fi
    ok "verify"
  else
    warn "skipping verify_stack (--no-verify)"
  fi

  if (( FLAG_SKIP_FRONTEND == 0 )); then
    frontend_install
  else
    info "skipping frontend (--skip-frontend)"
  fi

  local seeded=0
  if (( FLAG_WITH_SEED == 1 )); then
    run_seed
    seeded=1
  fi

  if (( FLAG_VERIFY_PROOFS == 1 )); then
    if (( FLAG_WITH_SEED == 0 )); then
      warn "--verify-proofs without --with-seed; proofs may fail without ACL grants"
    fi
    run_verify_proofs
  fi

  local summary_args=()
  if (( seeded == 1 )); then
    summary_args+=(--seeded)
  fi
  run_setup_python print_summary.py "${summary_args[@]+"${summary_args[@]}"}" || true

  if (( FLAG_START == 1 )); then
    info "starting ./start-dev.sh (Ctrl+C to stop)..."
    # Re-print summary note that servers are starting
    run_setup_python print_summary.py --started "${summary_args[@]+"${summary_args[@]}"}" || true
    exec "${REPO_ROOT}/start-dev.sh"
  fi

  ok "setup finished"
}

main "$@"
