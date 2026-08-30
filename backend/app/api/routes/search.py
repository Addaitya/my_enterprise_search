"""Product search route: client-side hybrid with user JWT (Task 5)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.deps import require_product_user, user_bearer_header
from app.core.config import get_settings
from app.core.security import CurrentUser
from app.schemas.search import SearchHit, SearchRequest, SearchResponse
from app.services.opensearch_search import (
    OpenSearchSearchError,
    client_hybrid_search,
    hit_to_dto,
    native_hybrid_search,
)

router = APIRouter(tags=["search"])


@router.post("/search", response_model=SearchResponse)
async def post_search(
    body: SearchRequest,
    request: Request,
    _user: CurrentUser = Depends(require_product_user),
) -> SearchResponse:
    q = body.q.strip()
    if not q:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="q must not be empty")

    settings = get_settings()
    size = body.size if body.size is not None else settings.search_default_size
    size = max(1, min(size, settings.search_max_size))

    if not settings.opensearch_model_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="opensearch_model_id is not configured; run init_services",
        )

    headers = user_bearer_header(request)
    mode = (settings.search_mode or "client_hybrid").strip().lower()

    try:
        if mode == "native_hybrid":
            result = await native_hybrid_search(q, size, headers, settings=settings)
        else:
            result = await client_hybrid_search(q, size, headers, settings=settings)
    except OpenSearchSearchError as exc:
        # Missing model already checked; remaining config-ish details → 503, else 502.
        if "opensearch_model_id" in exc.detail:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=exc.detail,
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=exc.detail,
        ) from exc

    hits = [
        SearchHit.model_validate(hit_to_dto(h, snippet_chars=settings.search_snippet_chars))
        for h in result.hits
    ]
    return SearchResponse(q=q, took_ms=result.took_ms, total=len(hits), hits=hits)
