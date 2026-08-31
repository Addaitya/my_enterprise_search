"""Admin member assignment proofs (Task 12b). Not part of init_services.

Needs live API on :8000, Keycloak + Postgres up.

Run (backend venv, stack up)::

    cd backend
    uv run python -m scripts.admin_member_assignment_proof
"""

from __future__ import annotations

import sys
import uuid
from typing import Any

import httpx
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_engine
from app.models.identity import Group, Role
from app.services.keycloak_admin import KeycloakAdmin
from init_services.keycloak import (
    REALM_ADMIN_PASSWORD,
    REALM_ADMIN_USERNAME,
    SEARCHER_PASSWORD,
    SEARCHER_USERNAME,
)

API = "http://localhost:8000"

QA_USERS = ("qa-ma-user1", "qa-ma-user2")
QA_PASSWORD = "qa-ma-pass-1"


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


def _role_id(name: str) -> uuid.UUID:
    with Session(bind=get_engine()) as db:
        role = db.scalar(select(Role).where(Role.name == name))
        if role is None:
            raise ProofFailure(f"role {name!r} missing")
        return role.id


def _group_id(name: str) -> uuid.UUID:
    with Session(bind=get_engine()) as db:
        group = db.scalar(select(Group).where(Group.name == name))
        if group is None:
            raise ProofFailure(f"group {name!r} missing")
        return group.id


def _hard_delete_user(username: str) -> None:
    kc = KeycloakAdmin()
    existing = kc.find_user_by_username(username)
    if not existing:
        with Session(get_engine()) as session:
            row = session.execute(
                text("SELECT id FROM users WHERE username = :u"), {"u": username}
            ).first()
            if row:
                uid = str(row[0])
                session.execute(text("DELETE FROM user_roles WHERE user_id = :id"), {"id": uid})
                session.execute(text("DELETE FROM user_groups WHERE user_id = :id"), {"id": uid})
                session.execute(text("DELETE FROM users WHERE id = :id"), {"id": uid})
                session.commit()
        return
    uid = existing["id"]
    try:
        kc.delete_user(uid)
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] kc delete {username}: {exc}")
    with Session(get_engine()) as session:
        session.execute(text("DELETE FROM user_roles WHERE user_id = :id"), {"id": uid})
        session.execute(text("DELETE FROM user_groups WHERE user_id = :id"), {"id": uid})
        session.execute(text("DELETE FROM users WHERE id = :id"), {"id": uid})
        session.commit()


def _cleanup() -> None:
    for name in QA_USERS:
        _hard_delete_user(name)


def _create_qa_user(admin_h: dict[str, str], username: str) -> dict[str, Any]:
    response = httpx.post(
        f"{API}/admin/users",
        headers=admin_h,
        json={
            "username": username,
            "email": f"{username}@example.com",
            "password": QA_PASSWORD,
            "enabled": True,
            "role_names": ["search-user"],
            "group_names": [],
        },
        timeout=30,
    )
    if response.status_code != 201:
        raise ProofFailure(f"create {username}: {response.status_code} {response.text}")
    return response.json()


def _pg_user_in_group(user_id: str, group_name: str) -> bool:
    with Session(get_engine()) as session:
        row = session.execute(
            text(
                """
                SELECT 1 FROM user_groups ug
                JOIN groups g ON g.id = ug.group_id
                WHERE ug.user_id = :uid AND g.name = :gname
                """
            ),
            {"uid": user_id, "gname": group_name},
        ).first()
        return row is not None


def _pg_user_has_role(user_id: str, role_name: str) -> bool:
    with Session(get_engine()) as session:
        row = session.execute(
            text(
                """
                SELECT 1 FROM user_roles ur
                JOIN roles r ON r.id = ur.role_id
                WHERE ur.user_id = :uid AND r.name = :rname
                """
            ),
            {"uid": user_id, "rname": role_name},
        ).first()
        return row is not None


def _kc_user_in_group(user_id: str, group_name: str) -> bool:
    kc = KeycloakAdmin()
    groups = kc.list_user_groups(user_id)
    return any(g.get("name") == group_name for g in groups)


def _kc_user_has_role(user_id: str, role_name: str) -> bool:
    kc = KeycloakAdmin()
    roles = kc.list_user_realm_roles(user_id)
    return any(r.get("name") == role_name for r in roles)


def main() -> int:
    print("=== admin member assignment proofs ===")
    _cleanup()

    admin = _token(REALM_ADMIN_USERNAME, REALM_ADMIN_PASSWORD)
    searcher = _token(SEARCHER_USERNAME, SEARCHER_PASSWORD)
    admin_h = _auth(admin)
    searcher_h = _auth(searcher)

    search_user_role_id = _role_id("search-user")
    engineering_id = _group_id("engineering")
    empty_id = _group_id("_empty")

    # 1: searcher forbidden
    r = httpx.get(
        f"{API}/admin/roles/{search_user_role_id}/members",
        headers=searcher_h,
        timeout=30,
    )
    _assert(r.status_code == 403, f"proof1 expected 403 got {r.status_code} {r.text}")
    print("[ok] 1: searcher GET role members → 403")

    # Create 2 QA users with search-user only
    u1 = _create_qa_user(admin_h, QA_USERS[0])
    u2 = _create_qa_user(admin_h, QA_USERS[1])
    ids = [u1["id"], u2["id"]]

    # 2: add both to engineering
    r = httpx.post(
        f"{API}/admin/groups/{engineering_id}/members",
        headers=admin_h,
        json={"user_ids": ids},
        timeout=30,
    )
    _assert(r.status_code == 200, f"proof2 add: {r.status_code} {r.text}")
    body = r.json()
    _assert(len(body.get("results") or []) == 2, f"proof2 results: {body}")
    _assert(not body.get("failed"), f"proof2 failed: {body}")

    r = httpx.get(
        f"{API}/admin/groups/{engineering_id}/members?limit=100",
        headers=admin_h,
        timeout=30,
    )
    _assert(r.status_code == 200, f"proof2 list: {r.status_code} {r.text}")
    members = {m["id"] for m in r.json().get("items") or []}
    _assert(u1["id"] in members and u2["id"] in members, f"proof2 not in list: {members}")
    for uid in ids:
        _assert(_pg_user_in_group(uid, "engineering"), f"proof2 PG missing group for {uid}")
        _assert(_kc_user_in_group(uid, "engineering"), f"proof2 KC missing group for {uid}")
    print("[ok] 2: add 2 users to engineering; KC+PG agree")

    # 3: add again → no-op success
    r = httpx.post(
        f"{API}/admin/groups/{engineering_id}/members",
        headers=admin_h,
        json={"user_ids": ids},
        timeout=30,
    )
    _assert(r.status_code == 200, f"proof3: {r.status_code} {r.text}")
    body = r.json()
    _assert(len(body.get("results") or []) == 2, f"proof3 results: {body}")
    _assert(not body.get("failed"), f"proof3 failed: {body}")
    print("[ok] 3: re-add same users → no-op success")

    # 4: remove both from engineering
    r = httpx.post(
        f"{API}/admin/groups/{engineering_id}/members:remove",
        headers=admin_h,
        json={"user_ids": ids},
        timeout=30,
    )
    _assert(r.status_code == 200, f"proof4: {r.status_code} {r.text}")
    body = r.json()
    _assert(len(body.get("results") or []) == 2, f"proof4 results: {body}")
    for uid in ids:
        _assert(not _pg_user_in_group(uid, "engineering"), f"proof4 still in PG {uid}")
        _assert(not _kc_user_in_group(uid, "engineering"), f"proof4 still in KC {uid}")
        _assert(_pg_user_has_role(uid, "search-user"), f"proof4 lost search-user PG {uid}")
        _assert(_kc_user_has_role(uid, "search-user"), f"proof4 lost search-user KC {uid}")
    print("[ok] 4: remove from engineering; still have search-user")

    # 5: remove search-user from user who only has that role → failed
    r = httpx.post(
        f"{API}/admin/roles/{search_user_role_id}/members:remove",
        headers=admin_h,
        json={"user_ids": [u1["id"]]},
        timeout=30,
    )
    _assert(r.status_code == 200, f"proof5: {r.status_code} {r.text}")
    body = r.json()
    _assert(len(body.get("failed") or []) == 1, f"proof5 expected failed: {body}")
    _assert(str(body["failed"][0]["user_id"]) == u1["id"], f"proof5 failed id: {body}")
    _assert(_pg_user_has_role(u1["id"], "search-user"), "proof5 role stripped in PG")
    _assert(_kc_user_has_role(u1["id"], "search-user"), "proof5 role stripped in KC")
    print("[ok] 5: remove last search-user → failed; role kept")

    # 6: add to _empty → 400
    r = httpx.post(
        f"{API}/admin/groups/{empty_id}/members",
        headers=admin_h,
        json={"user_ids": [u1["id"]]},
        timeout=30,
    )
    _assert(r.status_code == 400, f"proof6 expected 400 got {r.status_code} {r.text}")
    print("[ok] 6: add to _empty → 400")

    # 7: 101 user_ids → 400
    many = [str(uuid.uuid4()) for _ in range(101)]
    r = httpx.post(
        f"{API}/admin/groups/{engineering_id}/members",
        headers=admin_h,
        json={"user_ids": many},
        timeout=30,
    )
    _assert(r.status_code == 400, f"proof7 expected 400 got {r.status_code} {r.text}")
    print("[ok] 7: 101 user_ids → 400")

    # 8: unknown + good → partial
    unknown = str(uuid.uuid4())
    r = httpx.post(
        f"{API}/admin/groups/{engineering_id}/members",
        headers=admin_h,
        json={"user_ids": [u2["id"], unknown]},
        timeout=30,
    )
    _assert(r.status_code == 200, f"proof8: {r.status_code} {r.text}")
    body = r.json()
    result_ids = {str(x["id"]) for x in body.get("results") or []}
    failed_ids = {str(x["user_id"]) for x in body.get("failed") or []}
    _assert(u2["id"] in result_ids, f"proof8 good missing: {body}")
    _assert(unknown in failed_ids, f"proof8 unknown not failed: {body}")
    # cleanup engineering membership from proof 8
    httpx.post(
        f"{API}/admin/groups/{engineering_id}/members:remove",
        headers=admin_h,
        json={"user_ids": [u2["id"]]},
        timeout=30,
    )
    print("[ok] 8: mixed unknown + good → results/failed")

    # 9: health + admin-ping
    r = httpx.get(f"{API}/health", timeout=15)
    _assert(r.status_code == 200, f"proof9 health: {r.status_code}")
    r = httpx.get(f"{API}/auth/admin-ping", headers=admin_h, timeout=15)
    _assert(r.status_code == 200, f"proof9 admin-ping: {r.status_code} {r.text}")
    print("[ok] 9: /health + /auth/admin-ping → 200")

    _cleanup()
    print("=== all member assignment proofs passed ===")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ProofFailure as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
