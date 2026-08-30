#!/usr/bin/env bash
# Backend deps + Alembic migrations.

backend_uv_sync() {
  info "uv sync (backend)..."
  (
    cd "${REPO_ROOT}/backend"
    uv sync
  ) || die "uv sync failed" "${EXIT_MIGRATE_INIT}"
  ok "backend deps"
}

backend_migrate() {
  info "alembic upgrade head..."
  (
    cd "${REPO_ROOT}/backend"
    uv run alembic upgrade head
  ) || die "alembic upgrade head failed (identity tables will be missing)" "${EXIT_MIGRATE_INIT}"
  ok "migrations"
}