# Project Overview, Research, and Tasks

Product brief plus implementation details from OpenSearch, Keycloak, and ML Commons docs. Scaffold lives under `backend/`, `frontend/`, `docker-compose.yml`, and `docker_service_configs/`.

---

## What this is

A company-internal **hybrid search** engine (keyword + semantic) over files. Every file has access control. v1 is **local upload only** (PDF and TXT). Multi-source connectors come later; keep `original_source` on the index anyway.

---

## Current scope vs later


| Now                                                      | Later                            |
| -------------------------------------------------------- | -------------------------------- |
| Search with RACL on files                                | Connectors (Drive, email, wikis) |
| Local upload → chunk → OpenSearch auto-embed             | Populate `original_source`       |
| File permissions: **viewer** and **editor**              | `owner` / `deleter` later        |
| Admin creates users/roles/groups; others search and view | —                                |
| No auto-ACL on upload (admin assigns role/group grants)  | Connector-imported ACL           |


---



## System shape

```
React (bun, Tailwind, Zustand)
    │  public client `web-client` (PKCE)
    ▼
FastAPI (uv, SQLAlchemy, Alembic)
    │  confidential client `api-client`
    ├── PostgreSQL     files + file ACL + identity mirrors
    ├── MinIO          original bytes (`object_store_path`)
    └── OpenSearch     chunks + embeddings + DLS fields
            │          JWT (authenticator type jwt, not openid)
            └── Keycloak JWKS (jwks_uri on type jwt; not openid)
                + rolesmapping search-user → files_searcher
                + DLS on allowed_roles / allowed_groups
```

OpenSearch **3.8** fetches Keycloak JWKS from Docker DNS (`http://keycloak:8080/.../certs`) and still checks the public `iss`. FastAPI also fetches JWKS (host URL). Apply OS security with `init_services` (Security REST), not `securityadmin.sh`. Recreate the container only if compose env flags change.

Chosen versions for local compose:

- Keycloak **26.2** (`quay.io/keycloak/keycloak:26.2`)
- OpenSearch **3.8.0** (ML Commons pretrained MiniLM + security plugin; JWT via `jwks_uri`)
- PostgreSQL **16**
- MinIO latest
- Embedding: OpenSearch-hosted `huggingface/sentence-transformers/all-MiniLM-L6-v2` **v1.0.2**, **ONNX**, **384** dims

---



## Research: search and embeddings

Sources: [pretrained models](https://docs.opensearch.org/latest/ml-commons-plugin/pretrained-models/), [text_embedding processor](https://docs.opensearch.org/latest/ingest-pipelines/processors/text-embedding/), [semantic search](https://docs.opensearch.org/latest/vector-search/ai-search/semantic-search/), [hybrid search](https://docs.opensearch.org/latest/vector-search/ai-search/hybrid-search/index/), [neural tutorial](https://docs.opensearch.org/latest/tutorials/vector-search/neural-search-tutorial/).

**Do not generate embeddings in FastAPI for v1.** OpenSearch ML Commons runs the model on the cluster.

Bootstrap sequence (idempotent, `init_services`):

1. Cluster settings: `plugins.ml_commons.only_run_on_ml_node=false` (single node), `model_access_control_enabled=false` for local.
2. `POST /_plugins/_ml/model_groups/_register`
3. `POST /_plugins/_ml/models/_register` with `name: huggingface/sentence-transformers/all-MiniLM-L6-v2`, `version: 1.0.2`, `model_format: ONNX`
4. Poll task until `model_id` exists; **persist** `opensearch_model_id` **in** `backend/runtime_config.json` so restarts do not re-download.
5. `POST /_plugins/_ml/models/<id>/_deploy` (redeploy after node restart).
6. Ingest pipeline `text_embedding` maps `content` → `embedding`.
7. Search pipeline `normalization-processor`: `min_max` + `arithmetic_mean` weights `[0.3, 0.7]` (keyword, neural).
8. Index: `index.knn=true`, `default_pipeline` = ingest pipeline, `embedding` as `knn_vector` dim **384**, Lucene HNSW, `cosinesimil`.

**Chunking is mandatory.** MiniLM truncates at ~512 tokens. Long PDFs must be split (`chunk_seq`) or later chunks never enter the vector.

Hybrid query (backend forwards the **user** JWT):

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
  }
}
```

Give OpenSearch **≥2g heap** in compose; model load needs RAM and outbound HTTPS to `artifacts.opensearch.org` on first register.

---



## Research: Keycloak JWT shape for DLS

Sources: [JWT auth](https://docs.opensearch.org/latest/security/authentication-backends/jwt/), [OIDC auth](https://docs.opensearch.org/latest/security/authentication-backends/openid-connect/), [DLS](https://docs.opensearch.org/latest/security/access-control/document-level-security/), OpenSearch forum (JWT vs openid for `${attr.jwt.*}`).

**Use** `http_authenticator.type: jwt`**, not** `openid`**.** Document-level `${attr.jwt.<claim>}` substitution is documented for the jwt backend. Forum reports the same DLS placeholders stay empty with openid even when login works.

**Live access-token shape** (SPA `web-client`, `realm-admin`, captured 29 Aug 2026). DLS and `roles_key` use the **top-level** arrays only — ignore nested `realm_access.roles`:

```json
{
  "iss": "http://localhost:8080/realms/enterprise-search-realm",
  "aud": "api-client",
  "azp": "web-client",
  "sub": "14e573ad-7455-4401-a3f7-abb3b7dc0c32",
  "preferred_username": "realm-admin",
  "roles": ["admin", "search-user"],
  "groups": ["engineering"],
  "realm_access": { "roles": ["admin", "search-user"] }
}
```

**Flatten claims in Keycloak** (nested JWT objects are not usable in DLS):


| Claim                                         | Mapper                                  | Why                                             |
| --------------------------------------------- | --------------------------------------- | ----------------------------------------------- |
| `roles` (top-level array)                     | Realm role mapper, claim name `roles`   | OpenSearch `roles_key: roles` → `${user.roles}` |
| `groups` (top-level array, **full path off**) | Group Membership mapper, claim `groups` | `${attr.jwt.groups}` vs `allowed_groups`        |
| `aud` includes `api-client`                   | Audience mapper                         | `required_audience: api-client`                 |


Default Keycloak puts roles under `realm_access.roles` and groups nowhere. That is not enough. The token above already has both; keep the top-level mappers.

**How OpenSearch “connects” to Keycloak (3.8):** `type: jwt` + `jwks_uri` (not `openid`). The node fetches Keycloak certs; it does **not** call the Keycloak Admin API. Three repo files + one apply command:

| What you are looking for | File (reference) | Applied by |
| --- | --- | --- |
| Keycloak connection | `docker_service_configs/opensearch/security/jwt-auth-domain.yml.example` | `PUT /_plugins/_security/api/securityconfig/config` — `jwks_uri` (Docker DNS), `roles_key: roles`, `required_issuer` / `required_audience` matching the token |
| OS roles + DLS | `docker_service_configs/opensearch/security/roles.yml` | `PUT /_plugins/_security/api/roles/files_searcher` |
| KC role → OS role | `docker_service_configs/opensearch/security/rolesmapping.yml` | `PUT /_plugins/_security/api/rolesmapping/files_searcher` (`backend_roles: [search-user]`) |

`roles_key: roles` copies JWT `roles` into OpenSearch **backend_roles**. Rolesmapping then attaches OS security role `files_searcher`. DLS `${user.roles}` still sees **all** JWT role names (`admin` and `search-user` for this token). JWT `admin` must **not** map to `all_access`.

**Enable / “rebuild”:** after changing those configs, re-run `cd backend && uv run python -m init_services`. That is the OpenSearch enable command (Security REST). Compose already has `allow_securityconfig_modification`. Do **not** recreate the OpenSearch container for JWT/DLS/mapping edits. Do **not** use `securityadmin.sh`. Keycloak realm key rotation does **not** require re-init (JWKS cache picks up a new `kid`). Recreate the container only if you change compose **environment** flags.

**Issuer vs keys:**

| Who | Verify `iss` as | Fetch keys from |
| --- | --- | --- |
| FastAPI (host) | `http://localhost:8080/realms/enterprise-search-realm` | JWKS `http://localhost:8080/.../protocol/openid-connect/certs` |
| OpenSearch 3.8 | **same public `iss`** (`required_issuer`) | JWKS `http://keycloak:8080/.../protocol/openid-connect/certs` |

**Two clients:**

- `api-client` — confidential, secret `KEYCLOAK_API_SECRET`, service account for Admin API (create users/roles/groups). Audience on every access token.
- `web-client` — public + PKCE for React (`azp` in the sample token). SPA cannot hold a client secret.

Realm import: Keycloak 26 `start-dev --import-realm`, files in `/opt/keycloak/data/import`. Import runs only if the realm does **not** already exist. Admin bootstrap: `KC_BOOTSTRAP_ADMIN_USERNAME` / `KC_BOOTSTRAP_ADMIN_PASSWORD` (not the old `KEYCLOAK_ADMIN`).

---



## Research: DLS and RACL

DLS filters **reads** (search/get). It does **not** block writes. A user with write + DLS can index docs they cannot search.

**Split credentials:**


| Actor                              | Auth to OpenSearch                                                   | Permissions                           |
| ---------------------------------- | -------------------------------------------------------------------- | ------------------------------------- |
| End user search                    | User access token (JWT domain)                                       | `files_searcher` + DLS, **read only** |
| Ingest / ACL update / model deploy | Internal `admin` basic auth                                          | write, no DLS                         |
| Product admin UI                   | Same as user for search; backend uses admin/basic for privilege jobs | —                                     |


DLS query (see `docker_service_configs/opensearch/security/roles.yml`). Placeholders come from the JWT **after** `roles_key: roles` and jwt-attr substitution:

```json
{
  "bool": {
    "should": [
      { "terms": { "allowed_roles": [${user.roles}] } },
      { "terms": { "allowed_groups": [${attr.jwt.groups}] } }
    ],
    "minimum_should_match": 1
  }
}
```

For the `realm-admin` token above that **becomes**:

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

A chunk is visible if `allowed_roles` intersects those roles **or** `allowed_groups` intersects those groups. Empty ACL arrays → nobody. Never write `_empty` into `allowed_groups`. Do **not** DLS on `realm_access.roles` or `sub`.

`${user.roles}` expands to a quoted comma-separated list of **backend roles** (the top-level `roles` claim). `allowed_roles` and `allowed_groups` **must be** `keyword`, not `text` (Unicode analyzer would split values). Viewer and editor grants both copy the same names into those fields; DLS does not distinguish verbs.

If a user has a DLS role **and** a non-DLS role, OpenSearch still applies DLS unless `plugins.security.dfm_empty_overrides_all: true`. Keep search users on the DLS role only. Do not map `all_access` to `search-user`.

**Open-file / download** is not covered by DLS. Backend must re-check Postgres ACL (and/or a `GET` through OpenSearch with the user JWT) before streaming MinIO bytes.

ACL edits update **every chunk** of a file (`update_by_query` on `file_id` or per-`chunk_id` with progress). Postgres is the source of truth; OpenSearch is the search-time copy. Dual-write with a job + progress UI.

---



## Identity vs permissions (schema decision)


| Store                                  | Holds                                          |
| -------------------------------------- | ---------------------------------------------- |
| Keycloak                               | Users, realm roles, groups. **Not** file ACL   |
| Postgres `users` / `roles` / `groups`  | Mirrors for admin UI and FK                    |
| Postgres `file_acl`                    | File viewer/editor grants to role or group     |
| Admin dashboard                        | Keycloak realm role `admin` only (no table)    |
| OpenSearch chunk docs                  | `allowed_roles`, `allowed_groups` denormalized |


**Decision for v1: separate tables.** File ACL is resource-scoped. Admin capability is identity-scoped (realm role). Do not mix them in one permissions table. No `admin_grants` / `admin_principals` table.

Realm roles: `admin`, `search-user`. File verbs: `viewer`, `editor` (editor implies view at query time). Grants target **roles and groups**, not only users (RACL). `file_acl.user_id` exists for later connectors; v1 product writes do not require it.

Admin create user/role/group: Keycloak Admin API **and** Postgres in one backend transaction-like flow (compensate if one side fails).

---



## Ingest flow (local)

1. Authn: Bearer token, require `search-user` or `admin`.
2. Store original in MinIO; record `object_store_path`.
3. Parse PDF/TXT, chunk, assign `chunk_id` / `chunk_seq`.
4. Insert Postgres **file metadata only**. No automatic `file_acl` (not searchable until an admin grants a role/group).
5. Bulk index chunks **without** `embedding`; ingest pipeline fills it from `content`. Copy ACL **names** into `allowed_roles` / `allowed_groups` when grants exist.
6. `ingestion_type=local`, `original_source=null`.

---



## OpenSearch index (per chunk)


| Field                                                    | Mapping                                  |
| -------------------------------------------------------- | ---------------------------------------- |
| `file_id`, `chunk_id`                                    | keyword                                  |
| `chunk_seq`                                              | integer                                  |
| `meta_file_type`, `meta_file_size`                       | keyword, long                            |
| `updated_at`, `uploaded_at`                              | date                                     |
| `content`                                                | text (BM25)                              |
| `embedding`                                              | knn_vector 384, lucene hnsw, cosinesimil |
| `allowed_roles`, `allowed_groups`                        | keyword                                  |
| `object_store_path`, `ingestion_type`, `original_source` | keyword                                  |


---



## Product surfaces

**All users:** search; navbar **View files**; result **Open** streams original from MinIO after ACL check.

**Admin:** dashboard; assign file privileges to roles/groups (per-chunk OpenSearch progress + Postgres); create users/roles/groups (Keycloak + DB).

---



## Config management (already scaffolded)

1. `pydantic-settings` — hosts, index names, pipeline names, model name/dim.
2. Repo-root `.env` — passwords and `KEYCLOAK_API_SECRET`.
3. `backend/runtime_config.json` — `opensearch_model_id` and other generated ids. Load into Settings; **do not re-register the model** if id is present.

---



## Filesystem (created)

```
backend/app/{api,core,db,models,schemas,services}
backend/init_services/          # API bootstrap: wait, Keycloak, OpenSearch, MinIO
backend/alembic/
frontend/src/{api,components/{ui,layout},config,hooks,store}
docker_service_configs/{keycloak/realm.json,postgres,opensearch/security/{jwt-auth-domain.yml.example,roles.yml,rolesmapping.yml},minio}
docker-compose.yml
```

---



## Human checks (not verified in this pass)

- `docker compose up` (OpenSearch wants ~2–4 GB RAM; host `vm.max_map_count` ≥ 262144).
- Keycloak realm import on **first** empty DB only; confirm realm `enterprise-search-realm` and client `api-client`.
- First ML model register needs internet to OpenSearch artifact CDN.

---



## Tasks to do

Order is dependency order. Check a box only after the step has been run.

### 0. Local platform

- [x] Backend FastAPI + uv + SQLAlchemy + Alembic layout
- [x] Frontend React + bun + Tailwind + Zustand layout
- [x] Compose file: Postgres, Keycloak, OpenSearch, MinIO
- [x] Keycloak `realm.json`: `enterprise-search-realm`, `api-client`, flattened `roles`/`groups`, `web-client`
- [x] **Human:** `docker compose up -d` and confirm four services healthy
- [x] **Human:** `vm.max_map_count` if OpenSearch refuses to start
- [x] Run `cd backend && uv run python -m init_services` against a live stack
- [ ] Persist `opensearch_model_id` after first successful deploy



### 1. Auth

- [x] Merge JWT auth domain into OpenSearch security config (`type: jwt`, `jwks_uri`, `roles_key: roles`)
- [x] Create OS role `files_searcher` with DLS from `roles.yml`; map backend role `search-user` only (JWT `admin` is not `all_access`)
- [x] FastAPI: validate Bearer JWT (issuer, audience `api-client`, JWKS)
- [x] React: PKCE login via `web-client`; store access token in Zustand
- [x] Admin route guard: realm role `admin` only



### 2. Data model (Postgres)

- [x] Tables: `users`, `roles`, `groups`, memberships (Keycloak id mirrors)
- [x] Table `files` (id, object_store_path, type, size, timestamps, ingestion_type, original_source)
- [x] Table `file_acl` (nullable user/role/group FKs, permission viewer|editor)
- [x] Admin capability = Keycloak realm role `admin` (no `admin_grants` table)
- [x] Alembic revision and `alembic upgrade head`



### 3. Search platform

Plan: `prompts/cursor_summary/6_search_setup.md`. Cluster + proofs only — **not** `POST /search` / UI (Task 5).

- [ ] Visible OS security files: jwt domain, `roles.yml` DLS, `rolesmapping.yml`; re-apply with `init_services` (Security REST)
- [ ] DLS matches live JWT: top-level `roles` / `groups` → `allowed_roles` / `allowed_groups` (not `realm_access.roles`)
- [ ] `files_searcher` has ML **predict** so all searches can be hybrid as the user JWT
- [ ] Register + deploy MiniLM **ONNX**; write `opensearch_model_id` to runtime JSON
- [ ] Create ingest pipeline, hybrid search pipeline, index mapping
- [ ] Prove one document: ingest fills `embedding`, hybrid query returns it
- [ ] Prove DLS with hybrid: user without matching role/group gets zero hits; **keep** `proof-*` docs



### 4. Ingest API

- [ ] Upload PDF/TXT → MinIO
- [ ] Chunker (token-aware, overlap, `chunk_seq`)
- [ ] Bulk index chunks with ACL **names**; omit embedding field
- [ ] Postgres file metadata only (no auto `file_acl`)
- [ ] Reject unsupported MIME types



### 5. Search and view API + UI

- [x] `POST /search` proxies **client-side hybrid** (match + neural + merge) with **user** JWT on 3.8; native hybrid after 3.9 (`hybrid_search_issue_sol.md`)
- [x] Strip `embedding` from `_source` in the response
- [x] Results UI with Open (authenticated blob download via `GET /files/{id}/content`)
- [x] `GET /files/{id}` / stream: Postgres ACL then MinIO
- [x] Navbar View files list (ACL-filtered from Postgres)



### 6. Admin

Plans: `prompts/cursor_summary/9_admin_panel.md` (index) → **6a** `9a_admin_panel.md` (identity) then **6b** `9b_admin_panel.md` (file ACL + sync). Flip all boxes only when both phases are done.

- [x] Create/update users, roles, groups → Keycloak Admin API + Postgres *(6a — see `prompts/summary/8a_admin_panel.md`; React Proof 10 human)*
- [x] Assign file privileges to roles/groups *(6b — see `prompts/summary/8b_admin_panel.md`; React Proof 10 human)*
- [x] Background job: `update_by_query` (or per-chunk updates) + progress API/UI *(6b)*
- [x] Keep Postgres and OpenSearch ACL in sync; define retry/repair *(6b retry via `/admin/acl-jobs/{id}/retry`; deeper repair → Task 7)*



### 7. Hardening

- [ ] Search users have no OpenSearch write
- [ ] Dual-write repair command
- [ ] Init_services fully idempotent (realm exists, model deployed, index exists, bucket exists)
- [ ] Do not commit `.env`; rotate `realm-admin` / MinIO / OpenSearch demo passwords before any shared deploy