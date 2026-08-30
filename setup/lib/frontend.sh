#!/usr/bin/env bash
# Frontend dependency install.

frontend_install() {
  if [[ ! -f "${REPO_ROOT}/frontend/.env" ]]; then
    die "frontend/.env missing — re-run without --skip-frontend after env step" "${EXIT_ENV}"
  fi
  info "bun install (frontend)..."
  (
    cd "${REPO_ROOT}/frontend"
    bun install
  ) || die "bun install failed" "${EXIT_FAIL}"
  ok "frontend deps"
}
