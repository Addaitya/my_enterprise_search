# Search platform setup — implementation plan (Task 3)

Working notes to implement **Task 3 (Search platform)** from `prompts/cursor_summary/2_project_overview_tasks.md`. Auth is live (`prompts/summary/2_auth_layer.md`). Postgres identity + `file_acl` exist (`prompts/summary/3_data_modeling.md`). OpenSearch was bumped to **3.8.0** with JWKS JWT (`prompts/cursor_summary/update_opensearch_version.md`). This file is the source of truth for the search-platform slice. Do not invent a second ACL model or a second JWT path.

**Agent rules while implementing**
- Run and execute code to confirm it works before moving on.
- Do not proceed past a broken step; fix it first.
- Where something cannot be verified in this environment, leave a clear human check and wait for feedback.
- Do **not** start the ingest API, chunker, MinIO upload, `POST /search`, search results UI, View files, or admin ACL CRUD. Cluster + pipelines + index + **proof documents** only.
- Treat **Locked decisions** as law.

Human locked C1–C7 on 29 August 2026 (chat). JWT sample from `realm-admin` / `web-client` is the DLS contract.

---

## What “done” means

OpenSearch can store chunks, auto-embed them, run hybrid (BM25 + neural) search, and **hide** chunks the caller’s JWT roles/groups do not match. `opensearch_model_id` is persisted. A second `init_services` run does not re-download the model.

| Actor | What they may do in this slice |
| --- | --- |
| `init_services` | JWT domain (JWKS), OS roles + DLS + ML predict/models.get, MiniLM register/deploy, ingest + search pipelines, index mapping |
| Proof script | Index labeled `proof-*` chunks as basic `admin`; **hybrid** search with user JWTs; **keep** the chunks |
| FastAPI | Unchanged product APIs. Still no `/search` |
| React | Unchanged |
| Postgres / MinIO | Unchanged. Proof docs do **not** create `files` / `file_acl` rows |

**OpenSearch pin:** `3.8.0` (see `update_opensearch_version.md`). JWT uses `type: jwt` + `jwks_uri` (Docker DNS). **Blocker:** JWT **hybrid** + DLS on 3.8 raises `BooleanQuery cannot be cast to HybridQuery`. Keyword and neural-only DLS **pass**. Product still requires hybrid (C4); wait for OpenSearch **3.9+** (security PR 6416) or human override.

---

## Current state (after 3.8 upgrade — 29 Aug 2026)

Already in place from Tasks 0–2 + OpenSearch 3.8 upgrade:

### Keycloak (identity; not file ACL)

- Realm `enterprise-search-realm`. Clients `api-client` (confidential) and `web-client` (public + PKCE).
- Realm roles **`admin`** and **`search-user`** (plus Keycloak built-ins mirrored in Postgres).
- Groups `engineering`, `_empty` (sentinel so the `groups` claim is never omitted).
- Flattened JWT claims: top-level `roles[]`, top-level `groups[]` (`full.path: false`), `aud` includes `api-client`.
- Seed: `realm-admin` (`admin` + `search-user`, group `engineering`); `searcher` (`search-user` only, group `_empty`).

### OpenSearch ↔ Keycloak (live on 3.8.0)

`init_services/opensearch_security.py`:

1. Merges `jwt_auth_domain` (`type: jwt`, `jwks_uri` = Keycloak Docker DNS certs, `roles_key: roles`, `required_audience: api-client`, `required_issuer: http://localhost:8080/realms/enterprise-search-realm`). **Not** `openid`. PEM `signing_key` is emergency fallback only (not used on happy path).
2. Puts OS role `files_searcher` with DLS on `allowed_roles` / `allowed_groups`, plus `cluster:admin/opensearch/ml/predict` **and** `cluster:admin/opensearch/ml/models/get`.
3. Puts OS role `files_writer` (unmapped to JWT users).
4. Maps backend role **`search-user` → `files_searcher`**. Does **not** map Keycloak `admin` → `files_searcher` or `all_access`.
5. Strips backend role `admin` from `all_access`; keeps internal user `admin` on `all_access`.
6. DLS groups clause uses `${attr.jwt.groups}` **without** extra `[]` (3.8 jwt+JWKS already expands a JSON array; wrapping produced `[["_empty"]]` and 500s). Roles still use `[${user.roles}]`.

Auth proofs: JWT `authinfo` is `files_searcher`, not `all_access` (searcher + realm-admin). JWT cannot index; basic `admin` can.

### OpenSearch cluster (3.8.0 — mostly proved)

`init_services/opensearch.py`: ML Commons settings, MiniLM register/deploy (**ONNX**), ingest/search pipelines, index create-if-missing.

JSON on disk (applied via REST / code, not volume-mounted security YAML):

- `docker_service_configs/opensearch/index-mapping.json` — knn 384, Lucene HNSW, `cosinesimil`, ACL fields `keyword`
- `docker_service_configs/opensearch/ingest-pipeline.json` — `text_embedding` `content` → `embedding` (`model_id` patched at runtime)
- `docker_service_configs/opensearch/search-pipeline.json` — `min_max` + `arithmetic_mean` weights `[0.3, 0.7]`
- `docker_service_configs/opensearch/security/roles.yml` — reference copy of DLS + ML perms (applied via REST)
- `docker_service_configs/opensearch/security/rolesmapping.yml` — `search-user` → `files_searcher`
- `docker_service_configs/opensearch/security/jwt-auth-domain.yml.example` — JWKS + Docker-DNS vs public issuer

Proved on 3.8.0:

- Model deployed; `opensearch_model_id` in `runtime_config.json` (e.g. `2PAsTqABzKlhu0IdV6uY`); second init skips re-register.
- Ingest fills `embedding` dim 384; `proof-*` docs upserted and **kept**.
- DLS hit/miss with **match / neural** as JWT users (role grant, group grant, empty ACL).
- Neural-only JWT search returns hits under DLS.

Still open:

- **JWT hybrid + DLS** (`search_pipeline=enterprise-search-hybrid`) → `ClassCastException: BooleanQuery cannot be cast to HybridQuery`. Upstream fix = OpenSearch **3.9+** (security PR 6416). Do **not** fall back to keyword-only or basic-admin search (C4).
- If the index already exists with wrong mapping, `ensure_index_and_pipelines` fails loudly (G6); does not auto-delete.
- `Settings.opensearch_model_id` may still be a hand-rolled `@property` — clean up when touching config.

### Postgres (do not use for proof docs)

`file_id` in OpenSearch is a UUID **string** matching `files.id` later. This slice’s proof chunks use fake ids (`proof-*`). `allowed_roles` / `allowed_groups` must be **names** (`search-user`, `engineering`), never Keycloak UUIDs. Viewer and editor are both “readable”; DLS does not distinguish them. Do not copy user-principal ACL into OpenSearch (G2 / data-model plan).

---

## Human gate — decisions to lock

### G1. Slice boundary

| | |
| --- | --- |
| Status | **LOCKED 29 Aug 2026 (C2)** |
| Decision | This file is **Task 3 only**: cluster, JWT/DLS configs + apply command, MiniLM, pipelines, index, proof docs. **Not** Task 4 ingest API. **Not** Task 5 `POST /search` / results UI. |
| Why | Matches `2_project_overview_tasks.md`. Search API needs a stable index + proven DLS; UI needs the API. Proofs run as curl / `uv run python`, not as product routes. |

### G2. Keycloak roles vs OpenSearch security roles

| | |
| --- | --- |
| Status | **LOCKED 29 Aug 2026 (C1)** |
| Decision | Do **not** create OpenSearch roles named `search-user` or `admin`. Keep: Keycloak realm roles `admin` / `search-user`; OpenSearch roles `files_searcher` (DLS, read) and `files_writer` (write, unmapped). Map **only** backend role `search-user` → `files_searcher`. Product admins still search because seed `realm-admin` also has `search-user`. Internal basic user `admin` stays `all_access` for ingest / model deploy. |
| Why | Naming OS roles the same as Keycloak roles collides with the internal user `admin`. DLS still sees JWT `roles` via `${user.roles}`, so a file granted to realm role `admin` is visible to this token. |

### G3. JWT connection + DLS from the live token

| | |
| --- | --- |
| Status | **LOCKED 29 Aug 2026 (C3)** — human: do what it takes |
| Decision | Ship the full Keycloak ↔ OpenSearch path: visible jwt domain + `roles.yml` DLS + `rolesmapping.yml`, DLS from live JWT (top-level `roles` / `groups`), and **apply** via `init_services` Security REST until `authinfo` + DLS proofs pass. Keep `type: jwt` + `jwks_uri` (Docker DNS). Not `openid`, not PEM-only, not `securityadmin.sh`, not container recreate for config edits. Hybrid+DLS proofs remain gated by Landmine 13 on 3.8. |
| Why | Connection and role map must be readable in files and live on the cluster. OpenSearch 3.8 verifies JWT via Keycloak JWKS. |

### G4. All searches are hybrid (user JWT + ML predict)

| | |
| --- | --- |
| Status | **LOCKED 29 Aug 2026 (C4)** — human: all searches must be hybrid |
| Decision | **Every** search (proofs now, `POST /search` later) is hybrid: `match` + `neural` with `search_pipeline=enterprise-search-hybrid`, authenticated as the **user JWT**. **Proactively** add `cluster:admin/opensearch/ml/predict` **and** `cluster:admin/opensearch/ml/models/get` to `files_searcher` (in `roles.yml` and the REST PUT). Do **not** wait for a 403. Do **not** map `ml_full_access`. Do **not** fall back to keyword-only or basic `admin` for search. On **3.8.0**, JWT hybrid+DLS is blocked upstream (see Locked decisions / Landmine 13); keep the hybrid body and wait for **3.9+** rather than changing the product contract. |
| Why | Neural needs predict (+ models.get on 3.8) at query time. Admin search skips DLS. Keyword-only is not the product. |

### G5. Proof documents

| | |
| --- | --- |
| Status | **LOCKED 29 Aug 2026 (C5)** — human: keep chunks after testing |
| Decision | Index labeled `proof-*` chunks, run hybrid + DLS proofs, **leave them in the index**. Proof module is idempotent upsert (same `_id`s). Do **not** delete after proofs. |
| Why | Human wants fixtures available for re-checks. Task 5 may see `proof-*` hits until cleaned manually — that is accepted. |

### G6. Existing index with wrong mapping

| | |
| --- | --- |
| Status | **LOCKED 29 Aug 2026 (C6)** |
| Decision | If `enterprise-search-chunks` exists, GET mapping + settings. If required fields / knn / `default_pipeline` are missing or wrong, **fail loudly** and tell the human to delete the index. Do **not** auto-delete. Optional: PUT `_mapping` only to **add** missing fields that are safe. |
| Why | Auto-delete is destructive once real chunks exist. |

### G7. Group DLS and JWT arrays

| | |
| --- | --- |
| Status | **LOCKED 29 Aug 2026 (C7)** |
| Decision | Keep DLS `should` on both `allowed_roles` (`${user.roles}`) and `allowed_groups` (`${attr.jwt.groups}`). Prove **both**. If groups expansion 500s or never matches, fix the **claim shape** rather than dropping group DLS. Never put `_empty` in `allowed_groups`. |
| Why | Product ACL is RACL on roles **and** groups. The captured token already has `"groups": ["engineering"]`. |

---

## C1–C7 lock (29 Aug 2026)

| Id | Human | Outcome |
| --- | --- | --- |
| C1 | Continue with proposal | G2 locked. No OS roles named `search-user` / `admin`. |
| C2 | Continue with proposal | G1 locked. Task 3 = platform only. |
| C3 | Do what it takes | G3 locked. Visible configs + apply until live. See below. |
| C4 | All searches must be hybrid; do what it takes | G4 locked. **Decision:** add ML predict + models.get on `files_searcher` up front. Hybrid+DLS blocked on 3.8 — see below. |
| C5 | Keep proof chunks after testing | G5 locked. No delete after proofs. |
| C6 | Continue with proposal | G6 locked. Fail loudly; no auto-delete of product index. |
| C7 | Continue with proposal | G7 locked. Keep group DLS; fix claim shape if proofs fail. |

### How OpenSearch connects to Keycloak (C3)

OpenSearch does **not** have a Keycloak URL it calls on each search. Keycloak never talks to OpenSearch either. The user sends a Bearer token; OpenSearch checks it locally.

```
Browser / FastAPI
    Authorization: Bearer <access_token>
         │
         ▼
OpenSearch jwt_auth_domain
    1. Resolve signing key(s) from jwks_uri (Keycloak Docker DNS certs, cached)
    2. Check iss + aud match the token
    3. roles_key: roles  →  backend_roles = ["admin", "search-user"]
    4. groups stay on the JWT as attr.jwt.groups = ["engineering"]
         │
         ▼
rolesmapping.yml
    backend role "search-user"  →  OS role files_searcher
         │
         ▼
files_searcher DLS
    show docs where allowed_roles ∩ {admin, search-user}
                  OR allowed_groups ∩ {engineering}
```

**Where the config lives** (compose does **not** mount these; Python PUTs them):

| Question | File | OpenSearch API (the enable command) |
| --- | --- | --- |
| How does OS know this JWT is from Keycloak? | `docker_service_configs/opensearch/security/jwt-auth-domain.yml.example` | `PUT /_plugins/_security/api/securityconfig/config` |
| What may a search user do, and which docs? | `docker_service_configs/opensearch/security/roles.yml` | `PUT /_plugins/_security/api/roles/files_searcher` |
| How does KC `search-user` become OS `files_searcher`? | `docker_service_configs/opensearch/security/rolesmapping.yml` | `PUT /_plugins/_security/api/rolesmapping/files_searcher` |

`init_services/opensearch_security.py` issues those PUTs (needs compose flag `allow_securityconfig_modification`, already set).

**What rebuild / enable means**

| Action | When |
| --- | --- |
| `cd backend && uv run python -m init_services` | After you edit jwt domain, roles, rolesmapping, or DLS. This **is** the OpenSearch enable command. |
| Recreate OpenSearch container | Only if you change compose **environment** (heap, securityconfig flag, ML flags). Not needed for JWT/DLS edits. |
| `securityadmin.sh` / mount `config.yml` | **Do not.** This repo uses the Security REST API. |
| Re-run init after Keycloak realm key rotation | No — JWKS cache picks up a new `kid`. Re-init only if `jwks_uri` / issuer / audience change. |

Do not switch to `openid`. Do not map JWT `admin` to `all_access`.

### C4 decision (agent — all searches hybrid)

**Decided:** add these cluster permissions to `files_searcher` **before** proofs (not after a 403):

```yaml
cluster_permissions:
  - "cluster_composite_ops_ro"
  - "cluster:admin/opensearch/ml/predict"
  - "cluster:admin/opensearch/ml/models/get"   # required on 3.8 for neural as JWT
```

Update both `roles.yml` and `opensearch_security.py` PUT body. Keep index actions `read` + `search` + DLS. Do **not** map `ml_full_access` / `ml_readonly_access`.

Hybrid is two queries under one user JWT:

1. **Keyword:** `match` on `content` — no model.
2. **Neural:** MiniLM **predict** at query time → knn on `embedding`.

Without predict/models.get: neural 403. Searching as basic `admin`: DLS skipped (security hole). Keyword-only: not allowed for product or proofs.

Proofs and later Task 5 use only:

`GET .../_search?search_pipeline=enterprise-search-hybrid` with the hybrid body. No keyword-only fallback.

**3.8 status:** that hybrid call as `files_searcher` currently 500s (`BooleanQuery`→`HybridQuery`). Neural-only and keyword DLS proofs pass. Keep trying hybrid in `search_proof.py`; do not change the contract. Details in `update_opensearch_version.md` Implementation log.

### C5 decision (keep proof chunks)

Task 4 (upload) does not exist yet. Insert three **fake** chunks as basic `admin`, run **hybrid** searches with user JWTs, **leave them indexed**.

| chunk_id | content (unique phrase) | allowed_roles | allowed_groups | Who should see it |
| --- | --- | --- | --- | --- |
| `proof-role-search-user` | `alpha-proof-token` | `["search-user"]` | `[]` | `searcher` and `realm-admin` |
| `proof-group-engineering` | `bravo-proof-token` | `[]` | `["engineering"]` | `realm-admin` only |
| `proof-nobody` | `charlie-proof-token` | `[]` | `[]` | nobody |

Optional fourth: `proof-role-admin` with `allowed_roles: ["admin"]`.

Re-run upserts the same `_id`s (idempotent). Task 5 may return these until someone deletes them by hand — accepted. No Postgres `files` rows for them.

---

## Locked decisions (platform / process)

| Topic | Decision |
| --- | --- |
| OpenSearch | 3.8.0, security plugin on, Dashboards security plugin **off** |
| Authenticator | `http_authenticator.type: jwt` only. `jwks_uri` (Docker DNS). Not `openid`. PEM is fallback only |
| Issuer | Token `iss` = `http://localhost:8080/realms/enterprise-search-realm`. `jwks_uri` = `http://keycloak:8080/realms/.../protocol/openid-connect/certs` |
| Audience | `required_audience: api-client` |
| `roles_key` | `roles` (flattened realm roles) |
| Keycloak product roles | `admin`, `search-user` — already created; this slice does not recreate them |
| OS search role | `files_searcher`: `read` + `search` + DLS + **`cluster:admin/opensearch/ml/predict`** + **`cluster:admin/opensearch/ml/models/get`**. Map backend role `search-user` only |
| OS write role | `files_writer`: crud/manage, **no DLS**, **not** mapped to JWT. Ingest stays basic `admin` / `all_access` until Task 7 |
| Do not map | JWT `admin` → `all_access`. JWT users → `files_writer` or `ml_full_access` |
| Search mode | **Hybrid only** (match + neural + search pipeline). No keyword-only product path. **3.8 JWT hybrid + DLS is blocked** (BooleanQuery→HybridQuery); official fix is OpenSearch **3.9+** (security PR 6416). **Human 29 Aug 2026:** stay on 3.8; interim match/neural DLS proofs only; Task 5 waits. See `update_opensearch_version.md`. |
| DLS query | Top-level JWT `roles` / `groups` only. `should` terms on `allowed_roles` = `[${user.roles}]` **or** `allowed_groups` = `${attr.jwt.groups}` (no extra `[]` on groups in 3.8). Not `realm_access.roles`. |
| ACL field types | `allowed_roles`, `allowed_groups` must stay **keyword** (not `text`) |
| ACL values | Role/group **names**, not UUIDs. Include viewer **and** editor names. No user ids in v1 |
| `_empty` | Must never appear in `allowed_groups` |
| Empty ACL | Doc with empty `allowed_roles` and `allowed_groups` is visible to **nobody** under DLS |
| Embedding | Cluster MiniLM `huggingface/sentence-transformers/all-MiniLM-L6-v2` **1.0.2**, **ONNX**, dim **384**. FastAPI does **not** embed |
| Ingest pipeline | `enterprise-search-embed`; `text_embedding` maps `content` → `embedding`; index `default_pipeline` |
| Search pipeline | `enterprise-search-hybrid`; `min_max` + `arithmetic_mean` `[0.3, 0.7]` (keyword, neural) |
| Index | `enterprise-search-chunks`; `index.knn=true`; Lucene HNSW `cosinesimil` |
| Search credentials | User access token. Helper `user_bearer_header()` already exists |
| Write credentials | HTTP basic `admin` / `OPENSEARCH_INITIAL_ADMIN_PASSWORD` |
| Model id | Persist `opensearch_model_id` in `backend/runtime_config.json` (gitignored). Do not re-register if id exists and model is present |
| Proof data | Not in Postgres. **Keep** `proof-*` docs in OpenSearch after proofs (idempotent upsert) |
| Product APIs | None in this slice |

Sources of truth (unchanged):

```
Keycloak     → authentication: users, realm roles, groups, memberships
Postgres     → identity mirror + files metadata + file_acl   (not this slice)
OpenSearch   → chunks + embeddings + denormalized allowed_roles / allowed_groups
MinIO        → original bytes                                 (not this slice)
JWT          → request authn/authz and OpenSearch DLS
```

---

## Out of scope (do not do in this slice)

- Upload, PDF/TXT parse, chunker, MinIO put
- `POST /search`, strip `embedding` in API response, results UI, Open/download
- Writing `files` / `file_acl` or `update_by_query` from Postgres
- Admin create user/role/group
- Mapping JWT users to OpenSearch Dashboards
- Switching cluster to dedicated ML nodes
- TorchScript model format (already known broken on this version)

---

## Target filesystem (create / change)

```
backend/app/core/config.py                    # optional opensearch_model_id field; stop the hand-rolled property (if still present)
backend/init_services/opensearch.py           # mapping drift check; keep register/deploy/pipelines
backend/init_services/opensearch_security.py  # JWKS jwt domain; DLS + mapping; ML predict + models.get on files_searcher
backend/init_services/search_proof.py         # upsert proof docs, hybrid + DLS proofs; keep docs (hybrid blocked on 3.8)
backend/init_services/run.py                  # optional: call search_proof behind SEARCH_PROOF=1; default off
docker_service_configs/opensearch/index-mapping.json      # already correct; change only if proofs demand it
docker_service_configs/opensearch/ingest-pipeline.json    # already; model_id still patched in code
docker_service_configs/opensearch/search-pipeline.json    # already
docker_service_configs/opensearch/security/jwt-auth-domain.yml.example  # JWKS + Docker DNS vs public issuer
docker_service_configs/opensearch/security/roles.yml                    # files_searcher DLS + predict + models.get
docker_service_configs/opensearch/security/rolesmapping.yml             # search-user → files_searcher
backend/runtime_config.json                  # created at runtime; gitignored; must contain opensearch_model_id
```

No new FastAPI routes. No frontend files.

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
  POST /enterprise-search-chunks/_doc   (omit embedding)
  GET  /_search?search_pipeline=enterprise-search-hybrid
       Authorization: Bearer <user access token>
```

### A. Connection of OpenSearch to Keycloak (contract)

Visible files + `init_services` PUT. DLS is written for the captured `realm-admin` JWT.

#### A1. Roles

| Store | Names | Purpose |
| --- | --- | --- |
| Keycloak realm | `search-user`, `admin` | Product access + JWT `roles`. **Already created.** |
| OpenSearch | `files_searcher` | Search/read + DLS. Mapped from JWT/`roles_key` value `search-user`. |
| OpenSearch | `files_writer` | Ingest/ACL writes later. Not on JWT users. |
| OpenSearch internal | user `admin` | Basic auth, `all_access`, no DLS. |

Do not create a second pair of OS roles named after Keycloak.

#### A2. Connection config (`jwt_auth_domain`)

Already PUT by `opensearch_security.py`. Required fields:

| Key | Value |
| --- | --- |
| `http_authenticator.type` | `jwt` |
| `challenge` | `false` |
| `jwks_uri` | `http://keycloak:8080/realms/enterprise-search-realm/protocol/openid-connect/certs` |
| `jwt_header` | `Authorization` |
| `subject_key` | `preferred_username` |
| `roles_key` | `roles` |
| `required_audience` | `api-client` |
| `required_issuer` | `http://localhost:8080/realms/enterprise-search-realm` |
| `authentication_backend` | `noop` |
| Basic domain | **kept enabled**, order > JWT |

Do **not** wrap `${attr.jwt.groups}` in extra `[]` on 3.8 (it is already a JSON array). `${user.roles}` still needs `[${user.roles}]`.

Keycloak realm key rotation does not require re-init.

#### A3. Role mapping (`rolesmapping.yml`)

File: `docker_service_configs/opensearch/security/rolesmapping.yml`. Applied by `PUT .../rolesmapping/files_searcher`.

| Backend role (JWT `roles`) | OS security role |
| --- | --- |
| `search-user` | `files_searcher` |
| `admin` (JWT) | **none** (must not be `all_access`) |
| internal user `admin` | `all_access` via `users: ["admin"]` |

`${user.roles}` in DLS still expands to the JWT role **names**, including `admin` for `realm-admin`. File ACL granted to realm role `admin` therefore matches that user without mapping `admin` → `files_searcher`.

#### A4. DLS (from the captured JWT)

Index fields (keyword): `allowed_roles`, `allowed_groups`.

JWT claims used (ignore `realm_access`):

| JWT field | OpenSearch substitution | This token expands to |
| --- | --- | --- |
| `roles`: `["admin", "search-user"]` | `${user.roles}` after `roles_key: roles` | `"admin", "search-user"` |
| `groups`: `["engineering"]` | `${attr.jwt.groups}` (no extra `[]`) | `["engineering"]` |

Template (what we store on `files_searcher` — note groups have **no** extra `[]`):

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

Same query **after** substitution for this `realm-admin` token:

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

A chunk is visible if it lists any of those roles **or** groups. Empty arrays → nobody. `searcher` tokens still carry `_empty` so `${attr.jwt.groups}` is never missing; never write `_empty` into documents. Do not DLS on `sub` or `realm_access.roles`.

### B. Index mapping (per chunk)

| Field | Mapping |
| --- | --- |
| `file_id`, `chunk_id` | keyword |
| `chunk_seq` | integer |
| `meta_file_type`, `meta_file_size` | keyword, long |
| `updated_at`, `uploaded_at` | date |
| `content` | text (BM25) |
| `embedding` | knn_vector 384, lucene hnsw, cosinesimil |
| `allowed_roles`, `allowed_groups` | keyword |
| `object_store_path`, `ingestion_type`, `original_source` | keyword |

Settings: `index.knn=true`, `number_of_replicas=0` (single node), `default_pipeline` = ingest pipeline name.

### C. Hybrid query (proof and later Task 5)

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

`model_id` from `runtime_config.json`. **Do not** change the product contract to keyword-only (C4). On 3.8.0, hybrid+DLS as JWT is blocked — see Landmine 13; interim DLS proofs used match/neural only.

---

## Landmines

### 1. JWT `admin` + `all_access`

Do not add `admin` to `files_searcher` or `all_access` **backend_roles**. Internal user `admin` must remain on `all_access` via `users`.

### 2. DLS + a non-DLS role

If a JWT user also gets `all_access` / `files_writer`, DLS is skipped or mixed. Search users: `files_searcher` only.

### 3. `allowed_roles` as `text`

Unicode analyzer splits names. DLS `terms` then miss. Keep **keyword**.

### 4. Missing `groups` claim

Keycloak omits empty arrays. `_empty` sentinel stays. FastAPI/SPA still strip `_empty` from product JSON; OpenSearch DLS still sees it in the raw JWT. Documents must not list `_empty`.

### 5. Neural 403 as JWT user

`files_searcher` must include `cluster:admin/opensearch/ml/predict` **and** `cluster:admin/opensearch/ml/models/get` before proofs. Do not fall back to basic admin or keyword-only.

### 6. Index exists without `default_pipeline`

Proof docs would have null `embedding`. Check settings; fail if pipeline missing.

### 7. Re-registering MiniLM every boot

If `opensearch_model_id` is set and the model exists, skip register. Redeploy after node restart only. After a volume wipe, clear the model id in `runtime_config.json` so init re-registers.

### 8. TorchScript vs ONNX

Keep `MODEL_FORMAT = "ONNX"`. Do not “fix” it back to the overview’s TorchScript line.

### 9. Proof docs stay in the index

`proof-*` chunks remain after tests (C5). Task 5 search may return them. Distinct phrases (`alpha-proof-token`, etc.). No Postgres `files` rows. Manual delete later if desired.

### 10. `opensearch.yml` is not mounted

Compose sets ML + securityconfig flags via **environment**. Editing `docker_service_configs/opensearch/opensearch.yml` does nothing until it is mounted. Do not assume the YAML file is live.

### 11. Writes ignore DLS

Proof writes **must** use basic `admin`. JWT searcher must **not** be able to index.

### 12. Dual-write is later

This slice does not read `file_acl`. Hardcode ACL names on proof docs.

### 13. JWT hybrid + DLS on OpenSearch 3.8 (blocker)

DLS wraps the top-level `hybrid` query; 3.8 then throws `BooleanQuery cannot be cast to HybridQuery`. Keyword/neural + DLS work; JWKS and predict are fine. Fix is security PR [#6416](https://github.com/opensearch-project/security/pull/6416) on OpenSearch **3.9+** (no Hub tag yet as of 29 Aug 2026). **Do not** ship keyword-only or admin search as a workaround. See `update_opensearch_version.md`.

### 14. Extra `[]` on `${attr.jwt.groups}`

On 3.8 jwt+JWKS, groups is already a JSON array. `[${attr.jwt.groups}]` becomes `[["_empty"]]` and DLS 500s. Use `${attr.jwt.groups}` bare; keep `[${user.roles}]`.

### 15. `jwks_uri` must be Docker DNS

`http://keycloak:8080/.../certs` from the OpenSearch container. `localhost` inside the OS container fails. `required_issuer` stays the public `http://localhost:8080/...` issuer.

---

## Tasks to perform (implementation checklist)

Check a box only after that step has been **run**. Order is dependency order. Status reflects post–3.8 upgrade (`update_opensearch_version.md`).

### 0. Human lock

- [x] C1–C7 locked 29 Aug 2026 (C3–C5 final: do what it takes / hybrid+predict / keep proofs).

### A. Keycloak ↔ OpenSearch (C3 — do what it takes)

- [x] Ensure `jwt-auth-domain.yml.example` documents `jwks_uri` + `roles_key: roles` + iss/aud from the captured JWT.
- [x] Ensure `roles.yml` DLS matches A4 (top-level `roles` / `groups` only; groups **without** extra `[]`).
- [x] Ensure `rolesmapping.yml` exists: `files_searcher` ← `search-user` only; `all_access` users=`admin`, no backend role `admin`.
- [x] Add **`cluster:admin/opensearch/ml/predict`** and **`cluster:admin/opensearch/ml/models/get`** to `files_searcher` in `roles.yml` **and** `opensearch_security.py` (C4).
- [x] `cd backend && uv run python -m init_services` — PUT securityconfig + roles + rolesmapping (enable command).
- [x] Password-grant / SPA token → `GET /_plugins/_security/authinfo`: `files_searcher`, not `all_access` (searcher + realm-admin).
- [x] JWT user **cannot** `POST` a document to the index (403). Basic `admin` still can.

### B. Settings

- [x] `opensearch_model_id: str | None = None` as a real Settings field overlaid from `runtime_config.json` (remove the broken `@property` if still present).
- [x] `get_settings()` still loads runtime JSON; `extra=ignore` stays.

### C. Model + pipelines + index

- [x] `cd backend && uv run python -m init_services` with OpenSearch up and outbound HTTPS allowed.
- [x] `runtime_config.json` contains `opensearch_model_id`. Second run does not start a new register if the model exists.
- [x] Model state `DEPLOYED` (or `PARTIALLY_DEPLOYED` on this single node).
- [x] Ingest pipeline exists; processor `model_id` equals stored id.
- [x] Search pipeline exists with weights `[0.3, 0.7]`.
- [x] Index exists with knn, dim 384, keyword ACL fields, `default_pipeline` set.
- [x] If index mapping is wrong: abort with a clear message (G6). Do not silent-skip. *(G6 drift check in `ensure_index_and_pipelines`; current index matches)*

### D. Proof module (hybrid only; keep docs — C4 / C5)

- [x] Add `init_services/search_proof.py` (behind `SEARCH_PROOF=1` or explicit invoke; default off from `run.py`).
- [x] Upsert proof docs as basic `admin` (omit `embedding`; fixed `_id`s below).
- [x] After index, GET as admin: `embedding` present, length 384.
- [ ] **Hybrid** as **searcher** JWT for `alpha-proof-token`: hit `proof-role-search-user`. **BLOCKED on 3.8** (Landmine 13). Neural-only / keyword DLS **PASS**.
- [ ] **Hybrid** as **searcher** for `bravo-proof-token`: **zero** hits. **BLOCKED** (same). Keyword DLS miss **PASS**.
- [ ] **Hybrid** as **realm-admin** for `bravo-proof-token`: hit `proof-group-engineering`. **BLOCKED**. Keyword DLS hit **PASS**.
- [ ] **Hybrid** both users for `charlie-proof-token`: **zero** hits. **BLOCKED**. Keyword DLS miss **PASS**.
- [ ] **Hybrid** as **realm-admin** for `alpha-proof-token`: hit (has `search-user`). **BLOCKED**. Keyword DLS hit **PASS**.
- [x] **Do not delete** `proof-*` docs. Confirm they still exist after the run.
- [x] Print `opensearch_model_id` and pipeline names.

Proof documents (omit `embedding`):

| `_id` / `chunk_id` | `content` | `allowed_roles` | `allowed_groups` |
| --- | --- | --- | --- |
| `proof-role-search-user` | `alpha-proof-token` | `["search-user"]` | `[]` |
| `proof-group-engineering` | `bravo-proof-token` | `[]` | `["engineering"]` |
| `proof-nobody` | `charlie-proof-token` | `[]` | `[]` |

Optional: `proof-role-admin` with `allowed_roles: ["admin"]`.

`models/get` was the minimum extra ML permission needed for neural as JWT on 3.8 (already applied). Never switch to keyword-only or admin search as product path.

If group hit 500s: C7 — fix claim expansion (no extra `[]` on groups), do not drop the groups clause.

### E. Hygiene

- [x] No secrets in JSON configs. No Postgres writes. No frontend.
- [x] `roles.yml` matches the REST role body (including predict + models.get).
- [x] Second `init_services` is idempotent (model id stable, index not recreated, pipelines upserted).
- [x] `GET /health` and `GET /auth/me` still work.
- [x] Second `SEARCH_PROOF=1` run upserts same docs; **hybrid** proofs still pass. *(upsert OK; interim match/neural DLS PASS; hybrid blocked until 3.9+)*

---

## Proof table (fill when implementing)

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
| 10 | Hybrid realm-admin hits group-only chunk (`engineering`) | **BLOCKED**. Keyword DLS hit **PASS** (`attr.jwt.groups`) |
| 11 | Hybrid both miss empty-ACL chunk | **BLOCKED**. Keyword DLS miss **PASS** |
| 12 | `proof-*` docs still present after proofs | **PASS** |
| 13 | `/health` + `/auth/me` still 200 | **PASS** |

---

## Human checks (environment)

- [x] `docker compose ps` — OpenSearch 9200 healthy. Heap **≥2g** already in compose. Image **3.8.0**.
- [ ] Host `vm.max_map_count` ≥ 262144 if the node refused to start.
- [x] First model register needs **outbound HTTPS** to `artifacts.opensearch.org` (and Hugging Face as required by the distribution).
- [x] Keycloak still has seed users; `KEYCLOAK_API_SECRET` works for password-grant proofs.
- [ ] If mapping drift fails C/G6: human decides whether to `DELETE /enterprise-search-chunks` on this local volume.
- [x] Human chooses path for hybrid+DLS blocker: stay on 3.8 with interim neural/keyword DLS proofs; wait for `3.9.0`; or other (see `update_opensearch_version.md`).
  - **LOCKED 29 Aug 2026:** Stay on **3.8**. Hybrid remains the product contract; proofs use interim match/neural DLS only. Task 5 `POST /search` waits until hybrid+DLS works (3.9+) or a later override.

---

## Follow-on (not this slice)

| Task | Needs from this platform |
| --- | --- |
| 4 Ingest | Index + default ingest pipeline; bulk index omit `embedding`; ACL **names** on each chunk; basic admin writes |
| 5 Search/view API | Forward **user** JWT; same hybrid body; `_source` exclude `embedding`; DLS already enforced in OS — **WAIT** (human 29 Aug 2026: stay on 3.8; do not ship Task 5 until hybrid+DLS works on 3.9+ or override) |
| 6 Admin ACL | `update_by_query` on `file_id`; same keyword ACL fields; progress UI |
| 7 Hardening | Map ingest to `files_writer` instead of `all_access`; search users still read-only |
| OpenSearch 3.9+ | Re-run `search_proof.py` hybrid path after Hub publishes `3.9.0` (security PR 6416) |

---

## Checklist copied from Task 3 (map to this file)

- [x] Register + deploy MiniLM; write model id to runtime JSON — step C
- [x] Create ingest pipeline, hybrid search pipeline, index mapping — step C
- [ ] Prove one document: ingest fills `embedding`, hybrid query returns it — step D *(ingest PASS; hybrid JWT BLOCKED on 3.8)*
- [ ] Prove DLS with hybrid: user without matching role/group gets zero hits; **keep** `proof-*` — step D *(DLS PASS on match/neural; hybrid BLOCKED; proofs kept)*

OpenSearch ↔ Keycloak (C3):

- [x] Roles: Keycloak `search-user` / `admin` exist; OS `files_searcher` / `files_writer` exist — step A
- [x] Connection config: jwt domain JWKS + audience + issuer — step A
- [x] Role mapping: `search-user` → `files_searcher`; `admin` JWT not `all_access` — step A
- [x] ML predict (+ models.get) on `files_searcher` so neural works as JWT user — step A
- [ ] DLS on `allowed_roles` / `allowed_groups` proved with **hybrid** queries — step D *(proved with match/neural; hybrid pending 3.9+)*
