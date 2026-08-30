#!/usr/bin/env python3
"""Poll Postgres, Keycloak, OpenSearch, and MinIO until ready (or timeout).

Timeouts (override via SETUP_WAIT_TIMEOUT_S for a global cap, or per-service
SETUP_WAIT_POSTGRES_S / SETUP_WAIT_KEYCLOAK_S / SETUP_WAIT_OPENSEARCH_S /
SETUP_WAIT_MINIO_S):

  Postgres / MinIO: 60s
  Keycloak / OpenSearch: 180s
"""

from __future__ import annotations

import os
import sys
import time
from collections.abc import Callable
from pathlib import Path

# Ensure backend package imports work when invoked via `uv run` from backend/.
BACKEND_DIR = Path(__file__).resolve().parents[2] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import httpx
from sqlalchemy import create_engine, text

from app.core.config import get_settings


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return float(raw)


def _timeout(service: str, default: float) -> float:
    global_cap = os.environ.get("SETUP_WAIT_TIMEOUT_S")
    per = _env_float(f"SETUP_WAIT_{service.upper()}_S", default)
    if global_cap is not None and global_cap.strip() != "":
        return min(per, float(global_cap))
    return per


def wait_for(name: str, check: Callable[[], bool], timeout_s: float, interval_s: float = 2.0) -> None:
    deadline = time.monotonic() + timeout_s
    last: BaseException | None = None
    while time.monotonic() < deadline:
        try:
            if check():
                print(f"[ok] {name} ready")
                return
            last = None
        except BaseException as exc:  # noqa: BLE001
            last = exc
        time.sleep(interval_s)
    detail = f" ({last})" if last is not None else ""
    print(f"[fail] {name} not ready within {timeout_s:.0f}s{detail}", file=sys.stderr)
    raise SystemExit(4)


def main() -> int:
    settings = get_settings()

    def postgres() -> bool:
        engine = create_engine(settings.database_url, pool_pre_ping=True)
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        finally:
            engine.dispose()
        return True

    def keycloak() -> bool:
        url = f"{settings.keycloak_url}/realms/{settings.keycloak_realm}"
        r = httpx.get(url, timeout=5.0)
        return r.status_code < 500

    def opensearch() -> bool:
        r = httpx.get(
            f"{settings.opensearch_url}/_cluster/health",
            timeout=5.0,
            verify=settings.opensearch_verify_certs,
            auth=("admin", settings.opensearch_initial_admin_password),
        )
        return r.status_code < 500

    def minio() -> bool:
        r = httpx.get(f"http://{settings.minio_endpoint}/minio/health/live", timeout=5.0)
        return r.status_code < 500

    wait_for("postgres", postgres, _timeout("postgres", 60))
    wait_for("keycloak", keycloak, _timeout("keycloak", 180))
    wait_for("opensearch", opensearch, _timeout("opensearch", 180))
    wait_for("minio", minio, _timeout("minio", 60))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
