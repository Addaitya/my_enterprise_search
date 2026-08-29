from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class InitiateUploadRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=512)
    size_bytes: int = Field(ge=1)
    content_type: str | None = None


class InitiateUploadResponse(BaseModel):
    upload_id: UUID
    upload_url: str
    status: str
    size_bytes: int
    bytes_received: int
    expires_at: datetime


class UploadStatusResponse(BaseModel):
    upload_id: UUID
    status: str
    file_type: str
    size_bytes: int
    bytes_received: int
    file_id: UUID | None = None
    chunk_count: int | None = None
    error: str | None = None
    expires_at: datetime


class PutRangeResponse(BaseModel):
    status: str
    bytes_received: int


class CompleteUploadResponse(BaseModel):
    upload_id: UUID
    status: str
    id: UUID
    file_type: str
    size_bytes: int
    object_store_path: str
    ingestion_type: str
    original_source: str | None
    chunk_count: int
    uploaded_at: datetime
