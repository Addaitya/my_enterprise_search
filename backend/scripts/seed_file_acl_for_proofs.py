"""G3 proof scaffolding: grant file_acl + sync OpenSearch allowed_* for ingest files.

Not the Task 6 admin product. Idempotent upsert of ACL rows for specific file_ids.
Never grants ``_empty``. Uses basic OpenSearch ``admin`` only for ``update_by_query``.

Run (backend venv, stack up)::

    cd backend
    uv run python -m scripts.seed_file_acl_for_proofs
"""

from __future__ import annotations

import sys
import uuid
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_engine
from app.models.file import File, FileAcl
from app.models.identity import Group, Role
from app.services.file_access import display_name_from_path

# Prefer a txt/csv for easy content search proofs; fall back to newest file.
PREFERRED_TYPES = ("txt", "csv", "pdf")


class SeedFailure(RuntimeError):
    pass


def _session() -> Session:
    return Session(bind=get_engine())


def _pick_files(db: Session, *, want: int = 2) -> list[File]:
    rows = list(db.scalars(select(File).order_by(File.uploaded_at.desc())).all())
    if not rows:
        raise SeedFailure("no files in Postgres — run an ingest first")

    picked: list[File] = []
    for ft in PREFERRED_TYPES:
        for row in rows:
            if row.file_type == ft and row not in picked:
                picked.append(row)
                break
        if len(picked) >= want:
            break
    for row in rows:
        if len(picked) >= want:
            break
        if row not in picked:
            picked.append(row)
    return picked[:want]


def _role_by_name(db: Session, name: str) -> Role:
    role = db.scalar(select(Role).where(Role.name == name))
    if role is None:
        raise SeedFailure(f"role {name!r} missing from mirror — run init_services")
    return role


def _group_by_name(db: Session, name: str) -> Group:
    group = db.scalar(select(Group).where(Group.name == name))
    if group is None:
        raise SeedFailure(f"group {name!r} missing from mirror — run init_services")
    return group


def _upsert_role_acl(db: Session, file_id: uuid.UUID, role_id: uuid.UUID, permission: str = "viewer") -> None:
    existing = db.scalar(
        select(FileAcl).where(FileAcl.file_id == file_id, FileAcl.role_id == role_id)
    )
    if existing is not None:
        existing.permission = permission
        return
    db.add(
        FileAcl(
            file_id=file_id,
            role_id=role_id,
            user_id=None,
            group_id=None,
            permission=permission,
        )
    )


def _upsert_group_acl(
    db: Session, file_id: uuid.UUID, group_id: uuid.UUID, permission: str = "viewer"
) -> None:
    if group_id is None:
        raise SeedFailure("group_id required")
    existing = db.scalar(
        select(FileAcl).where(FileAcl.file_id == file_id, FileAcl.group_id == group_id)
    )
    if existing is not None:
        existing.permission = permission
        return
    db.add(
        FileAcl(
            file_id=file_id,
            group_id=group_id,
            user_id=None,
            role_id=None,
            permission=permission,
        )
    )


def _os_update_allowed(
    file_id: uuid.UUID,
    *,
    allowed_roles: list[str],
    allowed_groups: list[str],
) -> None:
    settings = get_settings()
    body: dict[str, Any] = {
        "query": {"term": {"file_id": str(file_id)}},
        "script": {
            "lang": "painless",
            "source": (
                "ctx._source.allowed_roles = params.roles; "
                "ctx._source.allowed_groups = params.groups;"
            ),
            "params": {"roles": allowed_roles, "groups": allowed_groups},
        },
    }
    with httpx.Client(
        base_url=settings.opensearch_url,
        verify=settings.opensearch_verify_certs,
        auth=("admin", settings.opensearch_initial_admin_password),
        timeout=60.0,
    ) as client:
        response = client.post(
            f"/{settings.opensearch_index}/_update_by_query",
            params={"refresh": "true"},
            json=body,
        )
    if response.is_error:
        raise SeedFailure(
            f"update_by_query file_id={file_id}: {response.status_code} {response.text}"
        )
    payload = response.json()
    updated = int(payload.get("updated") or 0)
    print(f"[ok] OS update_by_query file_id={file_id} updated={updated}")


def seed() -> dict[str, Any]:
    """Grant search-user on file A; engineering on file B (if ≥2 files)."""
    db = _session()
    try:
        files = _pick_files(db, want=2)
        search_user = _role_by_name(db, "search-user")
        engineering = _group_by_name(db, "engineering")

        file_a = files[0]
        _upsert_role_acl(db, file_a.id, search_user.id, "viewer")
        db.commit()
        _os_update_allowed(file_a.id, allowed_roles=["search-user"], allowed_groups=[])
        print(
            f"[ok] file A {file_a.id} ({display_name_from_path(file_a.object_store_path)}) "
            f"→ role search-user viewer"
        )

        result: dict[str, Any] = {
            "file_a": str(file_a.id),
            "file_a_name": display_name_from_path(file_a.object_store_path),
            "file_b": None,
            "file_b_name": None,
        }

        if len(files) >= 2:
            file_b = files[1]
            if file_b.id == file_a.id:
                print("[warn] only one distinct file; skipping engineering grant")
            else:
                _upsert_group_acl(db, file_b.id, engineering.id, "viewer")
                db.commit()
                _os_update_allowed(file_b.id, allowed_roles=[], allowed_groups=["engineering"])
                print(
                    f"[ok] file B {file_b.id} ({display_name_from_path(file_b.object_store_path)}) "
                    f"→ group engineering viewer"
                )
                result["file_b"] = str(file_b.id)
                result["file_b_name"] = display_name_from_path(file_b.object_store_path)

        return result
    finally:
        db.close()


def main() -> int:
    result = seed()
    print("seed_file_acl_for_proofs done:", result)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SeedFailure as exc:
        print(f"[fail] {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
