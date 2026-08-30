"""Product Search + View/Open API proofs (Task 5). Not part of init_services.

Ensures proof-* fixtures exist, optionally seeds G3 ACL, then exercises
``POST /search`` DLS hit/miss and ``GET /files`` list/open.

Does **not** change platform ``search_proof`` native-hybrid BLOCKED status.

Run (backend venv, stack up)::

    cd backend
    uv run python -m scripts.seed_file_acl_for_proofs   # once for list/open + S13
    uv run python -m scripts.search_view_proof
"""

from __future__ import annotations

import sys
import uuid
from typing import Any

import httpx
from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import get_engine
from app.services.minio_store import MinioStore
from init_services.keycloak import (
    REALM_ADMIN_PASSWORD,
    REALM_ADMIN_USERNAME,
    SEARCHER_PASSWORD,
    SEARCHER_USERNAME,
)
from init_services.search_proof import PROOF_DOCS

API = "http://localhost:8000"


class ProofFailure(RuntimeError):
    pass


def _ensure_proof_docs() -> None:
    """Idempotent upsert of proof-* (basic admin). Same bodies as search_proof."""
    settings = get_settings()
    with httpx.Client(
        base_url=settings.opensearch_url,
        verify=settings.opensearch_verify_certs,
        auth=("admin", settings.opensearch_initial_admin_password),
        timeout=60.0,
    ) as client:
        for doc in PROOF_DOCS:
            body = {
                "file_id": f"file-{doc['_id']}",
                "chunk_id": doc["_id"],
                "chunk_seq": 0,
                "content": doc["content"],
                "allowed_roles": doc["allowed_roles"],
                "allowed_groups": doc["allowed_groups"],
            }
            response = client.put(
                f"/{settings.opensearch_index}/_doc/{doc['_id']}",
                params={"refresh": "true"},
                json=body,
            )
            if response.is_error:
                raise ProofFailure(f"upsert {doc['_id']}: {response.status_code} {response.text}")
            print(f"[ok] upserted {doc['_id']}")


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
    return {"Authorization": f"Bearer {token}"}


def _search(token: str | None, body: dict[str, Any], *, timeout: float = 90.0) -> httpx.Response:
    headers = {"Content-Type": "application/json"}
    if token:
        headers.update(_auth(token))
    return httpx.post(f"{API}/search", headers=headers, json=body, timeout=timeout)


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise ProofFailure(msg)


def _hit_ids(payload: dict[str, Any]) -> list[str]:
    return [h.get("chunk_id") for h in payload.get("hits", []) if h.get("chunk_id")]


def _granted_search_user_file_id() -> str | None:
    """Latest file with role search-user viewer grant (G3 seed)."""
    with get_engine().connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT f.id::text
                FROM files f
                JOIN file_acl a ON a.file_id = f.id
                JOIN roles r ON r.id = a.role_id
                WHERE r.name = 'search-user'
                  AND a.permission IN ('viewer', 'editor')
                ORDER BY f.uploaded_at DESC
                LIMIT 1
                """
            )
        ).first()
    return str(row[0]) if row else None


# --- View / Open proofs (1–7) ---


def v1_files_no_token() -> None:
    response = httpx.get(f"{API}/files", timeout=10)
    _assert(response.status_code == 401, f"V1 expected 401 got {response.status_code} {response.text}")
    print("[ok] V1 GET /files no token → 401")


def v2_files_empty_or_list(searcher: str) -> None:
    response = httpx.get(f"{API}/files", headers=_auth(searcher), timeout=10)
    _assert(response.status_code == 200, f"V2 expected 200 got {response.status_code} {response.text}")
    body = response.json()
    _assert("items" in body and "total" in body, body)
    print(f"[ok] V2 GET /files as searcher → 200 total={body['total']}")


def v3_list_after_seed(searcher: str, file_a: str) -> None:
    response = httpx.get(f"{API}/files", headers=_auth(searcher), timeout=10)
    _assert(response.status_code == 200, f"V3 {response.status_code} {response.text}")
    body = response.json()
    ids = {item["id"] for item in body["items"]}
    _assert(file_a in ids, f"V3 expected file {file_a} in list: {ids}")
    item = next(i for i in body["items"] if i["id"] == file_a)
    _assert(item.get("display_name"), f"V3 missing display_name: {item}")
    _assert("/" not in item["display_name"], f"V3 display_name should be basename: {item}")
    print(f"[ok] V3 searcher lists file A display_name={item['display_name']}")


def v4_content_bytes(searcher: str, file_a: str) -> None:
    meta = httpx.get(f"{API}/files/{file_a}", headers=_auth(searcher), timeout=10)
    _assert(meta.status_code == 200, f"V4 meta {meta.status_code} {meta.text}")
    path = meta.json()["object_store_path"]
    expected = MinioStore().get_object_bytes(path)

    response = httpx.get(f"{API}/files/{file_a}/content", headers=_auth(searcher), timeout=60)
    _assert(response.status_code == 200, f"V4 content {response.status_code} {response.text[:200]}")
    _assert(response.content == expected, "V4 content bytes mismatch MinIO")
    print(f"[ok] V4 content stream matches MinIO ({len(expected)} bytes)")


def v5_content_forbidden(admin: str, file_a: str) -> None:
    """realm-admin has search-user too — use a user with no matching grant.

    If file_a is granted only to search-user, both searcher and realm-admin have
    search-user. For deny we need a file granted only to engineering (file B),
    opened as searcher (no engineering).
    """
    with get_engine().connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT f.id::text
                FROM files f
                JOIN file_acl a ON a.file_id = f.id
                JOIN groups g ON g.id = a.group_id
                WHERE g.name = 'engineering'
                  AND a.permission IN ('viewer', 'editor')
                  AND NOT EXISTS (
                    SELECT 1 FROM file_acl a2
                    JOIN roles r ON r.id = a2.role_id
                    WHERE a2.file_id = f.id AND r.name = 'search-user'
                  )
                ORDER BY f.uploaded_at DESC
                LIMIT 1
                """
            )
        ).first()
    if row is None:
        print("[skip] V5 no engineering-only file (run seed with ≥2 files)")
        return
    file_b = row[0]
    # searcher has search-user but not engineering → 403
    searcher = _token(SEARCHER_USERNAME, SEARCHER_PASSWORD)
    response = httpx.get(f"{API}/files/{file_b}/content", headers=_auth(searcher), timeout=30)
    _assert(response.status_code == 403, f"V5 expected 403 got {response.status_code} {response.text}")
    # sanity: admin (engineering) can open
    ok = httpx.get(f"{API}/files/{file_b}/content", headers=_auth(admin), timeout=30)
    _assert(ok.status_code == 200, f"V5 admin should open file B: {ok.status_code}")
    print(f"[ok] V5 searcher denied file B ({file_b}); realm-admin allowed")


def v6_missing_file(searcher: str) -> None:
    missing = str(uuid.uuid4())
    response = httpx.get(f"{API}/files/{missing}", headers=_auth(searcher), timeout=10)
    _assert(response.status_code == 404, f"V6 expected 404 got {response.status_code}")
    print("[ok] V6 GET /files/{missing} → 404")


def v7_content_no_token(file_a: str | None) -> None:
    fid = file_a or str(uuid.uuid4())
    response = httpx.get(f"{API}/files/{fid}/content", timeout=10)
    _assert(response.status_code == 401, f"V7 expected 401 got {response.status_code}")
    print("[ok] V7 content no token → 401")


def v8_jwt_cannot_index(searcher: str) -> None:
    settings = get_settings()
    with httpx.Client(
        base_url=settings.opensearch_url,
        verify=settings.opensearch_verify_certs,
        timeout=30.0,
    ) as client:
        response = client.put(
            f"/{settings.opensearch_index}/_doc/proof-should-fail-index",
            headers=_auth(searcher),
            json={"content": "nope", "allowed_roles": [], "allowed_groups": []},
        )
    _assert(response.status_code in (401, 403), f"V8 expected 401/403 got {response.status_code}")
    print(f"[ok] V8 JWT cannot index → {response.status_code}")


# --- Search proofs (9–13 / S1–S6 legacy names) ---


def s1_no_token() -> None:
    response = _search(None, {"q": "alpha-proof-token", "size": 10})
    _assert(response.status_code == 401, f"S1 expected 401 got {response.status_code} {response.text}")
    print("[ok] S1 POST /search no token → 401")


def s2_searcher_role_hit(searcher: str) -> None:
    response = _search(searcher, {"q": "alpha-proof-token", "size": 10})
    _assert(response.status_code == 200, f"S2 expected 200 got {response.status_code} {response.text}")
    body = response.json()
    ids = set(_hit_ids(body))
    _assert("proof-role-search-user" in ids, f"S2 missing role proof hit: {ids} body={body}")
    for hit in body["hits"]:
        _assert("embedding" not in hit, f"S2 embedding leaked: {hit}")
        _assert("snippet" in hit, hit)
    print(f"[ok] S2 searcher alpha → proof-role-search-user (total={body['total']})")


def s3_searcher_misses_group_and_nobody(searcher: str) -> None:
    for q, forbidden in (
        ("bravo-proof-token", "proof-group-engineering"),
        ("charlie-proof-token", "proof-nobody"),
    ):
        response = _search(searcher, {"q": q, "size": 10})
        _assert(response.status_code == 200, f"S3 {q}: {response.status_code} {response.text}")
        ids = set(_hit_ids(response.json()))
        _assert(forbidden not in ids, f"S3 searcher must not see {forbidden}: {ids}")
    print("[ok] S3 searcher misses bravo/charlie proof docs")


def s4_realm_admin_group_hit(admin: str) -> None:
    response = _search(admin, {"q": "bravo-proof-token", "size": 10})
    _assert(response.status_code == 200, f"S4 expected 200 got {response.status_code} {response.text}")
    ids = set(_hit_ids(response.json()))
    _assert("proof-group-engineering" in ids, f"S4 missing group proof: {ids}")
    print("[ok] S4 realm-admin bravo → proof-group-engineering")


def s5_empty_q(searcher: str) -> None:
    for q in ("", "   "):
        response = _search(searcher, {"q": q, "size": 10})
        _assert(
            response.status_code == 400,
            f"S5 q={q!r} expected 400 got {response.status_code} {response.text}",
        )
    print("[ok] S5 empty/whitespace q → 400")


def s6_health_and_me(searcher: str) -> None:
    health = httpx.get(f"{API}/health", timeout=10)
    _assert(health.status_code == 200, f"S6 health {health.status_code}")
    me = httpx.get(f"{API}/auth/me", headers=_auth(searcher), timeout=10)
    _assert(me.status_code == 200, f"S6 /auth/me {me.status_code} {me.text}")
    print("[ok] S6 /health + /auth/me → 200")


def s13_search_seeded_file(searcher: str, file_a: str) -> None:
    meta = httpx.get(f"{API}/files/{file_a}", headers=_auth(searcher), timeout=10)
    _assert(meta.status_code == 200, f"S13 meta {meta.status_code}")
    name = meta.json()["display_name"]
    # Use basename stem / distinctive token from path
    q = name.rsplit(".", 1)[0] if "." in name else name
    if len(q) < 3:
        q = name
    response = _search(searcher, {"q": q, "size": 20}, timeout=120.0)
    _assert(response.status_code == 200, f"S13 search {response.status_code} {response.text[:300]}")
    body = response.json()
    file_ids = {h.get("file_id") for h in body.get("hits", [])}
    if file_a not in file_ids:
        # Fallback: search a short unique substring from first OS chunk content
        settings = get_settings()
        with httpx.Client(
            base_url=settings.opensearch_url,
            verify=settings.opensearch_verify_certs,
            auth=("admin", settings.opensearch_initial_admin_password),
            timeout=30.0,
        ) as client:
            os_r = client.post(
                f"/{settings.opensearch_index}/_search",
                json={
                    "size": 1,
                    "query": {"term": {"file_id": file_a}},
                    "_source": ["content"],
                },
            )
        if os_r.is_error or not os_r.json().get("hits", {}).get("hits"):
            print(f"[skip] S13 no OS chunks for file_a={file_a}")
            return
        content = os_r.json()["hits"]["hits"][0]["_source"].get("content") or ""
        token = next((w for w in content.split() if len(w) >= 6), None)
        if not token:
            print("[skip] S13 no usable content token")
            return
        response = _search(searcher, {"q": token, "size": 20}, timeout=120.0)
        _assert(response.status_code == 200, f"S13 retry {response.status_code}")
        body = response.json()
        file_ids = {h.get("file_id") for h in body.get("hits", [])}
    _assert(file_a in file_ids, f"S13 expected file_id {file_a} in hits: {file_ids} q={q!r}")
    print(f"[ok] S13 search finds seeded file_id={file_a}")


def main() -> int:
    print("ensuring proof-* docs…")
    _ensure_proof_docs()
    print("acquiring tokens…")
    searcher = _token(SEARCHER_USERNAME, SEARCHER_PASSWORD)
    admin = _token(REALM_ADMIN_USERNAME, REALM_ADMIN_PASSWORD)

    # View / Open
    v1_files_no_token()
    v2_files_empty_or_list(searcher)
    file_a = _granted_search_user_file_id()
    if file_a:
        v3_list_after_seed(searcher, file_a)
        v4_content_bytes(searcher, file_a)
        v5_content_forbidden(admin, file_a)
    else:
        print("[skip] V3–V5 no G3 seed (run scripts.seed_file_acl_for_proofs)")
    v6_missing_file(searcher)
    v7_content_no_token(file_a)
    v8_jwt_cannot_index(searcher)

    # Search
    s1_no_token()
    s2_searcher_role_hit(searcher)
    s3_searcher_misses_group_and_nobody(searcher)
    s4_realm_admin_group_hit(admin)
    s5_empty_q(searcher)
    s6_health_and_me(searcher)
    if file_a:
        s13_search_seeded_file(searcher, file_a)
    else:
        print("[skip] S13 needs G3 seed")

    print("all search_view_proof checks passed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ProofFailure as exc:
        print(f"[fail] {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
