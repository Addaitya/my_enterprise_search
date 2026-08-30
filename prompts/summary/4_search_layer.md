# Search platform — implemented 29 August 2026

This slice is **implemented as of 29 August 2026**. It is Task 3 (Search platform) only: OpenSearch stores chunks, auto-embeds them, can run hybrid (BM25 + neural) search, and **hides** chunks the caller’s JWT roles/groups do not match. `opensearch_model_id` is persisted. A second `init_services` run does not re-download the model.

Auth is live (`prompts/summary/2_auth_layer.md`). Postgres identity + `file_acl` exist (`prompts/summary/3_data_modeling.md`). OpenSearch was bumped to **3.8.0** with JWKS JWT (`prompts/cursor_summary/update_opensearch_version.md`). Working plan: `prompts/cursor_summary/6_search_setup.md` (C1–C7 locked).

**Not** in this slice: ingest API, chunker, MinIO upload, `POST /search`, search results UI, View files, admin ACL CRUD.

---

## Sources of truth (unchanged)

```
Keycloak     → authentication: users, realm roles, groups, memberships
Postgres     → identity mirror + files metadata + file_acl   (not used for proof docs)
OpenSearch   → chunks + embeddings + denormalized allowed_roles / allowed_groups
MinIO        → original bytes                                 (not this slice)
JWT          → request authn/authz and OpenSearch DLS
```

---

## Architecture (this slice)

```
init_services (basic admin)
  ├─ jwt_auth_domain          ← jwks_uri (Keycloak Docker DNS)
  ├─ files_searcher + DLS     ← backend_roles: search-user
  ├─ files_writer             ← mapped to nobody
  ├─ MiniLM register/deploy   → runtime_config.json
  ├─ ingest pipeline          → content → embedding
  ├─ search pipeline          → hybrid 0.3 / 0.7
  └─ index enterprise-search-chunks

proof (basic admin writes; user JWT reads)
  PUT  /enterprise-search-chunks/_doc/{proof-*}   (omit embedding)
  GET  /_search?search_pipeline=enterprise-search-hybrid
       Authorization: Bearer <user access token>
       (3.8: hybrid+DLS blocked → interim match/neural DLS proofs)
```

OpenSearch does **not** call Keycloak on each search. The client sends a Bearer token; OS verifies via JWKS, maps `search-user` → `files_searcher`, then DLS filters on `allowed_roles` / `allowed_groups`.

---

## What shipped

### A. OpenSearch ↔ Keycloak (C3)

`init_services/opensearch_security.py` (Security REST; compose flag `allow_securityconfig_modification` already set):

1. Merges `jwt_auth_domain`: `type: jwt`, **`jwks_uri`** = `http://keycloak:8080/realms/.../protocol/openid-connect/certs` (Docker DNS), `roles_key: roles`, `required_audience: api-client`, `required_issuer: http://localhost:8080/realms/enterprise-search-realm`. **Not** `openid`. PEM `signing_key` is emergency fallback only (not used on happy path).
2. PUTs OS role `files_searcher` with DLS on `allowed_roles` / `allowed_groups`, plus `cluster:admin/opensearch/ml/predict` **and** `cluster:admin/opensearch/ml/models/get` (C4; neural as JWT on 3.8).
3. PUTs OS role `files_writer` (unmapped to JWT users).
4. Maps backend role **`search-user` → `files_searcher`**. Does **not** map Keycloak `admin` → `files_searcher` or `all_access`.
5. Strips backend role `admin` from `all_access`; keeps internal user `admin` on `all_access`.
6. DLS groups clause uses `${attr.jwt.groups}` **without** extra `[]` (3.8 jwt+JWKS already expands a JSON array; wrapping produced `[["_empty"]]` and 500s). Roles still use `[${user.roles}]`.

Reference YAML (applied via REST, not volume-mounted):

| File | Purpose |
| --- | --- |
| `docker_service_configs/opensearch/security/jwt-auth-domain.yml.example` | JWKS + Docker DNS vs public issuer |
| `docker_service_configs/opensearch/security/roles.yml` | `files_searcher` DLS + predict + models.get; `files_writer` |
| `docker_service_configs/opensearch/security/rolesmapping.yml` | `search-user` → `files_searcher`; `all_access` users=`admin` only |

Enable command: `cd backend && uv run python -m init_services`. Do **not** use `securityadmin.sh` or remount `config.yml` for JWT/DLS edits.

### B. Settings

`backend/app/core/config.py`:

- Real field `opensearch_model_id: str | None = None` (removed hand-rolled `@property` that re-read JSON on every access).
- `get_settings()` still overlays `runtime_config.json`; `extra=ignore` stays.
- Pipeline / index name settings unchanged (`enterprise-search-embed`, `enterprise-search-hybrid`, `enterprise-search-chunks`).

### C. Model + pipelines + index

`init_services/opensearch.py`:

- ML Commons single-node settings; MiniLM `huggingface/sentence-transformers/all-MiniLM-L6-v2` **1.0.2**, **ONNX**, dim **384**.
- Persist `opensearch_model_id` in `backend/runtime_config.json` (gitignored). If id exists and model is present → skip register; redeploy only if needed.
- Ingest pipeline `enterprise-search-embed`: `text_embedding` `content` → `embedding` (`model_id` patched at runtime).
- Search pipeline `enterprise-search-hybrid`: `min_max` + `arithmetic_mean` weights `[0.3, 0.7]`.
- Index `enterprise-search-chunks`: `index.knn=true`, Lucene HNSW `cosinesimil`, ACL fields **keyword**, `default_pipeline` set.
- **G6:** if index already exists, GET mapping + settings; fail loudly on drift (wrong types / knn / dim / `default_pipeline`). **Never** auto-delete.

JSON on disk:

- `docker_service_configs/opensearch/index-mapping.json`
- `docker_service_configs/opensearch/ingest-pipeline.json`
- `docker_service_configs/opensearch/search-pipeline.json`

Local model id after proofs: `2PAsTqABzKlhu0IdV6uY` (volume-specific).

### D. Proof module (C4 / C5)

`backend/init_services/search_proof.py`:

- Default **off** from `run.py`; opt-in via `SEARCH_PROOF=1` or `uv run python -m init_services.search_proof`.
- Upserts three `proof-*` chunks as basic `admin` (omit `embedding`; fixed `_id`s; idempotent).
- Asserts ingest filled `embedding` length 384.
- Asserts JWT cannot index (403).
- Tries **hybrid** with `search_pipeline=enterprise-search-hybrid` as user JWT (product contract).
- On OpenSearch **3.8** Landmine 13 (`BooleanQuery` → `HybridQuery`), reports **BLOCKED** and runs interim **match + neural** DLS proofs (does **not** change the product contract to keyword-only or basic-admin search).
- **Keeps** `proof-*` docs after the run (C5).

| `_id` / `chunk_id` | `content` | `allowed_roles` | `allowed_groups` | Who should see it |
| --- | --- | --- | --- | --- |
| `proof-role-search-user` | `alpha-proof-token` | `["search-user"]` | `[]` | `searcher` and `realm-admin` |
| `proof-group-engineering` | `bravo-proof-token` | `[]` | `["engineering"]` | `realm-admin` only |
| `proof-nobody` | `charlie-proof-token` | `[]` | `[]` | nobody |

No Postgres `files` / `file_acl` rows for these. ACL values are **names**, never Keycloak UUIDs. Never write `_empty` into `allowed_groups`.

### E. Compose / pin

- OpenSearch image **3.8.0**, Dashboards **3.8.0**, heap ≥2g, security plugin on, Dashboards security plugin **off**.
- `opensearch.yml` on disk is **reference**; live ML / securityconfig flags come from compose **environment**.

---

## DLS query (from live JWT)

Template on `files_searcher` (groups **no** extra `[]`):

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

After substitution for `realm-admin` (`roles: ["admin","search-user"]`, `groups: ["engineering"]`):

```json
{
  "bool": {
    "should": [
      { "terms": { "allowed_roles": ["admin", "search-user"] } },
      { "terms": { "allowed_groups": ["engineering"] } }
    ],
    "minimum_should_match": 1
  }
}
```

Empty `allowed_roles` + `allowed_groups` → visible to **nobody** under DLS. Do not DLS on `sub` or `realm_access.roles`.

---

## Hybrid query (product contract; Task 5 later)

```json
GET /enterprise-search-chunks/_search?search_pipeline=enterprise-search-hybrid
{
  "query": {
    "hybrid": {
      "queries": [
        { "match": { "content": "<q>" } },
        { "neural": { "embedding": { "query_text": "<q>", "model_id": "<id>", "k": 50 } } }
      ]
    }
  },
  "_source": { "excludes": ["embedding"] }
}
```

`model_id` from `runtime_config.json`. Searches must use the **user** JWT, never basic `admin` (admin skips DLS).

---

## Intentional deviations / landmines hit

1. **JWT hybrid + DLS blocked on 3.8 (Landmine 13).**  
   DLS wraps the top-level `hybrid` query; 3.8 throws `BooleanQuery cannot be cast to HybridQuery`. Keyword and neural-only DLS **pass**. Upstream fix: security PR [#6416](https://github.com/opensearch-project/security/pull/6416) on OpenSearch **3.9+**.

2. **Human lock 29 Aug 2026 (updated):** stay on **3.8**; keep hybrid as product contract. Platform `search_proof` native hybrid stays **BLOCKED**. Product Task 5 `POST /search` is **unblocked** via **client-side hybrid** (match ∥ neural + merge) — see `prompts/cursor_summary/hybrid_search_issue_sol.md`. Do **not** ship keyword-only or admin search.

3. **Extra `[]` on `${attr.jwt.groups}`** on 3.8 jwt+JWKS → `[["_empty"]]` and DLS 500s. Bare `${attr.jwt.groups}`; keep `[${user.roles}]`.

4. **`jwks_uri` must be Docker DNS** (`http://keycloak:8080/.../certs`). `localhost` inside the OS container fails. `required_issuer` stays the public `http://localhost:8080/...` issuer.

5. **`models/get`** required on `files_searcher` for neural as JWT on 3.8 (in addition to `predict`). Do not map `ml_full_access`.

6. **JWT `admin` must not map to `all_access` / `files_searcher`.** Internal basic user `admin` stays `all_access` via `users`. Seed `realm-admin` searches because it also has `search-user`.

7. **G6:** existing wrong mapping → fail loudly; human deletes index if this local volume may be wiped. No auto-delete.

---

## Automated proofs already run (29 August 2026)

| # | Test | Result |
| --- | --- | --- |
| 1 | `authinfo` searcher = `files_searcher`, not `all_access` | **PASS** (JWKS JWT) |
| 2 | `authinfo` realm-admin = `files_searcher`, not `all_access` | **PASS** |
| 3 | JWT searcher cannot index a doc | **PASS** (403) |
| 4 | Basic admin cluster health 200 | **PASS** (3.8.0 green) |
| 5 | Model deployed; `opensearch_model_id` in runtime JSON | **PASS** |
| 6 | Second init does not re-register | **PASS** |
| 7 | Ingest fills `embedding` (dim 384) | **PASS** |
| 8 | Hybrid searcher hits role-granted chunk | **BLOCKED** — BooleanQuery→HybridQuery. Neural-only **PASS** |
| 9 | Hybrid searcher misses group-only chunk | **BLOCKED**. Keyword/neural DLS miss **PASS** |
| 10 | Hybrid realm-admin hits group-only chunk (`engineering`) | **BLOCKED**. Keyword DLS hit **PASS** |
| 11 | Hybrid both miss empty-ACL chunk | **BLOCKED**. Keyword DLS miss **PASS** |
| 12 | `proof-*` docs still present after proofs | **PASS** |
| 13 | `/health` + `/auth/me` still 200 | **PASS** |
| — | G6 mapping/settings check on existing index | **PASS** |
| — | Second `search_proof` upsert same `_id`s | **PASS** |

---

## Files touched / created

```
backend/app/core/config.py                    # opensearch_model_id real Settings field
backend/init_services/opensearch.py           # MiniLM, pipelines, index, G6 drift check
backend/init_services/opensearch_security.py  # JWKS jwt domain; DLS; ML predict + models.get
backend/init_services/search_proof.py         # NEW: proof docs + hybrid attempt + interim DLS
backend/init_services/run.py                  # SEARCH_PROOF=1 opt-in
docker_service_configs/opensearch/index-mapping.json
docker_service_configs/opensearch/ingest-pipeline.json
docker_service_configs/opensearch/search-pipeline.json
docker_service_configs/opensearch/security/jwt-auth-domain.yml.example
docker_service_configs/opensearch/security/roles.yml
docker_service_configs/opensearch/security/rolesmapping.yml   # NEW reference
docker-compose.yml                            # OpenSearch 3.8.0 pin (with upgrade slice)
README.md                                     # version / JWKS notes
backend/runtime_config.json                   # runtime only; gitignored; holds model id
```

No new FastAPI routes. No frontend files. No Postgres writes for proofs.

---

## How to re-verify

```bash
docker compose ps   # opensearch 9200 healthy, keycloak 8080

cd backend && uv run python -m init_services
# expect: model already DEPLOYED, mapping/settings match, no new register

uv run python -m init_services.search_proof
# expect: upsert OK, embedding dim 384, hybrid BLOCKED, match/neural DLS [ok], proof-* kept

# or: SEARCH_PROOF=1 uv run python -m init_services

curl -sS http://localhost:8000/health
# with searcher Bearer: curl -sS -H "Authorization: Bearer $TOKEN" http://localhost:8000/auth/me
```

---

## What was intentionally not done

- Upload, PDF/TXT parse, chunker, MinIO put (Task 4).
- `POST /search`, strip `embedding` in API response, results UI, Open/download (Task 5 — product path = **client hybrid** on 3.8; see `hybrid_search_issue_sol.md` / summary 6 when shipped).
- Writing `files` / `file_acl` or `update_by_query` from Postgres (Task 6).
- Mapping JWT users to `files_writer` or `ml_full_access`.
- Switching cluster to dedicated ML nodes.
- TorchScript model format (ONNX only).
- Deleting `proof-*` after proofs (kept by design).

---

## Follow-on

| Task | Needs from this platform |
| --- | --- |
| 4 Ingest | Index + default ingest pipeline; bulk index omit `embedding`; ACL **names** on each chunk; basic admin writes |
| 5 Search/view API | Forward **user** JWT; **client-side hybrid** on 3.8 (match ∥ neural + merge); `_source` exclude `embedding`; DLS in OS — see `hybrid_search_issue_sol.md` |
| 6 Admin ACL | `update_by_query` on `file_id`; same keyword ACL fields |
| 7 Hardening | Map ingest to `files_writer` instead of `all_access` |
| OpenSearch 3.9+ | Re-run `search_proof.py` hybrid path after Hub publishes `3.9.0` (security PR 6416) |

Plan source of truth for this slice: `prompts/cursor_summary/6_search_setup.md`.
Product Search on 3.8 (client hybrid): see `prompts/summary/6_search_view.md` and `prompts/cursor_summary/hybrid_search_issue_sol.md`.
