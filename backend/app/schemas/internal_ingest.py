"""Request and response models for /internal/ingest/files.

Extra fields are forbidden so a client cannot supply file_id, ACL names,
an embedding, or an object path.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.file import FILE_INGESTION_TYPES
from app.services.ingest.detect import safe_filename


class ReserveIngestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str
    size_bytes: int
    ingestion_type: str
    original_source: str
    content_type: str | None = None

    @field_validator("filename")
    @classmethod
    def filename_is_safe_basename(cls, value: str) -> str:
        try:
            return safe_filename(value)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc

    @field_validator("ingestion_type")
    @classmethod
    def ingestion_type_allowed(cls, value: str) -> str:
        if value not in FILE_INGESTION_TYPES:
            raise ValueError("invalid ingestion_type")
        return value

    @field_validator("original_source")
    @classmethod
    def original_source_nonempty(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("original_source is required")
        return text


class ReserveIngestResponse(BaseModel):
    file_id: UUID
    object_store_path: str
    upload_url: str
    expires_at: datetime


class IngestChunk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seq: int = Field(ge=0)
    content: str = Field(min_length=1)


class CompleteIngestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    size_bytes: int = Field(ge=1)
    file_type: str
    chunks: list[IngestChunk] = Field(min_length=1)

    @field_validator("file_type")
    @classmethod
    def file_type_is_extension(cls, value: str) -> str:
        if not 1 <= len(value) <= 32 or any(char in value for char in "./\\"):
            raise ValueError("file_type must be 1-32 characters with no dot or slash")
        return value

    @model_validator(mode="after")
    def chunk_seq_unique(self) -> CompleteIngestRequest:
        seqs = [chunk.seq for chunk in self.chunks]
        if len(seqs) != len(set(seqs)):
            raise ValueError("chunk seq must be unique")
        return self


class CompleteIngestResponse(BaseModel):
    file_id: UUID
    status: str
    object_store_path: str
    file_type: str
    size_bytes: int
    ingestion_type: str
    chunk_count: int
