# Search and view API + UI — Task 5 complete

Shipped **30 August 2026**. Full Task 5 from `prompts/cursor_summary/8_search_view_api.md`:

1. **Search** — `POST /search` client-side hybrid on OpenSearch **3.8.0** (match ∥ neural + FastAPI merge), user JWT + DLS.
2. **View files** — `GET /files` lists Postgres `files` visible via `file_acl` (JWT role/group names).
3. **Open** — `GET /files/{id}/content` streams MinIO after Postgres ACL (not DLS alone).

Prior Search-half dump: `prompts/summary/6_search_view.md`. Hybrid workaround SoT: `prompts/cursor_summary/hybrid_search_issue_sol.md`.

---

## What “done” means (verified)

| Actor | Capability | Status |
| --- | --- | --- |
| FastAPI | `POST /search` | Live (client hybrid) |
| FastAPI | `GET /files`, `GET /files/{id}`, `GET /files/{id}/content` | Live |
| React `/` | Search + results + Open | Live |
| React `/files` | List + Open | Live |
| OpenSearch | User-JWT match + neural only on product path | Live |
| Postgres | ACL list/open authz | Live |
| MinIO | Stream after ACL | Live |
| `init_services.search_proof` native hybrid | Still **BLOCKED** on 3.8 | Unchanged |

---

## Locked decisions followed

| Gate | Choice |
| --- | --- |
| G1 | Client hybrid on 3.8; no native `hybrid` on hot path; no keyword-only / admin search |
| G2 | View/Open shipped in same slice as Search |
| G3 | Proof seed script (not Task 6 UI); inserts `file_acl` + `update_by_query` for 1–2 files |
| G4 | `display_name` = basename of `object_store_path` (no Alembic) |
| G5 | Chunk-grain search hits (not collapsed files) |
| G6 | `require_product_user`; realm `admin` does **not** bypass file ACL |
| G7 | Postgres `file_acl` authoritative for download |

Assumptions C1–C9 applied as written in the plan.

---

## Architecture

```
React (/) ──POST /search──► FastAPI
                              │ user_bearer_header (NOT basic admin)
                              ├── match  ──► OpenSearch (DLS OK)
                              ├── neural ──► OpenSearch (DLS OK)  (parallel)
                              │ min_max + 0.3/0.7 merge; strip embedding
                              ▼
                         SearchResponse DTO → Results UI → Open (blob)

React (/files) ──GET /files──► FastAPI ──SQL──► files ⋈ file_acl ⋈ roles/groups
                                                   (JWT names; editor⇒viewer; ignore _empty)
                              │
                              └─GET /files/{id}/content──► ACL ──► MinIO stream
```

Sources of truth at request time:

| Concern | Source |
| --- | --- |
| Authn / role names | JWT |
| Search visibility | OpenSearch DLS (`allowed_*`) |
| List / Open visibility | Postgres `file_acl` |
| File bytes | MinIO `object_store_path` from DB only |

---

## Backend changes (this completion pass)

### New

| Path | Role |
| --- | --- |
| `backend/app/services/file_access.py` | `user_can_view_file`, `list_visible_files`, `display_name_from_path`, content-type map |
| `backend/scripts/seed_file_acl_for_proofs.py` | G3: upsert role/group ACL + OS `update_by_query` |
| `frontend/src/api/files.ts` | `listFiles`, `getFile`, `downloadFileContent` (blob) |

### Extended

| Path | Change |
| --- | --- |
| `backend/app/services/minio_store.py` | `get_object_bytes`, `iter_object` |
| `backend/app/schemas/files.py` | `FileListItem`, `FileDetail`, `FileListResponse` |
| `backend/app/api/routes/files.py` | `GET ""`, `GET /{id}`, `GET /{id}/content` (uploads routes kept first) |
| `backend/scripts/search_view_proof.py` | V1–V8 list/open + prior S1–S6 + S13 seeded-file search |
| `frontend/src/pages/Files.tsx` | Real ACL list + Open |
| `frontend/src/pages/Search.tsx` | Open button → same blob download helper |

### Already present (Search half, 29 Aug)

`opensearch_search.py`, `schemas/search.py`, `routes/search.py`, `api/search.ts`, search config knobs, `search_unit_checks.py`.

### ACL matching rules

- Join `files` ↔ `file_acl` ↔ `roles` / `groups`.
- Match JWT **names** (`CurrentUser.roles` / `.groups`); `_empty` already stripped in `security.py`.
- `permission IN ('viewer','editor')` (editor ⇒ view).
- No user-principal grants required in v1 product path.
- Missing file → **404**; ACL deny → **403**; no token → **401**.
- Content stream uses **only** `files.object_store_path` from DB (no client object key).

### Content stream details

- `Content-Type`: pdf→`application/pdf`, txt→`text/plain`, csv→`text/csv`, else octet-stream.
- `Content-Disposition: attachment` with ASCII fallback + RFC 5987 `filename*`.
- Range requests out of scope.

---

## G3 proof seed

```bash
cd backend
uv run python -m scripts.seed_file_acl_for_proofs
```

Behavior:

1. Pick up to 2 recent ingest files (prefer txt/csv/pdf).
2. File A → role `search-user` viewer; OS `allowed_roles=["search-user"]`.
3. File B → group `engineering` viewer; OS `allowed_groups=["engineering"]`.
4. Idempotent ACL upsert; never grants `_empty`.
5. Uses basic OS `admin` **only** for `update_by_query` (not product search).

Local run (30 Aug): file A `opaque-redirect-fix.txt` (250 chunks updated); file B `longrow.csv` (2 chunks).

---

## Proofs run

```bash
cd backend
uv run python -m scripts.seed_file_acl_for_proofs
uv run python -m scripts.search_view_proof
uv run python -m scripts.search_unit_checks
```

| # | Test | Result |
| --- | --- | --- |
| V1 | `GET /files` no token → 401 | **PASS** |
| V2 | searcher list (empty or seeded) → 200 | **PASS** |
| V3 | after seed, searcher lists file A; basename display_name | **PASS** |
| V4 | content bytes == MinIO | **PASS** |
| V5 | searcher 403 on engineering-only file B; realm-admin 200 | **PASS** |
| V6 | missing UUID → 404 | **PASS** |
| V7 | content no token → 401 | **PASS** |
| V8 | JWT cannot index → 403 | **PASS** |
| S1 | `POST /search` no token → 401 | **PASS** |
| S2 | searcher `alpha-proof-token` → `proof-role-search-user`; no embedding | **PASS** |
| S3 | searcher misses bravo/charlie proofs | **PASS** |
| S4 | realm-admin hits group-engineering proof | **PASS** |
| S5 | empty/whitespace `q` → 400 | **PASS** |
| S6 | `/health` + `/auth/me` → 200 | **PASS** |
| S13 | search finds seeded real `file_id` | **PASS** |
| Unit | min_max / merge / DTO strip | **PASS** (prior) |
| Platform | native hybrid as JWT | **BLOCKED** (expected on 3.8) |

Frontend: `tsc --noEmit` clean. Manual UI smoke (browser list/download/search Open) left for human.

---

## Frontend behavior

- **View files:** fetch `GET /files`, show basename + short id + size; Open → authenticated fetch → blob → download.
- **Search Open:** same helper; synthetic `proof-*` hits show a clear error (no MinIO object).
- Plain `<a href>` never used for content (would omit Bearer).

---

## Intentionally not done

- Task 6 admin ACL CRUD / dual-write progress UI
- Auto `file_acl` on upload
- Keyword-only or basic-admin product search
- Native hybrid as product default / declaring `search_proof` PASS
- Collapsing chunk hits to one row per file
- In-browser PDF preview / HTTP Range
- `original_filename` column (G4 override not taken)
- Optional belt-and-suspenders OpenSearch exists-query on open (PG remains SoT)

---

## Follow-on

| Next | Needs from this slice |
| --- | --- |
| Task 6 Admin ACL | Reuse `file_access` helpers; replace G3 seed with real grants + sync job |
| OpenSearch 3.9+ | Re-prove native hybrid in `search_proof`; optionally `search_mode=native_hybrid` |
| Hardening | Repair PG↔OS ACL drift |

---

## Human checks (optional)

1. Sign in as `searcher` → `/files` shows seeded file A → Open downloads.
2. Sign in as `realm-admin` → `/files` shows A (search-user) and B (engineering) → Open both.
3. Search for content from file A → hit → Open downloads.
4. Confirm Search still refuses empty query and surfaces 502/503 clearly.
