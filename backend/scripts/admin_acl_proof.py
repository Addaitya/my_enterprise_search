"""Admin file ACL + sync job proofs (Task 6b). Not part of init_services.

Needs an ingested file and live API on :8000.

Run (backend venv, stack up)::

    cd backend
    uv run python -m scripts.admin_acl_proof
"""

from __future__ import annotations

import sys
import time
import uuid
from typing import Any

import httpx
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_engine
from app.models.identity import Group, Role
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


def _wait_job(admin_token: str, job_id: str, *, timeout_s: float = 60.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    headers = _auth(admin_token)
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        response = httpx.get(f"{API}/admin/acl-jobs/{job_id}", headers=headers, timeout=30)
        if response.status_code != 200:
            raise ProofFailure(f"job poll {response.status_code} {response.text}")
        last = response.json()
        if last.get("status") in ("succeeded", "failed"):
            return last
        time.sleep(1.0)
    raise ProofFailure(f"job {job_id} did not finish: {last}")


def _os_allowed(file_id: str) -> tuple[list[str], list[str]]:
    settings = get_settings()
    with httpx.Client(
        base_url=settings.opensearch_url,
        verify=settings.opensearch_verify_certs,
        auth=("admin", settings.opensearch_initial_admin_password),
        timeout=30.0,
    ) as client:
        response = client.post(
            f"/{settings.opensearch_index}/_search",
            json={
                "size": 1,
                "query": {"term": {"file_id": file_id}},
                "_source": ["allowed_roles", "allowed_groups"],
            },
        )
    if response.is_error:
        raise ProofFailure(f"OS search: {response.status_code} {response.text}")
    hits = response.json().get("hits", {}).get("hits", [])
    if not hits:
        raise ProofFailure(f"no OS chunks for file_id={file_id}")
    src = hits[0].get("_source") or {}
    return list(src.get("allowed_roles") or []), list(src.get("allowed_groups") or [])


def _pick_file(admin_token: str) -> dict[str, Any]:
    response = httpx.get(
        f"{API}/admin/files?limit=50&offset=0",
        headers=_auth(admin_token),
        timeout=30,
    )
    if response.status_code != 200:
        raise ProofFailure(f"list files: {response.status_code} {response.text}")
    items = response.json().get("items") or []
    if not items:
        raise ProofFailure("no files — upload one first")
    # Prefer txt for search proofs
    for item in items:
        if item.get("file_type") == "txt":
            return item
    return items[0]


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


def _empty_group_id() -> uuid.UUID:
    return _group_id("_empty")


def main() -> int:
    admin = _token(REALM_ADMIN_USERNAME, REALM_ADMIN_PASSWORD)
    searcher = _token(SEARCHER_USERNAME, SEARCHER_PASSWORD)
    admin_h = _auth(admin)
    searcher_h = _auth(searcher)

    # 1: searcher forbidden
    r = httpx.get(f"{API}/admin/files", headers=searcher_h, timeout=30)
    _assert(r.status_code == 403, f"proof1 expected 403 got {r.status_code}")
    print("[ok] 1: searcher GET /admin/files → 403")

    # 2: admin lists all
    r = httpx.get(f"{API}/admin/files?limit=100", headers=admin_h, timeout=30)
    _assert(r.status_code == 200, f"proof2 {r.status_code} {r.text}")
    body = r.json()
    _assert(body.get("total", 0) >= 1 and body.get("items"), f"proof2 empty {body}")
    print(f"[ok] 2: admin GET /admin/files → 200 total={body['total']}")

    file_row = _pick_file(admin)
    file_id = file_row["id"]
    print(f"     using file {file_id} ({file_row.get('display_name')})")

    search_user_id = str(_role_id("search-user"))
    engineering_id = str(_group_id("engineering"))
    empty_id = str(_empty_group_id())

    # Clear ACL first so proofs start clean
    r = httpx.put(
        f"{API}/admin/files/{file_id}/acl",
        headers=admin_h,
        json={"grants": []},
        timeout=30,
    )
    _assert(r.status_code == 200, f"clear ACL {r.status_code} {r.text}")
    clear_job = r.json().get("acl_job_id")
    if clear_job:
        job = _wait_job(admin, clear_job)
        _assert(job["status"] == "succeeded", f"clear job {job}")

    # 3: grant search-user viewer
    r = httpx.put(
        f"{API}/admin/files/{file_id}/acl",
        headers=admin_h,
        json={
            "grants": [
                {
                    "principal_type": "role",
                    "principal_id": search_user_id,
                    "permission": "viewer",
                }
            ]
        },
        timeout=30,
    )
    _assert(r.status_code == 200, f"proof3 {r.status_code} {r.text}")
    payload = r.json()
    job_id = payload.get("acl_job_id")
    _assert(job_id, f"proof3 missing acl_job_id {payload}")
    job = _wait_job(admin, job_id)
    _assert(job["status"] == "succeeded", f"proof3 job {job}")
    roles, groups = _os_allowed(file_id)
    _assert("search-user" in roles, f"proof3 OS roles={roles}")
    print(f"[ok] 3: PUT ACL search-user → job succeeded; OS allowed_roles={roles}")

    # 4: searcher list + search
    r = httpx.get(f"{API}/files", headers=searcher_h, timeout=30)
    _assert(r.status_code == 200, f"proof4 list {r.status_code}")
    listed_ids = {item["id"] for item in r.json().get("items", r.json() if isinstance(r.json(), list) else [])}
    # files list shape may be {items:[]} or []
    data = r.json()
    if isinstance(data, dict):
        listed_ids = {item["id"] for item in data.get("items", [])}
    else:
        listed_ids = {item["id"] for item in data}
    _assert(file_id in listed_ids, f"proof4 file not listed {listed_ids}")

    # Search with a token from the file name / generic term
    display = file_row.get("display_name") or ""
    query = display.rsplit(".", 1)[0][:40] if display else "the"
    def _search_file_ids(q: str, token_headers: dict[str, str]) -> set[str]:
        resp = httpx.post(
            f"{API}/search",
            headers=token_headers,
            json={"q": q, "size": 50},
            timeout=60,
        )
        if resp.status_code != 200:
            raise ProofFailure(f"search {resp.status_code} {resp.text}")
        hit_list = resp.json().get("hits") or []
        found: set[str] = set()
        for h in hit_list:
            fid = h.get("file_id")
            if fid:
                found.add(str(fid))
        return found

    hit_file_ids = _search_file_ids(query, searcher_h)
    if file_id not in hit_file_ids:
        for q in ("opaque", "redirect", "the", "and"):
            hit_file_ids |= _search_file_ids(q, searcher_h)
            if file_id in hit_file_ids:
                break
    _assert(file_id in hit_file_ids, f"proof4 search miss file_id; hits_files={hit_file_ids}")
    print("[ok] 4: searcher list + search hit file")

    # 5: revoke all
    r = httpx.put(
        f"{API}/admin/files/{file_id}/acl",
        headers=admin_h,
        json={"grants": []},
        timeout=30,
    )
    _assert(r.status_code == 200, f"proof5 {r.status_code}")
    job = _wait_job(admin, r.json()["acl_job_id"])
    _assert(job["status"] == "succeeded", f"proof5 job {job}")
    roles, groups = _os_allowed(file_id)
    _assert(roles == [] and groups == [], f"proof5 OS not empty {roles} {groups}")
    r = httpx.get(f"{API}/files", headers=searcher_h, timeout=30)
    data = r.json()
    listed_ids = {item["id"] for item in (data.get("items", []) if isinstance(data, dict) else data)}
    _assert(file_id not in listed_ids, "proof5 searcher still lists file")
    print("[ok] 5: revoke all → OS empty; searcher list miss")

    # 6: grant engineering group — realm-admin (in engineering) can search; searcher alone may miss
    r = httpx.put(
        f"{API}/admin/files/{file_id}/acl",
        headers=admin_h,
        json={
            "grants": [
                {
                    "principal_type": "group",
                    "principal_id": engineering_id,
                    "permission": "viewer",
                }
            ]
        },
        timeout=30,
    )
    _assert(r.status_code == 200, f"proof6 {r.status_code} {r.text}")
    job = _wait_job(admin, r.json()["acl_job_id"])
    _assert(job["status"] == "succeeded", f"proof6 job {job}")
    roles, groups = _os_allowed(file_id)
    _assert("engineering" in groups, f"proof6 OS groups={groups}")

    r = httpx.get(f"{API}/files", headers=admin_h, timeout=30)
    data = r.json()
    admin_listed = {item["id"] for item in (data.get("items", []) if isinstance(data, dict) else data)}
    _assert(file_id in admin_listed, "proof6 admin list miss (needs engineering group)")

    r = httpx.get(f"{API}/files", headers=searcher_h, timeout=30)
    data = r.json()
    searcher_listed = {item["id"] for item in (data.get("items", []) if isinstance(data, dict) else data)}
    _assert(file_id not in searcher_listed, "proof6 searcher should miss without role grant")
    print("[ok] 6: engineering grant — admin lists, searcher misses")

    # 7: reject _empty
    r = httpx.post(
        f"{API}/admin/files/{file_id}/acl",
        headers=admin_h,
        json={
            "principal_type": "group",
            "principal_id": empty_id,
            "permission": "viewer",
        },
        timeout=30,
    )
    _assert(r.status_code == 400, f"proof7 expected 400 got {r.status_code} {r.text}")
    print("[ok] 7: grant _empty → 400")

    # 8: force fail + retry
    r = httpx.put(
        f"{API}/admin/files/{file_id}/acl",
        headers=admin_h,
        json={
            "grants": [
                {
                    "principal_type": "role",
                    "principal_id": search_user_id,
                    "permission": "viewer",
                }
            ]
        },
        timeout=30,
    )
    _assert(r.status_code == 200, f"proof8 setup {r.status_code}")
    job_id = r.json()["acl_job_id"]
    job = _wait_job(admin, job_id)
    _assert(job["status"] == "succeeded", f"proof8 setup job {job}")

    with Session(bind=get_engine()) as db:
        db.execute(
            text(
                "UPDATE acl_sync_jobs SET status='failed', error='forced for proof', "
                "finished_at=NOW(), updated_at=NOW() WHERE id=:id"
            ),
            {"id": job_id},
        )
        db.commit()

    r = httpx.post(f"{API}/admin/acl-jobs/{job_id}/retry", headers=admin_h, timeout=30)
    _assert(r.status_code == 200, f"proof8 retry {r.status_code} {r.text}")
    _assert(r.json().get("status") == "queued", f"proof8 status {r.json()}")
    job = _wait_job(admin, job_id)
    _assert(job["status"] == "succeeded", f"proof8 after retry {job}")
    print("[ok] 8: retry failed job → succeeded")

    # 9: health + admin-ping
    r = httpx.get(f"{API}/health", timeout=15)
    _assert(r.status_code == 200, f"proof9 health {r.status_code}")
    r = httpx.get(f"{API}/auth/admin-ping", headers=admin_h, timeout=15)
    _assert(r.status_code == 200, f"proof9 admin-ping {r.status_code}")
    print("[ok] 9: /health + /auth/admin-ping → 200")

    print("=== all admin ACL proofs passed ===")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ProofFailure as exc:
        print(f"[fail] {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
