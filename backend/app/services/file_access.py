"""Postgres file_acl helpers for list / open (Task 5).

Authz uses JWT role/group **names** (not Postgres membership tables).
``editor`` implies view. Ignore ``_empty`` when matching (already stripped from
``CurrentUser.groups``). Realm ``admin`` does not bypass ACL.
"""

from __future__ import annotations

import uuid
from pathlib import PurePosixPath

from sqlalchemy import func, or_
from sqlalchemy.orm import Query, Session

from app.core.security import CurrentUser
from app.models.file import File, FileAcl
from app.models.identity import Group, Role

VIEW_PERMISSIONS = ("viewer", "editor")


def display_name_from_path(object_store_path: str) -> str:
    """Basename of object_store_path (G4 — no original_filename column)."""
    name = PurePosixPath(object_store_path.replace("\\", "/")).name
    return name or object_store_path


def content_type_for_file_type(file_type: str) -> str:
    mapping = {
        "pdf": "application/pdf",
        "txt": "text/plain",
        "csv": "text/csv",
    }
    return mapping.get((file_type or "").lower(), "application/octet-stream")


def _acl_match_filter(role_names: list[str], group_names: list[str]):
    conditions = []
    if role_names:
        conditions.append(Role.name.in_(role_names))
    if group_names:
        conditions.append(Group.name.in_(group_names))
    if not conditions:
        return False
    return or_(*conditions)


def _visible_base_query(
    db: Session,
    *,
    role_names: list[str],
    group_names: list[str],
) -> Query[File]:
    match = _acl_match_filter(role_names, group_names)
    return (
        db.query(File)
        .join(FileAcl, FileAcl.file_id == File.id)
        .outerjoin(Role, FileAcl.role_id == Role.id)
        .outerjoin(Group, FileAcl.group_id == Group.id)
        .filter(FileAcl.permission.in_(VIEW_PERMISSIONS))
        .filter(match)
    )


def user_can_view_file(db: Session, user: CurrentUser, file_id: uuid.UUID) -> bool:
    """True if any viewer|editor grant matches JWT role/group names."""
    row = (
        _visible_base_query(db, role_names=user.roles, group_names=user.groups)
        .filter(File.id == file_id)
        .limit(1)
        .first()
    )
    return row is not None


def list_visible_files(
    db: Session,
    user: CurrentUser,
    *,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[File], int]:
    """Distinct files the caller may view, newest first. Returns (page, total)."""
    match = _acl_match_filter(user.roles, user.groups)
    total = (
        db.query(func.count(func.distinct(File.id)))
        .select_from(File)
        .join(FileAcl, FileAcl.file_id == File.id)
        .outerjoin(Role, FileAcl.role_id == Role.id)
        .outerjoin(Group, FileAcl.group_id == Group.id)
        .filter(FileAcl.permission.in_(VIEW_PERMISSIONS))
        .filter(match)
        .scalar()
    )
    total_i = int(total or 0)
    items = (
        _visible_base_query(db, role_names=user.roles, group_names=user.groups)
        .distinct()
        .order_by(File.uploaded_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return items, total_i


def get_file(db: Session, file_id: uuid.UUID) -> File | None:
    return db.get(File, file_id)
