"""Pydantic schemas for Admin identity (users / roles / groups)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


class UserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=255)
    email: str | None = None
    password: str = Field(min_length=1, max_length=255)
    enabled: bool = True
    role_names: list[str] = Field(min_length=1)
    group_names: list[str] = Field(default_factory=list)

    @field_validator("username")
    @classmethod
    def strip_username(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("username is required")
        return cleaned

    @field_validator("role_names", "group_names")
    @classmethod
    def strip_names(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if item and item.strip()]

    @model_validator(mode="after")
    def require_product_role(self) -> UserCreate:
        if not any(name in {"search-user", "admin"} for name in self.role_names):
            raise ValueError("role_names must include search-user and/or admin")
        if "_empty" in self.group_names:
            raise ValueError("Cannot assign group _empty via API")
        return self


class UserUpdate(BaseModel):
    model_config = {"extra": "forbid"}

    email: str | None = None
    enabled: bool | None = None
    password: str | None = Field(default=None, min_length=1, max_length=255)
    role_names: list[str] | None = None
    group_names: list[str] | None = None

    @field_validator("role_names", "group_names")
    @classmethod
    def strip_names(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return [item.strip() for item in value if item and item.strip()]

    @model_validator(mode="after")
    def validate_memberships(self) -> UserUpdate:
        if self.role_names is not None:
            if not self.role_names:
                raise ValueError("role_names cannot be empty")
            if not any(name in {"search-user", "admin"} for name in self.role_names):
                raise ValueError("role_names must include search-user and/or admin")
        if self.group_names is not None and "_empty" in self.group_names:
            raise ValueError("Cannot assign group _empty via API")
        return self


class UserOut(BaseModel):
    id: UUID
    username: str
    email: str | None
    enabled: bool
    role_names: list[str]
    group_names: list[str]
    created_at: datetime
    updated_at: datetime


class UserListResponse(BaseModel):
    items: list[UserOut]
    total: int
    limit: int
    offset: int


class RoleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("name is required")
        return cleaned


class RoleUpdateRequest(BaseModel):
    """PATCH body: description only. ``name`` is rejected (G7)."""

    model_config = {"extra": "forbid"}

    description: str | None = None


class RoleOut(BaseModel):
    id: UUID
    name: str
    description: str | None
    is_system: bool
    created_at: datetime
    updated_at: datetime


class RoleListResponse(BaseModel):
    items: list[RoleOut]
    total: int


class GroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("name is required")
        return cleaned


class GroupOut(BaseModel):
    id: UUID
    name: str
    path: str | None
    is_system: bool
    created_at: datetime
    updated_at: datetime


class GroupListResponse(BaseModel):
    items: list[GroupOut]
    total: int
