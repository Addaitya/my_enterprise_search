from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    q: str
    size: int | None = Field(default=None, ge=1, le=50)


class SearchHit(BaseModel):
    file_id: str | None = None
    chunk_id: str
    chunk_seq: int | None = None
    score: float
    snippet: str
    meta_file_type: str | None = None
    object_store_path: str | None = None
    display_name: str | None = None
    uploaded_at: str | None = None


class SearchResponse(BaseModel):
    q: str
    took_ms: int
    total: int
    hits: list[SearchHit]
