from __future__ import annotations

import httpx

from app.core.config import get_settings
from init_services.keycloak import (
    REALM_ADMIN_PASSWORD,
    REALM_ADMIN_USERNAME,
    SEARCHER_PASSWORD,
    SEARCHER_USERNAME,
)

PROOF_DOCS = (
    {
        "_id": "proof-role-search-user",
        "content": "alpha-proof-token",
        "allowed_roles": ["search-user"],
        "allowed_groups": [],
    },
    {
        "_id": "proof-group-engineering",
        "content": "bravo-proof-token",
        "allowed_roles": [],
        "allowed_groups": ["engineering"],
    },
    {
        "_id": "proof-nobody",
        "content": "charlie-proof-token",
        "allowed_roles": [],
        "allowed_groups": [],
    },
)

# OpenSearch 3.8 + JWT DLS wraps hybrid and raises ClassCastException
# (BooleanQuery → HybridQuery). Fixed upstream in security PR 6416 (3.9+).
def _is_hybrid_dls_blocker(text: str) -> bool:
    return "BooleanQuery" in text and "HybridQuery" in text and "class_cast_exception" in text


def _admin_client() -> httpx.Client:
    settings = get_settings()
    return httpx.Client(
        base_url=settings.opensearch_url,
        verify=settings.opensearch_verify_certs,
        auth=("admin", settings.opensearch_initial_admin_password),
        timeout=60,
    )


def _password_token(username: str, password: str) -> str:
    settings = get_settings()
    response = httpx.post(
        f"{settings.keycloak_url}/realms/{settings.keycloak_realm}/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": settings.keycloak_client_id,
            "client_secret": settings.keycloak_api_secret,
            "username": username,
            "password": password,
        },
        timeout=15,
    )
    response.raise_for_status()
    return response.json()["access_token"]


def _search(token: str, body: dict, *, params: dict | None = None) -> httpx.Response:
    settings = get_settings()
    return httpx.post(
        f"{settings.opensearch_url}/{settings.opensearch_index}/_search",
        params=params or {},
        headers={"Authorization": f"Bearer {token}"},
        json=body,
        timeout=60,
        verify=settings.opensearch_verify_certs,
    )


def _hit_ids(response: httpx.Response, *, label: str = "search") -> list[str]:
    if response.is_error:
        raise RuntimeError(f"{label} {response.status_code}: {response.text}")
    hits = response.json().get("hits", {}).get("hits", [])
    return [hit.get("_id") for hit in hits]


def _hybrid_body(query: str) -> dict:
    settings = get_settings()
    model_id = settings.opensearch_model_id
    if not model_id:
        raise RuntimeError("opensearch_model_id missing; run init_services first")
    return {
        "size": 10,
        "query": {
            "hybrid": {
                "queries": [
                    {"match": {"content": query}},
                    {
                        "neural": {
                            "embedding": {
                                "query_text": query,
                                "model_id": model_id,
                                "k": 50,
                            }
                        }
                    },
                ]
            }
        },
        "_source": {"excludes": ["embedding"]},
    }


def _match_body(query: str) -> dict:
    return {"size": 10, "query": {"match": {"content": query}}, "_source": {"excludes": ["embedding"]}}


def _neural_body(query: str) -> dict:
    settings = get_settings()
    model_id = settings.opensearch_model_id
    if not model_id:
        raise RuntimeError("opensearch_model_id missing; run init_services first")
    return {
        "size": 10,
        "query": {
            "neural": {
                "embedding": {
                    "query_text": query,
                    "model_id": model_id,
                    "k": 50,
                }
            }
        },
        "_source": {"excludes": ["embedding"]},
    }


def _expect(label: str, ids: list[str], *, must: set[str] | None = None, must_not: set[str] | None = None) -> None:
    got = set(ids)
    if must and not must.issubset(got):
        raise RuntimeError(f"{label}: expected {sorted(must)} in hits {ids}")
    if must_not and got & must_not:
        raise RuntimeError(f"{label}: did not expect {sorted(got & must_not)} in hits {ids}")
    print(f"[ok] {label} hits={ids}")


def _jwt_cannot_index(token: str) -> None:
    settings = get_settings()
    response = httpx.put(
        f"{settings.opensearch_url}/{settings.opensearch_index}/_doc/jwt-should-fail",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"content": "jwt-write-should-fail"},
        timeout=15,
        verify=settings.opensearch_verify_certs,
    )
    if response.status_code not in {401, 403}:
        raise RuntimeError(f"JWT index expected 401/403, got {response.status_code}: {response.text}")
    print(f"[ok] JWT cannot index ({response.status_code})")


def _try_hybrid(token: str, query: str) -> tuple[str, list[str] | None]:
    """Return ('ok', ids), ('blocked', None), or raise on unexpected failure."""
    settings = get_settings()
    response = _search(
        token,
        _hybrid_body(query),
        params={"search_pipeline": settings.opensearch_search_pipeline},
    )
    if response.is_success:
        return "ok", _hit_ids(response, label="hybrid")
    text = response.text
    if _is_hybrid_dls_blocker(text):
        return "blocked", None
    raise RuntimeError(f"hybrid {response.status_code}: {text}")


def _run_dls_cases(mode: str, search_fn) -> None:
    searcher = _password_token(SEARCHER_USERNAME, SEARCHER_PASSWORD)
    realm_admin = _password_token(REALM_ADMIN_USERNAME, REALM_ADMIN_PASSWORD)

    _expect(
        f"{mode} searcher alpha",
        search_fn(searcher, "alpha-proof-token"),
        must={"proof-role-search-user"},
        must_not={"proof-group-engineering", "proof-nobody"},
    )
    _expect(
        f"{mode} searcher bravo (group-only miss)",
        search_fn(searcher, "bravo-proof-token"),
        must_not={"proof-group-engineering", "proof-nobody"},
    )
    _expect(
        f"{mode} searcher charlie (empty ACL miss)",
        search_fn(searcher, "charlie-proof-token"),
        must_not={"proof-nobody"},
    )
    _expect(
        f"{mode} realm-admin alpha",
        search_fn(realm_admin, "alpha-proof-token"),
        must={"proof-role-search-user"},
    )
    _expect(
        f"{mode} realm-admin bravo (group hit)",
        search_fn(realm_admin, "bravo-proof-token"),
        must={"proof-group-engineering"},
        must_not={"proof-nobody"},
    )
    _expect(
        f"{mode} realm-admin charlie (empty ACL miss)",
        search_fn(realm_admin, "charlie-proof-token"),
        must_not={"proof-nobody"},
    )


def run() -> None:
    """Upsert proof-* chunks and prove hybrid DLS as JWT users. Keeps the docs.

    On OpenSearch 3.8, JWT hybrid+DLS hits Landmine 13. Product contract stays
    hybrid-only; interim match/neural DLS proofs still run so RACL stays verified.
    """
    settings = get_settings()
    searcher = _password_token(SEARCHER_USERNAME, SEARCHER_PASSWORD)
    _jwt_cannot_index(searcher)

    with _admin_client() as client:
        for doc in PROOF_DOCS:
            body = {
                "file_id": f"file-{doc['_id']}",
                "chunk_id": doc["_id"],
                "chunk_seq": 0,
                "content": doc["content"],
                "allowed_roles": doc["allowed_roles"],
                "allowed_groups": doc["allowed_groups"],
            }
            response = client.put(
                f"/{settings.opensearch_index}/_doc/{doc['_id']}",
                params={"refresh": "true"},
                json=body,
            )
            if response.is_error:
                raise RuntimeError(f"index {doc['_id']} {response.status_code}: {response.text}")
            print(f"[ok] upserted {doc['_id']} {response.json().get('result')}")

        stored = client.get(f"/{settings.opensearch_index}/_doc/proof-role-search-user")
        if stored.is_error:
            raise RuntimeError(f"get proof doc {stored.status_code}: {stored.text}")
        embedding = (stored.json().get("_source") or {}).get("embedding") or []
        if len(embedding) != settings.opensearch_embedding_dim:
            raise RuntimeError(f"embedding dim {len(embedding)} != {settings.opensearch_embedding_dim}")
        print(f"[ok] ingest filled embedding dim {len(embedding)}")

    status, ids = _try_hybrid(searcher, "alpha-proof-token")
    hybrid_ok = status == "ok"
    if hybrid_ok:
        print(f"[ok] hybrid searcher alpha hits={ids}")
        _run_dls_cases(
            "hybrid",
            lambda token, q: _hit_ids(
                _search(
                    token,
                    _hybrid_body(q),
                    params={"search_pipeline": settings.opensearch_search_pipeline},
                )
            ),
        )
    else:
        print(
            "[blocked] JWT hybrid+DLS on OpenSearch 3.8 "
            "(BooleanQuery cannot be cast to HybridQuery). "
            "Keeping hybrid body as product contract; "
            "running interim match + neural DLS proofs. Wait for 3.9+ / security PR 6416."
        )
        _run_dls_cases(
            "match",
            lambda token, q: _hit_ids(_search(token, _match_body(q))),
        )
        _run_dls_cases(
            "neural",
            lambda token, q: _hit_ids(_search(token, _neural_body(q))),
        )

    # Confirm proof docs remain (C5).
    with _admin_client() as client:
        for doc in PROOF_DOCS:
            got = client.get(f"/{settings.opensearch_index}/_doc/{doc['_id']}")
            if got.is_error or not got.json().get("found"):
                raise RuntimeError(f"proof doc missing after proofs: {doc['_id']}")
        print("[ok] proof-* docs still present")

    print(
        f"[ok] proofs kept; hybrid={'PASS' if hybrid_ok else 'BLOCKED'}; "
        f"model={settings.opensearch_model_id} "
        f"ingest={settings.opensearch_ingest_pipeline} "
        f"search={settings.opensearch_search_pipeline}"
    )


if __name__ == "__main__":
    run()
