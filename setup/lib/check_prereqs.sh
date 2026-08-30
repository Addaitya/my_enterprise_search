#!/usr/bin/env bash
# Prerequisite checks: docker, compose, python ≥3.12, uv, bun, mmap, RAM hint.

check_prereqs() {
  local missing=0
  local hints=()

  _need_cmd() {
    local name="$1"
    local hint="$2"
    if ! command -v "${name}" >/dev/null 2>&1; then
      error "missing required command: ${name}"
      hints+=("${hint}")
      missing=1
      return 1
    fi
    log_verbose "found ${name}: $(command -v "${name}")"
    return 0
  }

  _need_cmd docker "Install Docker: https://docs.docker.com/get-docker/" \
    || true

  if command -v docker >/dev/null 2>&1; then
    if docker compose version >/dev/null 2>&1; then
      log_verbose "docker compose: $(docker compose version --short 2>/dev/null || echo ok)"
    elif command -v docker-compose >/dev/null 2>&1; then
      log_verbose "docker-compose: $(command -v docker-compose)"
    else
      error "missing Docker Compose (need 'docker compose' or 'docker-compose')"
      hints+=("Install Compose: https://docs.docker.com/compose/install/")
      missing=1
    fi
    if ! docker info >/dev/null 2>&1; then
      error "Docker daemon is not reachable (is Docker running?)"
      hints+=("Start Docker Desktop / dockerd, then re-run.")
      missing=1
    fi
  fi

  if ! command -v python3 >/dev/null 2>&1; then
    error "missing required command: python3"
    hints+=("Install Python 3.12+: https://www.python.org/downloads/")
    missing=1
  else
    local py_ver
    py_ver="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
    local major minor
    IFS=. read -r major minor <<<"${py_ver}"
    if (( major < 3 || (major == 3 && minor < 12) )); then
      error "Python ${py_ver} found; need 3.12+"
      hints+=("Install Python 3.12+ and ensure python3 points at it.")
      missing=1
    else
      log_verbose "python3 ${py_ver}"
    fi
  fi

  _need_cmd uv "Install uv: https://docs.astral.sh/uv/getting-started/installation/" || true
  _need_cmd bun "Install bun: https://bun.sh" || true

  # C1: print-only for mmap; fail if too low (G5).
  if [[ "$(uname -s)" == "Linux" ]] && [[ -r /proc/sys/vm/max_map_count ]]; then
    local mmap
    mmap="$(cat /proc/sys/vm/max_map_count)"
    if (( mmap < 262144 )); then
      error "vm.max_map_count=${mmap} is below 262144 (OpenSearch will fail to start)"
      error "Fix with: sudo sysctl -w vm.max_map_count=262144"
      error "Persist via /etc/sysctl.d/ or Docker Desktop WSL settings, then re-run."
      missing=1
    else
      log_verbose "vm.max_map_count=${mmap}"
    fi
  fi

  # RAM hint only (warn).
  if command -v free >/dev/null 2>&1; then
    local avail_mb
    avail_mb="$(free -m | awk '/^Mem:/{print $7}')"
    if [[ -n "${avail_mb}" ]] && (( avail_mb < 4096 )); then
      warn "Available memory ~${avail_mb} MiB; OpenSearch (2g heap + model download) prefers ≥4 GiB free."
    fi
  fi

  if (( missing != 0 )); then
    for h in "${hints[@]}"; do
      error "  → ${h}"
    done
    die "Prerequisites failed" "${EXIT_PREREQ}"
  fi

  ok "prerequisites"
}
