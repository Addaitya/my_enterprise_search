"""Admin file access UI proofs (Task 12a). Not part of init_services.

Needs ≥2 ingested files and live API on :8000.

Run (backend venv, stack up)::

    cd backend
    uv run python -m scripts.admin_file_access_proof
"""

from __future__ import annotations

import sys
import time
import uuid
from typing import Any

import httpx
from sqlalchemy import select
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


def _pick_two_files(admin_token: str) -> list[dict[str, Any]]:
    response = httpx.get(
        f"{API}/admin/files?limit=50&offset=0",
        headers=_auth(admin_token),
        timeout=30,
    )
    if response.status_code != 200:
        raise ProofFailure(f"list files: {response.status_code} {response.text}")
    items = response.json().get("items") or []
    if len(items) < 2:
        raise ProofFailure(f"need ≥2 ingested files, got {len(items)}")
    return items[:2]


def main() -> int:
    admin = _token(REALM_ADMIN_USERNAME, REALM_ADMIN_PASSWORD)
    searcher = _token(SEARCHER_USERNAME, SEARCHER_PASSWORD)
    admin_h = _auth(admin)
    searcher_h = _auth(searcher)

    # 1: searcher forbidden on bulk
    r = httpx.post(
        f"{API}/admin/files/acl:bulk",
        headers=searcher_h,
        json={
            "file_ids": [str(uuid.uuid4())],
            "mode": "upsert",
            "grants": [
                {
                    "principal_type": "role",
                    "principal_id": str(uuid.uuid4()),
                    "permission": "viewer",
                }
            ],
        },
        timeout=30,
    )
    _assert(r.status_code == 403, f"proof1 expected 403 got {r.status_code} {r.text}")
    print("[ok] 1: searcher POST /admin/files/acl:bulk → 403")

    files = _pick_two_files(admin)
    file_a, file_b = files[0], files[1]
    ids = [file_a["id"], file_b["id"]]
    print(f"     using files {ids[0]} ({file_a.get('display_name')}), {ids[1]} ({file_b.get('display_name')})")

    search_user_id = str(_role_id("search-user"))
    empty_id = str(_group_id("_empty"))

    # Clear both files first
    for fid in ids:
        r = httpx.put(
            f"{API}/admin/files/{fid}/acl",
            headers=admin_h,
            json={"grants": []},
            timeout=30,
        )
        _assert(r.status_code == 200, f"clear ACL {fid}: {r.status_code} {r.text}")
        job_id = r.json().get("acl_job_id")
        if job_id:
            job = _wait_job(admin, job_id)
            _assert(job["status"] == "succeeded", f"clear job {job}")

    # 2: bulk upsert search-user onto 2 files
    r = httpx.post(
        f"{API}/admin/files/acl:bulk",
        headers=admin_h,
        json={
            "file_ids": ids,
            "mode": "upsert",
            "grants": [
                {
                    "principal_type": "role",
                    "principal_id": search_user_id,
                    "permission": "viewer",
                }
            ],
        },
        timeout=30,
    )
    _assert(r.status_code == 200, f"proof2 {r.status_code} {r.text}")
    body = r.json()
    results = body.get("results") or []
    failed = body.get("failed") or []
    _assert(len(results) == 2 and not failed, f"proof2 results={results} failed={failed}")
    for item in results:
        grant_roles = [
            g["principal_name"]
            for g in item.get("grants") or []
            if g.get("principal_type") == "role"
        ]
        _assert("search-user" in grant_roles, f"proof2 missing grant {item}")
        _assert(item.get("acl_job_id"), f"proof2 missing job {item}")
        job = _wait_job(admin, item["acl_job_id"])
        _assert(job["status"] == "succeeded", f"proof2 job {job}")
        roles, _groups = _os_allowed(item["file_id"])
        _assert("search-user" in roles, f"proof2 OS roles={roles} for {item['file_id']}")
    print("[ok] 2: bulk upsert → both results; jobs succeeded; OS allowed_roles ok")

    # 3: bulk revoke
    r = httpx.post(
        f"{API}/admin/files/acl:bulk",
        headers=admin_h,
        json={
            "file_ids": ids,
            "mode": "revoke",
            "grants": [
                {
                    "principal_type": "role",
                    "principal_id": search_user_id,
                    "permission": "viewer",
                }
            ],
        },
        timeout=30,
    )
    _assert(r.status_code == 200, f"proof3 {r.status_code} {r.text}")
    body = r.json()
    results = body.get("results") or []
    _assert(len(results) == 2, f"proof3 results={results}")
    for item in results:
        _assert(
            not any(g.get("principal_name") == "search-user" for g in item.get("grants") or []),
            f"proof3 grant still present {item}",
        )
        job = _wait_job(admin, item["acl_job_id"])
        _assert(job["status"] == "succeeded", f"proof3 job {job}")
        roles, _groups = _os_allowed(item["file_id"])
        _assert("search-user" not in roles, f"proof3 OS still has role {roles}")
    print("[ok] 3: bulk revoke → grants gone; OS updated")

    # 4: replace without confirm_replace
    r = httpx.post(
        f"{API}/admin/files/acl:bulk",
        headers=admin_h,
        json={
            "file_ids": ids,
            "mode": "replace",
            "grants": [],
            "confirm_replace": False,
        },
        timeout=30,
    )
    _assert(r.status_code == 400, f"proof4 expected 400 got {r.status_code} {r.text}")
    # Ensure no PG change — still empty from revoke
    for fid in ids:
        r2 = httpx.get(f"{API}/admin/files/{fid}/acl", headers=admin_h, timeout=30)
        _assert(r2.status_code == 200, f"proof4 get acl {r2.status_code}")
        _assert(r2.json().get("grants") == [], f"proof4 PG changed {r2.json()}")
    print("[ok] 4: replace without confirm_replace → 400; no PG change")

    # 5: 101 file_ids → 400
    fake_ids = [str(uuid.uuid4()) for _ in range(101)]
    r = httpx.post(
        f"{API}/admin/files/acl:bulk",
        headers=admin_h,
        json={
            "file_ids": fake_ids,
            "mode": "upsert",
            "grants": [
                {
                    "principal_type": "role",
                    "principal_id": search_user_id,
                    "permission": "viewer",
                }
            ],
        },
        timeout=30,
    )
    _assert(r.status_code == 400, f"proof5 expected 400 got {r.status_code} {r.text}")
    print("[ok] 5: 101 file_ids → 400")

    # 6: unknown + good id
    unknown = str(uuid.uuid4())
    r = httpx.post(
        f"{API}/admin/files/acl:bulk",
        headers=admin_h,
        json={
            "file_ids": [ids[0], unknown],
            "mode": "upsert",
            "grants": [
                {
                    "principal_type": "role",
                    "principal_id": search_user_id,
                    "permission": "viewer",
                }
            ],
        },
        timeout=30,
    )
    _assert(r.status_code == 200, f"proof6 {r.status_code} {r.text}")
    body = r.json()
    result_ids = {item["file_id"] for item in body.get("results") or []}
    failed_ids = {item["file_id"] for item in body.get("failed") or []}
    _assert(ids[0] in result_ids, f"proof6 good missing {body}")
    _assert(unknown in failed_ids, f"proof6 bad missing {body}")
    for item in body.get("results") or []:
        if item.get("acl_job_id"):
            job = _wait_job(admin, item["acl_job_id"])
            _assert(job["status"] == "succeeded", f"proof6 job {job}")
    print("[ok] 6: unknown + good → results/failed split")

    # 7: file-grants for role after grant
    r = httpx.get(
        f"{API}/admin/roles/{search_user_id}/file-grants?limit=50&offset=0",
        headers=admin_h,
        timeout=30,
    )
    _assert(r.status_code == 200, f"proof7 {r.status_code} {r.text}")
    grant_items = r.json().get("items") or []
    grant_file_ids = {item["file_id"] for item in grant_items}
    _assert(ids[0] in grant_file_ids, f"proof7 missing file {grant_items}")
    matched = next(item for item in grant_items if item["file_id"] == ids[0])
    _assert(matched.get("permission") == "viewer", f"proof7 perm {matched}")
    print("[ok] 7: GET role file-grants lists granted file")

    # 8: q + has_acl filters
    basename = (file_a.get("display_name") or "").rsplit(".", 1)[0]
    _assert(basename, "proof8 empty basename")
    r = httpx.get(
        f"{API}/admin/files?q={basename}&has_acl=true&limit=50",
        headers=admin_h,
        timeout=30,
    )
    _assert(r.status_code == 200, f"proof8 {r.status_code} {r.text}")
    filtered = r.json().get("items") or []
    filtered_ids = {item["id"] for item in filtered}
    _assert(ids[0] in filtered_ids, f"proof8 expected file_a in {filtered_ids}")
    for item in filtered:
        _assert(item.get("access_total", 0) >= 1 or item["id"] != ids[0], "proof8 access_total")
        name = (item.get("display_name") or "").lower()
        path = (item.get("object_store_path") or "").lower()
        _assert(
            basename.lower() in name or basename.lower() in path,
            f"proof8 q miss {item}",
        )
    print("[ok] 8: GET /admin/files?q&has_acl=true filters correctly")

    # 9: grant _empty → 400 before mutate
    # Snapshot grants on file_b
    r = httpx.get(f"{API}/admin/files/{ids[1]}/acl", headers=admin_h, timeout=30)
    before = r.json().get("grants")
    r = httpx.post(
        f"{API}/admin/files/acl:bulk",
        headers=admin_h,
        json={
            "file_ids": ids,
            "mode": "upsert",
            "grants": [
                {
                    "principal_type": "group",
                    "principal_id": empty_id,
                    "permission": "viewer",
                }
            ],
        },
        timeout=30,
    )
    _assert(r.status_code == 400, f"proof9 expected 400 got {r.status_code} {r.text}")
    r = httpx.get(f"{API}/admin/files/{ids[1]}/acl", headers=admin_h, timeout=30)
    _assert(r.json().get("grants") == before, f"proof9 PG mutated {r.json()}")
    print("[ok] 9: bulk grant _empty → 400 before mutate")

    # 10: health + admin-ping
    r = httpx.get(f"{API}/health", timeout=15)
    _assert(r.status_code == 200, f"proof10 health {r.status_code}")
    r = httpx.get(f"{API}/auth/admin-ping", headers=admin_h, timeout=15)
    _assert(r.status_code == 200, f"proof10 admin-ping {r.status_code}")
    print("[ok] 10: /health + /auth/admin-ping → 200")

    print("=== all admin file access proofs passed ===")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ProofFailure as exc:
        print(f"[fail] {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
