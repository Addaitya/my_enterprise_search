from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_DIR.parent
RUNTIME_CONFIG_PATH = BACKEND_DIR / "runtime_config.json"


class Settings(BaseSettings):
    """Non-sensitive defaults live here. Secrets come from `.env`. Runtime
    values (model ids, discovered URLs) overlay from `runtime_config.json`.
    """

    model_config = SettingsConfigDict(
        env_file=(str(REPO_ROOT / ".env"), str(BACKEND_DIR / ".env")),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "enterprise-search"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: str = "http://localhost:5173"

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_admin_user: str = "postgres"
    postgres_admin_password: str = ""
    app_db: str = "app"
    app_user: str = "app_user"
    app_password: str = ""

    keycloak_url: str = "http://localhost:8080"
    keycloak_internal_url: str = "http://keycloak:8080"
    keycloak_realm: str = "enterprise-search-realm"
    keycloak_client_id: str = "api-client"
    keycloak_api_secret: str = ""
    keycloak_admin: str = "admin"
    keycloak_admin_password: str = ""
    keycloak_db: str = "keycloak"
    keycloak_user: str = "keycloak_user"
    keycloak_password: str = ""

    opensearch_url: str = "http://localhost:9200"
    opensearch_verify_certs: bool = False
    opensearch_index: str = "enterprise-search-chunks"
    opensearch_embedding_model: str = "huggingface/sentence-transformers/all-MiniLM-L6-v2"
    opensearch_embedding_version: str = "1.0.2"
    opensearch_embedding_dim: int = 384
    opensearch_initial_admin_password: str = ""
    opensearch_ingest_pipeline: str = "enterprise-search-embed"
    opensearch_search_pipeline: str = "enterprise-search-hybrid"
    # opensearch_model_id: str | None = None

    @property
    def opensearch_model_id(self) -> str:
        config = load_runtime_config()
        return config.get("opensearch_model_id") if config.get("opensearch_model_id") else None
   

    minio_endpoint: str = "localhost:9000"
    minio_root_user: str = "minioadmin"
    minio_root_password: str = ""
    minio_bucket: str = "enterprise-search-files"
    minio_secure: bool = False

    @computed_field
    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg2://{self.app_user}:{self.app_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.app_db}"
        )

    @computed_field
    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @computed_field
    @property
    def keycloak_issuer(self) -> str:
        return f"{self.keycloak_url}/realms/{self.keycloak_realm}"

    @computed_field
    @property
    def keycloak_jwks_url(self) -> str:
        return f"{self.keycloak_issuer}/protocol/openid-connect/certs"


def load_runtime_config() -> dict[str, Any]:
    if not RUNTIME_CONFIG_PATH.exists():
        return {}
    return json.loads(RUNTIME_CONFIG_PATH.read_text(encoding="utf-8"))


def save_runtime_config(updates: dict[str, Any]) -> dict[str, Any]:
    current = load_runtime_config()
    current.update({key: value for key, value in updates.items() if value is not None})
    RUNTIME_CONFIG_PATH.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")
    get_settings.cache_clear()
    return current


@lru_cache
def get_settings() -> Settings:
    return Settings(**load_runtime_config())
