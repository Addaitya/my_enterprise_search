#!/usr/bin/env python3
"""Confirm the internal ingest schema and the ingest-client token.

Checks Alembic head ``d4e5f6a7b8c9``, the partial unique source index,
``ingest_jobs`` with no foreign key, the widened ingestion-type check,
and that ``connectors`` has no config or password column. Then requests a
client-credentials token and requires ``aud=api-client`` plus realm role
``ingest-service``, without ``admin`` or ``search-user``.

The realm-admin password grant is the local demo user (``adminpass``).
That token must not carry ``ingest-service``.
"""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import httpx
from sqlalchemy import create_engine, text

from app.core.config import get_settings

HEAD_REVISION = "d4e5f6a7b8c9"
DEMO_ADMIN_USER = "realm-admin"
DEMO_ADMIN_PASSWORD = "adminpass"


def _claims(access_token: str) -> dict:
    part = access_token.split(".")[1]
    part += "=" * ((4 - len(part) % 4) % 4)
    return json.loads(base64.urlsafe_b64decode(part))


def _token(settings, data: dict) -> dict:
    url = (
        f"{settings.keycloak_url}/realms/{settings.keycloak_realm}"
        "/protocol/openid-connect/token"
    )
    response = httpx.post(url, data=data, timeout=20.0)
    if response.status_code != 200:
        raise SystemExit(
            f"token request failed ({response.status_code}): {response.text[:300]}"
        )
    body = response.json()
    if not body.get("access_token"):
        raise SystemExit("token response had no access_token")
    return _claims(body["access_token"])


def _check_schema(settings) -> None:
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    try:
        with engine.connect() as conn:
            revision = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            if revision != HEAD_REVISION:
                raise SystemExit(f"alembic_version is {revision!r}, expected {HEAD_REVISION}")

            indexdef = conn.execute(
                text("SELECT indexdef FROM pg_indexes WHERE indexname = 'uq_files_ingestion_source'")
            ).scalar()
            if not indexdef:
                raise SystemExit("partial unique index uq_files_ingestion_source is missing")
            folded = indexdef.upper()
            if "UNIQUE" not in folded or "ORIGINAL_SOURCE IS NOT NULL" not in folded:
                raise SystemExit(f"uq_files_ingestion_source is not the partial unique index: {indexdef}")

            fk = conn.execute(
                text(
                    "SELECT 1 FROM pg_constraint "
                    "WHERE conrelid = 'ingest_jobs'::regclass AND contype = 'f'"
                )
            ).first()
            if fk is not None:
                raise SystemExit("ingest_jobs must not have a foreign key")

            check_def = conn.execute(
                text(
                    "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE conname = 'ck_files_ingestion_type'"
                )
            ).scalar()
            if not check_def or "pipeline" not in check_def or "local" not in check_def:
                raise SystemExit(f"files ingestion_type check was not widened: {check_def}")

            missing = conn.execute(
                text(
                    """
                    SELECT name FROM (VALUES
                      ('ingest_jobs'),
                      ('connectors'),
                      ('connector_syncs')
                    ) AS required(name)
                    WHERE to_regclass('public.' || name) IS NULL
                    """
                )
            ).scalars().all()
            if missing:
                raise SystemExit(f"ingest tables missing: {', '.join(missing)}")

            secret_cols = conn.execute(
                text(
                    """
                    SELECT column_name FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'connectors'
                      AND column_name IN ('config', 'password')
                    """
                )
            ).scalars().all()
            if secret_cols:
                raise SystemExit(f"connectors must not store secrets: {', '.join(secret_cols)}")
    finally:
        engine.dispose()
    print(f"[ok] schema at {HEAD_REVISION}")


def _check_tokens(settings) -> None:
    if not settings.keycloak_ingest_secret:
        raise SystemExit("KEYCLOAK_INGEST_SECRET is empty")

    ingest = _token(
        settings,
        {
            "grant_type": "client_credentials",
            "client_id": settings.keycloak_ingest_client_id,
            "client_secret": settings.keycloak_ingest_secret,
        },
    )
    aud = ingest.get("aud")
    aud_list = aud if isinstance(aud, list) else [aud]
    roles = ingest.get("roles") or []
    if "api-client" not in aud_list:
        raise SystemExit(f"ingest token aud missing api-client: {aud_list}")
    if "ingest-service" not in roles:
        raise SystemExit(f"ingest token missing ingest-service: {roles}")
    if "admin" in roles or "search-user" in roles:
        raise SystemExit(f"ingest token must not carry product roles: {roles}")
    print("[ok] ingest-client token aud=api-client role=ingest-service")

    admin = _token(
        settings,
        {
            "grant_type": "password",
            "client_id": settings.keycloak_client_id,
            "client_secret": settings.keycloak_api_secret,
            "username": DEMO_ADMIN_USER,
            "password": DEMO_ADMIN_PASSWORD,
        },
    )
    admin_roles = admin.get("roles") or []
    if "ingest-service" in admin_roles:
        raise SystemExit(f"{DEMO_ADMIN_USER} must not have ingest-service: {admin_roles}")
    if "admin" not in admin_roles:
        raise SystemExit(f"{DEMO_ADMIN_USER} token missing admin: {admin_roles}")
    print(f"[ok] {DEMO_ADMIN_USER} has no ingest-service role")


def main() -> int:
    settings = get_settings()
    _check_schema(settings)
    _check_tokens(settings)
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
