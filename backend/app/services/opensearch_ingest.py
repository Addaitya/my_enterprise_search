"""OpenSearch bulk ingest as internal basic `admin` (never user JWT)."""

from __future__ import annotations

import json
import time
from typing import Any
from uuid import UUID

import httpx

from app.core.config import Settings, get_settings


def _admin_client(settings: Settings) -> httpx.Client:
    return httpx.Client(
        base_url=settings.opensearch_url,
        verify=settings.opensearch_verify_certs,
        auth=("admin", settings.opensearch_initial_admin_password),
        timeout=120,
    )


def build_chunk_document(
    *,
    file_id: UUID,
    chunk_seq: int,
    content: str,
    file_type: str,
    size_bytes: int,
    object_store_path: str,
    uploaded_at: str,
    updated_at: str,
) -> dict[str, Any]:
    """Chunk body for bulk index. Omits ``embedding`` (ingest pipeline fills it)."""
    chunk_id = f"{file_id}:{chunk_seq:06d}"
    return {
        "file_id": str(file_id),
        "chunk_id": chunk_id,
        "chunk_seq": chunk_seq,
        "meta_file_type": file_type,
        "meta_file_size": size_bytes,
        "updated_at": updated_at,
        "uploaded_at": uploaded_at,
        "content": content,
        "allowed_roles": [],
        "allowed_groups": [],
        "object_store_path": object_store_path,
        "ingestion_type": "local",
        "original_source": None,
    }


def bulk_index_chunks(
    docs: list[dict[str, Any]],
    *,
    settings: Settings | None = None,
) -> None:
    """Index chunks with basic admin. Raises RuntimeError on bulk errors."""
    if not docs:
        raise ValueError("no docs to index")
    settings = settings or get_settings()
    lines: list[str] = []
    for doc in docs:
        chunk_id = doc["chunk_id"]
        lines.append(json.dumps({"index": {"_index": settings.opensearch_index, "_id": chunk_id}}))
        lines.append(json.dumps(doc))
    body = "\n".join(lines) + "\n"

    with _admin_client(settings) as client:
        response = client.post(
            "/_bulk",
            params={"refresh": "wait_for"},
            content=body,
            headers={"Content-Type": "application/x-ndjson"},
        )
    if response.is_error:
        raise RuntimeError(f"OpenSearch bulk HTTP {response.status_code}: {response.text}")
    payload = response.json()
    if payload.get("errors"):
        items = payload.get("items") or []
        details = []
        for item in items:
            index = item.get("index") or {}
            if index.get("error"):
                details.append(index["error"])
        raise RuntimeError(f"OpenSearch bulk item errors: {details[:3]}")


def delete_chunks_by_file_id(file_id: UUID, *, settings: Settings | None = None) -> None:
    """Best-effort delete of all chunks for a file (compensation)."""
    settings = settings or get_settings()
    with _admin_client(settings) as client:
        response = client.post(
            f"/{settings.opensearch_index}/_delete_by_query",
            params={"refresh": "true"},
            json={"query": {"term": {"file_id": str(file_id)}}},
        )
    if response.is_error:
        raise RuntimeError(
            f"OpenSearch delete_by_query HTTP {response.status_code}: {response.text}"
        )


def get_chunks_by_file_id(
    file_id: UUID,
    *,
    settings: Settings | None = None,
    wait_seconds: float = 0,
) -> list[dict]:
    """Admin fetch of chunks for proofs. Optionally retry until hits appear."""
    settings = settings or get_settings()
    deadline = time.monotonic() + max(0.0, wait_seconds)
    last: list[dict] = []
    while True:
        with _admin_client(settings) as client:
            response = client.post(
                f"/{settings.opensearch_index}/_search",
                json={
                    "size": 1000,
                    "query": {"term": {"file_id": str(file_id)}},
                    "sort": [{"chunk_seq": "asc"}],
                },
            )
        if response.is_error:
            raise RuntimeError(f"OpenSearch search HTTP {response.status_code}: {response.text}")
        last = response.json().get("hits", {}).get("hits", [])
        if last or time.monotonic() >= deadline:
            return last
        time.sleep(0.25)
