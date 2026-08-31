"""Pydantic schemas for Admin file ACL + sync jobs (Task 6b / 12a)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class AccessPreviewOut(BaseModel):
    principal_type: Literal["role", "group"]
    principal_id: UUID
    principal_name: str
    permission: str


class AdminFileOut(BaseModel):
    id: UUID
    display_name: str
    file_type: str
    size_bytes: int
    object_store_path: str
    uploaded_at: datetime
    updated_at: datetime
    access_total: int = 0
    access_preview: list[AccessPreviewOut] = Field(default_factory=list)


class AdminFileListResponse(BaseModel):
    items: list[AdminFileOut]
    total: int
    limit: int
    offset: int


class AclGrantIn(BaseModel):
    principal_type: Literal["role", "group"]
    principal_id: UUID
    permission: Literal["viewer", "editor"] = "viewer"

    @model_validator(mode="before")
    @classmethod
    def reject_user_principal(cls, data: object) -> object:
        if isinstance(data, dict) and data.get("principal_type") == "user":
            raise ValueError("principal_type=user is not allowed")
        return data


class AclGrantOut(BaseModel):
    id: UUID
    principal_type: Literal["role", "group"]
    principal_id: UUID
    principal_name: str
    permission: str


class AclReplaceRequest(BaseModel):
    grants: list[AclGrantIn] = Field(default_factory=list)


class AclUpsertRequest(BaseModel):
    principal_type: Literal["role", "group"]
    principal_id: UUID
    permission: Literal["viewer", "editor"] = "viewer"

    @model_validator(mode="before")
    @classmethod
    def reject_user_principal(cls, data: object) -> object:
        if isinstance(data, dict) and data.get("principal_type") == "user":
            raise ValueError("principal_type=user is not allowed")
        return data


class FileAclResponse(BaseModel):
    file_id: UUID
    grants: list[AclGrantOut]
    acl_job_id: UUID | None = None


class BulkAclRequest(BaseModel):
    file_ids: list[UUID]
    mode: Literal["upsert", "replace", "revoke"]
    grants: list[AclGrantIn] = Field(default_factory=list)
    confirm_replace: bool = False


class BulkAclResult(BaseModel):
    file_id: UUID
    grants: list[AclGrantOut]
    acl_job_id: UUID | None = None


class BulkAclFailed(BaseModel):
    file_id: UUID
    error: str


class BulkAclResponse(BaseModel):
    results: list[BulkAclResult]
    failed: list[BulkAclFailed]


class FileGrantItemOut(BaseModel):
    acl_id: UUID
    file_id: UUID
    display_name: str
    file_type: str
    permission: str
    updated_at: datetime


class FileGrantListResponse(BaseModel):
    items: list[FileGrantItemOut]
    total: int
    limit: int
    offset: int


class AclJobOut(BaseModel):
    id: UUID
    file_id: UUID
    status: str
    total_chunks: int | None = None
    updated_chunks: int | None = None
    error: str | None = None
    created_by_user_id: UUID | None = None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class AclJobListResponse(BaseModel):
    items: list[AclJobOut]
    total: int
    limit: int
    offset: int
