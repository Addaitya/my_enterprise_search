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
| File permissions: **viewer** and **owner**               | Richer verbs if needed           |
| Admin creates users/roles/groups; others search and view | —                                |


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
            └── Keycloak JWKS + DLS on allowed_roles / allowed_groups
```

Chosen versions for local compose:

- Keycloak **26.2** (`quay.io/keycloak/keycloak:26.2`)
- OpenSearch **2.19.1** (ML Commons pretrained MiniLM + security plugin)
- PostgreSQL **16**
- MinIO latest
- Embedding: OpenSearch-hosted `huggingface/sentence-transformers/all-MiniLM-L6-v2` **v1.0.2**, **384** dims

---



## Research: search and embeddings

Sources: [pretrained models](https://docs.opensearch.org/latest/ml-commons-plugin/pretrained-models/), [text_embedding processor](https://docs.opensearch.org/latest/ingest-pipelines/processors/text-embedding/), [semantic search](https://docs.opensearch.org/latest/vector-search/ai-search/semantic-search/), [hybrid search](https://docs.opensearch.org/latest/vector-search/ai-search/hybrid-search/index/), [neural tutorial](https://docs.opensearch.org/latest/tutorials/vector-search/neural-search-tutorial/).

**Do not generate embeddings in FastAPI for v1.** OpenSearch ML Commons runs the model on the cluster.

Bootstrap sequence (idempotent, `init_services`):

1. Cluster settings: `plugins.ml_commons.only_run_on_ml_node=false` (single node), `model_access_control_enabled=false` for local.
2. `POST /_plugins/_ml/model_groups/_register`
3. `POST /_plugins/_ml/models/_register` with `name: huggingface/sentence-transformers/all-MiniLM-L6-v2`, `version: 1.0.2`, `model_format: TORCH_SCRIPT`
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

**Flatten claims in Keycloak** (nested JWT objects are not usable in DLS):


| Claim                                         | Mapper                                  | Why                                             |
| --------------------------------------------- | --------------------------------------- | ----------------------------------------------- |
| `roles` (top-level array)                     | Realm role mapper, claim name `roles`   | OpenSearch `roles_key: roles` → `${user.roles}` |
| `groups` (top-level array, **full path off**) | Group Membership mapper, claim `groups` | `${attr.jwt.groups}` vs `allowed_groups`        |
| `aud` includes `api-client`                   | Audience mapper                         | `required_audience: api-client`                 |


Default Keycloak puts roles under `realm_access.roles` and groups nowhere. That is not enough.

**Issuer vs JWKS URL:** tokens get `iss: http://localhost:8080/realms/enterprise-search-realm` (browser). OpenSearch must fetch JWKS on the Docker network: `http://keycloak:8080/realms/enterprise-search-realm/protocol/openid-connect/certs`. Set `required_issuer` to the public iss.

**Two clients (research recommendation):**

- `api-client` — confidential, secret `KEYCLOAK_API_SECRET`, service account for Admin API (create users/roles/groups).
- `web-client` — public + PKCE for React. Instruction file only named `api-client`; SPA cannot hold a client secret.

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


DLS query (see `docker_service_configs/opensearch/security/roles.yml`):

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

`${user.roles}` expands to a quoted comma-separated list. `allowed_roles` and `allowed_groups` **must be** `keyword`, not `text` (Unicode analyzer would split values).

If a user has a DLS role **and** a non-DLS role, OpenSearch still applies DLS unless `plugins.security.dfm_empty_overrides_all: true`. Keep search users on the DLS role only. Do not map `all_access` to `search-user`.

**Open-file / download** is not covered by DLS. Backend must re-check Postgres ACL (and/or a `GET` through OpenSearch with the user JWT) before streaming MinIO bytes.

ACL edits update **every chunk** of a file (`update_by_query` on `file_id` or per-`chunk_id` with progress). Postgres is the source of truth; OpenSearch is the search-time copy. Dual-write with a job + progress UI.

---



## Identity vs permissions (schema decision)


| Store                                  | Holds                                          |
| -------------------------------------- | ---------------------------------------------- |
| Keycloak                               | Users, realm roles, groups. **Not** file ACL   |
| Postgres `users` / `roles` / `groups`  | Mirrors for admin UI and FK                    |
| Postgres `file_acl`                    | File viewer/owner grants to role or group      |
| Postgres `admin_principals` (separate) | Who may open the admin dashboard               |
| OpenSearch chunk docs                  | `allowed_roles`, `allowed_groups` denormalized |


**Decision for v1: separate tables.** File ACL is resource-scoped. Admin capability is identity-scoped. Do not mix them in one permissions table.

Realm roles: `admin`, `search-user`. File verbs: `viewer`, `owner` (owner implies view). Grants target **roles and groups**, not only users (RACL).

Admin create user/role/group: Keycloak Admin API **and** Postgres in one backend transaction-like flow (compensate if one side fails).

---



## Ingest flow (local)

1. Authn: Bearer token, require `search-user` or `admin`.
2. Store original in MinIO; record `object_store_path`.
3. Parse PDF/TXT, chunk, assign `chunk_id` / `chunk_seq`.
4. Insert Postgres file row + default ACL (uploader as owner; optional default roles).
5. Bulk index chunks **without** `embedding`; ingest pipeline fills it from `content`.
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
docker_service_configs/{keycloak/realm.json,postgres,opensearch,minio}
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

- [x] Merge JWT auth domain into OpenSearch security config (`type: jwt`, JWKS, `roles_key: roles`)
- [x] Create OS role `files_searcher` with DLS from `roles.yml`; map backend role `search-user`
- [x] FastAPI: validate Bearer JWT (issuer, audience `api-client`, JWKS)
- [x] React: PKCE login via `web-client`; store access token in Zustand
- [x] Admin route guard: realm role `admin` only



### 2. Data model (Postgres)

- [ ] Tables: `users`, `roles`, `groups`, memberships (Keycloak id mirrors)
- [ ] Table `files` (id, object_store_path, type, size, timestamps, ingestion_type, original_source)
- [ ] Table `file_acl` (file_id, principal_type role|group, principal_id, permission viewer|owner)
- [ ] Separate table `admin_grants` (or rely only on Keycloak `admin` role — pick one and document)
- [ ] Alembic revision and `alembic upgrade head`



### 3. Search platform

- [ ] Register + deploy MiniLM; write model id to runtime JSON
- [ ] Create ingest pipeline, hybrid search pipeline, index mapping
- [ ] Prove one document: ingest fills `embedding`, hybrid query returns it
- [ ] Prove DLS: user without matching role/group gets zero hits



### 4. Ingest API

- [ ] Upload PDF/TXT → MinIO
- [ ] Chunker (token-aware, overlap, `chunk_seq`)
- [ ] Bulk index chunks with ACL fields; omit embedding field
- [ ] Postgres file + owner ACL
- [ ] Reject unsupported MIME types



### 5. Search and view API + UI

- [ ] `POST /search` proxies hybrid query with **user** JWT to OpenSearch
- [ ] Strip `embedding` from `_source` in the response
- [ ] Results UI + Open button
- [ ] `GET /files/{id}` / stream: Postgres ACL (or user-JWT GET) then MinIO
- [ ] Navbar View files list (ACL-filtered from Postgres)



### 6. Admin

- [ ] Create/update users, roles, groups → Keycloak Admin API + Postgres
- [ ] Assign file privileges to roles/groups
- [ ] Background job: `update_by_query` (or per-chunk updates) + progress API/UI
- [ ] Keep Postgres and OpenSearch ACL in sync; define retry/repair



### 7. Hardening

- [ ] Search users have no OpenSearch write
- [ ] Dual-write repair command
- [ ] Init_services fully idempotent (realm exists, model deployed, index exists, bucket exists)
- [ ] Do not commit `.env`; rotate `realm-admin` / MinIO / OpenSearch demo passwords before any shared deploy