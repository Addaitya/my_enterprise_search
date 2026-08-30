#!/usr/bin/env bash
# Start Compose stack and wait until core services accept connections.

_compose_cmd() {
  if docker compose version >/dev/null 2>&1; then
    echo "docker compose"
  else
    echo "docker-compose"
  fi
}

compose_up() {
  local cmd
  cmd="$(_compose_cmd)"
  info "starting docker compose stack..."
  (
    cd "${REPO_ROOT}"
    # shellcheck disable=SC2086
    ${cmd} up -d
  ) || die "docker compose up failed" "${EXIT_COMPOSE}"
  ok "compose up"
}

wait_stack_ready() {
  info "waiting for Postgres / Keycloak / OpenSearch / MinIO..."
  if ! run_setup_python wait_ready.py; then
    die "stack wait timed out — see which service failed above" "${EXIT_COMPOSE}"
  fi
  ok "stack ready"
}
