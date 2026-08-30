#!/usr/bin/env bash
# Shared helpers for setup/. Sourced by setup.sh and lib modules.

if [[ -n "${_SETUP_COMMON_LOADED:-}" ]]; then
  return 0
fi
_SETUP_COMMON_LOADED=1

SETUP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="$(cd "${SETUP_DIR}/.." && pwd)"

# Exit codes (CLI contract)
readonly EXIT_OK=0
readonly EXIT_FAIL=1
readonly EXIT_PREREQ=2
readonly EXIT_ENV=3
readonly EXIT_COMPOSE=4
readonly EXIT_MIGRATE_INIT=5

SETUP_VERBOSE="${SETUP_VERBOSE:-0}"

_color() {
  local code="$1"
  shift
  if [[ -t 1 ]]; then
    printf '\033[%sm%s\033[0m\n' "${code}" "$*"
  else
    printf '%s\n' "$*"
  fi
}

info()  { _color "1;34" "[info] $*"; }
warn()  { _color "1;33" "[warn] $*"; }
error() { _color "1;31" "[error] $*" >&2; }
ok()    { _color "1;32" "[ok] $*"; }

die() {
  local code="${2:-${EXIT_FAIL}}"
  error "${1}"
  exit "${code}"
}

log_verbose() {
  if [[ "${SETUP_VERBOSE}" == "1" ]]; then
    info "$*"
  fi
}

require_repo_root() {
  [[ -f "${REPO_ROOT}/docker-compose.yml" ]] \
    || die "docker-compose.yml not found at ${REPO_ROOT}" "${EXIT_FAIL}"
  [[ -d "${REPO_ROOT}/backend" ]] \
    || die "backend/ not found at ${REPO_ROOT}" "${EXIT_FAIL}"
}

# Run a Python helper under the backend uv environment (has httpx, sqlalchemy, etc.).
run_setup_python() {
  local script="$1"
  shift
  (
    cd "${REPO_ROOT}/backend"
    uv run python "${SETUP_DIR}/python/${script}" "$@"
  )
}
