#!/usr/bin/env python3
"""Post-bootstrap smoke checks (infra). Run after init_services.

Fails if OpenSearch model id is missing unless SETUP_SKIP_OPENSEARCH_ML=1
or --skip-opensearch-ml is passed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import httpx
from minio import Minio
from sqlalchemy import create_engine, inspect, text

from app.core.config import RUNTIME_CONFIG_PATH, get_settings, load_runtime_config


def _fail(msg: str) -> None:
    print(f"[fail] {msg}", file=sys.stderr)
    raise SystemExit(1)


def _ok(msg: str) -> None:
    print(f"[ok] {msg}")


def check_postgres(settings) -> None:
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            ver = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        insp = inspect(engine)
        tables = set(insp.get_table_names())
    finally:
        engine.dispose()

    if "users" not in tables:
        _fail("identity tables missing (users) — alembic upgrade head likely failed")
    _ok(f"postgres identity tables present (alembic={ver})")


def check_keycloak(settings) -> None:
    url = f"{settings.keycloak_url}/realms/{settings.keycloak_realm}"
    r = httpx.get(url, timeout=10.0)
    if r.status_code >= 500:
        _fail(f"keycloak realm unreachable: {url} status={r.status_code}")
    _ok(f"keycloak realm {settings.keycloak_realm}")


def check_opensearch(settings, *, require_model: bool) -> None:
    auth = ("admin", settings.opensearch_initial_admin_password)
    health = httpx.get(
        f"{settings.opensearch_url}/_cluster/health",
        timeout=10.0,
        verify=settings.opensearch_verify_certs,
        auth=auth,
    )
    if health.status_code >= 500:
        _fail(f"opensearch health status={health.status_code}")
    body = health.json()
    status = body.get("status", "unknown")
    if status == "red":
        _fail(f"opensearch cluster status is red: {body}")
    _ok(f"opensearch cluster status={status}")

    idx = settings.opensearch_index
    head = httpx.head(
        f"{settings.opensearch_url}/{idx}",
        timeout=10.0,
        verify=settings.opensearch_verify_certs,
        auth=auth,
    )
    if head.status_code == 404:
        _fail(f"opensearch index {idx!r} missing — re-run init_services")
    if head.status_code >= 400:
        _fail(f"opensearch index check failed status={head.status_code}")
    _ok(f"opensearch index {idx}")

    runtime = load_runtime_config()
    model_id = runtime.get("opensearch_model_id") or settings.opensearch_model_id
    if not model_id:
        if require_model:
            _fail(
                f"opensearch_model_id missing in {RUNTIME_CONFIG_PATH} — init_services ML "
                "bootstrap incomplete (first boot can take several minutes / needs RAM). "
                "Re-run init_services, or pass --skip-opensearch-ml / SETUP_SKIP_OPENSEARCH_ML=1."
            )
        print("[warn] opensearch_model_id missing (skipped by flag)")
    else:
        mid = str(model_id)
        shown = f"{mid[:12]}…" if len(mid) > 12 else mid
        _ok(f"opensearch_model_id set ({shown})")


def check_minio(settings) -> None:
    client = Minio(
        settings.minio_endpoint,
        access_key=settings.minio_root_user,
        secret_key=settings.minio_root_password,
        secure=settings.minio_secure,
    )
    if not client.bucket_exists(settings.minio_bucket):
        _fail(f"minio bucket {settings.minio_bucket!r} missing — re-run init_services")
    _ok(f"minio bucket {settings.minio_bucket}")


def check_api_optional() -> None:
    try:
        r = httpx.get("http://localhost:8000/health", timeout=2.0)
    except httpx.HTTPError:
        print("[info] API not running yet (expected until ./start-dev.sh)")
        return
    if r.status_code == 200:
        _ok("GET /health")
    else:
        print(f"[warn] GET /health status={r.status_code}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify local stack after init_services")
    parser.add_argument(
        "--skip-opensearch-ml",
        action="store_true",
        help="Do not fail if opensearch_model_id is missing",
    )
    args = parser.parse_args()
    skip_ml = args.skip_opensearch_ml or os.environ.get("SETUP_SKIP_OPENSEARCH_ML") == "1"

    settings = get_settings()
    if not settings.app_password:
        _fail("Settings.app_password empty — root .env not loaded or invalid")

    check_postgres(settings)
    check_keycloak(settings)
    check_opensearch(settings, require_model=not skip_ml)
    check_minio(settings)
    check_api_optional()
    print(json.dumps({"verify": "ok"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
