"""Machine search client proof.

Stack: API on http://localhost:8000, Keycloak, and ``init_services`` already
run so ``external-api-client`` exists. ``KEYCLOAK_EXTERNAL_SECRET`` must
match that client's secret.

Requests a client-credentials token, checks ``aud``, ``roles``, and
``groups``, then calls FastAPI. Search is not sent to OpenSearch directly.

Run::

    cd backend && uv run python -m scripts.external_api_client_proof
"""

from __future__ import annotations

import base64
import json
from typing import Any

import httpx

from app.core.config import get_settings

API = "http://localhost:8000"
PROOF_CHUNK_ID = "proof-role-search-user"
SEARCH_BODY = {"q": "alpha-proof-token", "size": 10}


class ProofFailure(RuntimeError):
    pass


def _assert(condition: bool, detail: object) -> None:
    if not condition:
        raise ProofFailure(str(detail))


def _claims(access_token: str) -> dict[str, Any]:
    part = access_token.split(".")[1]
    part += "=" * ((4 - len(part) % 4) % 4)
    return json.loads(base64.urlsafe_b64decode(part))


def _token_url(settings) -> str:
    return (
        f"{settings.keycloak_url}/realms/{settings.keycloak_realm}"
        "/protocol/openid-connect/token"
    )


def _client_credentials(settings, secret: str) -> httpx.Response:
    return httpx.post(
        _token_url(settings),
        data={
            "grant_type": "client_credentials",
            "client_id": settings.keycloak_external_client_id,
            "client_secret": secret,
        },
        timeout=20,
    )


def _check_token(settings) -> str:
    if not settings.keycloak_external_secret:
        raise ProofFailure("KEYCLOAK_EXTERNAL_SECRET is empty")
    response = _client_credentials(settings, settings.keycloak_external_secret)
    _assert(response.status_code == 200, f"token {response.status_code} {response.text[:300]}")
    access_token = response.json().get("access_token")
    _assert(bool(access_token), "token response had no access_token")
    claims = _claims(access_token)
    aud = claims.get("aud")
    aud_list = aud if isinstance(aud, list) else [aud]
    roles = claims.get("roles") or []
    groups = claims.get("groups") or []
    _assert(bool(claims.get("sub")), "token missing sub")
    _assert("api-client" in aud_list, f"aud missing api-client: {aud_list}")
    _assert("admin" in roles, f"roles missing admin: {roles}")
    _assert("search-user" in roles, f"roles missing search-user: {roles}")
    _assert("ingest-service" not in roles, f"roles must not include ingest-service: {roles}")
    _assert("_empty" in groups, f"groups missing _empty: {groups}")
    print(
        "[ok] token aud=api-client roles=admin,search-user "
        f"groups={groups} sub=present"
    )
    return access_token


def _check_bad_secret(settings) -> None:
    response = _client_credentials(settings, "wrong-secret")
    _assert(response.status_code == 401, f"bad secret expected 401, got {response.status_code}")
    print("[ok] bad secret → 401")


def _check_admin_ping(token: str) -> None:
    response = httpx.get(
        f"{API}/auth/admin-ping",
        headers={"Authorization": f"Bearer {token}"},
        timeout=20,
    )
    _assert(response.status_code == 200, f"admin-ping {response.status_code} {response.text[:300]}")
    print("[ok] GET /auth/admin-ping → 200")


def _check_search(token: str) -> None:
    response = httpx.post(
        f"{API}/search",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json=SEARCH_BODY,
        timeout=60,
    )
    _assert(
        response.status_code == 200,
        f"search {response.status_code} {response.text[:300]}",
    )
    body = response.json()
    hits = body.get("hits") or []
    chunk_ids = [hit.get("chunk_id") for hit in hits]
    if not hits:
        print("[ok] POST /search → 200 (no ACL-visible hits)")
        return
    _assert(
        PROOF_CHUNK_ID in chunk_ids,
        f"search 200 but {PROOF_CHUNK_ID} not in hits: {chunk_ids}",
    )
    print(f"[ok] POST /search → 200 hit {PROOF_CHUNK_ID} (total={body.get('total')})")


def _check_search_without_bearer() -> None:
    response = httpx.post(
        f"{API}/search",
        headers={"Content-Type": "application/json"},
        json=SEARCH_BODY,
        timeout=20,
    )
    _assert(response.status_code == 401, f"search without bearer expected 401, got {response.status_code}")
    print("[ok] POST /search without Bearer → 401")


def main() -> int:
    settings = get_settings()
    token = _check_token(settings)
    _check_bad_secret(settings)
    _check_admin_ping(token)
    _check_search(token)
    _check_search_without_bearer()
    print("PASS")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ProofFailure as exc:
        print(f"FAIL {exc}")
        raise SystemExit(1) from exc
