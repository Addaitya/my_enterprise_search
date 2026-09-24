# Search platform and client hybrid

Shipped search platform plus the 3.8 workaround. Sources: `prompts/summary/4_search_layer.md`, `prompts/summary/hybrid_search_issue.md`, `prompts/summary/6_search_view.md`.

## Index and model

- Image `opensearchproject/opensearch:3.8.0` and matching Dashboards. Heap 2g. Dashboards security plugin off. Live flags come from Compose environment; `opensearch.yml` on disk is reference.
- MiniLM `all-MiniLM-L6-v2` 1.0.2 ONNX, dim 384. Model id is stored in `backend/runtime_config.json` (gitignored). Skip re-register when the id is still present.
- Ingest pipeline `enterprise-search-embed`: `content` → `embedding`.
- Search pipeline `enterprise-search-hybrid`: `min_max` + `arithmetic_mean` weights `[0.3, 0.7]`. It is not the product hot path on 3.8.
- Index `enterprise-search-chunks`: `index.knn=true`, Lucene HNSW `cosinesimil`, ACL fields are keywords, `default_pipeline` set. If the index exists, fail on mapping drift. Never auto-delete it.

`files_searcher` DLS (groups clause has no extra `[]` on 3.8 JWKS):

```json
{
  "bool": {
    "should": [
      { "terms": { "allowed_roles": [${user.roles}] } },
      { "terms": { "allowed_groups": ${attr.jwt.groups} } }
    ],
    "minimum_should_match": 1
  }
}
```

Empty `allowed_roles` and `allowed_groups` are visible to nobody. Do not DLS on `sub`. ACL values are names, never Keycloak UUIDs. JWT users also need `cluster:admin/opensearch/ml/predict` and `models/get` so neural search works as the user.

Security REST is applied by `cd backend && uv run python -m init_services`. Do not use `securityadmin.sh` for JWT/DLS edits.

## Why client hybrid

Native `hybrid` plus DLS throws ClassCast (`BooleanQuery` → `HybridQuery`) on 3.8. `init_services.search_proof` still reports hybrid BLOCKED and then runs interim match and neural proofs. That script uses basic `admin` only to write `proof-*` docs and omits `embedding`.

Product `POST /search` never sends a native `hybrid` query:

- `search_mode=client_hybrid`
- Parallel `match` and `neural` with the user JWT (`search_neural_k=50`)
- FastAPI `min_max` then weights keyword `0.3`, neural `0.7` (missing side scores 0)
- `_source` excludes `embedding`
- Defaults: size 10, max size 50, snippet 400 chars, fetch multiplier 5, max fetch 100
- Model missing → 503. Other OpenSearch search errors → 502. Empty `q` → 400. No token → 401.

Service: `backend/app/services/opensearch_search.py`. Route: `backend/app/api/routes/search.py` with `require_product_user` and `user_bearer_header`.

Proof docs (no Postgres rows): `proof-role-search-user` (`alpha-proof-token`, role `search-user`), `proof-group-engineering` (`bravo-proof-token`, group `engineering`), `proof-nobody` (`charlie-proof-token`, empty ACL).
