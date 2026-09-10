"""Admin dashboard stats proofs. Not part of init_services.

Needs live API on :8000 (reload after this slice) and a working POST /search.

Run (backend venv, stack up)::

    cd backend
    uv run python -m scripts.admin_stats_proof
"""

from __future__ import annotations

import sys
import time

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_engine
from init_services.keycloak import (
    REALM_ADMIN_PASSWORD,
    REALM_ADMIN_USERNAME,
    SEARCHER_PASSWORD,
    SEARCHER_USERNAME,
)

API = "http://localhost:8000"


class ProofFailure(RuntimeError):
    pass


def _token(username: str, password: str) -> str:
    settings = get_settings()
    response = httpx.post(
        f"{settings.keycloak_url}/realms/{settings.keycloak_realm}/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": settings.keycloak_client_id,
            "client_secret": settings.keycloak_api_secret,
            "username": username,
            "password": password,
        },
        timeout=15,
    )
    if response.is_error:
        raise ProofFailure(f"token {username}: {response.status_code} {response.text}")
    return response.json()["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": "Bearer " + token}


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise ProofFailure(msg)


QA_STATS_USERNAME = "qa-stats-user"
QA_STATS_PASSWORD = "qa-stats-pass"


def _get_stats(headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.get(f"{API}/admin/stats", headers=headers or {}, timeout=30)


def _non_admin_token(admin_headers: dict[str, str]) -> tuple[str, str]:
    """Return (token, label) for a product user without realm role admin.

    Seed ``searcher`` is preferred. If this environment granted them ``admin``
    (e.g. 12b experiments), mint ``qa-stats-user`` with only ``search-user``.
    """
    searcher = _token(SEARCHER_USERNAME, SEARCHER_PASSWORD)
    ping = httpx.get(f"{API}/auth/admin-ping", headers=_auth(searcher), timeout=15)
    if ping.status_code == 403:
        return searcher, SEARCHER_USERNAME
    created = httpx.post(
        f"{API}/admin/users",
        headers=admin_headers,
        json={
            "username": QA_STATS_USERNAME,
            "password": QA_STATS_PASSWORD,
            "email": "qa-stats@example.com",
            "enabled": True,
            "role_names": ["search-user"],
        },
        timeout=30,
    )
    if created.status_code not in (201, 409):
        raise ProofFailure(
            f"could not ensure {QA_STATS_USERNAME}: {created.status_code} {created.text}"
        )
    token = _token(QA_STATS_USERNAME, QA_STATS_PASSWORD)
    ping = httpx.get(f"{API}/auth/admin-ping", headers=_auth(token), timeout=15)
    _assert(ping.status_code == 403, f"{QA_STATS_USERNAME} should not be admin: {ping.status_code}")
    return token, QA_STATS_USERNAME


def main() -> int:
    # 1: unauthenticated → 401
    r = _get_stats()
    _assert(r.status_code == 401, f"proof1 expected 401 got {r.status_code} {r.text}")
    print("[ok] 1: unauth GET /admin/stats → 401")

    admin = _token(REALM_ADMIN_USERNAME, REALM_ADMIN_PASSWORD)
    admin_h = _auth(admin)
    non_admin, non_admin_name = _non_admin_token(admin_h)

    # 2: non-admin product user → 403
    r = _get_stats(_auth(non_admin))
    _assert(r.status_code == 403, f"proof2 expected 403 got {r.status_code} {r.text}")
    print(f"[ok] 2: {non_admin_name} GET /admin/stats → 403")

    # 3: admin → 200 with live ints + placeholder constants
    r = _get_stats(admin_h)
    _assert(r.status_code == 200, f"proof3 expected 200 got {r.status_code} {r.text}")
    body = r.json()
    _assert(isinstance(body.get("total_docs_indexed"), int), f"proof3 docs {body}")
    _assert(isinstance(body.get("total_data_ingested_bytes"), int), f"proof3 bytes {body}")
    _assert(body["total_data_ingested_bytes"] >= 0, f"proof3 bytes negative {body}")
    _assert(body.get("active_connectors") == 8, f"proof3 connectors {body}")
    _assert(body.get("ingestion_rate_docs_per_hour") == 12400, f"proof3 rate {body}")
    _assert(body.get("last_sync") == "2 min ago", f"proof3 last_sync {body}")
    placeholders = body.get("placeholders") or {}
    _assert(placeholders.get("active_connectors") is True, f"proof3 ph connectors {body}")
    _assert(placeholders.get("ingestion_rate_docs_per_hour") is True, f"proof3 ph rate {body}")
    _assert(placeholders.get("last_sync") is True, f"proof3 ph last_sync {body}")
    _assert("avg_query_time_ms" in body, f"proof3 missing avg {body}")
    print(
        f"[ok] 3: admin GET /admin/stats → 200 "
        f"docs={body['total_docs_indexed']} bytes={body['total_data_ingested_bytes']} "
        f"avg={body['avg_query_time_ms']}"
    )

    # 4: successful POST /search then avg is non-null
    search = httpx.post(
        f"{API}/search",
        headers=admin_h,
        json={"q": "test", "size": 5},
        timeout=60,
    )
    _assert(search.status_code == 200, f"proof4 search {search.status_code} {search.text}")
    took_ms = search.json().get("took_ms")
    _assert(isinstance(took_ms, int), f"proof4 took_ms {search.json()}")

    deadline = time.monotonic() + 5.0
    avg = None
    while time.monotonic() < deadline:
        with Session(bind=get_engine()) as db:
            n = db.execute(text("SELECT COUNT(*) FROM search_query_metrics")).scalar()
        if n and int(n) > 0:
            break
        time.sleep(0.1)
    else:
        raise ProofFailure("proof4 metrics row not inserted after successful search")

    r = _get_stats(admin_h)
    _assert(r.status_code == 200, f"proof4 stats {r.status_code} {r.text}")
    avg = r.json().get("avg_query_time_ms")
    _assert(avg is not None, f"proof4 avg still null {r.json()}")
    _assert(isinstance(avg, (int, float)), f"proof4 avg type {avg!r}")
    print(f"[ok] 4: POST /search took_ms={took_ms} then avg_query_time_ms={avg}")

    print("=== all admin stats proofs passed ===")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ProofFailure as exc:
        print(f"[fail] {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
