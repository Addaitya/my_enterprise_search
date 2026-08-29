from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from app.db.session import get_engine
from app.models.file import FileAcl
from app.models.identity import Group, Role, User, UserGroup, UserRole
from init_services.keycloak import (
    GROUPS_EMPTY_SENTINEL,
    REALM_ADMIN_USERNAME,
    SEARCHER_USERNAME,
    _admin_client,
    list_all_groups,
    list_all_realm_roles,
    list_all_users,
    list_user_groups,
    list_user_realm_roles,
)

_SYSTEM_ROLE_NAMES = frozenset({"offline_access", "uma_authorization"})
_SYSTEM_ROLE_PREFIX = "default-roles-"


def sync() -> None:
    """One-way Keycloak → Postgres identity mirror. Does not create tables."""
    engine = get_engine()
    with Session(engine) as session:
        try:
            _sync(session)
            session.commit()
        except ProgrammingError as exc:
            session.rollback()
            if _is_undefined_table(exc):
                print(
                    "[error] identity tables missing; "
                    "run `cd backend && uv run alembic upgrade head` first"
                )
                raise SystemExit(1) from exc
            raise
        except Exception:
            session.rollback()
            raise


def _sync(session: Session) -> None:
    admin = _admin_client()
    with admin:
        kc_roles = list_all_realm_roles(admin)
        kc_groups = list_all_groups(admin)
        kc_users = list_all_users(admin)
        user_memberships: dict[str, tuple[list[dict[str, Any]], list[dict[str, Any]]]] = {}
        for user in kc_users:
            user_id = user["id"]
            user_memberships[user_id] = (
                list_user_realm_roles(admin, user_id),
                list_user_groups(admin, user_id),
            )

    _upsert_roles(session, kc_roles)
    _upsert_groups(session, kc_groups)
    _upsert_users(session, kc_users)
    session.flush()
    for user in kc_users:
        roles, groups = user_memberships[user["id"]]
        _replace_memberships(session, uuid.UUID(user["id"]), roles, groups)
    _warn_stale_users(session, {uuid.UUID(user["id"]) for user in kc_users})
    _delete_stale_roles(session, {uuid.UUID(role["id"]) for role in kc_roles})
    _delete_stale_groups(session, {uuid.UUID(group["id"]) for group in kc_groups})
    session.flush()
    _print_counts(session)


def _upsert_roles(session: Session, kc_roles: list[dict[str, Any]]) -> None:
    now = _now()
    for payload in kc_roles:
        role_id = uuid.UUID(payload["id"])
        name = payload["name"]
        role = session.get(Role, role_id)
        is_system = _role_is_system(name)
        description = payload.get("description") or None
        if role is None:
            session.add(
                Role(
                    id=role_id,
                    name=name,
                    description=description,
                    is_system=is_system,
                    created_at=now,
                    updated_at=now,
                )
            )
        else:
            role.name = name
            role.description = description
            role.is_system = is_system
            role.updated_at = now


def _upsert_groups(session: Session, kc_groups: list[dict[str, Any]]) -> None:
    now = _now()
    for payload in kc_groups:
        group_id = uuid.UUID(payload["id"])
        name = payload["name"]
        group = session.get(Group, group_id)
        is_system = name == GROUPS_EMPTY_SENTINEL
        path = payload.get("path") or None
        if group is None:
            session.add(
                Group(
                    id=group_id,
                    name=name,
                    path=path,
                    is_system=is_system,
                    created_at=now,
                    updated_at=now,
                )
            )
        else:
            group.name = name
            group.path = path
            group.is_system = is_system
            group.updated_at = now


def _upsert_users(session: Session, kc_users: list[dict[str, Any]]) -> None:
    now = _now()
    for payload in kc_users:
        user_id = uuid.UUID(payload["id"])
        username = payload["username"]
        email = payload.get("email") or None
        enabled = bool(payload.get("enabled", True))
        created_at = _created_at(payload, now)
        user = session.get(User, user_id)
        if user is None:
            session.add(
                User(
                    id=user_id,
                    username=username,
                    email=email,
                    enabled=enabled,
                    created_at=created_at,
                    updated_at=now,
                )
            )
        else:
            user.username = username
            user.email = email
            user.enabled = enabled
            user.updated_at = now


def _replace_memberships(
    session: Session,
    user_id: uuid.UUID,
    kc_roles: list[dict[str, Any]],
    kc_groups: list[dict[str, Any]],
) -> None:
    wanted_roles = {uuid.UUID(role["id"]) for role in kc_roles if role.get("id")}
    current_roles = set(
        session.scalars(select(UserRole.role_id).where(UserRole.user_id == user_id))
    )
    for role_id in current_roles - wanted_roles:
        link = session.get(UserRole, (user_id, role_id))
        if link is not None:
            session.delete(link)
    for role_id in wanted_roles - current_roles:
        session.add(UserRole(user_id=user_id, role_id=role_id))

    wanted_groups = {uuid.UUID(group["id"]) for group in kc_groups if group.get("id")}
    current_groups = set(
        session.scalars(select(UserGroup.group_id).where(UserGroup.user_id == user_id))
    )
    for group_id in current_groups - wanted_groups:
        link = session.get(UserGroup, (user_id, group_id))
        if link is not None:
            session.delete(link)
    for group_id in wanted_groups - current_groups:
        session.add(UserGroup(user_id=user_id, group_id=group_id))


def _warn_stale_users(session: Session, kc_user_ids: set[uuid.UUID]) -> None:
    for user in session.scalars(select(User)).all():
        if user.id not in kc_user_ids:
            print(
                f"[warn] postgres user {user.username} id={user.id} "
                "missing in keycloak; not deleting"
            )


def _delete_stale_roles(session: Session, kc_role_ids: set[uuid.UUID]) -> None:
    for role in session.scalars(select(Role)).all():
        if role.id in kc_role_ids:
            continue
        blocked = session.scalar(select(FileAcl.id).where(FileAcl.role_id == role.id).limit(1))
        if blocked is not None:
            print(
                f"[warn] skip delete role {role.name} id={role.id}: file_acl still references it"
            )
            continue
        session.delete(role)
        print(f"[ok] removed mirrored role {role.name} (gone from keycloak)")


def _delete_stale_groups(session: Session, kc_group_ids: set[uuid.UUID]) -> None:
    for group in session.scalars(select(Group)).all():
        if group.id in kc_group_ids:
            continue
        blocked = session.scalar(select(FileAcl.id).where(FileAcl.group_id == group.id).limit(1))
        if blocked is not None:
            print(
                f"[warn] skip delete group {group.name} id={group.id}: file_acl still references it"
            )
            continue
        session.delete(group)
        print(f"[ok] removed mirrored group {group.name} (gone from keycloak)")


def _print_counts(session: Session) -> None:
    users = session.scalars(select(User)).all()
    roles = session.scalars(select(Role)).all()
    groups = session.scalars(select(Group)).all()
    print(
        f"[ok] identity mirror users={len(users)} roles={len(roles)} groups={len(groups)}"
    )
    by_username = {user.username: user for user in users}
    for username in (REALM_ADMIN_USERNAME, SEARCHER_USERNAME):
        user = by_username.get(username)
        if user is None:
            print(f"[warn] seed user {username} missing from mirror")
            continue
        role_names = sorted(
            session.scalars(
                select(Role.name)
                .join(UserRole, UserRole.role_id == Role.id)
                .where(UserRole.user_id == user.id)
            ).all()
        )
        group_names = sorted(
            session.scalars(
                select(Group.name)
                .join(UserGroup, UserGroup.group_id == Group.id)
                .where(UserGroup.user_id == user.id)
            ).all()
        )
        print(
            f"[ok] seed user {username} id={user.id} "
            f"roles={role_names} groups={group_names}"
        )


def _role_is_system(name: str) -> bool:
    return name in _SYSTEM_ROLE_NAMES or name.startswith(_SYSTEM_ROLE_PREFIX)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _created_at(payload: dict[str, Any], fallback: datetime) -> datetime:
    timestamp = payload.get("createdTimestamp")
    if isinstance(timestamp, (int, float)):
        return datetime.fromtimestamp(timestamp / 1000, tz=timezone.utc)
    return fallback


def _is_undefined_table(exc: ProgrammingError) -> bool:
    orig = getattr(exc, "orig", None)
    if orig is None:
        return False
    if orig.__class__.__name__ == "UndefinedTable":
        return True
    pgcode = getattr(orig, "pgcode", None)
    return pgcode == "42P01"
