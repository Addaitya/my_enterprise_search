"""Postgres file_acl mutation + allowed_* name recompute (Task 6b / 12a).

Roles and groups only (G3). Never write `_empty` or system principals.
User-principal rows are ignored for OS recompute and rejected on write.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from fastapi import HTTPException, status
from sqlalchemy import and_, delete, exists, func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.models.file import File, FileAcl
from app.models.identity import Group, Role
from app.services.file_access import display_name_from_path

PrincipalType = Literal["role", "group"]
Permission = Literal["viewer", "editor"]
BulkMode = Literal["upsert", "replace", "revoke"]

BULK_MAX_FILES = 100


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
class AccessPreviewGrant:
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
    access_total: int = 0
    access_preview: list[AccessPreviewGrant] = field(default_factory=list)


@dataclass
class FileGrantItem:
    acl_id: uuid.UUID
    file_id: uuid.UUID
    display_name: str
    file_type: str
    permission: str
    updated_at: datetime


@dataclass
class BulkResultItem:
    file_id: uuid.UUID
    grants: list[GrantView]
    acl_job_id: uuid.UUID | None


@dataclass
class BulkFailedItem:
    file_id: uuid.UUID
    error: str


def get_file_or_404(db: Session, file_id: uuid.UUID) -> File:
    row = db.get(File, file_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    return row


def list_all_files(
    db: Session,
    *,
    limit: int,
    offset: int,
    q: str | None = None,
    has_acl: bool | None = None,
) -> tuple[list[FileInventoryItem], int]:
    """Admin inventory with optional name filter and has_acl (C-FA4)."""
    filters = []
    q_norm = (q or "").strip()
    if q_norm:
        pattern = f"%{q_norm}%"
        filters.append(File.object_store_path.ilike(pattern))

    product_acl = and_(
        FileAcl.file_id == File.id,
        FileAcl.user_id.is_(None),
        or_(FileAcl.role_id.is_not(None), FileAcl.group_id.is_not(None)),
    )
    if has_acl is True:
        filters.append(exists(select(FileAcl.id).where(product_acl)))
    elif has_acl is False:
        filters.append(~exists(select(FileAcl.id).where(product_acl)))

    count_stmt = select(func.count()).select_from(File)
    if filters:
        count_stmt = count_stmt.where(*filters)
    total = db.scalar(count_stmt) or 0

    stmt = select(File).order_by(File.uploaded_at.desc()).limit(limit).offset(offset)
    if filters:
        stmt = stmt.where(*filters)
    rows = list(db.scalars(stmt).all())

    file_ids = [row.id for row in rows]
    preview_by_file = _access_previews_for_files(db, file_ids)

    items = [
        FileInventoryItem(
            id=row.id,
            display_name=display_name_from_path(row.object_store_path),
            file_type=row.file_type,
            size_bytes=row.size_bytes,
            object_store_path=row.object_store_path,
            uploaded_at=row.uploaded_at,
            updated_at=row.updated_at,
            access_total=preview_by_file.get(row.id, (0, []))[0],
            access_preview=preview_by_file.get(row.id, (0, []))[1],
        )
        for row in rows
    ]
    return items, int(total)


def _access_previews_for_files(
    db: Session, file_ids: list[uuid.UUID]
) -> dict[uuid.UUID, tuple[int, list[AccessPreviewGrant]]]:
    if not file_ids:
        return {}
    rows = list(
        db.scalars(
            select(FileAcl)
            .options(joinedload(FileAcl.role), joinedload(FileAcl.group))
            .where(FileAcl.file_id.in_(file_ids), FileAcl.user_id.is_(None))
            .order_by(FileAcl.created_at.asc())
        )
        .unique()
        .all()
    )
    grouped: dict[uuid.UUID, list[AccessPreviewGrant]] = {fid: [] for fid in file_ids}
    for row in rows:
        if row.role_id is not None and row.role is not None:
            grouped[row.file_id].append(
                AccessPreviewGrant(
                    principal_type="role",
                    principal_id=row.role_id,
                    principal_name=row.role.name,
                    permission=row.permission,
                )
            )
        elif row.group_id is not None and row.group is not None:
            grouped[row.file_id].append(
                AccessPreviewGrant(
                    principal_type="group",
                    principal_id=row.group_id,
                    principal_name=row.group.name,
                    permission=row.permission,
                )
            )
    return {fid: (len(grants), grants[:2]) for fid, grants in grouped.items()}


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


def delete_grants_for_principals(
    db: Session, file_id: uuid.UUID, principals: list[GrantSpec]
) -> list[GrantView]:
    """Remove grants matching principal type+id; permission ignored. Missing = no-op."""
    get_file_or_404(db, file_id)
    for principal in principals:
        if principal.principal_type == "role":
            row = db.scalar(
                select(FileAcl).where(
                    FileAcl.file_id == file_id, FileAcl.role_id == principal.principal_id
                )
            )
        else:
            row = db.scalar(
                select(FileAcl).where(
                    FileAcl.file_id == file_id, FileAcl.group_id == principal.principal_id
                )
            )
        if row is not None and row.user_id is None:
            db.delete(row)
    db.flush()
    return list_grants(db, file_id)


def upsert_grants(db: Session, file_id: uuid.UUID, grants: list[GrantSpec]) -> list[GrantView]:
    get_file_or_404(db, file_id)
    for grant in grants:
        _upsert_grant_row(db, file_id, grant)
    db.flush()
    return list_grants(db, file_id)


def validate_bulk_request(
    db: Session,
    *,
    file_ids: list[uuid.UUID],
    mode: BulkMode,
    grants: list[GrantSpec],
    confirm_replace: bool,
) -> list[uuid.UUID]:
    """Validate whole request before mutating. Returns deduped file_ids. Raises HTTPException."""
    if not file_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="file_ids must not be empty",
        )
    if len(file_ids) > BULK_MAX_FILES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"At most {BULK_MAX_FILES} file_ids per bulk request",
        )

    seen: set[uuid.UUID] = set()
    deduped: list[uuid.UUID] = []
    for fid in file_ids:
        if fid not in seen:
            seen.add(fid)
            deduped.append(fid)

    if mode == "upsert":
        if not grants:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="grants required and must be non-empty for upsert",
            )
        for grant in grants:
            _validate_grant(db, grant)
    elif mode == "replace":
        if not confirm_replace:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="confirm_replace must be true for replace mode",
            )
        for grant in grants:
            _validate_grant(db, grant)
    elif mode == "revoke":
        if not grants:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="grants required and must be non-empty for revoke",
            )
        for grant in grants:
            # Validate principal exists and is not system/_empty (same as grant rules).
            if grant.principal_type == "role":
                _resolve_role(db, grant.principal_id)
            elif grant.principal_type == "group":
                _resolve_group(db, grant.principal_id)
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="principal_type must be role or group",
                )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="mode must be upsert, replace, or revoke",
        )

    return deduped


def apply_bulk_to_file(
    db: Session,
    *,
    file_id: uuid.UUID,
    mode: BulkMode,
    grants: list[GrantSpec],
) -> list[GrantView]:
    """Mutate one file in the current transaction (caller commits). Raises if file missing."""
    if mode == "upsert":
        return upsert_grants(db, file_id, grants)
    if mode == "replace":
        return replace_all_grants(db, file_id, grants)
    return delete_grants_for_principals(db, file_id, grants)


def list_grants_for_role(
    db: Session, role_id: uuid.UUID, *, limit: int, offset: int
) -> tuple[list[FileGrantItem], int]:
    role = db.get(Role, role_id)
    if role is None or role.is_system:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")

    base = (
        select(FileAcl)
        .join(File, File.id == FileAcl.file_id)
        .where(FileAcl.role_id == role_id)
    )
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = list(
        db.scalars(
            base.options(joinedload(FileAcl.file))
            .order_by(FileAcl.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        .unique()
        .all()
    )
    items = [
        FileGrantItem(
            acl_id=row.id,
            file_id=row.file_id,
            display_name=display_name_from_path(row.file.object_store_path),
            file_type=row.file.file_type,
            permission=row.permission,
            updated_at=row.created_at,
        )
        for row in rows
        if row.file is not None
    ]
    return items, int(total)


def list_grants_for_group(
    db: Session, group_id: uuid.UUID, *, limit: int, offset: int
) -> tuple[list[FileGrantItem], int]:
    group = db.get(Group, group_id)
    if group is None or group.is_system or group.name == "_empty":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")

    base = (
        select(FileAcl)
        .join(File, File.id == FileAcl.file_id)
        .where(FileAcl.group_id == group_id)
    )
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = list(
        db.scalars(
            base.options(joinedload(FileAcl.file))
            .order_by(FileAcl.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        .unique()
        .all()
    )
    items = [
        FileGrantItem(
            acl_id=row.id,
            file_id=row.file_id,
            display_name=display_name_from_path(row.file.object_store_path),
            file_type=row.file.file_type,
            permission=row.permission,
            updated_at=row.created_at,
        )
        for row in rows
        if row.file is not None
    ]
    return items, int(total)
