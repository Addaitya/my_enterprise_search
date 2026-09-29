from pydantic import BaseModel, Field


class AdminStatsPlaceholders(BaseModel):
    active_connectors: bool = False
    ingestion_rate_docs_per_hour: bool = False
    last_sync: bool = False


class AdminStatsOut(BaseModel):
    avg_query_time_ms: float | None = None
    total_data_ingested_bytes: int
    total_docs_indexed: int
    active_connectors: int
    ingestion_rate_docs_per_hour: int
    last_sync: str
    placeholders: AdminStatsPlaceholders = Field(default_factory=AdminStatsPlaceholders)
