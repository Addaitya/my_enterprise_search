# Search and view API + UI — implementation plan (Task 5)

Working notes to implement **Task 5 (Search and view API + UI)** from `prompts/cursor_summary/2_project_overview_tasks.md`. Auth is live (`prompts/summary/2_auth_layer.md`). Postgres identity + `files` / `file_acl` exist (`prompts/summary/3_data_modeling.md`). Search platform (index, MiniLM, ingest/search pipelines, DLS) is live (`prompts/summary/4_search_layer.md`). Local ingest + React `/upload` are live (`prompts/summary/5_local_ingestion_setup.md`). This file is the source of truth for the search/view slice. Do not invent a second ACL model, search as basic `admin`, or FastAPI-side embeddings.

**Agent rules while implementing**
- Run and execute code to confirm it works before moving on.
- Do not proceed past a broken step; fix it first.
- Where something cannot be verified in this environment, leave a clear human check and wait for feedback.
- Do **not** start admin ACL CRUD, Keycloak user/role/group create, or `update_by_query` progress UI (Task 6). Search/view/list/open only.
- Treat **Locked decisions** as law. For **Remaining confusion**, use the **Assumption** in that row until the human overrides; do not invent a third option.
- **Hard gate (G1):** ship product `POST /search` / results UI via **client-side hybrid** (match ∥ neural + merge in FastAPI) per `prompts/cursor_summary/hybrid_search_issue_sol.md`. Stay on OpenSearch **3.8.0**. Native OS `hybrid` + DLS remains blocked until 3.9+. Do **not** ship keyword-only or basic-admin search. View files + Open may proceed under G2 independently.

**Human override 29 August 2026:** G1 WAIT lifted for product search via client-side hybrid (not via OpenSearch upgrade). Platform native-hybrid proofs in `init_services/search_proof.py` stay **BLOCKED** on 3.8.

---

## What “done” means

A signed-in `search-user` or `admin` can:

1. **Search** — `POST /search` runs **client-side hybrid** (BM25 match ∥ neural, then min_max + 0.3/0.7 merge in FastAPI) against `enterprise-search-chunks` with the **caller’s JWT** so OpenSearch DLS applies. Response strips `embedding`. React `/` shows results with snippet + **Open**.
2. **View files** — navbar `/files` lists Postgres `files` the caller may see via `file_acl` (JWT role/group **names**; `editor` implies view).
3. **Open / download** — stream original bytes from MinIO only after a **Postgres ACL** check (DLS does **not** cover downloads). Optional belt-and-suspenders: user-JWT OpenSearch `GET` on a chunk for the same `file_id`.

| Actor | What they may do in this slice |
| --- | --- |
| FastAPI | `POST /search`; `GET /files`; `GET /files/{id}`; `GET /files/{id}/content` (stream) |
| React | Wire `/` Search + `/files` View files; Open downloads; keep `/upload` as-is |
| OpenSearch | **Read** only, as **user JWT** (match + neural + DLS; no native `hybrid` on 3.8 hot path). Never basic `admin` for search |
| Postgres | ACL-filtered list + open authz; **no** new auto-grants |
| MinIO | `get_object` / stream after ACL pass |
| `init_services` | Unchanged unless OpenSearch version bump is human-approved |

---

## Current state (do not re-scaffold)

Already in place from Tasks 0–4:

### Auth
- Bearer JWT (`search-user` or `admin`) via `require_product_user`.
- `user_bearer_header(request)` exists specifically so search forwards the user token — **use it**.
- OpenSearch: JWT domain + `files_searcher` DLS + ML `predict` / `models.get`. JWT users **cannot** index (proved).
- Seed: `realm-admin` (`admin`+`search-user`, group `engineering`); `searcher` (`search-user`, group `_empty`).

### OpenSearch (3.8.0)
- Index `enterprise-search-chunks`; ingest pipeline embeds `content` → 384-dim; search pipeline `enterprise-search-hybrid` weights `[0.3, 0.7]`.
- `opensearch_model_id` in `runtime_config.json`.
- **Landmine 13:** JWT **hybrid + DLS** → `BooleanQuery cannot be cast to HybridQuery`. Keyword and neural-only DLS **pass**. Product contract remains hybrid (Task 3 C4).
- `proof-*` docs kept (role / group / empty ACL fixtures). Ingested product chunks currently have **`allowed_roles: []`, `allowed_groups: []`** until Task 6 grants.

### Ingest / MinIO / Postgres
- Resumable upload API + React `/upload` (PDF/TXT/CSV).
- `files` row on complete; **no** auto `file_acl`.
- MinIO: single full object at `local/{file_id}/{safe_name}`. `MinioStore` has put/delete/exists — **no get/stream yet**.
- `files` has **no** `original_filename` (data-model G8 / C5). Display must derive from `object_store_path` basename **or** add a column (human gate G4).

### FastAPI / React stubs today
- Routes: `/health`, `/auth/*`, `/files/uploads*` only. No `POST /search`, no `GET /files` list, no content stream.
- React: `/` Search page is a **disabled** input stub; `/files` is a placeholder; Navbar already links Search / Upload / View files.

---

## Dependency map (read this first)

```
                    ┌──────────────────────────────────────────┐
                    │  OpenSearch 3.8: native hybrid+DLS BLOCKED │
                    │  Product path: client hybrid (G1 override) │
                    └──────────────────┬───────────────────────┘
                                       ▼
              POST /search: match ∥ neural (user JWT) → merge → DTO
                                       │
Ingested files ──empty ACL──► need grants for DLS hits on real files
                                       │
                    ┌──────────────────┴───────────────────────┐
                    │  Task 6 admin ACL (later)                │
                    │  OR proof-seed ACL (G3)                  │
                    └──────────────────┬───────────────────────┘
                                       ▼
              View files / Open  ◄── Postgres file_acl (no hybrid needed)
```

| Capability | Needs hybrid behavior? | Needs `file_acl` rows? | Needs OS `allowed_*`? |
| --- | --- | --- | --- |
| `GET /files` list | No | **Yes** | No |
| `GET /files/{id}/content` | No | **Yes** | No (Postgres check) |
| `POST /search` + results UI | **Yes** (client hybrid on 3.8) | Indirect (via OS denorm) | **Yes** |
| Search hits on `proof-*` | Yes | No (fixtures have OS ACL) | Already set |

**Implication:** without G3 proof-seed (or Task 6), View files is empty for real uploads, and product search returns no real-file hits. `proof-*` can exercise client-hybrid DLS without waiting on native hybrid or Task 6.

---

## Human gate — decisions to lock

### G1. Hybrid+DLS unblock path

| | |
| --- | --- |
| Status | **LOCKED 29 Aug 2026 (override)** — client-side hybrid on 3.8 |
| Prior lock | Stay on **3.8.0**; hybrid remains product contract; Task 5 `POST /search` waited until hybrid+DLS or override. Do **not** ship keyword-only or basic-admin search. |
| Lock now | **Client hybrid** per `prompts/cursor_summary/hybrid_search_issue_sol.md`: parallel match + neural with user JWT, min_max + arithmetic_mean weights `[0.3, 0.7]` in FastAPI. Native OS `hybrid` stays off the hot path until `search_proof` PASS on 3.9+. |
| Forbidden | Keyword-only product search; admin-proxy search; declaring platform native hybrid PASS via app merge. |
| Assumption | Ship `POST /search` + Search UI on this workaround **now**. View/Open still independent (G2). |

### G2. Slice split (View/Open vs Search)

| | |
| --- | --- |
| Status | **OPEN — Assumption** |
| Assumption | **Ship View files + Open in this plan in parallel with Search.** Search no longer waits on native hybrid (G1 client hybrid). Same checklist file. |
| Not | Implementing Task 6 ACL UI “so View files has data” — use G3 seed instead. |

### G3. How to get ACL data for proofs (pre–Task 6)

| | |
| --- | --- |
| Status | **OPEN — Assumption** |
| Assumption | Proof driver (and optional one-shot script) may **insert `file_acl` rows** + **`update_by_query`** (basic `admin`) to copy role/group **names** into chunk `allowed_roles` / `allowed_groups` for **specific proof `file_id`s**. This is test scaffolding, **not** the admin product. Never grant `_empty`. Never auto-grant on every upload. |
| Alternative | Human runs Task 6 first — then Task 5 proofs use real admin grants. |
| Why | Without this, View/Open/search proofs against real ingest cannot show hits. |

### G4. Display name for list / Open / results

| | |
| --- | --- |
| Status | **OPEN — Assumption** |
| Assumption | **No Alembic in this slice.** Display name = basename of `object_store_path` (already `local/{file_id}/{safe_name}`). Show `file_id` (short) as secondary. |
| Override | Add `original_filename` column (new revision) if human wants a stable name independent of path. |

### G5. Search result grain

| | |
| --- | --- |
| Status | **OPEN — Assumption** |
| Assumption | Return **chunk hits** (OpenSearch docs), not collapsed files. UI shows `content` snippet, `file_id`, `chunk_seq`, score. Multiple chunks from one file may appear. **Open** uses `file_id` → content stream. |
| Why | Matches hybrid ranking; collapsing is a later UX polish. |

### G6. Who may call search / list / open

| | |
| --- | --- |
| Status | **OPEN — Assumption** |
| Assumption | Same as upload: realm role **`search-user` or `admin`** (`require_product_user`). No anonymous. Admin does **not** bypass file ACL for list/open (no “see all files” via realm admin alone). Realm-admin sees files only via grants to `admin` / `search-user` / `engineering` (same as DLS). |

### G7. Open authz path

| | |
| --- | --- |
| Status | **OPEN — Assumption** |
| Assumption | **Postgres `file_acl` is authoritative for download.** Resolve JWT top-level `roles` / `groups` (ignore `_empty` for matching) against role/group names; allow if any grant has `permission IN ('viewer','editor')`. Optionally also verify a user-JWT OpenSearch exists-query on `file_id` (belt-and-suspenders); if OS says miss but PG says allow → still allow (PG source of truth); if PG denies → **403** even if OS would hit. |
| Not | Streaming MinIO based only on knowing `file_id` / path. Not trusting DLS alone. |

---

## Remaining confusion (assumptions for implementation)

### C1. `POST /search` body shape

| Assumption | `{ "q": "<string>", "size": 10 }` with `size` clamped 1..50 (default 10). No filters/facets in v1. Empty/whitespace `q` → **400**. |

### C2. Hybrid body (locked product contract)

| Assumption | **Default (`search_mode=client_hybrid`):** two user-JWT OS queries in parallel (match on `content` + neural on `embedding`, `k=50`), then FastAPI min_max + arithmetic_mean weights `[0.3, 0.7]`. `_source.excludes: ["embedding"]` on both OS requests **and** strip again in the API mapper. **Do not** send native `hybrid` or `search_pipeline` on this path. Native hybrid body + `search_pipeline=enterprise-search-hybrid` only when `search_mode=native_hybrid` after 3.9 proofs. Details: `hybrid_search_issue_sol.md`. |

```json
// Query A (match) — no search_pipeline
{ "size": <fetch>, "query": { "match": { "content": "<q>" } }, "_source": { "excludes": ["embedding"] } }

// Query B (neural) — no search_pipeline
{ "size": <fetch>, "query": { "neural": { "embedding": { "query_text": "<q>", "model_id": "<id>", "k": 50 } } }, "_source": { "excludes": ["embedding"] } }
```

### C3. Response shape for search

| Assumption | Stable product DTO — do not dump raw OS JSON to the SPA.

```json
{
  "q": "<q>",
  "took_ms": 12,
  "total": 3,
  "hits": [
    {
      "file_id": "<uuid>",
      "chunk_id": "<uuid>:000000",
      "chunk_seq": 0,
      "score": 1.23,
      "snippet": "<content truncated ~400 chars>",
      "meta_file_type": "txt",
      "object_store_path": "local/<uuid>/hello.txt",
      "display_name": "hello.txt",
      "uploaded_at": "<iso8601|null>"
    }
  ]
}
```

Omit `embedding` always. `proof-*` hits are allowed to appear (Task 3 C5).

### C4. View files list query

| Assumption | `GET /files?limit=50&offset=0`. Join `files` ↔ `file_acl` ↔ `roles`/`groups` where role/group **name** ∈ JWT roles/groups (exclude matching on `_empty`), and `permission IN ('viewer','editor')`. Distinct files. Order by `uploaded_at DESC`. |

```json
{
  "items": [
    {
      "id": "<uuid>",
      "display_name": "hello.txt",
      "file_type": "txt",
      "size_bytes": 123,
      "ingestion_type": "local",
      "object_store_path": "local/<uuid>/hello.txt",
      "uploaded_at": "<iso8601>",
      "updated_at": "<iso8601>"
    }
  ],
  "total": 1,
  "limit": 50,
  "offset": 0
}
```

### C5. Content stream

| Assumption | `GET /files/{id}/content` → after ACL: MinIO `get_object`, stream with `Content-Type` from `file_type` map (`pdf`→`application/pdf`, `txt`/`csv`→`text/plain` or `text/csv`), `Content-Disposition: attachment; filename="<display_name>"`. **404** if no file or no object; **403** if ACL deny. Range requests **out of scope** v1. |

### C6. `GET /files/{id}` metadata

| Assumption | Same ACL as list; return one file metadata object (no bytes). Useful for Open confirmation UI. |

### C7. Frontend behavior

| Assumption | Search page: controlled input, Enter/button → `POST /search`, list hits with snippet + Open. Files page: fetch list, row Open. Open = `window` navigation or blob download via authenticated fetch to `/files/{id}/content` (Bearer). Prefer blob download so Authorization header works (plain `<a href>` will not send Bearer). |

### C8. Proof ACL seed details

| Assumption | Script seeds one completed ingest file (or reuses last proof upload): grant role `search-user` viewer; optionally grant group `engineering` viewer on a second file. `update_by_query` sets `allowed_roles` / `allowed_groups` to matching **names**. Document IDs / cleanup. Idempotent upsert of ACL rows. |

### C9. Errors from OpenSearch

| Assumption | OS 401/403/5xx/timeout on either subquery → API **502** (fail closed; no silent keyword-only). Missing `opensearch_model_id` → API **503** config error. Default `client_hybrid` never sends native `hybrid`, so ClassCast must not occur on the product path. |

---

## Architecture (this slice)

```
React (/) ──POST /search──► FastAPI
                              │ user_bearer_header (NOT basic admin)
                              ├── match query  ──► OpenSearch (DLS OK)
                              ├── neural query ──► OpenSearch (DLS OK)  (parallel)
                              │ min_max + 0.3/0.7 merge; strip embedding
                              ▼
                         SearchResponse DTO → Results UI → Open

React (/files) ──GET /files──► FastAPI ──SQL──► files ⋈ file_acl ⋈ roles/groups
                                                   (JWT names; editor⇒viewer)
                              │
                              └─GET /files/{id}/content──► ACL check ──► MinIO get_object stream
```

```
Sources of truth at request time
────────────────────────────────
Authn / role names     → JWT (not Postgres membership tables)
Search visibility      → OpenSearch DLS (denormalized allowed_*)
List / Open visibility → Postgres file_acl (JWT names)
File bytes             → MinIO object_store_path
```

---

## API contract (locked shape once G1–G7 settle)

### `POST /search`

- Auth: `search-user` | `admin`.
- Ships with **client hybrid** (G1 override); see `hybrid_search_issue_sol.md`.
- Body: `{ "q": "...", "size": 10 }`.
- **200:** C3 DTO.
- **400** empty q; **401/403** auth; **502** OS failures; **503** missing model_id.

### `GET /files`

- Auth: product user.
- Query: `limit` (default 50, max 100), `offset` (default 0).
- **200:** C4 list. Empty list if no ACL grants (normal pre–Task 6).

### `GET /files/{id}`

- Auth: product user + ACL.
- **200** metadata; **403** deny; **404** missing.

### `GET /files/{id}/content`

- Auth: product user + ACL.
- **200** stream; **403** / **404** as above.

### Out of scope endpoints

- Upload routes — already Task 4.
- Admin ACL assign / progress — Task 6.
- Delete file, rename, preview PDF in-browser viewer chrome — later.
- Suggest / autocomplete / filters — later.

---

## Module layout (proposed)

```
backend/app/
  api/routes/search.py           # POST /search
  api/routes/files.py            # EXTEND: GET /files, GET /{id}, GET /{id}/content
                                 # (keep existing /uploads* routes)
  schemas/search.py              # request + hit DTOs
  schemas/files.py               # EXTEND: FileListItem, FileDetail
  services/
    opensearch_search.py         # client_hybrid_search (default); optional native_hybrid_search
    file_access.py               # Postgres ACL helpers (list / can_view)
    minio_store.py               # ADD get_object / stream helper
  api/deps.py                    # already has user_bearer_header — use it
frontend/src/
  api/search.ts                  # POST /search
  api/files.ts                   # list + metadata + download blob
  pages/Search.tsx               # wire results + Open
  pages/Files.tsx                # list + Open
backend/scripts/
  search_view_proof.py           # API proofs (list/open + client-hybrid search)
  seed_file_acl_for_proofs.py    # optional G3 helper
```

Settings (if needed): `search_default_size`, `search_max_size`, `search_snippet_chars` — defaults fine in code constants first.

---

## Landmines

### 1. Searching as basic `admin`

Bypasses DLS. **Forbidden.** Always `user_bearer_header`.

### 2. Shipping keyword-only / neural-only as product search

Violates Task 3 C4 / G1. Interim proofs only — not the SPA.

### 3. Trusting DLS for downloads

DLS is read-filter on search/get in OS. MinIO stream must re-check **Postgres** ACL (G7).

### 4. Auto-ACL on upload creep

Do not “fix” empty View files by granting everyone on ingest. Use G3 seed or Task 6.

### 5. Granting `_empty`

Never write `_empty` into `file_acl` or `allowed_groups`. Ignore `_empty` when matching JWT groups for list/open.

### 6. Resolving roles from Postgres membership tables

Stale mirror can hide/show incorrectly. Use **JWT** claim names for ACL checks (data-model plan).

### 7. Returning `embedding` to the client

Strip in OS `_source.excludes` and in the DTO mapper.

### 8. `proof-*` in product search

Accepted until manually deleted (Task 3 C5). UI may show odd hits; do not special-case delete in this slice.

### 9. Open via naked `<a href>` without Bearer

Will 401. Use authenticated `apiFetch` → blob → object URL, or a short-lived cookie strategy (out of scope — prefer blob).

### 10. Admin bypass of file ACL

Realm `admin` is dashboard capability, not “all files”. Same ACL rules (G6).

### 11. Dual-write drift (PG grant, OS empty)

List/Open can succeed while Search misses until `allowed_*` updated. G3 seed must update **both**. Task 6 owns ongoing sync.

### 12. Calling native hybrid on the 3.8 hot path

Do **not** send OS native `hybrid` from product `POST /search` on 3.8 (ClassCast). Client hybrid is the product path. Native hybrid only behind `search_mode=native_hybrid` after proofs.

### 13. MinIO path traversal

Only stream `files.object_store_path` from DB after ACL; never take a client-supplied object key.

### 14. Filename-only display without path safety

Basename only; do not reflect raw path into `Content-Disposition` without quoting/sanitizing.

---

## Proofs (run after implementation)

| # | Test | Expect | Needs |
| --- | --- | --- | --- |
| 1 | `GET /files` without token | 401 | — |
| 2 | `GET /files` as searcher, no ACL rows | 200 empty | — |
| 3 | G3 seed: ACL role `search-user` on file A | searcher lists A; `display_name` = basename | G3 |
| 4 | `GET /files/{A}/content` as searcher | 200 bytes match MinIO | G3 |
| 5 | Same content as user with no matching grant | 403 | G3 + second user or revoke |
| 6 | `GET /files/{missing}` | 404 | — |
| 7 | Content without token | 401 | — |
| 8 | JWT still cannot index | 403 | regression |
| 9 | `POST /search` without token | 401 | — |
| 10 | `POST /search` q=`alpha-proof-token` as searcher | hits `proof-role-search-user`; no `embedding` | client hybrid |
| 11 | Searcher search does not return `proof-group-engineering` / `proof-nobody` | miss | client hybrid |
| 12 | realm-admin search hits group-engineering proof | hit | client hybrid |
| 13 | Search after G3 seed finds real file content | hit with `file_id` | client hybrid + G3 |
| 14 | `/health` + `/auth/me` | 200 | — |
| 15 | React smoke: list + download; search | manual | — |

Proof driver: `uv run python -m scripts.search_view_proof` — **not** default `init_services`. Prove **client** hybrid DLS hit/miss (9–12). Skip/print only if API not implemented yet. Platform `search_proof` native hybrid remains **BLOCKED**.

---

## Tasks to perform (implementation checklist)

Check a box only after that step has been **run**.

### 0. Human lock

- [x] G1 path chosen: **client hybrid on 3.8** (`hybrid_search_issue_sol.md`)
- [ ] G2–G7 accepted or overridden
- [ ] C1–C9 assumptions accepted or overridden
- [ ] Confirm: official `3.9.0` image availability before any compose bump (native hybrid only)

### A. Shared ACL + MinIO read (unblocked)

- [x] `file_access.py`: `user_can_view_file(db, user, file_id)`, `list_visible_files(...)` using JWT names; editor⇒viewer; ignore `_empty`
- [x] `MinioStore.get_object` / stream helper
- [x] Schemas for file list/detail
- [x] Routes: `GET /files`, `GET /files/{id}`, `GET /files/{id}/content`
- [x] Wire authz; never client-supplied object keys

### B. Proof seed (G3)

- [x] Script to insert `file_acl` + `update_by_query` for one/two ingest files
- [x] Prove list + download hit/miss (proofs 1–7)

### C. React View files + Open (unblocked)

- [x] `api/files.ts` list + download blob helper
- [x] `Files.tsx` real list + Open
- [x] Reuse download helper from Search Open later

### D. Search API (client hybrid on 3.8)

- [x] Confirm client hybrid product path (not native): unit merge + live `POST /search` proofs
- [x] Keep `init_services.search_proof` native hybrid **BLOCKED** until 3.9
- [x] `opensearch_search.py` + `POST /search` (`client_hybrid_search`)
- [x] Strip embedding; map C3 DTO
- [x] Proofs 9–12 (13 needs G3)

### E. React Search UI

- [x] `api/search.ts`
- [x] `Search.tsx`: enable input, results + Open
- [x] Empty / error states (400/502/503)

### F. Hygiene

- [x] No Task 6 ACL UI; no auto-ACL on upload; no admin search bypass
- [x] Leave `proof-*` unless human asks to delete
- [x] Write summary writeup in `prompts/summary/7_search_view_api.md` when done
- [x] Update checkboxes in `2_project_overview_tasks.md` Task 5 when done

---

## Recommended execution order

1. **G1 locked** — client hybrid on 3.8 (`hybrid_search_issue_sol.md`).
2. Implement **Search D → E** (settings, merge, `POST /search`, proofs, UI) in parallel with **A → B → C** (list/open).
3. When official 3.9 lands: bump OS → re-prove native hybrid in `search_proof` → optionally flip `search_mode=native_hybrid`.
4. Write summary + flip Task 5 boxes.

---

## Explicitly out of scope

- Admin assign privileges / dual-write job UI (Task 6)
- Auto `file_acl` on upload
- Keyword-only or basic-admin product search
- Collapsing chunk hits to one row per file
- In-browser PDF renderer / preview
- HTTP Range downloads
- Connectors / non-`local` files
- Mapping JWT users to `files_writer` (Task 7)
- Deleting `proof-*` fixtures
- Celery/Redis

---

## Follow-on

| Task | Needs from this slice |
| --- | --- |
| 6 Admin ACL | Same PG ACL helpers; replace G3 seed with real grants + `update_by_query` progress |
| 7 Hardening | Search users remain read-only; repair command if PG/OS ACL drift |
| OpenSearch 3.9+ | Retires client-hybrid workaround; re-run `search_proof` native hybrid then set `search_mode=native_hybrid` |

---

## Changelog

| Date | Change |
| --- | --- |
| 29 Aug 2026 | Plan created from Task 5 in `2_project_overview_tasks.md` + summaries 2–5. Captures hybrid+DLS WAIT on 3.8, ACL dependency on Task 6 / G3 seed, and View/Open vs Search split. |
| 29 Aug 2026 | **G1 override:** product Search ships via client-side hybrid on 3.8 (`hybrid_search_issue_sol.md`). Native hybrid remains platform-BLOCKED. C2/C9/diagram/proofs/§D–E updated. |
| 29 Aug 2026 | Search half implemented: `POST /search` client hybrid + proofs + React Search; §D/§E checked. View/Open still open. |
| 30 Aug 2026 | View/Open complete: Postgres ACL list/stream, G3 seed, React `/files` + Search Open; full proofs V1–V8 + S1–S13. Summary → `prompts/summary/7_search_view_api.md`. |
