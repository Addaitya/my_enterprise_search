"""Admin identity API proofs (Task 6a). Not part of init_services.

Run (backend venv, stack up, API on :8000)::

    cd backend
    uv run python -m init_services.keycloak   # or full init_services — grants api-client Admin roles
    uv run python -m scripts.admin_identity_proof
"""

from __future__ import annotations

import sys

import httpx
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_engine
from app.models.file import File, FileAcl
from app.models.identity import Role
from app.services.keycloak_admin import KeycloakAdmin
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
    return {"Authorization": f"Bearer {token}"}


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise ProofFailure(msg)


def _cleanup_qa(admin_token: str) -> None:
    """Best-effort remove prior qa-* fixtures so proofs are re-runnable."""
    headers = _auth(admin_token)
    for path, name_key, name in (
        ("/admin/users", "username", "qa-user"),
        ("/admin/roles", "name", "qa-role"),
        ("/admin/groups", "name", "qa-group"),
    ):
        response = httpx.get(f"{API}{path}", headers=headers, timeout=30)
        if response.status_code != 200:
            continue
        body = response.json()
        for item in body.get("items", []):
            if item.get(name_key) != name:
                continue
            entity_id = item["id"]
            if path == "/admin/users":
                httpx.patch(
                    f"{API}/admin/users/{entity_id}",
                    headers=headers,
                    json={"enabled": False},
                    timeout=30,
                )
                # Users have no hard delete; leave disabled with renamed username risk —
                # disable is enough for re-create conflict. Delete via KC if still blocking.
            elif path == "/admin/roles":
                httpx.delete(f"{API}/admin/roles/{entity_id}", headers=headers, timeout=30)
            else:
                httpx.delete(f"{API}/admin/groups/{entity_id}", headers=headers, timeout=30)

    # If qa-user still exists (disabled), hard-delete in KC + PG so create can reuse username.
    kc = KeycloakAdmin()
    existing = kc.find_user_by_username("qa-user")
    if existing:
        try:
            kc.delete_user(existing["id"])
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] could not delete kc qa-user: {exc}")
        with Session(get_engine()) as session:
            session.execute(text("DELETE FROM user_roles WHERE user_id = :id"), {"id": existing["id"]})
            session.execute(text("DELETE FROM user_groups WHERE user_id = :id"), {"id": existing["id"]})
            session.execute(text("DELETE FROM users WHERE id = :id"), {"id": existing["id"]})
            session.commit()


def run() -> None:
    print("=== admin identity proofs ===")

    # Token fetch for product Keycloak admin client
    kc = KeycloakAdmin()
    token = kc.fetch_token()
    _assert(bool(token), "client_credentials token empty")
    print("[ok] A: api-client client_credentials token")

    searcher = _token(SEARCHER_USERNAME, SEARCHER_PASSWORD)
    admin = _token(REALM_ADMIN_USERNAME, REALM_ADMIN_PASSWORD)

    # 9: health + admin-ping
    health = httpx.get(f"{API}/health", timeout=15)
    _assert(health.status_code == 200, f"health {health.status_code}")
    ping = httpx.get(f"{API}/auth/admin-ping", headers=_auth(admin), timeout=15)
    _assert(ping.status_code == 200 and ping.json().get("ok") is True, f"admin-ping {ping.text}")
    print("[ok] 9: /health + /auth/admin-ping")

    # 1: searcher forbidden
    r1 = httpx.get(f"{API}/admin/users", headers=_auth(searcher), timeout=30)
    _assert(r1.status_code == 403, f"proof1 expected 403 got {r1.status_code}")
    print("[ok] 1: searcher GET /admin/users → 403")

    # Cleanup prior runs so create proofs are idempotent
    _cleanup_qa(admin)

    # 2: admin list includes seeds
    r2 = httpx.get(f"{API}/admin/users", headers=_auth(admin), timeout=30)
    _assert(r2.status_code == 200, f"proof2 {r2.status_code} {r2.text}")
    usernames = {u["username"] for u in r2.json()["items"]}
    _assert("realm-admin" in usernames, "realm-admin missing from list")
    _assert("searcher" in usernames, "searcher missing from list")
    print("[ok] 2: admin GET /admin/users includes seeds")

    # 3: create role
    r3 = httpx.post(
        f"{API}/admin/roles",
        headers=_auth(admin),
        json={"name": "qa-role", "description": "QA role"},
        timeout=30,
    )
    _assert(r3.status_code == 201, f"proof3 {r3.status_code} {r3.text}")
    role = r3.json()
    _assert(role["name"] == "qa-role" and role["is_system"] is False, f"proof3 body {role}")
    print("[ok] 3: POST /admin/roles qa-role")

    # 4: create group
    r4 = httpx.post(
        f"{API}/admin/groups",
        headers=_auth(admin),
        json={"name": "qa-group"},
        timeout=30,
    )
    _assert(r4.status_code == 201, f"proof4 {r4.status_code} {r4.text}")
    group = r4.json()
    _assert(group["name"] == "qa-group" and group["is_system"] is False, f"proof4 body {group}")
    print("[ok] 4: POST /admin/groups qa-group")

    # 5: create user
    r5 = httpx.post(
        f"{API}/admin/users",
        headers=_auth(admin),
        json={
            "username": "qa-user",
            "email": "qa-user@example.com",
            "password": "QaUserPass1!",
            "enabled": True,
            "role_names": ["search-user"],
            "group_names": ["qa-group"],
        },
        timeout=30,
    )
    _assert(r5.status_code == 201, f"proof5 {r5.status_code} {r5.text}")
    user = r5.json()
    _assert("password" not in user, "password leaked in response")
    _assert(user["username"] == "qa-user", user)
    _assert("search-user" in user["role_names"], user)
    _assert("qa-group" in user["group_names"], user)

    # password grant + claims
    qa_token = _token("qa-user", "QaUserPass1!")
    # decode via /auth/me
    me = httpx.get(f"{API}/auth/me", headers=_auth(qa_token), timeout=15)
    _assert(me.status_code == 200, f"qa-user /auth/me {me.status_code} {me.text}")
    me_body = me.json()
    _assert("search-user" in me_body["roles"], me_body)
    _assert("qa-group" in me_body["groups"], me_body)
    # permanent password: temporary=false means grant works without required actions
    print("[ok] 5: POST /admin/users qa-user + token claims")

    # 6: duplicate username
    r6 = httpx.post(
        f"{API}/admin/users",
        headers=_auth(admin),
        json={
            "username": "qa-user",
            "password": "OtherPass1!",
            "role_names": ["search-user"],
            "group_names": [],
        },
        timeout=30,
    )
    _assert(r6.status_code == 409, f"proof6 expected 409 got {r6.status_code} {r6.text}")
    print("[ok] 6: duplicate username → 409")

    # 7: rename forbidden
    r7 = httpx.patch(
        f"{API}/admin/roles/{role['id']}",
        headers=_auth(admin),
        json={"name": "qa-role-renamed", "description": "x"},
        timeout=30,
    )
    _assert(r7.status_code in (400, 422), f"proof7 expected 400/422 got {r7.status_code} {r7.text}")
    print(f"[ok] 7: PATCH role rename → {r7.status_code}")

    # 8: delete role with file_acl → 409 (seed a temp ACL if needed)
    with Session(get_engine()) as session:
        role_row = session.scalar(select(Role).where(Role.name == "qa-role"))
        _assert(role_row is not None, "qa-role missing in PG")
        # Ensure a file exists for FK
        file_row = session.scalar(select(File).limit(1))
        created_file = False
        if file_row is None:
            file_row = File(
                object_store_path="local/proof/qa-acl-placeholder.txt",
                file_type="txt",
                size_bytes=1,
                ingestion_type="local",
            )
            session.add(file_row)
            session.flush()
            created_file = True
        acl = FileAcl(file_id=file_row.id, role_id=role_row.id, permission="viewer")
        session.add(acl)
        session.commit()
        acl_id = str(acl.id)
        file_id = str(file_row.id)

    r8 = httpx.delete(f"{API}/admin/roles/{role['id']}", headers=_auth(admin), timeout=30)
    _assert(r8.status_code == 409, f"proof8 expected 409 got {r8.status_code} {r8.text}")
    print("[ok] 8: DELETE role with file_acl → 409")

    # cleanup ACL so qa-role can be deleted later
    with Session(get_engine()) as session:
        session.execute(text("DELETE FROM file_acl WHERE id = :id"), {"id": acl_id})
        if created_file:
            session.execute(text("DELETE FROM files WHERE id = :id"), {"id": file_id})
        session.commit()

    print("=== all admin identity proofs passed ===")


def main() -> None:
    try:
        run()
    except ProofFailure as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
