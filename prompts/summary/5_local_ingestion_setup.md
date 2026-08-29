# Local ingestion — implemented 29 August 2026

This slice is **implemented as of 29 August 2026**. Task 4 (Ingest API): a signed-in `search-user` or `admin` can upload **PDF / TXT / CSV** via a **Google Drive–style resumable, multi-step API** (initiate → PUT byte ranges → complete/process). Original bytes land in MinIO as **one full object**. Postgres gets a `files` row only (**no** `file_acl`). Text is extracted, chunked (**600 tokens**, **75-token overlap**), and bulk-indexed into `enterprise-search-chunks` **without** an `embedding` field (ingest pipeline fills **384-dim** vectors). Chunk identity uses existing **`chunk_id`** + **`chunk_seq`** only.

**React multi-file uploader** (same day follow-on): `/upload` drives that API from the SPA — multi-select PDF/TXT/CSV, per-file progress, sequential resumable sessions, cancel/retry. Still **no** auto-ACL (files index but are not searchable until Task 6).

Auth is live (`prompts/summary/2_auth_layer.md`). Postgres identity + `files` / `file_acl` exist (`prompts/summary/3_data_modeling.md`). Search platform is live (`prompts/summary/4_search_layer.md`). Working plan: `prompts/cursor_summary/7_ingest_api.md` (G1–G8, C2/C4/C9 locked; MinIO no-chunking locked). G8 originally deferred React; the Drive-style client below supersedes that for the upload path only.

**Not** done yet: `POST /search`, search UI, View files / Open stream, admin ACL CRUD, connectors, OCR, Celery/Redis.

---

## Sources of truth (unchanged)

```
Keycloak     → authentication: users, realm roles, groups, memberships
Postgres     → identity mirror + files metadata + file_acl + upload_sessions
OpenSearch   → chunks + embeddings + denormalized allowed_roles / allowed_groups
MinIO        → original bytes at object_store_path (single full put on complete)
JWT          → request authn/authz (upload routes); NOT used for OpenSearch writes
```

---

## Architecture (this slice)

```
Client (React /upload · curl · scripts/ingest_proof.py)
  Authorization: Bearer <user JWT>
        │
        ├─ POST /files/uploads              → upload_id + upload_sessions row
        ├─ PUT  /files/uploads/{id}         → Content-Range parts → local staging .bin
        ├─ GET  /files/uploads/{id}         → progress / status
        ├─ POST /files/uploads/{id}/complete
        │         │
        │         ├─ read local staging
        │         ├─ parse → chunk (600 / 75; CSV packs by token budget)
        │         ├─ MinIO put_object → local/{file_id}/{safe_name}   (ONE object)
        │         ├─ Postgres INSERT files (no file_acl)
        │         └─ OpenSearch _bulk as basic admin (omit embedding; refresh=wait_for)
        └─ DELETE /files/uploads/{id}       → cancel; drop local staging
```

```
PDF  → pypdf extract text ──────────► [chunker 600 / overlap 75] → chunks
TXT  → UTF-8 decode ────────────────► [chunker 600 / overlap 75] → chunks
CSV  → rows → serialize (all cols)
         → pack rows while tokens ≤ 600
         → if single row > 600 ──► [chunker 600 / overlap 75]
```

---

## Locked decisions (law)

| ID | Decision |
| --- | --- |
| G1 | Accept **pdf / txt / csv** only; else **415**. `file_type` = extension. |
| G2 | Upload allowed for realm roles **`search-user` or `admin`**. |
| G3 | **No** auto `file_acl`. Chunks indexed with `allowed_roles: []`, `allowed_groups: []`. Never write `_empty`. |
| G4–G6 | CSV like text; pack consecutive rows by token budget (not fixed N); serialize `ColumnName: value`; blank line between packed rows; skip empty cells. |
| G7 | Drive-style resumable multi-step API (not single multipart POST). |
| G8 | Task 4 lock was **API only**. **Superseded for UI:** React Drive-style uploader shipped (multi-file `/upload`). API contract unchanged. |
| C2 | **600** tokens / **75** overlap. Estimator ≈4 chars/token (no tiktoken / no OS tokenize). Embedding dim stays 384. |
| C4 | **`pypdf`**; no OCR; empty PDF → **422**. |
| C9 | Use existing `chunk_id` + `chunk_seq` only; no `row_index` / mapping migration. |
| MinIO | **No chunking in MinIO.** Ranges assemble on local disk; **one** `put_object` on complete. |

Assumptions used as written: C1 (UTF-8 CSV, header, excel dialect), C3 (25 MiB), C5 (`chunk_id = {file_id}:{seq:06d}` = OS `_id`), C6 (compensation), C7 (`upload_sessions` TTL 24h), C8 (inline process on complete).

---

## What shipped

### A. Schema + settings + deps

**Alembic** `a1b2c3d4e5f6` (revises `68a730544554`): table `upload_sessions`

| Column | Notes |
| --- | --- |
| `id` | UUID PK |
| `user_id` | JWT `sub` (string); session owner |
| `safe_filename`, `file_type` | basename; `pdf`\|`txt`\|`csv` CHECK |
| `size_bytes`, `bytes_received` | declared vs received |
| `status` | `initiated` \| `uploading` \| `processing` \| `completed` \| `failed` \| `expired` \| `cancelled` |
| `staging_path` | **local filesystem** path (not MinIO) |
| `file_id`, `chunk_count` | set on success |
| `error_message`, timestamps, `expires_at` | TTL 24h from initiate |

**Does not** alter `files` (still no `original_filename` / `status` / `uploaded_by` — data-model G8).

**Settings** (`app/core/config.py`):

- `ingest_max_upload_bytes = 26_214_400` (25 MiB)
- `ingest_chunk_tokens = 600`
- `ingest_chunk_overlap_tokens = 75`
- `ingest_upload_part_multiple = 262144` (256 KiB Drive convention; advisory)
- `ingest_upload_session_ttl_hours = 24`
- `ingest_local_staging_dir` → `backend/data/upload-staging` (gitignored)

**Dep:** `pypdf>=6` in `pyproject.toml` (proved `6.16.2`).

### B. Extractors + chunker

| Module | Role |
| --- | --- |
| `services/ingest/chunker.py` | `estimate_tokens` ≈ `ceil(len/4)`; overlapping `chunk_text` |
| `services/ingest/detect.py` | Extension allowlist; `safe_filename` |
| `services/ingest/txt_extract.py` | UTF-8; empty → error |
| `services/ingest/pdf_extract.py` | pypdf (lazy import); no text → error |
| `services/ingest/csv_extract.py` | DictReader; serialize; pack by budget; oversized row → chunker |
| `services/ingest/__init__.py` | `build_content_chunks` orchestrator helper |

Offline unit checks: `uv run python -m scripts.ingest_unit_checks` — **PASS**.

### C. Staging + MinIO + OpenSearch + process

| Module | Role |
| --- | --- |
| `services/local_staging.py` | Sequential append to `{upload_id}.bin` during PUT ranges |
| `services/minio_store.py` | `put_object` / `delete_object` / `object_exists` only — **no** multipart, **no** MinIO ranges |
| `services/opensearch_ingest.py` | Bulk as basic `admin`; omit `embedding`; `refresh=wait_for`; delete-by-query for compensation; proof fetch with optional wait |
| `services/upload.py` | Initiate / put_range / status / complete / cancel + C6 compensation |

**Complete flow (C6/C8):** validate bytes → `processing` → parse/chunk → **single MinIO put** → INSERT `files` → OS bulk → `completed` → delete local staging. On failure: rollback `files`, delete OS docs if any, delete MinIO object if written, status=`failed`, leave local staging for debug. **Never** auto-insert `file_acl`.

**Authz:** every upload route requires `require_product_user`; session `user_id == JWT sub` (admins do **not** bypass — landmine 14).

### D. API

Wired in `app/api/router.py` → `app/api/routes/files.py` (`prefix=/files`).

| Method | Path | Notes |
| --- | --- | --- |
| `POST` | `/files/uploads` | 201 initiate; 401/413/415 |
| `PUT` | `/files/uploads/{id}` | `Content-Range: bytes start-end/total`; sequential `start == bytes_received`; incomplete **308** + `Range`; full bytes **200** |
| `GET` | `/files/uploads/{id}` | status / progress |
| `POST` | `/files/uploads/{id}/complete` | inline process; 201 completed; 422 parse; 502 infra; 409 already done |
| `DELETE` | `/files/uploads/{id}` | cancel → 204 |

`upload_url` in initiate response is `/api/files/uploads/<uuid>` (Vite proxy shape); FastAPI path has no `/api` prefix.

Schemas: `app/schemas/files.py`.

### E. Chunk document shape (unchanged mapping)

```json
{
  "file_id": "<uuid>",
  "chunk_id": "<uuid>:000000",
  "chunk_seq": 0,
  "meta_file_type": "csv",
  "meta_file_size": 12345,
  "updated_at": "<iso8601>",
  "uploaded_at": "<iso8601>",
  "content": "<chunk text>",
  "allowed_roles": [],
  "allowed_groups": [],
  "object_store_path": "local/<uuid>/export.csv",
  "ingestion_type": "local",
  "original_source": null
}
```

`chunk_id` = OpenSearch `_id` = `{file_id}:{chunk_seq:06d}`. No FastAPI-side embeddings. No new OS fields.

### F. React uploader (follow-on, 29 August 2026)

Signed-in users open **`/upload`** (nav **Upload**). Same product rules as the API: PDF/TXT/CSV, **25 MiB** each, roles `search-user`|`admin` via existing `ProtectedRoute` + Bearer JWT.

| Piece | Role |
| --- | --- |
| `frontend/src/api/client.ts` | `apiFetch` / GET / POST JSON / DELETE; silent refresh on 401; PUT uses `redirect: 'manual'` so Drive-style **308** Resume Incomplete is not followed by the browser |
| `frontend/src/api/uploads.ts` | Client validation; `resumableUpload` = initiate → sequential **256 KiB** `Content-Range` PUTs → complete; cancel → DELETE |
| `frontend/src/pages/Upload.tsx` | Multi-file picker; per-file progress / errors / result; uploads **sequentially**; Cancel aborts current session and stops the queue; retry failed/cancelled; Remove before start |
| `frontend/src/App.tsx` | Route `/upload` behind `ProtectedRoute` |
| `frontend/src/components/layout/Navbar.tsx` | **Upload** link |
| `frontend/src/components/ui/Button.tsx` | `disabled` support |

**UX notes:** multi-select replaces the previous selection; each file is its own `upload_sessions` row; success shows `file_id` + `chunk_count` and reminds that **no ACL** was assigned. Does **not** implement View files list or download (Task 5).

**How to try:** stack + API up → sign in → `/upload` → select one or more allowed files → Upload.

---

## Automated proofs already run (29 August 2026)

Driver: `cd backend && uv run python -m scripts.ingest_proof` (**not** `init_services`).

| # | Test | Result |
| --- | --- | --- |
| 1 | Initiate without token | **PASS** 401 |
| 2 | Initiate `.exe` | **PASS** 415 |
| 3 | Initiate size > cap | **PASS** 413 |
| 4 | TXT initiate → PUT → complete as searcher | **PASS** completed; MinIO final; PG `files`; `file_acl` count 0 |
| 5 | OS docs for `file_id` | **PASS** ≥1 chunk; embedding len 384; ACL empty; `chunk_id`/`chunk_seq`; `ingestion_type=local` |
| 6 | Long TXT (>600 tokens) | **PASS** `chunk_count=6`; contiguous `chunk_seq` |
| 7 | PDF with text | **PASS** |
| 8 | Textless PDF | **PASS** complete → 422 / `failed` |
| 9 | CSV short rows | **PASS** packed `chunk_count=1`; content has column names |
| 10 | CSV one row ≫ 600 tokens | **PASS** `chunk_count=2` |
| 11 | Interrupt mid-PUT → GET → resume → complete | **PASS** |
| 12 | Other user accesses `upload_id` | **PASS** 403 |
| 13 | OS bulk failure compensation | **SKIP** (manual/chaos only) |
| 14 | JWT still cannot index directly | **PASS** 403 |
| 15 | `/health` + `/auth/me` | **PASS** 200 |

Also: `uv run alembic upgrade head` applied `upload_sessions`; `uv sync` installed `pypdf==6.16.2`; unit checks **PASS**.

**Fix during proofs:** empty OS hits on CSV was a refresh race → bulk now uses `refresh=wait_for`; proof fetch retries up to 10s.

---

## Intentional deviations / landmines honored

1. **No auto-ACL** — empty arrays only; Task 6 grants later.
2. **User JWT never writes OS** — bulk uses basic `admin`.
3. **No FastAPI embeddings** — pipeline fills 384-dim.
4. **Always chunk** — long emails/PDFs not left as one blob.
5. **CSV packing by token budget**, not fixed N.
6. **Never `_empty` in ACL fields.**
7. **No filename/status on `files`** — in-flight state lives on `upload_sessions`.
8. **Resumable API**, not single-shot multipart.
9. **v1 sequential ranges only** (`start == bytes_received`); gaps → 400.
10. **No new OS mapping fields.**
11. **C6 compensation** — no orphan `files` / searchable chunks without `files`.
12. **Does not wait on hybrid+DLS** (Task 5 still blocked on OS 3.8 Landmine 13).
13. **600/75 kept** despite MiniLM ~512 input truncate risk — monitor; do not silently lower.
14. **Session ownership** — `user_id == JWT sub`; admin does not hijack.
15. **Final path includes `file_id`**; local staging uses `upload_id`.
16. **MinIO not chunked** — local staging for API ranges; one full put on complete.

---

## Files touched / created

| Path | Change |
| --- | --- |
| `backend/app/models/upload_session.py` | **NEW** model |
| `backend/app/models/__init__.py` | export `UploadSession` |
| `backend/alembic/versions/a1b2c3d4e5f6_upload_sessions.py` | **NEW** migration |
| `backend/app/core/config.py` | ingest settings + local staging dir |
| `backend/app/schemas/files.py` | **NEW** request/response models |
| `backend/app/api/routes/files.py` | **NEW** upload routes |
| `backend/app/api/router.py` | include files router |
| `backend/app/services/local_staging.py` | **NEW** disk staging |
| `backend/app/services/minio_store.py` | **NEW** single full put |
| `backend/app/services/opensearch_ingest.py` | **NEW** admin bulk + helpers |
| `backend/app/services/upload.py` | **NEW** session + process orchestrator |
| `backend/app/services/ingest/*` | **NEW** detect / chunker / txt / pdf / csv |
| `backend/scripts/ingest_unit_checks.py` | **NEW** offline checks |
| `backend/scripts/ingest_proof.py` | **NEW** live proof driver |
| `backend/pyproject.toml` | `pypdf` |
| `.gitignore` | `backend/data/upload-staging/` |
| `prompts/cursor_summary/7_ingest_api.md` | plan + checklist + locks |
| `prompts/summary/5_local_ingestion_setup.md` | **this file** |
| `frontend/src/api/client.ts` | general authenticated fetch (incl. 308-safe PUT) |
| `frontend/src/api/uploads.ts` | **NEW** resumable upload client |
| `frontend/src/pages/Upload.tsx` | **NEW** multi-file upload page |
| `frontend/src/App.tsx` | `/upload` route |
| `frontend/src/components/layout/Navbar.tsx` | Upload nav link |
| `frontend/src/components/ui/Button.tsx` | `disabled` prop |

OpenSearch mapping JSON / `init_services` product path: **unchanged** (except settings available to the app). `proof-*` docs left alone.

---

## How to re-verify

```bash
cd backend
uv sync
uv run alembic upgrade head
uv run python -m scripts.ingest_unit_checks
uv run python -m scripts.ingest_proof
```

Stack must be up (`./start-dev.sh`). Expect `[ok] 1`…`12`, `[skip] 13`, `[ok] 14`…`15`.

Spot-check MinIO: only `local/<file_id>/<safe_name>` after success — **no** `staging/` MinIO prefixes.

---

## What was intentionally not done

- `GET /files`, `GET /files/{id}/content`, `POST /search`, search UI / View files list (Task 5)
- Admin ACL assign + `update_by_query` (Task 6)
- Background workers / async complete (C8 stays inline)
- MinIO multipart or ranged writes
- Mapping JWT users to `files_writer` (Task 7)
- Session GC cron (lazy expire on access only)
- Proof 13 chaos (force OS bulk failure)
- Parallel multi-file PUTs (UI uploads files one after another)
- Client resume of a prior `upload_id` across page reloads (Cancel → DELETE; new pick starts new sessions)

---

## Follow-on

| Task | Needs from this ingest slice |
| --- | --- |
| 5 Search/view | Real `file_id`s + MinIO paths; ACL grants still required for DLS hits; still **WAIT** on hybrid+DLS (OS 3.9+) |
| 6 Admin ACL | `update_by_query` on `file_id` to fill `allowed_*` |
| 7 Hardening | Ingest via `files_writer`; session GC cron |
| Upload UI | **Done** — multi-file Drive-style client on `/upload` (`bytes_received` progress per file) |

---

## Changelog

| Date | Change |
| --- | --- |
| 29 Aug 2026 | Ingest API + proofs (Task 4). |
| 29 Aug 2026 | React multi-file resumable uploader (`/upload`); summary updated. |
