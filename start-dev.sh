#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

BACKEND_PID=""
FRONTEND_PID=""

cleanup() {
  trap - EXIT INT TERM
  echo "Stopping frontend and backend..."
  if [[ -n "${FRONTEND_PID}" ]]; then
    kill "${FRONTEND_PID}" 2>/dev/null || true
  fi
  if [[ -n "${BACKEND_PID}" ]]; then
    kill "${BACKEND_PID}" 2>/dev/null || true
  fi
  wait "${FRONTEND_PID}" "${BACKEND_PID}" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

prefix() {
  local name="$1"
  sed -u "s/^/[${name}] /"
}

echo "Starting backend (http://localhost:8000)..."
(
  cd "${ROOT}/backend"
  exec uv run python -c "from app.main import run; run()"
) > >(prefix backend) 2>&1 &
BACKEND_PID=$!

echo "Starting frontend (http://localhost:5173)..."
(
  cd "${ROOT}/frontend"
  exec bun run dev
) > >(prefix frontend) 2>&1 &
FRONTEND_PID=$!

echo "Ctrl+C to stop both."
wait "${BACKEND_PID}" "${FRONTEND_PID}"
