"""Postgres file_acl mutation + allowed_* name recompute (Task 6b).

Roles and groups only (G3). Never write `_empty` or system principals.
User-principal rows are ignored for OS recompute and rejected on write.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, joinedload

from app.models.file import File, FileAcl
from app.models.identity import Group, Role
from app.services.file_access import display_name_from_path

PrincipalType = Literal["role", "group"]
Permission = Literal["viewer", "editor"]


@dataclass
class GrantSpec:
    principal_type: PrincipalType
    principal_id: uuid.UUID
    permission: Permission = "viewer"


@dataclass
class GrantView:
    id: uuid.UUID
    principal_type: PrincipalType
    principal_id: uuid.UUID
    principal_name: str
    permission: str


@dataclass
class FileInventoryItem:
    id: uuid.UUID
    display_name: str
    file_type: str
    size_bytes: int
    object_store_path: str
    uploaded_at: datetime
    updated_at: datetime


def get_file_or_404(db: Session, file_id: uuid.UUID) -> File:
    row = db.get(File, file_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    return row


def list_all_files(db: Session, *, limit: int, offset: int) -> tuple[list[FileInventoryItem], int]:
    """Admin inventory — all files, not ACL-filtered (C5)."""
    total = db.scalar(select(func.count()).select_from(File)) or 0
    rows = list(
        db.scalars(
            select(File).order_by(File.uploaded_at.desc()).limit(limit).offset(offset)
        ).all()
    )
    items = [
        FileInventoryItem(
            id=row.id,
            display_name=display_name_from_path(row.object_store_path),
            file_type=row.file_type,
            size_bytes=row.size_bytes,
            object_store_path=row.object_store_path,
            uploaded_at=row.uploaded_at,
            updated_at=row.updated_at,
        )
        for row in rows
    ]
    return items, int(total)


def list_grants(db: Session, file_id: uuid.UUID) -> list[GrantView]:
    get_file_or_404(db, file_id)
    rows = list(
        db.scalars(
            select(FileAcl)
            .options(joinedload(FileAcl.role), joinedload(FileAcl.group))
            .where(FileAcl.file_id == file_id)
            .order_by(FileAcl.created_at.asc())
        )
        .unique()
        .all()
    )
    out: list[GrantView] = []
    for row in rows:
        if row.role_id is not None and row.role is not None:
            out.append(
                GrantView(
                    id=row.id,
                    principal_type="role",
                    principal_id=row.role_id,
                    principal_name=row.role.name,
                    permission=row.permission,
                )
            )
        elif row.group_id is not None and row.group is not None:
            out.append(
                GrantView(
                    id=row.id,
                    principal_type="group",
                    principal_id=row.group_id,
                    principal_name=row.group.name,
                    permission=row.permission,
                )
            )
        # user-principal rows ignored in product list (G3)
    return out


def recompute_allowed_names(db: Session, file_id: uuid.UUID) -> tuple[list[str], list[str]]:
    """Full recompute from role/group grants only (C7). Never includes `_empty`."""
    rows = list(
        db.scalars(
            select(FileAcl)
            .options(joinedload(FileAcl.role), joinedload(FileAcl.group))
            .where(FileAcl.file_id == file_id)
        )
        .unique()
        .all()
    )
    roles: set[str] = set()
    groups: set[str] = set()
    for row in rows:
        if row.role_id is not None and row.role is not None:
            roles.add(row.role.name)
        elif row.group_id is not None and row.group is not None:
            if row.group.name == "_empty":
                continue
            groups.add(row.group.name)
    return sorted(roles), sorted(groups)


def _resolve_role(db: Session, role_id: uuid.UUID) -> Role:
    role = db.get(Role, role_id)
    if role is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Role not found")
    if role.is_system:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot grant ACL to system role",
        )
    return role


def _resolve_group(db: Session, group_id: uuid.UUID) -> Group:
    group = db.get(Group, group_id)
    if group is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Group not found")
    if group.is_system or group.name == "_empty":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot grant ACL to system group",
        )
    return group


def _validate_grant(db: Session, grant: GrantSpec) -> None:
    if grant.permission not in ("viewer", "editor"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="permission must be viewer or editor",
        )
    if grant.principal_type == "role":
        _resolve_role(db, grant.principal_id)
    elif grant.principal_type == "group":
        _resolve_group(db, grant.principal_id)
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="principal_type must be role or group",
        )


def _upsert_grant_row(db: Session, file_id: uuid.UUID, grant: GrantSpec) -> FileAcl:
    _validate_grant(db, grant)
    if grant.principal_type == "role":
        existing = db.scalar(
            select(FileAcl).where(FileAcl.file_id == file_id, FileAcl.role_id == grant.principal_id)
        )
        if existing is not None:
            existing.permission = grant.permission
            return existing
        row = FileAcl(
            file_id=file_id,
            role_id=grant.principal_id,
            user_id=None,
            group_id=None,
            permission=grant.permission,
        )
        db.add(row)
        return row

    existing = db.scalar(
        select(FileAcl).where(FileAcl.file_id == file_id, FileAcl.group_id == grant.principal_id)
    )
    if existing is not None:
        existing.permission = grant.permission
        return existing
    row = FileAcl(
        file_id=file_id,
        group_id=grant.principal_id,
        user_id=None,
        role_id=None,
        permission=grant.permission,
    )
    db.add(row)
    return row


def replace_all_grants(db: Session, file_id: uuid.UUID, grants: list[GrantSpec]) -> list[GrantView]:
    """Replace role/group ACL for a file. Empty list clears product grants (C6)."""
    get_file_or_404(db, file_id)
    for grant in grants:
        _validate_grant(db, grant)

    # Delete only role/group product ACL (leave any user-principal connector rows).
    db.execute(
        delete(FileAcl).where(
            FileAcl.file_id == file_id,
            FileAcl.user_id.is_(None),
        )
    )
    db.flush()
    for grant in grants:
        _upsert_grant_row(db, file_id, grant)
    db.flush()
    return list_grants(db, file_id)


def upsert_one_grant(db: Session, file_id: uuid.UUID, grant: GrantSpec) -> list[GrantView]:
    get_file_or_404(db, file_id)
    _upsert_grant_row(db, file_id, grant)
    db.flush()
    return list_grants(db, file_id)


def delete_grant(db: Session, file_id: uuid.UUID, acl_id: uuid.UUID) -> list[GrantView]:
    get_file_or_404(db, file_id)
    row = db.scalar(select(FileAcl).where(FileAcl.id == acl_id, FileAcl.file_id == file_id))
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ACL entry not found")
    if row.user_id is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot revoke user-principal ACL via product admin",
        )
    db.delete(row)
    db.flush()
    return list_grants(db, file_id)
