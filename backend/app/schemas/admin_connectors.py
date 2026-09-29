"""Admin connector mirror and the ingest status callback.

``config`` is write-only. It is accepted on create and update and is never
returned. Source passwords stay in that object and are not a database column.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _required_text(value: str, label: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{label} is required")
    return cleaned


class ConnectorCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str
    name: str
    enabled: bool = False
    schedule: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)

    @field_validator("type")
    @classmethod
    def type_nonempty(cls, value: str) -> str:
        return _required_text(value, "type")

    @field_validator("name")
    @classmethod
    def name_nonempty(cls, value: str) -> str:
        return _required_text(value, "name")

    @field_validator("schedule")
    @classmethod
    def schedule_blank_is_none(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class ConnectorUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    enabled: bool | None = None
    schedule: str | None = None
    config: dict[str, Any] | None = None

    @field_validator("name")
    @classmethod
    def name_nonempty(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _required_text(value, "name")

    @field_validator("schedule")
    @classmethod
    def schedule_blank_is_none(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @model_validator(mode="after")
    def at_least_one_field(self) -> ConnectorUpdate:
        if not self.model_fields_set:
            raise ValueError("at least one of name, enabled, schedule, config is required")
        return self


class ConnectorOut(BaseModel):
    id: UUID
    type: str
    name: str
    enabled: bool
    schedule: str | None
    pipeline_connector_id: str | None
    status: str
    last_sync_at: datetime | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime


class ConnectorSyncOut(BaseModel):
    id: UUID
    connector_id: UUID
    status: str
    started_at: datetime
    finished_at: datetime | None
    files_count: int | None
    error: str | None


class ConnectorSyncAccepted(BaseModel):
    sync_id: UUID
    status: str


class ConnectorStatusRequest(BaseModel):
    """Pipeline callback. ``id`` in the URL is our connector UUID."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["success", "failed"]
    files_count: int | None = None
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
