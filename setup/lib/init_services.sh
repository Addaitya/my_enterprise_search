#!/usr/bin/env bash
# Invoke existing init_services bootstrap (do not reimplement).

run_init_services() {
  info "running python -m init_services..."
  (
    cd "${REPO_ROOT}/backend"
    uv run python -m init_services
  ) || die "init_services failed — see backend/README.md (init_services section)" "${EXIT_MIGRATE_INIT}"
  ok "init_services"
}
