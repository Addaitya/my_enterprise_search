"""Orchestrate Keycloak-first identity writes with Postgres mirror upsert."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.models.file import FileAcl
from app.models.identity import Group, Role, User, UserGroup, UserRole
from app.schemas.admin_identity import (
    GroupCreate,
    GroupOut,
    MEMBERS_MAX_USERS,
    MembersFailed,
    MembersMutationResponse,
    RoleCreate,
    RoleOut,
    UserCreate,
    UserOut,
    UserUpdate,
)
from app.services.keycloak_admin import (
    GROUPS_EMPTY_SENTINEL,
    KeycloakAdmin,
    KeycloakAdminError,
    is_reserved_name,
    is_system_role_name,
)

logger = logging.getLogger(__name__)

ORPHAN_HINT = "orphan in Keycloak — re-run identity mirror"


class IdentityAdminService:
    def __init__(self, db: Session, kc: KeycloakAdmin | None = None) -> None:
        self.db = db
        self.kc = kc or KeycloakAdmin()

    # --- Users ---

    def list_users(
        self, *, limit: int, offset: int, q: str | None
    ) -> tuple[list[UserOut], int]:
        stmt = select(User).options(
            selectinload(User.role_links).selectinload(UserRole.role),
            selectinload(User.group_links).selectinload(UserGroup.group),
        )
        count_stmt = select(func.count()).select_from(User)
        if q:
            pattern = f"%{q.strip()}%"
            filt = or_(User.username.ilike(pattern), User.email.ilike(pattern))
            stmt = stmt.where(filt)
            count_stmt = count_stmt.where(filt)
        total = int(self.db.scalar(count_stmt) or 0)
        rows = self.db.scalars(stmt.order_by(User.username).offset(offset).limit(limit)).all()
        return [self._user_out(row) for row in rows], total

    def get_user(self, user_id: uuid.UUID) -> UserOut:
        user = self._load_user(user_id)
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        return self._user_out(user)

    def create_user(self, body: UserCreate) -> UserOut:
        self._assert_roles_exist(body.role_names)
        self._assert_groups_exist(body.group_names)
        if self.kc.find_user_by_username(body.username):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists")
        existing = self.db.scalar(select(User).where(User.username == body.username))
        if existing is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists")

        try:
            user_id = self.kc.create_user(
                username=body.username,
                email=body.email,
                enabled=body.enabled,
            )
            self.kc.set_password(user_id, body.password)
            self.kc.replace_user_realm_roles(user_id, body.role_names)
            self.kc.replace_user_groups(user_id, body.group_names)
        except KeycloakAdminError as exc:
            raise self._http_from_kc(exc) from exc

        try:
            now = _now()
            user = User(
                id=uuid.UUID(user_id),
                username=body.username,
                email=body.email,
                enabled=body.enabled,
                created_at=now,
                updated_at=now,
            )
            self.db.add(user)
            self.db.flush()
            self._replace_pg_memberships(user.id, body.role_names, body.group_names)
            self.db.commit()
        except Exception as exc:  # noqa: BLE001
            self.db.rollback()
            logger.exception("Postgres mirror failed after Keycloak user create id=%s", user_id)
            try:
                self.kc.delete_user(user_id)
            except KeycloakAdminError:
                logger.exception(
                    "Compensate delete failed for Keycloak user %s — %s", user_id, ORPHAN_HINT
                )
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=f"Postgres mirror failed; {ORPHAN_HINT} (user_id={user_id})",
                ) from exc
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Postgres mirror failed after Keycloak create; Keycloak user rolled back",
            ) from exc

        return self.get_user(uuid.UUID(user_id))

    def update_user(self, user_id: uuid.UUID, body: UserUpdate) -> UserOut:
        user = self._load_user(user_id)
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        if body.role_names is not None:
            self._assert_roles_exist(body.role_names)
        if body.group_names is not None:
            self._assert_groups_exist(body.group_names)

        try:
            if body.email is not None or body.enabled is not None:
                self.kc.update_user(
                    str(user_id),
                    email=body.email if body.email is not None else user.email,
                    enabled=body.enabled if body.enabled is not None else user.enabled,
                )
            if body.password is not None:
                self.kc.set_password(str(user_id), body.password)
            if body.role_names is not None:
                self.kc.replace_user_realm_roles(str(user_id), body.role_names)
            if body.group_names is not None:
                self.kc.replace_user_groups(str(user_id), body.group_names)
        except KeycloakAdminError as exc:
            raise self._http_from_kc(exc) from exc

        try:
            if body.email is not None:
                user.email = body.email
            if body.enabled is not None:
                user.enabled = body.enabled
            user.updated_at = _now()
            if body.role_names is not None or body.group_names is not None:
                role_names = (
                    body.role_names
                    if body.role_names is not None
                    else [link.role.name for link in user.role_links]
                )
                group_names = (
                    body.group_names
                    if body.group_names is not None
                    else [
                        link.group.name
                        for link in user.group_links
                        if link.group.name != GROUPS_EMPTY_SENTINEL
                    ]
                )
                self._replace_pg_memberships(user.id, role_names, group_names)
            self.db.commit()
        except Exception as exc:  # noqa: BLE001
            self.db.rollback()
            logger.exception("Postgres mirror failed after Keycloak user update id=%s", user_id)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Postgres mirror failed; {ORPHAN_HINT} (user_id={user_id})",
            ) from exc

        return self.get_user(user_id)

    # --- Roles ---

    def list_roles(self, *, include_system: bool) -> tuple[list[RoleOut], int]:
        stmt = select(Role)
        if not include_system:
            stmt = stmt.where(Role.is_system.is_(False))
        rows = self.db.scalars(stmt.order_by(Role.name)).all()
        items = [self._role_out(row) for row in rows]
        return items, len(items)

    def get_role(self, role_id: uuid.UUID) -> RoleOut:
        role = self.db.get(Role, role_id)
        if role is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")
        return self._role_out(role)

    def create_role(self, body: RoleCreate) -> RoleOut:
        if is_reserved_name(body.name) or is_system_role_name(body.name):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Reserved or system role name",
            )
        if self.db.scalar(select(Role).where(Role.name == body.name)) is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Role name already exists")

        try:
            kc_role = self.kc.create_realm_role(name=body.name, description=body.description)
        except KeycloakAdminError as exc:
            raise self._http_from_kc(exc) from exc

        role_id = uuid.UUID(kc_role["id"])
        try:
            now = _now()
            role = Role(
                id=role_id,
                name=body.name,
                description=body.description,
                is_system=False,
                created_at=now,
                updated_at=now,
            )
            self.db.add(role)
            self.db.commit()
        except Exception as exc:  # noqa: BLE001
            self.db.rollback()
            logger.exception("Postgres mirror failed after Keycloak role create id=%s", role_id)
            try:
                self.kc.delete_realm_role(body.name)
            except KeycloakAdminError:
                logger.exception("Compensate delete failed for Keycloak role %s", body.name)
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=f"Postgres mirror failed; {ORPHAN_HINT} (role={body.name})",
                ) from exc
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Postgres mirror failed after Keycloak create; Keycloak role rolled back",
            ) from exc

        return self.get_role(role_id)

    def update_role(self, role_id: uuid.UUID, *, description: str | None) -> RoleOut:
        role = self.db.get(Role, role_id)
        if role is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")
        if role.is_system:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot mutate system role",
            )
        try:
            self.kc.update_realm_role_description(role.name, description)
        except KeycloakAdminError as exc:
            raise self._http_from_kc(exc) from exc

        try:
            role.description = description
            role.updated_at = _now()
            self.db.commit()
        except Exception as exc:  # noqa: BLE001
            self.db.rollback()
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Postgres mirror failed; {ORPHAN_HINT} (role_id={role_id})",
            ) from exc
        return self.get_role(role_id)

    def delete_role(self, role_id: uuid.UUID) -> None:
        role = self.db.get(Role, role_id)
        if role is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")
        if role.is_system:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot delete system role",
            )
        acl_count = self.db.scalar(
            select(func.count()).select_from(FileAcl).where(FileAcl.role_id == role_id)
        )
        if acl_count:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Role is referenced by file_acl",
            )
        name = role.name
        try:
            self.kc.delete_realm_role(name)
        except KeycloakAdminError as exc:
            raise self._http_from_kc(exc) from exc

        try:
            self.db.delete(role)
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Role is referenced by file_acl",
            ) from exc
        except Exception as exc:  # noqa: BLE001
            self.db.rollback()
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Postgres delete failed; {ORPHAN_HINT} (role={name})",
            ) from exc

    # --- Groups ---

    def list_groups(self, *, include_system: bool) -> tuple[list[GroupOut], int]:
        stmt = select(Group)
        if not include_system:
            stmt = stmt.where(Group.is_system.is_(False))
        rows = self.db.scalars(stmt.order_by(Group.name)).all()
        items = [self._group_out(row) for row in rows]
        return items, len(items)

    def get_group(self, group_id: uuid.UUID) -> GroupOut:
        group = self.db.get(Group, group_id)
        if group is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")
        return self._group_out(group)

    def create_group(self, body: GroupCreate) -> GroupOut:
        if is_reserved_name(body.name) or body.name == GROUPS_EMPTY_SENTINEL:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Reserved or system group name",
            )
        if self.db.scalar(select(Group).where(Group.name == body.name)) is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Group name already exists")

        try:
            kc_group = self.kc.create_group(name=body.name)
        except KeycloakAdminError as exc:
            raise self._http_from_kc(exc) from exc

        group_id = uuid.UUID(kc_group["id"])
        try:
            now = _now()
            group = Group(
                id=group_id,
                name=body.name,
                path=kc_group.get("path") or f"/{body.name}",
                is_system=False,
                created_at=now,
                updated_at=now,
            )
            self.db.add(group)
            self.db.commit()
        except Exception as exc:  # noqa: BLE001
            self.db.rollback()
            logger.exception("Postgres mirror failed after Keycloak group create id=%s", group_id)
            try:
                self.kc.delete_group(str(group_id))
            except KeycloakAdminError:
                logger.exception("Compensate delete failed for Keycloak group %s", group_id)
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=f"Postgres mirror failed; {ORPHAN_HINT} (group_id={group_id})",
                ) from exc
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Postgres mirror failed after Keycloak create; Keycloak group rolled back",
            ) from exc

        return self.get_group(group_id)

    def delete_group(self, group_id: uuid.UUID) -> None:
        group = self.db.get(Group, group_id)
        if group is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")
        if group.is_system or group.name == GROUPS_EMPTY_SENTINEL:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot delete system group",
            )
        acl_count = self.db.scalar(
            select(func.count()).select_from(FileAcl).where(FileAcl.group_id == group_id)
        )
        if acl_count:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Group is referenced by file_acl",
            )
        name = group.name
        try:
            self.kc.delete_group(str(group_id))
        except KeycloakAdminError as exc:
            raise self._http_from_kc(exc) from exc

        try:
            self.db.delete(group)
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Group is referenced by file_acl",
            ) from exc
        except Exception as exc:  # noqa: BLE001
            self.db.rollback()
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Postgres delete failed; {ORPHAN_HINT} (group={name})",
            ) from exc

    # --- Members (12b) ---

    def list_role_members(
        self,
        role_id: uuid.UUID,
        *,
        limit: int,
        offset: int,
        q: str | None,
    ) -> tuple[list[UserOut], int]:
        role = self.db.get(Role, role_id)
        if role is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")
        return self._list_members_for_link(
            UserRole,
            UserRole.role_id == role_id,
            limit=limit,
            offset=offset,
            q=q,
        )

    def list_group_members(
        self,
        group_id: uuid.UUID,
        *,
        limit: int,
        offset: int,
        q: str | None,
    ) -> tuple[list[UserOut], int]:
        group = self.db.get(Group, group_id)
        if group is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")
        if group.name == GROUPS_EMPTY_SENTINEL or group.is_system:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot manage members of system group",
            )
        return self._list_members_for_link(
            UserGroup,
            UserGroup.group_id == group_id,
            limit=limit,
            offset=offset,
            q=q,
        )

    def add_users_to_role(
        self, role_id: uuid.UUID, user_ids: list[uuid.UUID]
    ) -> MembersMutationResponse:
        role = self.db.get(Role, role_id)
        if role is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")
        ids = self._normalize_user_ids(user_ids)
        results: list[UserOut] = []
        failed: list[MembersFailed] = []
        for uid in ids:
            try:
                results.append(self._add_user_role(uid, role))
            except Exception as exc:  # noqa: BLE001
                failed.append(MembersFailed(user_id=uid, error=self._member_error(exc)))
        return MembersMutationResponse(results=results, failed=failed)

    def remove_users_from_role(
        self, role_id: uuid.UUID, user_ids: list[uuid.UUID]
    ) -> MembersMutationResponse:
        role = self.db.get(Role, role_id)
        if role is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")
        ids = self._normalize_user_ids(user_ids)
        results: list[UserOut] = []
        failed: list[MembersFailed] = []
        for uid in ids:
            try:
                results.append(self._remove_user_role(uid, role))
            except Exception as exc:  # noqa: BLE001
                failed.append(MembersFailed(user_id=uid, error=self._member_error(exc)))
        return MembersMutationResponse(results=results, failed=failed)

    def add_users_to_group(
        self, group_id: uuid.UUID, user_ids: list[uuid.UUID]
    ) -> MembersMutationResponse:
        group = self._require_manageable_group(group_id)
        ids = self._normalize_user_ids(user_ids)
        results: list[UserOut] = []
        failed: list[MembersFailed] = []
        for uid in ids:
            try:
                results.append(self._add_user_group(uid, group))
            except Exception as exc:  # noqa: BLE001
                failed.append(MembersFailed(user_id=uid, error=self._member_error(exc)))
        return MembersMutationResponse(results=results, failed=failed)

    def remove_users_from_group(
        self, group_id: uuid.UUID, user_ids: list[uuid.UUID]
    ) -> MembersMutationResponse:
        group = self._require_manageable_group(group_id)
        ids = self._normalize_user_ids(user_ids)
        results: list[UserOut] = []
        failed: list[MembersFailed] = []
        for uid in ids:
            try:
                results.append(self._remove_user_group(uid, group))
            except Exception as exc:  # noqa: BLE001
                failed.append(MembersFailed(user_id=uid, error=self._member_error(exc)))
        return MembersMutationResponse(results=results, failed=failed)

    # --- helpers ---

    def _require_manageable_group(self, group_id: uuid.UUID) -> Group:
        group = self.db.get(Group, group_id)
        if group is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")
        if group.name == GROUPS_EMPTY_SENTINEL or group.is_system:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot manage members of system group",
            )
        return group

    @staticmethod
    def _normalize_user_ids(user_ids: list[uuid.UUID]) -> list[uuid.UUID]:
        if not user_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="user_ids cannot be empty",
            )
        # Preserve order while deduping.
        seen: set[uuid.UUID] = set()
        unique: list[uuid.UUID] = []
        for uid in user_ids:
            if uid in seen:
                continue
            seen.add(uid)
            unique.append(uid)
        if len(unique) > MEMBERS_MAX_USERS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"user_ids exceeds max of {MEMBERS_MAX_USERS}",
            )
        return unique

    def _list_members_for_link(
        self,
        join_model: type[UserRole] | type[UserGroup],
        link_filter,
        *,
        limit: int,
        offset: int,
        q: str | None,
    ) -> tuple[list[UserOut], int]:
        base = (
            select(User)
            .join(join_model, join_model.user_id == User.id)
            .where(link_filter)
            .options(
                selectinload(User.role_links).selectinload(UserRole.role),
                selectinload(User.group_links).selectinload(UserGroup.group),
            )
        )
        count_base = (
            select(func.count())
            .select_from(User)
            .join(join_model, join_model.user_id == User.id)
            .where(link_filter)
        )
        if q:
            pattern = f"%{q.strip()}%"
            filt = or_(User.username.ilike(pattern), User.email.ilike(pattern))
            base = base.where(filt)
            count_base = count_base.where(filt)
        total = int(self.db.scalar(count_base) or 0)
        rows = self.db.scalars(base.order_by(User.username).offset(offset).limit(limit)).all()
        return [self._user_out(row) for row in rows], total

    def _add_user_role(self, user_id: uuid.UUID, role: Role) -> UserOut:
        user = self._load_user(user_id)
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        already = any(link.role_id == role.id for link in user.role_links)
        if already:
            return self._user_out(user)
        try:
            self.kc.add_user_realm_role(str(user_id), role.name)
        except KeycloakAdminError as exc:
            raise self._http_from_kc(exc) from exc
        try:
            self.db.add(UserRole(user_id=user_id, role_id=role.id))
            user.updated_at = _now()
            self.db.commit()
        except Exception as exc:  # noqa: BLE001
            self.db.rollback()
            logger.exception(
                "Postgres mirror failed after Keycloak add role user=%s role=%s",
                user_id,
                role.name,
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Postgres mirror failed; {ORPHAN_HINT} (user_id={user_id})",
            ) from exc
        return self.get_user(user_id)

    def _remove_user_role(self, user_id: uuid.UUID, role: Role) -> UserOut:
        user = self._load_user(user_id)
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        has_link = any(link.role_id == role.id for link in user.role_links)
        if not has_link:
            return self._user_out(user)

        remaining = {
            link.role.name
            for link in user.role_links
            if link.role and link.role_id != role.id and not is_system_role_name(link.role.name)
        }
        # MA4: after remove, user must still have search-user and/or admin.
        if not any(name in {"search-user", "admin"} for name in remaining):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot remove last search-user/admin role",
            )

        try:
            self.kc.remove_user_realm_role(str(user_id), role.name)
        except KeycloakAdminError as exc:
            raise self._http_from_kc(exc) from exc
        try:
            self.db.execute(
                delete(UserRole).where(
                    UserRole.user_id == user_id,
                    UserRole.role_id == role.id,
                )
            )
            user.updated_at = _now()
            self.db.commit()
        except Exception as exc:  # noqa: BLE001
            self.db.rollback()
            logger.exception(
                "Postgres mirror failed after Keycloak remove role user=%s role=%s",
                user_id,
                role.name,
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Postgres mirror failed; {ORPHAN_HINT} (user_id={user_id})",
            ) from exc
        return self.get_user(user_id)

    def _add_user_group(self, user_id: uuid.UUID, group: Group) -> UserOut:
        user = self._load_user(user_id)
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        already = any(link.group_id == group.id for link in user.group_links)
        if already:
            return self._user_out(user)
        try:
            self.kc.join_user_group(str(user_id), group.name)
        except KeycloakAdminError as exc:
            raise self._http_from_kc(exc) from exc
        try:
            empty = self.db.scalar(select(Group).where(Group.name == GROUPS_EMPTY_SENTINEL))
            if empty is not None:
                self.db.execute(
                    delete(UserGroup).where(
                        UserGroup.user_id == user_id,
                        UserGroup.group_id == empty.id,
                    )
                )
            self.db.add(UserGroup(user_id=user_id, group_id=group.id))
            user.updated_at = _now()
            self.db.commit()
        except Exception as exc:  # noqa: BLE001
            self.db.rollback()
            logger.exception(
                "Postgres mirror failed after Keycloak join group user=%s group=%s",
                user_id,
                group.name,
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Postgres mirror failed; {ORPHAN_HINT} (user_id={user_id})",
            ) from exc
        return self.get_user(user_id)

    def _remove_user_group(self, user_id: uuid.UUID, group: Group) -> UserOut:
        user = self._load_user(user_id)
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        has_link = any(link.group_id == group.id for link in user.group_links)
        if not has_link:
            return self._user_out(user)

        try:
            self.kc.leave_user_group(str(user_id), group.name)
        except KeycloakAdminError as exc:
            raise self._http_from_kc(exc) from exc
        try:
            self.db.execute(
                delete(UserGroup).where(
                    UserGroup.user_id == user_id,
                    UserGroup.group_id == group.id,
                )
            )
            remaining_product = [
                link
                for link in user.group_links
                if link.group_id != group.id
                and link.group
                and link.group.name != GROUPS_EMPTY_SENTINEL
            ]
            if not remaining_product:
                empty = self.db.scalar(select(Group).where(Group.name == GROUPS_EMPTY_SENTINEL))
                if empty is not None:
                    already_empty = any(link.group_id == empty.id for link in user.group_links)
                    if not already_empty:
                        self.db.add(UserGroup(user_id=user_id, group_id=empty.id))
            user.updated_at = _now()
            self.db.commit()
        except Exception as exc:  # noqa: BLE001
            self.db.rollback()
            logger.exception(
                "Postgres mirror failed after Keycloak leave group user=%s group=%s",
                user_id,
                group.name,
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Postgres mirror failed; {ORPHAN_HINT} (user_id={user_id})",
            ) from exc
        return self.get_user(user_id)

    @staticmethod
    def _member_error(exc: Exception) -> str:
        if isinstance(exc, HTTPException):
            detail = exc.detail
            if isinstance(detail, str):
                return detail
            return str(detail)
        return str(exc)

    def _load_user(self, user_id: uuid.UUID) -> User | None:
        return self.db.scalars(
            select(User)
            .where(User.id == user_id)
            .options(
                selectinload(User.role_links).selectinload(UserRole.role),
                selectinload(User.group_links).selectinload(UserGroup.group),
            )
        ).first()

    def _assert_roles_exist(self, role_names: list[str]) -> None:
        for name in role_names:
            if is_system_role_name(name):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Cannot assign system role {name}",
                )
            role = self.db.scalar(select(Role).where(Role.name == name))
            if role is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Unknown role {name}",
                )

    def _assert_groups_exist(self, group_names: list[str]) -> None:
        for name in group_names:
            if name == GROUPS_EMPTY_SENTINEL:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot assign group _empty via API",
                )
            group = self.db.scalar(select(Group).where(Group.name == name))
            if group is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Unknown group {name}",
                )

    def _replace_pg_memberships(
        self,
        user_id: uuid.UUID,
        role_names: list[str],
        group_names: list[str],
    ) -> None:
        self.db.execute(delete(UserRole).where(UserRole.user_id == user_id))
        self.db.execute(delete(UserGroup).where(UserGroup.user_id == user_id))

        for name in role_names:
            role = self.db.scalar(select(Role).where(Role.name == name))
            if role is None:
                raise RuntimeError(f"role {name} missing in mirror")
            self.db.add(UserRole(user_id=user_id, role_id=role.id))

        # Mirror product groups; if empty, mirror sentinel _empty to match KC.
        effective_groups = list(group_names) if group_names else [GROUPS_EMPTY_SENTINEL]
        for name in effective_groups:
            group = self.db.scalar(select(Group).where(Group.name == name))
            if group is None:
                raise RuntimeError(f"group {name} missing in mirror")
            self.db.add(UserGroup(user_id=user_id, group_id=group.id))

    def _user_out(self, user: User) -> UserOut:
        role_names = sorted(
            {
                link.role.name
                for link in user.role_links
                if link.role and not is_system_role_name(link.role.name)
            }
        )
        group_names = sorted(
            {
                link.group.name
                for link in user.group_links
                if link.group and link.group.name != GROUPS_EMPTY_SENTINEL
            }
        )
        return UserOut(
            id=user.id,
            username=user.username,
            email=user.email,
            enabled=user.enabled,
            role_names=role_names,
            group_names=group_names,
            created_at=user.created_at,
            updated_at=user.updated_at,
        )

    @staticmethod
    def _role_out(role: Role) -> RoleOut:
        return RoleOut(
            id=role.id,
            name=role.name,
            description=role.description,
            is_system=role.is_system,
            created_at=role.created_at,
            updated_at=role.updated_at,
        )

    @staticmethod
    def _group_out(group: Group) -> GroupOut:
        return GroupOut(
            id=group.id,
            name=group.name,
            path=group.path,
            is_system=group.is_system,
            created_at=group.created_at,
            updated_at=group.updated_at,
        )

    @staticmethod
    def _http_from_kc(exc: KeycloakAdminError) -> HTTPException:
        return HTTPException(status_code=exc.status_code, detail=exc.message)


def _now() -> datetime:
    return datetime.now(timezone.utc)
