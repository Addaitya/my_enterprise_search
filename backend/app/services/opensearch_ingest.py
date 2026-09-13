"""OpenSearch bulk ingest as internal basic `admin` (never user JWT)."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
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
    original_source: str | None = None,
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
        "original_source": original_source,
    }


def bulk_item_error_details(payload: dict[str, Any]) -> list[Any]:
    """Extract per-item ``index.error`` objects from a ``_bulk`` response body."""
    details: list[Any] = []
    for item in payload.get("items") or []:
        index = item.get("index") or {}
        if index.get("error"):
            details.append(index["error"])
    return details


def bulk_failure_is_retryable(
    *,
    http_status: int | None = None,
    item_errors: list[Any] | None = None,
    response_text: str = "",
) -> bool:
    """True for transient OpenSearch memory / overload failures.

    Folder proofs failed with ``circuit_breaking_exception`` durability
    ``TRANSIENT`` (bytes_wanted/limit 0) while the parent breaker was open.
    Mapping / parse errors are not retryable.
    """
    if http_status in {429, 503}:
        return True
    if "circuit_breaking_exception" in response_text:
        return True
    for err in item_errors or []:
        if not isinstance(err, dict):
            continue
        if err.get("type") != "circuit_breaking_exception":
            continue
        if str(err.get("durability") or "TRANSIENT").upper() == "PERMANENT":
            continue
        return True
    return False


def execute_bulk_with_retry(
    send: Callable[[], tuple[int, dict[str, Any] | None, str]],
    *,
    max_attempts: int = 5,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Call ``send()`` until success or a non-retryable / exhausted failure.

    ``send`` must return ``(http_status, payload_or_none, response_text)``.
    ``payload_or_none`` is None on HTTP-level errors.
    """
    last_message = "OpenSearch bulk failed"
    for attempt in range(max_attempts):
        status, payload, text = send()
        item_errors: list[Any] = []
        if payload is None:
            last_message = f"OpenSearch bulk HTTP {status}: {text}"
        elif not payload.get("errors"):
            return payload
        else:
            item_errors = bulk_item_error_details(payload)
            last_message = f"OpenSearch bulk item errors: {item_errors[:3]}"
        can_retry = attempt < max_attempts - 1 and bulk_failure_is_retryable(
            http_status=status,
            item_errors=item_errors,
            response_text=text,
        )
        if can_retry:
            sleep(min(16.0, 2.0 * (2**attempt)))
            continue
        raise RuntimeError(last_message)
    raise RuntimeError(last_message)


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

    def send() -> tuple[int, dict[str, Any] | None, str]:
        with _admin_client(settings) as client:
            response = client.post(
                "/_bulk",
                params={"refresh": "wait_for"},
                content=body,
                headers={"Content-Type": "application/x-ndjson"},
            )
        if response.is_error:
            return response.status_code, None, response.text
        return response.status_code, response.json(), response.text

    execute_bulk_with_retry(send)


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
            raise RuntimeError(
                f"OpenSearch search HTTP {response.status_code}: {response.text}"
            )
        last = response.json().get("hits", {}).get("hits", [])
        if last or time.monotonic() >= deadline:
            return last
        time.sleep(0.25)
