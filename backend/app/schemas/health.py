from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    app_name: str
    realm: str
    opensearch_index: str
