"""Admin identity routes: users / roles / groups (Task 6a)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.core.security import CurrentUser
from app.db.session import get_db
from app.schemas.admin_identity import (
    GroupCreate,
    GroupListResponse,
    GroupOut,
    RoleCreate,
    RoleListResponse,
    RoleOut,
    RoleUpdateRequest,
    UserCreate,
    UserListResponse,
    UserOut,
    UserUpdate,
)
from app.services.identity_admin import IdentityAdminService

router = APIRouter(prefix="/admin", tags=["admin-identity"])


def _service(db: Session = Depends(get_db)) -> IdentityAdminService:
    return IdentityAdminService(db)


@router.get("/users", response_model=UserListResponse)
def list_users(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    q: str | None = Query(None),
    _admin: CurrentUser = Depends(require_admin),
    service: IdentityAdminService = Depends(_service),
) -> UserListResponse:
    items, total = service.list_users(limit=limit, offset=offset, q=q)
    return UserListResponse(items=items, total=total, limit=limit, offset=offset)


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(
    body: UserCreate,
    _admin: CurrentUser = Depends(require_admin),
    service: IdentityAdminService = Depends(_service),
) -> UserOut:
    return service.create_user(body)


@router.get("/users/{user_id}", response_model=UserOut)
def get_user(
    user_id: UUID,
    _admin: CurrentUser = Depends(require_admin),
    service: IdentityAdminService = Depends(_service),
) -> UserOut:
    return service.get_user(user_id)


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: UUID,
    body: UserUpdate,
    _admin: CurrentUser = Depends(require_admin),
    service: IdentityAdminService = Depends(_service),
) -> UserOut:
    return service.update_user(user_id, body)


@router.get("/roles", response_model=RoleListResponse)
def list_roles(
    include_system: bool = Query(False),
    _admin: CurrentUser = Depends(require_admin),
    service: IdentityAdminService = Depends(_service),
) -> RoleListResponse:
    items, total = service.list_roles(include_system=include_system)
    return RoleListResponse(items=items, total=total)


@router.post("/roles", response_model=RoleOut, status_code=status.HTTP_201_CREATED)
def create_role(
    body: RoleCreate,
    _admin: CurrentUser = Depends(require_admin),
    service: IdentityAdminService = Depends(_service),
) -> RoleOut:
    return service.create_role(body)


@router.get("/roles/{role_id}", response_model=RoleOut)
def get_role(
    role_id: UUID,
    _admin: CurrentUser = Depends(require_admin),
    service: IdentityAdminService = Depends(_service),
) -> RoleOut:
    return service.get_role(role_id)


@router.patch("/roles/{role_id}", response_model=RoleOut)
def update_role(
    role_id: UUID,
    body: RoleUpdateRequest,
    _admin: CurrentUser = Depends(require_admin),
    service: IdentityAdminService = Depends(_service),
) -> RoleOut:
    return service.update_role(role_id, description=body.description)


@router.delete("/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_role(
    role_id: UUID,
    _admin: CurrentUser = Depends(require_admin),
    service: IdentityAdminService = Depends(_service),
) -> Response:
    service.delete_role(role_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/groups", response_model=GroupListResponse)
def list_groups(
    include_system: bool = Query(False),
    _admin: CurrentUser = Depends(require_admin),
    service: IdentityAdminService = Depends(_service),
) -> GroupListResponse:
    items, total = service.list_groups(include_system=include_system)
    return GroupListResponse(items=items, total=total)


@router.post("/groups", response_model=GroupOut, status_code=status.HTTP_201_CREATED)
def create_group(
    body: GroupCreate,
    _admin: CurrentUser = Depends(require_admin),
    service: IdentityAdminService = Depends(_service),
) -> GroupOut:
    return service.create_group(body)


@router.get("/groups/{group_id}", response_model=GroupOut)
def get_group(
    group_id: UUID,
    _admin: CurrentUser = Depends(require_admin),
    service: IdentityAdminService = Depends(_service),
) -> GroupOut:
    return service.get_group(group_id)


@router.delete("/groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_group(
    group_id: UUID,
    _admin: CurrentUser = Depends(require_admin),
    service: IdentityAdminService = Depends(_service),
) -> Response:
    service.delete_group(group_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
