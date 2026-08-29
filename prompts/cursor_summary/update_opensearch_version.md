# Upgrade OpenSearch 2.19.1 → 3.8.0 — research plan and tasks

Working notes to research and execute an OpenSearch major upgrade for this repo. Auth / JWT / DLS / MiniLM contracts live in `prompts/cursor_summary/6_search_setup.md` and `prompts/cursor_summary/2_project_overview_tasks.md`. This file is the source of truth for the **version bump only**. Do not invent a second ACL model or a second auth path.

**Agent rules while implementing**
- Run and execute code to confirm it works before moving on.
- Do not proceed past a broken step; fix it first.
- Where something cannot be verified in this environment, leave a clear human check and wait for feedback.
- Prefer a **clean local wipe** over a production-style rolling upgrade (this compose stack is single-node, disposable data).
- Treat **Locked decisions** as law once the human locks them.
- Do **not** start Task 4 ingest API, Task 5 search UI, or admin ACL CRUD as part of this upgrade.

**Primary product motivation:** OpenSearch **3.3+** adds native `jwks_uri` on `http_authenticator.type: jwt`. On 2.19 we copy Keycloak realm `public_key` into PEM `signing_key`. After 3.8 we can (and should) verify JWTs via Keycloak’s JWKS endpoint while keeping `type: jwt` (not `openid`) so `${attr.jwt.*}` DLS still works.

---

## What “done” means

| Criterion | Pass condition |
| --- | --- |
| Images | Compose runs `opensearchproject/opensearch:3.8.0` and matching Dashboards `3.8.0` |
| Cluster | `_cluster/health` green/yellow; `GET /` reports version `3.8.0` |
| Security | Basic `admin` still works; JWT users still `files_searcher` via `authinfo` |
| JWT keys | `jwt_auth_domain` uses `type: jwt` + **`jwks_uri`** (no static PEM required for normal ops) |
| DLS | `${user.roles}` and `${attr.jwt.groups}` still expand; hybrid DLS proofs pass |
| ML | MiniLM ONNX registers/deploys; ingest fills `embedding` dim 384; hybrid search works as JWT user |
| Docs | README + cursor_summary plans no longer claim “2.19 PEM only / no jwks_uri” |
| Idempotency | Second `init_services` does not re-download the model when id is valid |

---

## Current state (baseline → after 29 Aug 2026 implement)

| Item | Was (2.19.1) | Now (3.8.0) |
| --- | --- | --- |
| Image | `opensearchproject/opensearch:2.19.1` | `opensearchproject/opensearch:3.8.0` |
| Dashboards | `2.19.1` (security plugin **off**) | `3.8.0` (security plugin **off**) |
| Heap | `-Xms2g -Xmx2g` | unchanged |
| Security | Plugin on; HTTP SSL off; `allow_securityconfig_modification=true` | unchanged; flags accepted |
| JWT | `type: jwt`, PEM `signing_key` | `type: jwt` + **`jwks_uri`** (Docker DNS). PEM fallback unused |
| Roles | `files_searcher` (DLS + predict), `files_writer` (unmapped) | + `cluster:admin/opensearch/ml/models/get` |
| ML | MiniLM 1.0.2 ONNX, dim 384 | same; id `2PAsTqABzKlhu0IdV6uY` |
| Index | `enterprise-search-chunks`, Lucene HNSW `cosinesimil` | recreated on fresh volume |
| Apply path | Security REST via `init_services` | unchanged |
| Data volume | wiped (Strategy A); Postgres/MinIO kept | `my_enterprise_search_opensearch_data` new |

Key files to touch for the upgrade:

```
docker-compose.yml
docker_service_configs/opensearch/opensearch.yml          # reference; env in compose is live
docker_service_configs/opensearch/security/jwt-auth-domain.yml.example
docker_service_configs/opensearch/security/roles.yml
docker_service_configs/opensearch/security/rolesmapping.yml
docker_service_configs/opensearch/index-mapping.json
docker_service_configs/opensearch/ingest-pipeline.json
docker_service_configs/opensearch/search-pipeline.json
backend/init_services/opensearch.py
backend/init_services/opensearch_security.py
backend/app/core/config.py
README.md
prompts/cursor_summary/2_project_overview_tasks.md
prompts/cursor_summary/6_search_setup.md
prompts/cursor_summary/4_auth_setup.md                    # historical; add “superseded by 3.8” note if edited
```

---

## Research findings (pre-implementation)

### R1. Target version availability

- Docker Hub publishes `opensearchproject/opensearch:3.8.0` (linux/amd64 + arm64).
- Pair Dashboards to the **same** minor: `opensearchproject/opensearch-dashboards:3.8.0`.
- Prefer pinning `3.8.0` (not floating `3.8` / `latest`) for reproducible local stacks.

**Human check:** Confirm `3.8.0` is still the desired pin if a newer 3.8.x patch exists at implement time; use the latest **3.8.x** patch if available.

### R2. Why 3.8 (not just 3.3)

| Capability | Since | Relevance |
| --- | --- | --- |
| `jwks_uri` on `type: jwt` | **3.3** | Unblocks Keycloak JWKS without switching to `openid` |
| Stay on latest 3.x patch line | 3.8 | Security/CVE bumps, Lucene, Jackson, etc. |
| S3 repo default SSE → `AES256` | **3.8.0** | Only matters if/when we register S3/MinIO **snapshot** repos; product MinIO object store is unrelated |

Jumping straight **2.19.1 → 3.8.0** is fine for this **local single-node** project. Do not intermediate through every minor unless a blocker appears.

### R3. Index / data compatibility (2.x → 3.x)

From [Breaking changes](https://docs.opensearch.org/latest/breaking-changes/):

- OpenSearch **3.0** rejects indexes created in versions **earlier than 2.x** (must reindex those first).
- Indexes created on **2.19** are in the supported band for 3.x **in principle**.
- **This repo’s local strategy:** treat `opensearch_data` as disposable. Prefer **delete volume + recreate index + re-register model** over in-place upgrade of an old security/ML system index. Proof/`proof-*` docs and any real chunks are re-ingested later (Task 4+) or re-proofed.

**Do not** assume an old 2.19 data directory boots cleanly on 3.8 without testing. If a human wants to keep data, run research task **T-R4** (boot 3.8 on existing volume) before locking wipe-vs-migrate.

### R4. JWT: PEM vs JWKS (the main design change)

| | 2.19.1 (today) | 3.8.0 (target) |
| --- | --- | --- |
| Authenticator | `type: jwt` | **Keep** `type: jwt` |
| Keys | Static PEM `signing_key` | Prefer **`jwks_uri`** → Keycloak certs |
| Keycloak call | Only at `init_services` (host copies key) | OpenSearch node fetches JWKS (cached) |
| `openid` type | Forbidden (breaks `${attr.jwt.*}`) | Still forbidden |
| FastAPI | Already JWKS via `PyJWKClient` | Unchanged |

Keycloak JWKS URL shape:

```
{keycloak_base}/realms/{realm}/protocol/openid-connect/certs
```

**Critical networking split** (same pattern as issuer vs fetch today):

| Setting | Value | Why |
| --- | --- | --- |
| Token `iss` / `required_issuer` | `http://localhost:8080/realms/enterprise-search-realm` | Must match claim inside JWT |
| `jwks_uri` from **OpenSearch container** | `http://keycloak:8080/realms/enterprise-search-realm/protocol/openid-connect/certs` | Docker DNS; `localhost` inside OS container is wrong |
| FastAPI JWKS (host) | `http://localhost:8080/.../certs` | Already correct in `Settings.keycloak_jwks_url` |

Optional JWKS knobs to research then set intentionally:

- `cache_jwks_endpoint` (default **true** on jwt+jwks) — keep true
- `jwks_request_timeout_ms` (default 5000)
- Rate-limit / refresh behavior when `kid` rotates

**Fallback:** PEM `signing_key` remains supported on 3.8 if JWKS networking fails. Ship JWKS as the locked path; keep PEM code path only as a documented emergency fallback (or delete after proofs pass — human gate G3).

### R5. Security plugin / REST apply path

- Keep applying via `PUT /_plugins/_security/api/securityconfig/config` + roles + rolesmapping.
- Keep `plugins.security.unsupported.restapi.allow_securityconfig_modification: true`.
- Re-verify on 3.8:
  - Blake2b hash salt fix (3.0) — internal passwords may differ if anything relied on old hashes; demo `admin` is bootstrapped via `OPENSEARCH_INITIAL_ADMIN_PASSWORD` on fresh volume → OK.
  - System index REST access removed in 3.0 — confirm we never poke `.opendistro_security` via raw CRUD (we use Security API only).
  - `roles_key: roles`, `subject_key: preferred_username`, `required_audience: api-client` still accepted.

### R6. ML Commons / MiniLM

- Pretrained `huggingface/sentence-transformers/all-MiniLM-L6-v2` **1.0.2** still listed with ONNX + TorchScript artifacts on current docs.
- Keep **ONNX** unless 3.8 proofs show TorchScript is healthier (do not flip without evidence).
- Fresh volume ⇒ clear stale `opensearch_model_id` in `backend/runtime_config.json` (or delete the file) so init re-registers.
- Re-confirm cluster settings still valid:
  - `plugins.ml_commons.only_run_on_ml_node=false`
  - `plugins.ml_commons.model_access_control_enabled=false`
  - `plugins.ml_commons.native_memory_threshold=99`
- Re-confirm permission `cluster:admin/opensearch/ml/predict` on `files_searcher` (action name may be unchanged; **prove** with hybrid as JWT user).
- 3.0 removed `CatIndexTool` (agent tooling) — irrelevant unless we add ML agents later.

### R7. k-NN / mappings

Our mapping already uses:

```json
"method": { "name": "hnsw", "engine": "lucene", "space_type": "cosinesimil" }
```

That avoids the 2.18 default-engine Faiss surprise and the 3.0 removal of legacy `index.knn.algo_param.*` / `index.knn.space_type` **index settings**. Still verify:

- Create index on 3.8 with current `index-mapping.json` succeeds.
- Ingest + knn query + hybrid pipeline still work.
- No deprecated settings sneak in via ML or pipeline templates.

### R8. JDK / image

- OpenSearch 3.0+ requires **JDK 21** (bundled in official image — no host JDK change for Docker).
- Java Security Manager replaced by a Java agent in 3.0 — expect different plugin sandbox behavior only if we add custom plugins (we do not).

### R9. MinIO / S3 repository note (3.8)

- Product file storage in MinIO is **not** an OpenSearch snapshot repository.
- If someone later registers an `s3` snapshot repo against MinIO, 3.8 defaults `server_side_encryption_type` to `AES256` and MinIO may 501. Mitigate then with `bucket_default`. **Out of scope** unless we add snapshots in this upgrade.

### R10. Docs / plans that hard-code 2.19

These currently assert “no jwks_uri / PEM only”:

- `prompts/cursor_summary/2_project_overview_tasks.md`
- `prompts/cursor_summary/6_search_setup.md` (G3, locked JWT table)
- `prompts/cursor_summary/4_auth_setup.md`
- `docker_service_configs/opensearch/security/jwt-auth-domain.yml.example`
- `README.md` version table

Update them in the same PR/slice as the compose bump so agents do not re-implement PEM forever.

### R11. Upgrade strategies (local)

| Strategy | When | Pros | Cons |
| --- | --- | --- | --- |
| **A. Wipe volume + pin 3.8** (recommended) | Default for this repo | Clean security/ML indexes; matches “local demo” | Loses proof docs / model id |
| B. In-place: stop → change image → start on same volume | Human insists on keeping chunks | Keeps data if Lucene/security indexes compatible | Higher risk; security/ML system indexes may fail |
| C. Snapshot/restore or remote reindex | Future multi-node / prod | Proper migration | Overkill for current compose |

**Proposed lock:** Strategy **A**.

---

## Human gates (lock before coding)

### G1. Target pin

| | |
| --- | --- |
| Status | **LOCKED 29 Aug 2026** (implement request; latest 3.8.x = `3.8.0`) |
| Decision | Pin `opensearchproject/opensearch:3.8.0` and Dashboards `3.8.0` (or latest 3.8.x patch at implement time). |
| Why | JWKS on jwt (≥3.3) + current patch line. |

### G2. Data volume

| | |
| --- | --- |
| Status | **LOCKED 29 Aug 2026** |
| Decision | Strategy A: `docker compose down`, remove `opensearch_data` volume, bring up 3.8 fresh. Clear `backend/runtime_config.json` model id. |
| Why | Local stack; avoids opaque 2→3 system-index failures. |

### G3. JWT key source

| | |
| --- | --- |
| Status | **LOCKED 29 Aug 2026** |
| Decision | Switch to `jwks_uri` on `type: jwt`. `jwks_uri` = Keycloak **Docker DNS** certs URL. Keep `required_issuer` = public localhost issuer. Remove PEM fetch from the happy path. Keep `openid` forbidden. |
| Why | Matches FastAPI; survives Keycloak key rotation without re-init; preserves `${attr.jwt.*}`. |

### G4. Scope boundary

| | |
| --- | --- |
| Status | **LOCKED 29 Aug 2026** |
| Decision | This slice = version bump + JWT JWKS + re-prove security/ML/hybrid/DLS. Not Task 4/5 product APIs. |
| Why | Isolate upgrade risk. |

### G5. Dashboards

| | |
| --- | --- |
| Status | **LOCKED 29 Aug 2026** |
| Decision | Bump Dashboards to 3.8.0; keep `DISABLE_SECURITY_DASHBOARDS_PLUGIN=true`. |
| Why | Version skew with the node is unsupported; we still do not use Dashboards security. |

---

## Architecture after upgrade

```
Browser / FastAPI
    Authorization: Bearer <access_token>
         │
         ▼
OpenSearch 3.8 jwt_auth_domain  (type: jwt)
    1. Resolve signing key(s) from jwks_uri (Keycloak certs, cached)
    2. Verify signature (kid / JWKS)
    3. Check iss + aud
    4. roles_key: roles  → backend_roles
    5. groups on attr.jwt.groups
         │
         ▼
rolesmapping: search-user → files_searcher
         │
         ▼
DLS on allowed_roles / allowed_groups + hybrid (ML predict)
```

```
init_services (basic admin)
  ├─ jwt_auth_domain     ← jwks_uri (no PEM copy)
  ├─ files_searcher+DLS  ← + ml predict
  ├─ files_writer        ← unmapped
  ├─ MiniLM ONNX         → runtime_config.json
  ├─ ingest / search pipelines
  └─ index enterprise-search-chunks
```

---

## Landmines

1. **`jwks_uri` pointing at `localhost`** from inside the OpenSearch container → connection refused / JWT always 401. Use `http://keycloak:8080/...`.
2. **`required_issuer` set to Docker DNS** → tokens issued with `iss=http://localhost:8080/...` fail. Issuer stays public URL.
3. **Switching to `type: openid` for JWKS** → login may work; `${attr.jwt.groups}` DLS dies. Forbidden.
4. **Keeping old `opensearch_data`** → mysterious security/ML boot failures. Prefer wipe.
5. **Stale `opensearch_model_id`** after wipe → init thinks model exists; hybrid/ingest break. Clear runtime JSON.
6. **ML predict permission rename** (unlikely but prove) → hybrid 403 as JWT user.
7. **Heap / native memory** — 3.x + ONNX may need ≥2g still; if OOM, raise heap before changing model format.
8. **Agents reading old plans** — if cursor_summary still says “PEM only”, they will regress the JWT domain. Update docs in the same change set.
9. **MinIO as snapshot repo later** — 3.8 AES256 default; unrelated to object storage, but do not “fix” snapshots without `bucket_default`.

---

## Research tasks (read / verify before or during upgrade)

Check only after the step is **done**.

### Phase 0 — Confirm target and docs

- [x] **T-R0.1** Confirm Docker tags `3.8.0` (or latest 3.8.x) exist for both `opensearch` and `opensearch-dashboards`.
- [x] **T-R0.2** Skim [Breaking changes](https://docs.opensearch.org/latest/breaking-changes/) for 3.0.0 and 3.8.0; note any new items past this file’s R-sections.
- [x] **T-R0.3** Skim [JWT auth + JWKS](https://docs.opensearch.org/latest/security/authentication-backends/jwt/) for exact config keys on 3.8.
- [x] **T-R0.4** Skim [pretrained models](https://docs.opensearch.org/latest/ml-commons-plugin/pretrained-models/) — confirm MiniLM 1.0.2 ONNX still published.
- [x] **T-R0.5** Human locks G1–G5 (or amends them in this file).

### Phase 1 — Optional: try in-place volume (only if G2 = B)

- [x] **T-R1.1** Snapshot note of `GET /` version, index list, model id, security `authinfo` on 2.19. *(skipped — G2 = A)*
- [x] **T-R1.2** Stop stack; retag images to 3.8; start **without** deleting volume. *(skipped — G2 = A)*
- [x] **T-R1.3** Record boot logs: does security index migrate? Does ML model survive? *(skipped — G2 = A)*
- [x] **T-R1.4** If fail → fall back to Strategy A and document why. *(N/A — Strategy A chosen)*

### Phase 2 — Network proof for JWKS (can run on 2.19 host tools)

- [x] **T-R2.1** From host: `GET http://localhost:8080/realms/enterprise-search-realm/protocol/openid-connect/certs` returns keys (`kid`, `n`, `e`).
- [x] **T-R2.2** From **inside** a throwaway container on the compose network: `GET http://keycloak:8080/realms/.../certs` succeeds.
- [x] **T-R2.3** Confirm `GET http://localhost:8080/.../certs` from inside OpenSearch container **fails** (documents why Docker DNS is required).

---

## Implementation tasks

Order is dependency order. Check only after **run**.

### A. Compose + config pin

- [x] **T-A1** `docker-compose.yml`: `opensearch` image → `opensearchproject/opensearch:3.8.0`.
- [x] **T-A2** `docker-compose.yml`: `opensearch-dashboard` image → `opensearchproject/opensearch-dashboards:3.8.0`.
- [x] **T-A3** Keep env flags (securityconfig modification, ML settings, SSL http off, 2g heap) unless 3.8 rejects a key — then fix and document.
- [x] **T-A4** Update `docker_service_configs/opensearch/opensearch.yml` comments/settings to match live compose (still reference-only unless mounted).
- [x] **T-A5** README version table: OpenSearch **3.8.0**.

### B. Fresh data (Strategy A)

- [x] **T-B1** `docker compose down`. *(stopped/removed OS + Dashboards only; Keycloak/Postgres/MinIO kept)*
- [x] **T-B2** Remove volume `opensearch_data` (explicit `docker volume rm` / `compose down -v` only for OS volume — do **not** wipe Postgres/MinIO unless human asks).
- [x] **T-B3** Delete or clear `opensearch_model_id` from `backend/runtime_config.json`.
- [x] **T-B4** `docker compose up -d opensearch` (and Keycloak if down); wait until 9200 accepts basic `admin`.
- [x] **T-B5** `GET /` → version `3.8.0`.

### C. JWT domain → JWKS

- [x] **T-C1** Rewrite `jwt-auth-domain.yml.example` for 3.8: `type: jwt`, `jwks_uri`, iss/aud/roles_key; document Docker DNS vs issuer; mark PEM as legacy/fallback only.
- [x] **T-C2** Change `opensearch_security.py`:
  - Stop requiring realm `public_key` PEM for the happy path.
  - PUT `jwt_auth_domain` with `jwks_uri` = `{keycloak_internal_url}/realms/{realm}/protocol/openid-connect/certs`.
  - Keep `required_issuer` = public `keycloak_url` issuer.
  - Keep `roles_key: roles`, `required_audience: api-client`, basic domain enabled order > JWT.
  - Do **not** set authenticator type `openid`.
- [x] **T-C3** Ensure `Settings` exposes internal Keycloak URL for JWKS (already `keycloak_internal_url`) and use it only for `jwks_uri`.
- [x] **T-C4** `cd backend && uv run python -m init_services` (security portion at least).
- [x] **T-C5** Password-grant token → `GET /_plugins/_security/authinfo`: `files_searcher`, not `all_access` (searcher + realm-admin).
- [x] **T-C6** Prove JWT rejects garbage token; prove basic `admin` still works.
- [x] **T-C7** (Optional stretch) Rotate Keycloak realm keys in a throwaway realm/clone **or** document that JWKS cache picks up new `kid` without re-init — human check if rotation test is too heavy.

### D. Roles / DLS / ML predict (re-apply, re-prove)

- [x] **T-D1** Re-PUT `files_searcher` / `files_writer` / rolesmapping (idempotent); keep ML predict on searcher.
- [x] **T-D2** JWT user cannot index; basic admin can.
- [x] **T-D3** Confirm DLS template still uses `${user.roles}` and `${attr.jwt.groups}` only.

### E. Model, pipelines, index

- [x] **T-E1** Register/deploy MiniLM ONNX 1.0.2; persist new `opensearch_model_id`.
- [x] **T-E2** Second init does not start a new register if model present.
- [x] **T-E3** Upsert ingest + search pipelines; create index from `index-mapping.json`.
- [x] **T-E4** Index one doc without `embedding`; confirm ingest fills dim 384.
- [ ] **T-E5** Hybrid search as JWT user returns the doc (predict permission live). **BLOCKED — see Implementation log.** Neural-only JWT search **does** return the doc.

### F. DLS hybrid proofs (reuse Task 3 proof table)

- [x] **T-F1** Run / revive `SEARCH_PROOF=1` (or `search_proof.py`) on 3.8. *(script added; hybrid path 500s)*
- [x] **T-F2** searcher hits role chunk; misses group-only; misses empty ACL. *(proved with **match / neural**, not hybrid pipeline)*
- [x] **T-F3** realm-admin hits group-only (`engineering`) and role chunk. *(keyword DLS; hybrid blocked)*
- [x] **T-F4** `${attr.jwt.groups}` did **not** go empty (proves we stayed on `jwt`, not `openid`).

### G. Documentation sync

- [x] **T-G1** Update `2_project_overview_tasks.md`: version 3.8.0; JWT via JWKS; remove “2.19 cannot jwks_uri”.
- [x] **T-G2** Update `6_search_setup.md`: G3 / connection diagram / locked table → JWKS; note Docker DNS for `jwks_uri`.
- [x] **T-G3** README OpenSearch row → 3.8.0; short note on JWKS.
- [x] **T-G4** Add a one-line pointer in this file’s checklist when complete; leave 4_auth_setup as historical or stamp “superseded for JWT keys by 3.8 upgrade”.

### H. Hygiene

- [x] **T-H1** No secrets committed; no Postgres/MinIO wipe unless requested.
- [x] **T-H2** `/health` and `/auth/me` still 200.
- [x] **T-H3** Compose from a clean clone path documented in README (volume wipe command).

---

## Proof table (fill when implementing)

| # | Test | Result |
| --- | --- | --- |
| 1 | `GET /` version = 3.8.0 | **PASS** — Lucene 10.5.0, cluster green |
| 2 | Dashboards 3.8.0 reaches node (optional UI smoke) | **PASS** `/api/status` green 3.8.0 + “OpenSearch is available”. `GET /` is 401 (security Dashboards plugin off; not used) |
| 3 | `authinfo` searcher = `files_searcher` via JWKS JWT | **PASS** — `backend_roles=[search-user]`, `attr.jwt.groups` present |
| 4 | `authinfo` realm-admin = `files_searcher`, not `all_access` | **PASS** |
| 5 | JWT cannot index; basic admin can | **PASS** — JWT 403 |
| 6 | Model deployed; `opensearch_model_id` set | **PASS** — `2PAsTqABzKlhu0IdV6uY` DEPLOYED |
| 7 | Second init skips re-register | **PASS** — “already DEPLOYED” |
| 8 | Ingest fills embedding dim 384 | **PASS** |
| 9 | Hybrid JWT search returns hit | **BLOCKED** — ClassCastException BooleanQuery→HybridQuery (3.8 security wrap). Neural-only JWT **PASS** (`proof-role-search-user`) |
| 10 | DLS role hit / group miss / empty miss (searcher) | **PASS** on `match_all` / neural (not hybrid pipeline) |
| 11 | DLS group hit (realm-admin) | **PASS** on keyword DLS (`attr.jwt.groups` expands) |
| 12 | `/health` + `/auth/me` 200 | **PASS** |
| 13 | Docs no longer mandate PEM-only | **PASS** |

---

## Proposed `jwt_auth_domain` shape (3.8)

Reference only — applied by `init_services`, not mounted:

```yaml
jwt_auth_domain:
  http_enabled: true
  transport_enabled: true
  order: 0
  http_authenticator:
    type: jwt          # NOT openid
    challenge: false
    config:
      jwks_uri: "http://keycloak:8080/realms/enterprise-search-realm/protocol/openid-connect/certs"
      # signing_key: omitted when jwks_uri is set
      jwt_header: Authorization
      subject_key: preferred_username
      roles_key: roles
      required_audience: api-client
      required_issuer: "http://localhost:8080/realms/enterprise-search-realm"
      jwt_clock_skew_tolerance_seconds: 30
  authentication_backend:
    type: noop
```

---

## Out of scope

- Production rolling upgrade / blue-green
- Snapshot repos to MinIO
- Changing embedding model or dimension
- Enabling Dashboards security / mapping JWT users into Dashboards
- Task 4 ingest API / Task 5 search UI
- Upgrading Keycloak, Postgres, or MinIO as part of this slice

---

## Follow-on (after this upgrade)

| Item | Note |
| --- | --- |
| Remove PEM helper entirely | Once JWKS proofs are stable for a while |
| Key rotation chaos test | Confirm new `kid` works without `init_services` |
| Heap tuning | If ONNX on 3.8 OOMs under hybrid load |
| Update CI compose pin | If/when CI exists |

---

## Sources

- [Breaking changes](https://docs.opensearch.org/latest/breaking-changes/) (3.0.0, 3.8.0)
- [JWT authentication / JWKS](https://docs.opensearch.org/latest/security/authentication-backends/jwt/) (`jwks_uri` since 3.3)
- Security PR [#5578](https://github.com/opensearch-project/security/pull/5578) (direct JWKS on jwt backend)
- [Pretrained models](https://docs.opensearch.org/latest/ml-commons-plugin/pretrained-models/)
- Docker Hub: `opensearchproject/opensearch:3.8.0`
- Repo baseline: `docker-compose.yml`, `init_services/opensearch_security.py`, `prompts/cursor_summary/6_search_setup.md`

---

## Checklist status

- [x] Human locked G1–G5
- [x] Research phases 0–2 complete (phase 1 only if keeping volume)
- [ ] Implementation A–H complete *(A–D, E1–E4, F keyword/neural DLS, G–H done; **T-E5 hybrid JWT blocked**)*
- [x] Proof table filled
- [x] Sibling docs updated so agents stop implementing PEM-only JWT

---

## Implementation log (29 Aug 2026)

Executed against the running local compose stack. G1–G5 locked as proposed (latest 3.8.x tag is `3.8.0`; no `3.8.1` / `3.9.0` on Docker Hub).

### Research notes

- **T-R0.1:** Hub tags `opensearch:3.8.0` and `opensearch-dashboards:3.8.0` exist. Name filter also matches old `1.3.8`. No newer 3.8.x patch.
- **T-R0.2:** 3.0 items match this file’s R-sections (JDK 21, system-index REST, Blake2b, knn setting removals). 3.8.0 only adds S3 repo default SSE `AES256` — out of scope (no snapshot repo).
- **T-R0.3:** Official JWT docs: `jwks_uri` on `type: jwt` since 3.3; `signing_key` ignored when `jwks_uri` is set; `kid` required in the JWT header. Keys used: `jwks_uri`, `jwt_header`, `subject_key`, `roles_key`, `required_audience`, `required_issuer`, `jwt_clock_skew_tolerance_seconds`. `cache_jwks_endpoint` is not a documented config key (cache is automatic).
- **T-R0.4:** MiniLM `huggingface/sentence-transformers/all-MiniLM-L6-v2` **1.0.2** still listed with ONNX.
- **T-R2:** Host JWKS 200, two RSA keys (`kid` `IBFmff…`, `xaH5mg…`). Compose-network `http://keycloak:8080/.../certs` 200. `localhost:8080` from inside the OS container: curl exit 7.

### What changed in the repo

- `docker-compose.yml` images → `3.8.0` / Dashboards `3.8.0`. Env flags unchanged; 3.8 accepted them.
- `opensearch.yml` (reference): comments list live compose env; added `allow_securityconfig_modification`.
- `jwt-auth-domain.yml.example`: JWKS + Docker-DNS vs public issuer. PEM marked fallback.
- `opensearch_security.py`: no PEM fetch. `jwks_uri` from `Settings.keycloak_internal_url`. `files_searcher` now has `cluster:admin/opensearch/ml/predict` **and** `cluster:admin/opensearch/ml/models/get` (3.8 neural query 403 without the latter).
- DLS template: `${attr.jwt.groups}` **without** extra `[]`. 3.8 jwt+JWKS expands that claim as a JSON array; `[${attr.jwt.groups}]` became `[["_empty"]]` and DLS evaluation 500ed. `${user.roles}` still needs `[${user.roles}]`.
- `roles.yml` matches the REST body.
- `search_proof.py` added; `SEARCH_PROOF=1` optional from `run.py`.
- `runtime_config.json` model id after wipe+init: `2PAsTqABzKlhu0IdV6uY`.
- Docs: README, `2_project_overview_tasks.md`, `6_search_setup.md`, stamp on `4_auth_setup.md`.
- Postgres + MinIO volumes were **not** removed (`my_enterprise_search_postgres_data`, `my_enterprise_search_minio_data` still present).

### Hybrid + DLS blocker (needs human)

JWT **hybrid** search (`match` + `neural` + `enterprise-search-hybrid`) as `files_searcher` fails:

```
class_cast_exception: BooleanQuery cannot be cast to HybridQuery
```

Keyword `match` / `match_all` + DLS works. Neural-only + DLS works (searcher sees only `proof-role-search-user`). So JWKS, DLS expansion, predict, and `models/get` are fine. The failure is DLS wrapping the top-level `hybrid` query.

Upstream: Security PR [#6416](https://github.com/opensearch-project/security/pull/6416) (merged **25 Aug 2026**) applies DLS via `hybrid.filter(...)` so HybridQuery stays top-level. **Supported only on OpenSearch 3.9+.** Docker Hub has **no** `3.9.0` tag yet (29 Aug 2026). Neural-search PR #1432 (unwrap DLS wrappers) is in 3.8.0.0 and is **not** enough for this wrap shape.

**Do not** fall back to keyword-only or basic `admin` for product search (C4). Waiting on human:

1. Stay on 3.8.0; accept neural/keyword DLS proofs; defer hybrid+DLS JWT until 3.9 ships.
2. Pause this slice until `opensearchproject/opensearch:3.9.0` exists, then bump G1 and re-run `search_proof.py`.
3. Something else (say so).

T-C7 key-rotation chaos test was **not** run (documented only).

### Human test instructions

Cluster is already on 3.8.0 with JWKS applied. From repo root:

```bash
# version + health
curl -sS -u 'admin:OpenSearchAdmin123!' http://localhost:9200/ | python3 -c 'import json,sys; print(json.load(sys.stdin)["version"]["number"])'
curl -sS -u 'admin:OpenSearchAdmin123!' http://localhost:9200/_cluster/health

# Dashboards
curl -sS http://localhost:5601/api/status   # expect 200, version 3.8.0, overall green
# Browser: http://localhost:5601  (GET / may 401; plugin off)

# JWT authinfo (demo secret from .env.sample)
TOKEN=$(curl -sS -X POST 'http://localhost:8080/realms/enterprise-search-realm/protocol/openid-connect/token' \
  -d grant_type=password -d client_id=api-client -d client_secret=api-client-secret \
  -d username=searcher -d password=searcherpass | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')
curl -sS http://localhost:9200/_plugins/_security/authinfo -H "Authorization: Bearer $TOKEN"
# expect roles=["files_searcher"], no all_access

# FastAPI
cd backend && uv run python -c "from app.main import run; run()"
# other terminal:
curl -sS http://localhost:8000/health
curl -sS http://localhost:8000/auth/me -H "Authorization: Bearer $TOKEN"

# hybrid proof (currently expected to fail on 3.8)
cd backend && uv run python -c 'from init_services.search_proof import run; run()'
```

UI login: `http://localhost:5173` as `searcher` / `searcherpass` or `realm-admin` / `adminpass`.

After a future wipe, use the README volume-rm snippet (OS volume only) then `cd backend && uv run python -m init_services`.
