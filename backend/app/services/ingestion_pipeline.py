"""Outbound client for the ingestion pipeline control plane.

This process does not implement the pipeline. It calls a base URL and does not
send the admin JWT or the ingest JWT. ``config`` is a string-keyed object of
catalog field values. It is forwarded and not written to Postgres.

Contract (the other side is not in this repo):

| Call | Request | Success body |
| --- | --- | --- |
| ``POST {base}/connectors`` | ``type``, ``name``, ``enabled``, ``schedule``, ``config``, ``callback_connector_id`` | JSON object with string ``id`` |
| ``PATCH {base}/connectors/{pipeline_id}`` | same fields, all optional | 2xx, body ignored |
| ``POST {base}/connectors/{pipeline_id}/sync`` | empty object | 2xx, body ignored |

Errors become ``PipelineError``:

- ``ingestion_pipeline_url`` empty or whitespace → 503
- DNS, connect, or timeout → 502
- status not 2xx → 502, with the pipeline status code and no response body
- 2xx create body missing a string ``id`` → 502

Timeout is ``ingestion_pipeline_timeout_seconds``. One attempt. No retries.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.core.config import Settings, get_settings


class PipelineError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


def _base_url(settings: Settings) -> str:
    url = settings.ingestion_pipeline_url.strip()
    if not url:
        raise PipelineError(503, "ingestion pipeline URL is not configured")
    return url.rstrip("/")


def _request(method: str, path: str, body: dict[str, Any]) -> httpx.Response:
    settings = get_settings()
    url = f"{_base_url(settings)}{path}"
    timeout = settings.ingestion_pipeline_timeout_seconds
    try:
        response = httpx.request(method, url, json=body, timeout=timeout)
    except httpx.TimeoutException as exc:
        raise PipelineError(502, "ingestion pipeline request timed out") from exc
    except httpx.RequestError as exc:
        raise PipelineError(502, "ingestion pipeline unreachable") from exc
    if response.status_code < 200 or response.status_code >= 300:
        raise PipelineError(502, f"ingestion pipeline returned HTTP {response.status_code}")
    return response


def create_connector(
    *,
    type: str,
    name: str,
    enabled: bool,
    schedule: str | None,
    config: dict[str, Any],
    callback_connector_id: str,
) -> str:
    """POST /connectors. Returns the pipeline connector id. Does not write Postgres.

    ``callback_connector_id`` is this API's connector UUID. The pipeline uses it
    on ``POST /internal/connectors/{id}/status``.
    """
    response = _request(
        "POST",
        "/connectors",
        {
            "type": type,
            "name": name,
            "enabled": enabled,
            "schedule": schedule,
            "config": config,
            "callback_connector_id": callback_connector_id,
        },
    )
    try:
        payload = response.json()
    except ValueError as exc:
        raise PipelineError(502, "ingestion pipeline create response missing string id") from exc
    pipeline_id = payload.get("id") if isinstance(payload, dict) else None
    if not isinstance(pipeline_id, str) or not pipeline_id:
        raise PipelineError(502, "ingestion pipeline create response missing string id")
    return pipeline_id


def update_connector(pipeline_id: str, fields: dict[str, Any]) -> None:
    """PATCH /connectors/{pipeline_id}. Body is ignored on 2xx."""
    _request("PATCH", f"/connectors/{pipeline_id}", fields)


def sync_connector(pipeline_id: str) -> None:
    """POST /connectors/{pipeline_id}/sync. Body is ignored on 2xx."""
    _request("POST", f"/connectors/{pipeline_id}/sync", {})
