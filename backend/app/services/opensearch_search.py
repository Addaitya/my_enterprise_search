"""Product OpenSearch search: client-side hybrid on 3.8 (user JWT + DLS).

Native ``hybrid`` + DLS is blocked on OpenSearch 3.8. Product path runs match and
neural in parallel with the caller's Bearer, then min_max + weighted merge to
match ``enterprise-search-hybrid`` pipeline weights [0.3, 0.7].
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

import httpx

from app.core.config import Settings, get_settings


class OpenSearchSearchError(Exception):
    """Raised when an OpenSearch subquery fails; map to HTTP 502 at the route."""

    def __init__(self, detail: str, *, status_code: int | None = None) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


@dataclass
class RawHit:
    id: str
    score: float
    source: dict[str, Any]


@dataclass
class MergedHit:
    id: str
    score: float
    source: dict[str, Any]
    score_kw: float = 0.0
    score_nn: float = 0.0


@dataclass
class SearchResult:
    hits: list[MergedHit] = field(default_factory=list)
    took_ms: int = 0


def min_max_normalize(scores: list[float]) -> list[float]:
    """Normalize scores to [0, 1]. Single hit or all-equal → 1.0 each."""
    if not scores:
        return []
    lo = min(scores)
    hi = max(scores)
    if hi == lo:
        return [1.0] * len(scores)
    span = hi - lo
    return [(s - lo) / span for s in scores]


def merge_hybrid_scores(
    kw_hits: list[RawHit],
    nn_hits: list[RawHit],
    *,
    w_kw: float = 0.3,
    w_nn: float = 0.7,
    size: int | None = None,
) -> list[MergedHit]:
    """Union by ``_id``, missing side = 0, sort by combined score desc, optional top-N."""
    kw_norms = min_max_normalize([h.score for h in kw_hits])
    nn_norms = min_max_normalize([h.score for h in nn_hits])

    merged: dict[str, MergedHit] = {}
    for hit, norm in zip(kw_hits, kw_norms, strict=True):
        merged[hit.id] = MergedHit(
            id=hit.id,
            score=0.0,
            source=dict(hit.source),
            score_kw=norm,
            score_nn=0.0,
        )
    for hit, norm in zip(nn_hits, nn_norms, strict=True):
        row = merged.get(hit.id)
        if row is None:
            merged[hit.id] = MergedHit(
                id=hit.id,
                score=0.0,
                source=dict(hit.source),
                score_kw=0.0,
                score_nn=norm,
            )
        else:
            row.score_nn = norm
            # Prefer richer _source if the other side had more fields
            if len(hit.source) > len(row.source):
                row.source = dict(hit.source)

    ranked = list(merged.values())
    for row in ranked:
        row.score = w_kw * row.score_kw + w_nn * row.score_nn
    ranked.sort(key=lambda r: r.score, reverse=True)
    if size is not None:
        ranked = ranked[:size]
    return ranked


def _display_name(object_store_path: str | None) -> str | None:
    if not object_store_path:
        return None
    name = PurePosixPath(object_store_path.replace("\\", "/")).name
    return name or None


def _snippet(content: Any, max_chars: int) -> str:
    if content is None:
        return ""
    text = str(content)
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1] + "…"


def hit_to_dto(hit: MergedHit, *, snippet_chars: int) -> dict[str, Any]:
    """Map merged OS hit → Task 5 C3 fields. Never include embedding."""
    src = {k: v for k, v in hit.source.items() if k != "embedding"}
    object_store_path = src.get("object_store_path")
    path_str = str(object_store_path) if object_store_path is not None else None
    uploaded_at = src.get("uploaded_at")
    if uploaded_at is not None and not isinstance(uploaded_at, str):
        uploaded_at = str(uploaded_at)
    return {
        "file_id": src.get("file_id"),
        "chunk_id": hit.id,
        "chunk_seq": src.get("chunk_seq"),
        "score": hit.score,
        "snippet": _snippet(src.get("content"), snippet_chars),
        "meta_file_type": src.get("meta_file_type"),
        "object_store_path": path_str,
        "display_name": _display_name(path_str),
        "uploaded_at": uploaded_at,
    }


def match_body(q: str, size: int) -> dict[str, Any]:
    return {
        "size": size,
        "query": {"match": {"content": q}},
        "_source": {"excludes": ["embedding"]},
    }


def neural_body(q: str, size: int, model_id: str, *, k: int = 50) -> dict[str, Any]:
    return {
        "size": size,
        "query": {
            "neural": {
                "embedding": {
                    "query_text": q,
                    "model_id": model_id,
                    "k": k,
                }
            }
        },
        "_source": {"excludes": ["embedding"]},
    }


def native_hybrid_body(q: str, size: int, model_id: str, *, k: int = 50) -> dict[str, Any]:
    return {
        "size": size,
        "query": {
            "hybrid": {
                "queries": [
                    {"match": {"content": q}},
                    {
                        "neural": {
                            "embedding": {
                                "query_text": q,
                                "model_id": model_id,
                                "k": k,
                            }
                        }
                    },
                ]
            }
        },
        "_source": {"excludes": ["embedding"]},
    }


def _parse_hits(payload: dict[str, Any]) -> list[RawHit]:
    raw = payload.get("hits", {}).get("hits", [])
    out: list[RawHit] = []
    for item in raw:
        hit_id = item.get("_id")
        if not hit_id:
            continue
        source = item.get("_source") or {}
        if isinstance(source, dict) and "embedding" in source:
            source = {k: v for k, v in source.items() if k != "embedding"}
        score = item.get("_score")
        out.append(
            RawHit(
                id=str(hit_id),
                score=float(score) if score is not None else 0.0,
                source=dict(source) if isinstance(source, dict) else {},
            )
        )
    return out


async def _os_search(
    body: dict[str, Any],
    headers: dict[str, str],
    settings: Settings,
    *,
    params: dict[str, str] | None = None,
    label: str = "search",
) -> dict[str, Any]:
    url = f"{settings.opensearch_url}/{settings.opensearch_index}/_search"
    try:
        async with httpx.AsyncClient(verify=settings.opensearch_verify_certs, timeout=60.0) as client:
            response = await client.post(url, headers=headers, json=body, params=params or {})
    except httpx.TimeoutException as exc:
        raise OpenSearchSearchError(f"OpenSearch {label} timed out") from exc
    except httpx.HTTPError as exc:
        raise OpenSearchSearchError(f"OpenSearch {label} request failed: {exc}") from exc

    if response.status_code in (401, 403):
        raise OpenSearchSearchError(
            "search backend rejected the token",
            status_code=response.status_code,
        )
    if response.is_error:
        raise OpenSearchSearchError(
            f"OpenSearch {label} error {response.status_code}: {response.text[:500]}",
            status_code=response.status_code,
        )
    return response.json()


async def search_match(
    q: str,
    size: int,
    headers: dict[str, str],
    *,
    settings: Settings | None = None,
) -> list[RawHit]:
    settings = settings or get_settings()
    payload = await _os_search(match_body(q, size), headers, settings, label="match")
    return _parse_hits(payload)


async def search_neural(
    q: str,
    size: int,
    headers: dict[str, str],
    model_id: str,
    *,
    settings: Settings | None = None,
) -> list[RawHit]:
    settings = settings or get_settings()
    body = neural_body(q, size, model_id, k=settings.search_neural_k)
    payload = await _os_search(body, headers, settings, label="neural")
    return _parse_hits(payload)


async def client_hybrid_search(
    q: str,
    size: int,
    headers: dict[str, str],
    *,
    settings: Settings | None = None,
) -> SearchResult:
    settings = settings or get_settings()
    model_id = settings.opensearch_model_id
    if not model_id:
        raise OpenSearchSearchError("opensearch_model_id is not configured")

    fetch = min(settings.search_max_fetch, size * settings.search_fetch_multiplier)
    started = time.perf_counter()
    kw_hits, nn_hits = await asyncio.gather(
        search_match(q, fetch, headers, settings=settings),
        search_neural(q, fetch, headers, model_id, settings=settings),
    )
    ranked = merge_hybrid_scores(
        kw_hits,
        nn_hits,
        w_kw=settings.search_keyword_weight,
        w_nn=settings.search_neural_weight,
        size=size,
    )
    took_ms = int((time.perf_counter() - started) * 1000)
    return SearchResult(hits=ranked, took_ms=took_ms)


async def native_hybrid_search(
    q: str,
    size: int,
    headers: dict[str, str],
    *,
    settings: Settings | None = None,
) -> SearchResult:
    """Single native hybrid query. Do not use as default on OpenSearch 3.8."""
    settings = settings or get_settings()
    model_id = settings.opensearch_model_id
    if not model_id:
        raise OpenSearchSearchError("opensearch_model_id is not configured")

    started = time.perf_counter()
    body = native_hybrid_body(q, size, model_id, k=settings.search_neural_k)
    payload = await _os_search(
        body,
        headers,
        settings,
        params={"search_pipeline": settings.opensearch_search_pipeline},
        label="native_hybrid",
    )
    raw = _parse_hits(payload)
    ranked = [
        MergedHit(id=h.id, score=h.score, source=h.source, score_kw=0.0, score_nn=0.0)
        for h in raw
    ]
    took_ms = int((time.perf_counter() - started) * 1000)
    return SearchResult(hits=ranked, took_ms=took_ms)
