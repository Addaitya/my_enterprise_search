#!/usr/bin/env bash
# Copy .env samples once; validate required keys. Never overwrite without --force-env.

# Keys required in root .env (from backend/.env.sample).
_ROOT_ENV_KEYS=(
  POSTGRES_ADMIN_USER
  POSTGRES_ADMIN_PASSWORD
  KEYCLOAK_DB
  KEYCLOAK_USER
  KEYCLOAK_PASSWORD
  APP_DB
  APP_USER
  APP_PASSWORD
  KEYCLOAK_API_SECRET
  KEYCLOAK_ADMIN
  KEYCLOAK_ADMIN_PASSWORD
  OPENSEARCH_INITIAL_ADMIN_PASSWORD
  MINIO_ROOT_USER
  MINIO_ROOT_PASSWORD
)

_FRONTEND_ENV_KEYS=(
  VITE_API_BASE_URL
  VITE_KEYCLOAK_URL
  VITE_KEYCLOAK_REALM
  VITE_KEYCLOAK_CLIENT_ID
)

_env_has_key() {
  local file="$1"
  local key="$2"
  grep -E "^[[:space:]]*${key}=" "${file}" >/dev/null 2>&1
}

_validate_env_file() {
  local file="$1"
  shift
  local missing=()
  local key
  for key in "$@"; do
    if ! _env_has_key "${file}" "${key}"; then
      missing+=("${key}")
    fi
  done
  if (( ${#missing[@]} > 0 )); then
    error "${file} missing keys: ${missing[*]}"
    return 1
  fi
  return 0
}

_copy_env() {
  local src="$1"
  local dest="$2"
  local force="${3:-0}"

  if [[ ! -f "${src}" ]]; then
    die "env sample missing: ${src}" "${EXIT_ENV}"
  fi

  if [[ -f "${dest}" ]] && [[ "${force}" != "1" ]]; then
    log_verbose "keeping existing ${dest}"
    return 0
  fi

  if [[ -f "${dest}" ]] && [[ "${force}" == "1" ]]; then
    warn "overwriting ${dest} from ${src} (--force-env)"
  else
    info "creating ${dest} from ${src}"
  fi
  cp "${src}" "${dest}"
}

prepare_env() {
  local force="${1:-0}"
  local root_env="${REPO_ROOT}/.env"
  local fe_env="${REPO_ROOT}/frontend/.env"
  local root_sample="${REPO_ROOT}/backend/.env.sample"
  local fe_sample="${REPO_ROOT}/frontend/.env.sample"

  if [[ ! -f "${fe_sample}" ]] && [[ -f "${REPO_ROOT}/frontend/.env.example" ]]; then
    fe_sample="${REPO_ROOT}/frontend/.env.example"
  fi

  _copy_env "${root_sample}" "${root_env}" "${force}"
  _copy_env "${fe_sample}" "${fe_env}" "${force}"

  local bad=0
  _validate_env_file "${root_env}" "${_ROOT_ENV_KEYS[@]}" || bad=1
  _validate_env_file "${fe_env}" "${_FRONTEND_ENV_KEYS[@]}" || bad=1
  if (( bad != 0 )); then
    die "Env validation failed (fix keys or use --force-env from samples)" "${EXIT_ENV}"
  fi

  ok "env files"
}
