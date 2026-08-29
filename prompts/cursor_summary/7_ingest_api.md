# Ingest API — implementation plan (Task 4)

Working notes to implement **Task 4 (Ingest API)** from `prompts/cursor_summary/2_project_overview_tasks.md`. Auth is live (`prompts/summary/2_auth_layer.md`). Postgres identity + `files` / `file_acl` exist (`prompts/summary/3_data_modeling.md`). Search platform (index, MiniLM, ingest pipeline, DLS proofs) is live (`prompts/summary/4_search_layer.md`). This file is the source of truth for the ingest slice. Do not invent a second ACL model, auto-grant on upload, or FastAPI-side embeddings.

**Agent rules while implementing**
- Run and execute code to confirm it works before moving on.
- Do not proceed past a broken step; fix it first.
- Where something cannot be verified in this environment, leave a clear human check and wait for feedback.
- Do **not** start `POST /search`, search results UI, View files list, Open/download streaming, or admin ACL CRUD (Tasks 5–6). Resumable upload → parse → chunk → MinIO + Postgres + OpenSearch only.
- Treat **Locked decisions** as law. For **Remaining confusion**, use the **Assumption** in that row until the human overrides; do not invent a third option.
- Task 5 remains **WAIT** on OpenSearch 3.8 hybrid+DLS (Landmine 13). Ingest does **not** depend on hybrid search working.

Human locked **G1–G8** and **C2 / C4 / C9** on **29 August 2026** (chat). Remaining C1 / C3 / C5 / C6 / C7 use the documented Assumption.

---

## What “done” means

A signed-in `search-user` or `admin` can upload **PDF / TXT / CSV** via a **Google Drive–style resumable, multi-step API** (initiate → PUT byte ranges → complete/process). Original bytes land in MinIO. Postgres gets a `files` row only (**no** `file_acl`). Text is extracted, chunked (**600 tokens**, **75-token overlap**), and bulk-indexed into `enterprise-search-chunks` **without** an `embedding` field (ingest pipeline fills it → **384-dim** vectors). Chunk identity uses existing **`chunk_id`** + **`chunk_seq`** only (no new mapping fields). Chunks start with empty `allowed_roles` / `allowed_groups`. Unsupported types are rejected. **No React uploader** in this slice (API + curl/script proofs only).

| Actor | What they may do in this slice |
| --- | --- |
| FastAPI | Resumable upload routes (initiate / put range / status / complete); **not** byte download streaming |
| React | **Unchanged** (G8) |
| MinIO | **Single full-object put only** on complete (`local/{file_id}/{safe_name}`). No multipart, no ranged/partial MinIO writes. Resumable byte ranges assemble in **local filesystem staging** first. |
| Postgres | `upload_sessions` (new) + insert `files` on success; **never** auto-insert `file_acl` |
| OpenSearch | Bulk index chunks as basic `admin`; omit `embedding` |
| `init_services` | Unchanged except settings if needed |

---

## Current state (do not re-scaffold)

Already in place from Tasks 0–3:

### Auth
- Bearer JWT (`search-user` or `admin`) on product APIs.
- OpenSearch writes: internal basic `admin` only. JWT users cannot index (proved).
- Ingest must **not** use the user JWT to write chunks.

### Postgres (`files`)
- Columns: `id`, `object_store_path`, `file_type`, `size_bytes`, `ingestion_type`, `original_source`, `uploaded_at`, `updated_at`.
- **No** `original_filename`, `content_type`, `status`, `uploaded_by_user_id` (data-model G8).
- `ingestion_type` CHECK = `'local'` only.
- `file_acl` exists but ingest must not write it (G3).
- **No** `upload_sessions` table yet → add in this slice (Alembic).

### OpenSearch
- Index `enterprise-search-chunks` with `default_pipeline=enterprise-search-embed`.
- Existing fields only — including `chunk_id`, `chunk_seq`. **Do not** add `row_index` or other CSV provenance fields (C9).
- MiniLM ONNX → embedding dim **384**. Chunking is mandatory.
- `proof-*` docs remain (leave them alone).

### MinIO
- Bucket `enterprise-search-files` ensured by `init_services`.
- No product put/get helpers in `app/services` yet.

### FastAPI surface today
- Routes: `/health`, `/auth/me`, `/auth/admin-ping` only.
- `app/services/` is a docstring stub.

---

## Human gate — decisions (LOCKED 29 Aug 2026)

### G1. Supported file types this slice

| | |
| --- | --- |
| Status | **LOCKED** |
| Decision | Accept **PDF, TXT, CSV**. Reject everything else with **415**. |
| `file_type` / `meta_file_type` | `pdf`, `txt`, `csv`. |
| Still | `ingestion_type=local` only. |

### G2. Who may upload

| | |
| --- | --- |
| Status | **LOCKED** |
| Decision | Authenticated users with realm role **`search-user` or `admin`**. |
| Not | Anonymous. No separate uploader role. |

### G3. Default ACL on upload (reaffirm)

| | |
| --- | --- |
| Status | **LOCKED** (from data-model G3) |
| Decision | **No automatic `file_acl`.** Chunks indexed with `allowed_roles: []` and `allowed_groups: []`. Not searchable until Task 6. Never write `_empty` into ACL fields. |

### G4. CSV → text pipeline

| | |
| --- | --- |
| Status | **LOCKED** |
| Decision | CSV is ingested like text, but **rows are packed into groups by token/word budget during chunking** (see G5), then serialized (G6), then split with the shared chunker when a unit still exceeds the budget. |
| One file | One completed upload = one MinIO object + one `files` row + many OpenSearch chunks sharing that `file_id`. |

### G5. How many CSV rows per group

| | |
| --- | --- |
| Status | **LOCKED** |
| Decision | **Not a fixed N.** While building chunks, pack consecutive serialized rows into a group **while the estimated token count stays ≤ `ingest_chunk_tokens` (600)**. Never split mid-row when packing. |
| Oversized single row | If **one** row alone exceeds 600 tokens (long email body), that row is its own unit and the **overlapping text chunker** splits it into multiple chunks (`chunk_seq` advances). |
| Short rows | Multiple short rows may share one OpenSearch chunk (same `content` blob) when they fit under 600 tokens together. |
| Estimator | Same token estimator as the text chunker (C2). Prefer not crossing row boundaries inside a single emitted chunk when packing; overlap applies when a single unit is force-split. |

### G6. How a CSV row/group becomes `content`

| | |
| --- | --- |
| Status | **LOCKED** |
| Decision | Include **all columns**. Format each row as lines `ColumnName: value`. Rows in a packed group separated by a blank line. Skip empty cells. Preserve Unicode. |
| Example | `From: a@co\nTo: b@co\nSubject: Reset\nBody: <long email text>` |

### G7. Upload protocol (Google Drive–style resumable)

| | |
| --- | --- |
| Status | **LOCKED** |
| Decision | **Multi-step resumable upload**, modeled on [Google Drive resumable uploads](https://developers.google.com/workspace/drive/api/guides/manage-uploads) — not a single multipart POST. |
| Why | Client can show progress, retry failed ranges, and resume after network failure. No React UI in this slice; API must still support the protocol so a later UI (or curl) can drive it. |

**Protocol (product shape):**

| Step | HTTP | Role |
| --- | --- | --- |
| 1. Initiate | `POST /files/uploads` | JSON metadata: declared `filename`, `size_bytes`, `content_type` (advisory). Returns `upload_id` + session info. Creates `upload_sessions` row; prepares MinIO staging. |
| 2. Upload bytes | `PUT /files/uploads/{upload_id}` | Body = one byte range. Headers: `Content-Range: bytes start-end/total` (Drive-style), `Content-Length` = chunk size. Chunks ideally multiples of **256 KiB** except the final chunk (Drive convention). Response **308** (or **204**) with `Range: bytes=0-received` while incomplete; **200** when all bytes received. |
| 3. Status | `GET /files/uploads/{upload_id}` | `bytes_received`, `size_bytes`, `status` (`initiated` \| `uploading` \| `processing` \| `completed` \| `failed` \| `expired`). |
| 4. Complete / process | Automatic on final byte receipt **or** explicit `POST /files/uploads/{upload_id}/complete` | Validate size match → promote staging object to final path → parse → chunk → Postgres `files` → OpenSearch bulk. Status → `processing` then `completed` / `failed`. |

Resume (Drive-like): if a PUT fails, client `GET`s status (or empty PUT with `Content-Range: */total`) and continues from `bytes_received`. Session owned by initiating user (`JWT sub`); other users get **403**.

Max file size still capped (C3). Sessions expire (C7).

### G8. Frontend in this slice?

| | |
| --- | --- |
| Status | **LOCKED** |
| Decision | **API only.** No React uploader. Prove with curl / a Python script that walks initiate → ranged PUTs → status → completed file. |

### C9. Chunk metadata fields

| | |
| --- | --- |
| Status | **LOCKED** |
| Decision | Use existing index fields **`chunk_id`** and **`chunk_seq`** for chunk identity/order. **Do not** add `row_index`, thread id, or other CSV-only fields to the mapping. |

---

## Remaining confusion (assumptions for implementation)

### C1. CSV dialect

| Assumption | UTF-8; delimiter `,`; first row is header; `csv` module excel dialect. Reject if zero data rows. No `.xlsx`. |

### C2. Chunk size / overlap / tokenizer — **LOCKED**

| | |
| --- | --- |
| Status | **LOCKED** |
| Decision | Target **600 tokens** per chunk, **75-token overlap**. Embedding output dim remains **384** (model property, unrelated to input window). |
| Tokenizer | Lightweight estimator (`tiktoken` or ≈4 chars/token word-ish splitter). Document choice. Do **not** call OpenSearch to tokenize. |
| Note | See Landmine 13: MiniLM implementations often truncate near **512** input tokens. Human explicitly chose 600; implement 600 and monitor that OS still embeds full `content` (or accept model-side truncate). Do not silently change back to 400 without human override. |

### C3. Max upload size

| Assumption | **25 MiB** declared `size_bytes` / received total (`ingest_max_upload_bytes`). Oversize initiate or final mismatch → **413** / **400**. |

### C4. PDF library — **LOCKED**

| | |
| --- | --- |
| Status | **LOCKED** |
| Decision | **`pypdf`**. Page order → plain text → chunker. No extractable text → fail processing with clear error (**422** on complete). **No OCR**. |

### C5. OpenSearch `_id` / `chunk_id` scheme

| Assumption | `chunk_id` = `{file_id}:{chunk_seq:06d}`. Same string as OpenSearch `_id`. `chunk_seq` is **global monotonic** across the file (0..n-1), including across CSV row groups and force-splits. |

### C6. Failure compensation

| Assumption | Bytes assemble in **local staging** until process succeeds. On process failure: no `files` row (or delete if inserted), delete any partial OS docs, delete MinIO final object if already written, leave/delete local staging per status=`failed`, return error on complete/status. On success: **one** MinIO `put_object` to `local/{file_id}/{safe_name}`; `files` inserted; OS bulk OK; local staging deleted. Never leave searchable chunks without a `files` row. **Do not** multipart or range-write to MinIO. |

### C7. Upload session storage + TTL

| Assumption | New Postgres table `upload_sessions` (Alembic). TTL **24h** from initiate; expired sessions GC’d lazily on access + optional init/cron later. Store: id, user_id (JWT `sub`), safe_filename, file_type, size_bytes, bytes_received, status, staging_path (**local filesystem** path for resumable assembly), file_id nullable, error_message nullable, timestamps, expires_at. **Not** a column on `files` (keeps data-model G8). MinIO is written only on successful complete (single full object). |

### C8. Processing model after bytes complete

| Assumption | Processing runs **inline** on the complete step (same request as finalization). Status flips to `processing` then `completed`. No Redis/Celery in v1. If processing is too slow for large 25 MiB files, revisit — not in scope unless human asks. Client polls `GET .../status` only if we later move process to background; for v1, complete response waits until index finishes. |

---

## Architecture (this slice)

```
Client (curl / script — no React)
  Authorization: Bearer <user JWT>
        │
        ├─ POST /files/uploads          → upload_id (session)
        ├─ PUT  /files/uploads/{id}     → Content-Range byte parts → **local staging file**
        ├─ GET  /files/uploads/{id}     → progress / status
        └─ POST /files/uploads/{id}/complete  (or auto on last byte)
                │
                ├─ read local staging → parse → CSV word-budget groups → text chunker (600 / 75)
                ├─ MinIO **single** put_object → final object_store_path (no multipart / no ranged MinIO)
                ├─ Postgres INSERT files (no file_acl)
                └─ OpenSearch bulk (basic admin, omit embedding)
```

```
PDF  → extract text ──────────────► [chunker 600 / overlap 75] → chunks
TXT  → decode utf-8 ──────────────► [chunker 600 / overlap 75] → chunks
CSV  → rows → serialize (all cols)
         → pack rows while tokens ≤ 600
         → if single row > 600 ──► [chunker 600 / overlap 75]
         → else emit packed group as one chunk (or chunker if estimator drift)
```

---

## API contract (locked shape)

### `POST /files/uploads`

- Auth: `search-user` | `admin`.
- Body:

```json
{
  "filename": "export.csv",
  "size_bytes": 12345,
  "content_type": "text/csv"
}
```

- **201**:

```json
{
  "upload_id": "<uuid>",
  "upload_url": "/api/files/uploads/<uuid>",
  "status": "initiated",
  "size_bytes": 12345,
  "bytes_received": 0,
  "expires_at": "<iso8601>"
}
```

- **415** if extension not pdf/txt/csv; **413** if `size_bytes` over cap.

### `PUT /files/uploads/{upload_id}`

- Headers: `Content-Range: bytes {start}-{end}/{total}`, body = raw bytes.
- `total` must match session `size_bytes`; `start` must equal current `bytes_received` (strict sequential for v1 — simpler than arbitrary sparse ranges).
- Incomplete: **308** (Resume Incomplete) or **204** with `Range: bytes=0-{bytes_received-1}`.
- Complete bytes: **200** `{ "status": "uploading", "bytes_received": <total> }` (ready to complete) **or** auto-kick process per C8.

### `GET /files/uploads/{upload_id}`

```json
{
  "upload_id": "<uuid>",
  "status": "uploading",
  "file_type": "csv",
  "size_bytes": 12345,
  "bytes_received": 4096,
  "file_id": null,
  "chunk_count": null,
  "error": null,
  "expires_at": "<iso8601>"
}
```

When `completed`: `file_id` set, `chunk_count` set, mirrors `files` metadata needed by proofs.

### `POST /files/uploads/{upload_id}/complete`

- Requires `bytes_received == size_bytes`.
- Runs parse → chunk → PG → OS (C6/C8).
- **201** (or **200**):

```json
{
  "upload_id": "<uuid>",
  "status": "completed",
  "id": "<file uuid>",
  "file_type": "csv",
  "size_bytes": 12345,
  "object_store_path": "local/<file-uuid>/export.csv",
  "ingestion_type": "local",
  "original_source": null,
  "chunk_count": 42,
  "uploaded_at": "<iso8601>"
}
```

- **422** parse/empty PDF/bad CSV; **502** OpenSearch failure after compensation; **409** if already completed.

### Out of scope endpoints

- `GET /files/{id}/content` / Open → Task 5.
- `GET /files` list → Task 5.
- ACL assign → Task 6.
- Delete file / abort cleanup beyond session expire → minimal `DELETE /files/uploads/{id}` to cancel staging is **allowed** and recommended.

---

## Chunk document shape (unchanged mapping)

Every bulk item **omits** `embedding`:

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

`chunk_id` / `chunk_seq` are the only chunk metadata identifiers (C9). No mapping migration.

---

## Module layout (proposed)

```
backend/app/
  api/routes/files.py              # upload session routes
  schemas/files.py                 # initiate / status / complete responses
  models/upload_session.py         # NEW upload_sessions
  services/
    local_staging.py               # resumable byte assembly on disk
    minio_store.py                 # single full-object put / delete (no MinIO chunking)
    opensearch_ingest.py           # bulk index as basic admin
    ingest/
      __init__.py                  # complete/process orchestrator helpers
      detect.py
      chunker.py                   # 600 tokens, 75 overlap
      pdf_extract.py               # pypdf
      txt_extract.py
      csv_extract.py               # serialize + word/token budget packing
    upload.py                      # session + process orchestrator
backend/alembic/versions/…         # upload_sessions
```

Settings:

- `ingest_max_upload_bytes: int = 26_214_400`  # 25 MiB
- `ingest_chunk_tokens: int = 600`
- `ingest_chunk_overlap_tokens: int = 75`
- `ingest_upload_part_multiple: int = 262144`  # 256 KiB (Drive convention; last part exempt)
- `ingest_upload_session_ttl_hours: int = 24`
- `ingest_local_staging_dir` — local path for resumable assembly (default `backend/data/upload-staging`)

Deps: `pypdf`; tokenizer helper as needed; MinIO client already used by init.

---

## MIME / extension allowlist

| Ext | Accepted Content-Type (advisory) | `file_type` |
| --- | --- | --- |
| `.pdf` | `application/pdf` | `pdf` |
| `.txt` | `text/plain` | `txt` |
| `.csv` | `text/csv`, `application/csv`, `text/plain` | `csv` |

Extension (lowercased) is source of truth. Unknown → 415 on initiate.

---

## CSV specifics (email-row safe)

1. Decode UTF-8 (hard failure → processing error).
2. `csv.DictReader` with header required.
3. Serialize each row (G6).
4. **Pack by token budget (G5):** accumulate rows while `estimate_tokens(group_text) ≤ 600`; flush group as one chunk when the next row would exceed; if a lone row exceeds 600, run `chunker(row_text, size=600, overlap=75)`.
5. `chunk_seq` global across the file; `chunk_id = f"{file_id}:{chunk_seq:06d}"`.
6. No extra OpenSearch fields for row numbers (C9).

**Do not** embed cells separately. **Do not** use a fixed row count N.

---

## Landmines

### 1. Auto-ACL on upload

Empty ACL arrays only (G3).

### 2. User JWT writing to OpenSearch

Bulk index with basic `admin` only.

### 3. Embedding in FastAPI

Omit `embedding`; pipeline fills 384-dim vectors.

### 4. Skipping chunking

Long emails / PDFs truncate in the model if unchunked. Always chunk.

### 5. Fixed-N CSV grouping

Human rejected fixed N. Pack by token/word budget only.

### 6. Writing `_empty` into `allowed_groups`

Keep `[]`.

### 7. Filename / status on `files`

Do not add `original_filename` or `status` to `files`. Use `upload_sessions` for in-flight state.

### 8. Single-shot multipart instead of resumable

Violates G7. Implement initiate + ranged PUT + complete.

### 9. Sparse / out-of-order ranges (v1)

Require sequential `start == bytes_received`. Reject gaps with **400** (simpler than full Drive sparse resume). Document; upgrade later if needed.

### 10. Mapping drift / new chunk fields

No new OS fields. `chunk_id` + `chunk_seq` only (C9).

### 11. Partial dual-write orphans

Follow C6. Staging ≠ final `files` row.

### 12. Blocking on hybrid search

Prove ingest with admin GET + embedding length 384. Do not wait for JWT hybrid+DLS.

### 13. 600-token chunks vs MiniLM input window

Human locked **600 / 75**. Many MiniLM builds truncate near **512**. Implement as locked; if embeddings look truncated in proofs, report to human — do not silently lower size.

### 14. Session hijacking

Authorize every upload route with `session.user_id == JWT sub` (admins do not bypass unless human later asks).

### 15. `object_store_path` uniqueness

Final path always includes `file_id`. Local staging paths use `upload_id` (not MinIO).

### 16. MinIO chunked / multipart upload

**Forbidden.** API resumable ranges ≠ MinIO multipart. One `put_object` of the full file on complete only.

---

## Proofs (run after implementation)

| # | Test | Expect |
| --- | --- | --- |
| 1 | Initiate without token | 401 |
| 2 | Initiate `.exe` | 415 |
| 3 | Initiate size > cap | 413 |
| 4 | Initiate TXT → PUT parts (incl. non-final 256KiB-aligned if large) → complete as searcher | `completed`; MinIO final object; PG `files`; `file_acl` count 0 |
| 5 | OS docs for `file_id` | ≥1 chunk; `embedding` len 384; ACL empty; `chunk_id`/`chunk_seq` set; `ingestion_type=local` |
| 6 | Long TXT (>600 tokens) | `chunk_count` > 1; contiguous `chunk_seq` |
| 7 | PDF with text | completed + chunks |
| 8 | Textless PDF | complete → failed/422 |
| 9 | CSV short rows | packing may yield fewer chunks than row count; content has column names |
| 10 | CSV one row ≫ 600 tokens | `chunk_count` > 1; overlap behavior present |
| 11 | Interrupt mid-PUT → GET status → resume from `bytes_received` → complete | success |
| 12 | Other user accesses `upload_id` | 403 |
| 13 | OS bulk failure | no orphan `files` row / compensated |
| 14 | JWT still cannot index directly | 403 |
| 15 | `proof-*` untouched; `/health` + `/auth/me` | 200 |

Proof driver: `uv run python -m …` or `scripts/ingest_proof.py` — **not** default `init_services`.

---

## Tasks to perform (implementation checklist)

Check a box only after that step has been **run**.

### 0. Human lock

- [x] G1–G8 locked 29 Aug 2026
- [x] C2 (600/75), C4 (pypdf), C9 (chunk_id/seq only) locked
- [x] MinIO no-chunking locked 29 Aug 2026 (local staging → single full put)
- [ ] C1, C3, C5–C8 assumptions accepted or overridden (use as written unless human says otherwise)

### A. Schema + settings + deps

- [x] Alembic revision written: `a1b2c3d4e5f6_upload_sessions.py` (**migration not applied yet — human**)
- [x] Settings: max bytes, 600/75, 256KiB part multiple, session TTL, `ingest_local_staging_dir`
- [x] `pypdf` added to `pyproject.toml` (**`uv sync` not run in agent env — human**)

### B. Extractors + chunker

- [x] `chunker.py`: ≈4 chars/token estimator; 600 tokens, 75 overlap
- [x] `txt_extract.py`, `pdf_extract.py` (lazy pypdf import; empty → error)
- [x] `csv_extract.py`: serialize all columns; pack by token budget; oversized row → chunker
- [x] Offline unit checks passed: `uv run python -m scripts.ingest_unit_checks`

### C. Resumable upload + stores

- [x] `local_staging.py`: sequential ranged append on disk
- [x] `minio_store.py`: **single** full-object put / delete (no multipart / no MinIO ranges)
- [x] Session service: initiate, put range (sequential), status, complete, cancel
- [x] `opensearch_ingest.py`: bulk as basic admin; omit `embedding`
- [x] Process orchestrator with C6 compensation (`upload.py`)

### D. API

- [x] Routes: `POST /files/uploads`, `PUT …/{id}`, `GET …/{id}`, `POST …/{id}/complete`, `DELETE …/{id}`
- [x] Authz: `search-user`|`admin` + session owner check
- [x] Wire router (`app/api/router.py`); backend reload starts clean

### E. Proofs

- [x] Run proof table (incl. resume + long CSV email row) — 2026-08-29; proof 13 skipped (chaos-only)
- [x] Confirm empty ACL; embedding dim 384; `chunk_id`/`chunk_seq` only
- [x] Fix: bulk uses `refresh=wait_for`; proof fetches retry up to 10s (proof 9 race)

### F. Hygiene

- [x] No React changes; no auto ACL; no FastAPI embeddings; no new OS mapping fields
- [x] No Task 5/6 scope creep
- [x] Leave `proof-*` alone
- [x] Summary writeup in `prompts/summary/5_local_ingestion_setup.md`

---

## Human testing (do this next)

Agent sandbox cannot hit `localhost:8000`, Docker socket, or PyPI. Please run these on your machine and paste the output (especially any failures).

### 1. Install deps + migrate

```bash
cd backend
uv sync
uv run alembic upgrade head
```

Confirm:

```bash
uv run python -c "import pypdf; print(pypdf.__version__)"
# psql or:
uv run python -c "from sqlalchemy import text; from app.db.session import get_engine; e=get_engine();
print(e.connect().execute(text(\"SELECT to_regclass('public.upload_sessions')\")).scalar())"
```

Expect `upload_sessions` printed (not `None`).

### 2. Ensure stack is up

`./start-dev.sh` (or your usual compose + API). Smoke:

```bash
curl -sS http://localhost:8000/health
curl -sS http://localhost:9200 -u "admin:$OPENSEARCH_INITIAL_ADMIN_PASSWORD"
```

### 3. Offline unit checks (already green in agent; re-run after sync)

```bash
cd backend
uv run python -m scripts.ingest_unit_checks
```

### 4. Full ingest proofs

```bash
cd backend
uv run python -m scripts.ingest_proof
```

Expect lines `[ok] 1` … `[ok] 15` (13 is intentionally skipped). Failures print `PROOF FAILED: …`.

### 5. Manual spot checks (optional)

```bash
# token as searcher
TOKEN=$(curl -sS -X POST "http://localhost:8080/realms/enterprise-search-realm/protocol/openid-connect/token" \
  -d "grant_type=password&client_id=api-client&client_secret=$KEYCLOAK_API_SECRET&username=searcher&password=searcherpass" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

printf 'hello\n' > /tmp/hello.txt
SIZE=$(wc -c </tmp/hello.txt)

curl -sS -X POST http://localhost:8000/files/uploads \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d "{\"filename\":\"hello.txt\",\"size_bytes\":$SIZE,\"content_type\":\"text/plain\"}"

# then PUT with Content-Range bytes 0-$((SIZE-1))/$SIZE, then POST .../complete
```

Verify MinIO object is **one** key under `local/<file_id>/…` (no `staging/` objects).

---

## Implementation notes (agent dump 29 Aug 2026)

| Area | Choice |
| --- | --- |
| Token estimator | ≈4 chars/token (no tiktoken); documented in `chunker.py` |
| MinIO | Single `put_object` on complete only; ranges → `backend/data/upload-staging/{upload_id}.bin` |
| Chunk ids | `{file_id}:{chunk_seq:06d}` = OS `_id` |
| ACL | Always `[]` / `[]`; never write `file_acl` |
| PUT incomplete | HTTP **308** + `Range: bytes=0-{n-1}` |
| PUT complete bytes | HTTP **200** `{status, bytes_received}` — client must `POST …/complete` |
| Tokenizer vs MiniLM | Still 600/75 per lock; watch embedding truncate near 512 |

**Blocked on human:** ~~`uv sync` / alembic / proofs~~ — done 29 Aug 2026. Proof 13 (OS bulk failure compensation) still manual/chaos-only.

---

## Explicitly out of scope

- React uploader (G8)
- `POST /search` / results UI / View files / Open stream (Task 5)
- Admin ACL + `update_by_query` (Task 6)
- Connectors / non-`local` ingestion
- OCR; `.xlsx` / TSV / JSONL
- New OpenSearch fields beyond existing mapping
- Celery/Redis background workers (unless C8 revisited)
- Mapping JWT users to `files_writer` (Task 7)

---

## Follow-on

| Task | Needs from this ingest slice |
| --- | --- |
| 5 Search/view | Real `file_id`s + MinIO paths; ACL grants still required for DLS hits |
| 6 Admin ACL | `update_by_query` on `file_id` |
| 7 Hardening | Ingest via `files_writer`; session GC cron |
| Later UI | Drive-style client using these APIs (progress from `bytes_received`) |

---

## Changelog (locks)

| Date | Change |
| --- | --- |
| 29 Aug 2026 | Human locked G1–G8, C2 (600/75), C4 (pypdf), C9 (chunk_id/seq only). G5 = token/word-budget packing. G7 = Drive-style resumable multi-step upload. G8 = no React. |
| 29 Aug 2026 | Human: MinIO must receive the file **without chunking** — local staging for API ranges; single full-object put on complete. |
