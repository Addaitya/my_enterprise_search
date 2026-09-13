# Local folder ingestion script — implementation plan

Working notes to implement a **CLI that recursively walks a folder and ingests every allowed file** into the same pipeline as Task 4 (Ingest API). Product reality: `prompts/summary/5_local_ingestion_setup.md`. Search platform, View/Open, and Admin ACL are already live. Connectors remain later (`prompts/cursor_summary/12_ingestion_pipeline_proposal.md`).

This file is the source of truth for this slice. Do **not** invent a second ingest path (different chunk sizes, embeddings in Python, auto-ACL, MinIO multipart, new OpenSearch fields, or a Drive-style HTTP client wrapping files that are already on disk).

**Agent rules while implementing**

- Run and execute code to confirm it works before moving on.
- Do not proceed past a broken step; fix it first.
- Where something cannot be verified in this environment, leave a clear human check and wait for feedback.
- Treat **Locked decisions** as law. For **Remaining confusion**, use the **Assumption** in that row until the human overrides; do not invent a third option.
- Reuse existing ingest modules. Extract a shared “bytes → MinIO + `files` + OpenSearch chunks” function so HTTP complete and the folder script cannot drift.
- Do **not** start connectors, Airbyte/Kafka/Spark, OCR, Celery, new file types, React UI, or ACL assignment.

Human intent (13 Sep 2026): a Python script; pass a folder path; recurse; ingest each file; reuse modules from Task 4.

---

## What “done” means

An operator with the stack up can run:

```bash
cd backend
uv run python -m scripts.ingest_folder /path/to/folder
```

and every **PDF / TXT / CSV** under that folder (nested included) is ingested **exactly like a successful `/files/uploads/.../complete`**:

| Store | Result per file |
| --- | --- |
| MinIO | One full object at `local/{file_id}/{safe_name}` |
| Postgres | One `files` row; **no** `file_acl`; **no** `upload_sessions` row |
| OpenSearch | Chunks in `enterprise-search-chunks`; omit `embedding` (pipeline fills **384-dim**); `allowed_roles: []`, `allowed_groups: []`; `ingestion_type=local` |

Unsupported types and parse failures are **reported and skipped / failed** (default). The process ends with a summary. HTTP upload API still enforces **25 MiB**; React `/upload` stays unchanged. Folder CLI does **not** skip on 25 MiB (S8 / A1).

| Actor | What they may do in this slice |
| --- | --- |
| CLI script | Walk folder → per-file ingest via shared service |
| FastAPI / React | **Unchanged** (complete() refactored to call the shared helper only) |
| MinIO | Same single `put_object` helper |
| Postgres | Insert `files` only |
| OpenSearch | Bulk as basic `admin` |
| Keycloak | **Not used** (this is an ops script, not a user JWT flow) |

---

## Current state (do not re-scaffold)

Already in place from Task 4 (`prompts/summary/5_local_ingestion_setup.md`):

| Module | Role — **reuse, do not rewrite** |
| --- | --- |
| `services/ingest/detect.py` | Extension allowlist; `safe_filename`; `detect_file_type` |
| `services/ingest/chunker.py` | `estimate_tokens` ≈ `ceil(len/4)`; 600 / 75 overlap |
| `services/ingest/txt_extract.py` | UTF-8; empty → error |
| `services/ingest/pdf_extract.py` | pypdf; no OCR; empty → error |
| `services/ingest/csv_extract.py` | DictReader; serialize; pack by token budget; **oversized row → `chunk_text`** (G5). Parser still uses CPython default `csv.field_size_limit` **131072 (128 KiB)** — that is the gap to fix in this slice. |
| `services/ingest/__init__.py` | `build_content_chunks` orchestrator |
| `services/minio_store.py` | `put_object` / `delete_object` / `final_object_path` |
| `services/opensearch_ingest.py` | `build_chunk_document`, `bulk_index_chunks`, `delete_chunks_by_file_id` |
| `services/upload.py` | HTTP session + **inline process** (parse → MinIO → PG → OS + C6) |
| `models/file.py` | `files` row shape |
| `app/core/config.py` | `ingest_max_upload_bytes`, `ingest_chunk_tokens`, `ingest_chunk_overlap_tokens` |
| `scripts/ingest_proof.py` | Live HTTP proof (leave as-is; do not teach the folder script to speak Drive protocol) |
| `scripts/ingest_unit_checks.py` | Offline chunker/CSV checks (keep; add folder-walker checks separately) |

**HTTP complete flow today** (must stay semantically identical after extract):

```
staging bytes
  → build_content_chunks (pdf/txt/csv, 600/75)
  → MinIO put_object  local/{file_id}/{safe_name}
  → INSERT files (no file_acl)
  → OpenSearch _bulk (omit embedding; refresh=wait_for)
  → on failure: C6 compensate (rollback files, delete OS docs, delete MinIO object)
```

`upload_sessions` + local staging exist **only** for Drive-style ranged PUTs. A folder walk does not need them: the source file is already complete on disk.

---

## Why not call the upload HTTP API

`ingest_proof.py` already walks initiate → 256 KiB `Content-Range` PUTs → complete. That is the right proof for the **API**. It is the wrong driver for a **folder ingest tool**:

1. Files are already on disk — ranged PUTs add nothing.
2. Needs a user JWT (`search-user` / `admin`) and Keycloak.
3. Creates `upload_sessions` + staging copies of every file.
4. User asked to **reuse modules**, not to wrap the HTTP surface.

**Locked: direct service call.** No HTTP, no JWT, no staging copy, no `upload_sessions`.

---

## Architecture (this slice)

```
CLI  uv run python -m scripts.ingest_folder ROOT [--dry-run] [--fail-fast]
        │
        ├─ Path.rglob / walk files under ROOT
        ├─ skip hidden, skip dirs, skip unsupported ext
        └─ for each eligible file (sequential):
                  read bytes
                        │
                        ▼
              ingest_local_bytes(...)     ← NEW shared helper
                        │
                        ├─ detect / already known file_type
                        ├─ build_content_chunks(...)
                        ├─ MinIO put_object → local/{file_id}/{safe_name}
                        ├─ Postgres INSERT files (no file_acl)
                        └─ OpenSearch bulk as basic admin
                              (C6 compensate on failure)

UploadService.complete()  ──calls──►  same ingest_local_bytes(...)
   (after reading staging; still owns session status / staging GC)
```

```
PDF  → pypdf extract text ──────────► [chunker 600 / overlap 75] → chunks
TXT  → UTF-8 decode ────────────────► [chunker 600 / overlap 75] → chunks
CSV  → rows → serialize (all cols)
         → pack rows while tokens ≤ 600
         → if single row > 600 ──► [chunker 600 / overlap 75]
```

Same as Task 4. Do not fork extractors. See **CSV large fields (S8)** — G5 already splits huge rows **after** parse; raise `csv.field_size_limit` so those rows can be parsed.

---

## Human gates / locked decisions

Honor Task 4 locks (G1–G6, C2, C4, C9, MinIO no-chunking, G3 no auto-ACL). New locks for this slice:

### S1. Entry point

| | |
| --- | --- |
| Status | **LOCKED** (from human: Python script + folder path) |
| Decision | `backend/scripts/ingest_folder.py`, run as `uv run python -m scripts.ingest_folder <folder>`. argparse. Folder path is positional and required. |

### S2. Transport

| | |
| --- | --- |
| Status | **LOCKED** (from human: reuse modules) |
| Decision | Call Python services directly. **Not** HTTP. **Not** `UploadService.initiate` / ranged PUT. |

### S3. Shared process helper

| | |
| --- | --- |
| Status | **LOCKED** |
| Decision | Extract the bytes→stores path from `UploadService.complete` into a reusable function (proposed: `app/services/ingest/local_file.py` → `ingest_local_bytes`). HTTP complete **must** call it so chunking, MinIO path, `files` insert, OS doc shape, and C6 stay one implementation. |

### S4. File types

| | |
| --- | --- |
| Status | **LOCKED** (G1) |
| Decision | Accept **pdf / txt / csv** only via `detect_file_type`. Other extensions are skipped (not a process crash). Extension is source of truth. |

### S5. ACL

| | |
| --- | --- |
| Status | **LOCKED** (G3) |
| Decision | **Never** insert `file_acl`. Chunks get `allowed_roles: []`, `allowed_groups: []`. Never write `_empty`. Files are not searchable until an admin grants ACL (existing Task 6 UI). |

### S6. Processing model

| | |
| --- | --- |
| Status | **LOCKED** |
| Decision | **Sequential**, one file at a time, inline (same as C8). No thread pool, no Celery. |

### S7. MinIO / chunk identity / embeddings

| | |
| --- | --- |
| Status | **LOCKED** (Task 4) |
| Decision | One `put_object` of the **original bytes**. Chunk `_id` = `chunk_id` = `{file_id}:{chunk_seq:06d}`. Omit `embedding`. `ingestion_type=local`. |

### S8. CSV cell / field size (13 Sep 2026)

| | |
| --- | --- |
| Status | **LOCKED** (human: allow CSV fields larger than ~512 MiB) |
| Decision | Keep G5 chunking. Raise CPython `csv.field_size_limit` in `csv_extract.py` so a **single cell** larger than ~512 MiB can be parsed. Then the existing oversized-row path splits it into 600/75 chunks. Do **not** invent a second CSV chunker. |

---

## CSV large fields — current vs required

**Yes: large rows are already chunked** (Task 4 G5 / `extract_csv_units`). After a row is parsed and serialized:

| Case | What happens today |
| --- | --- |
| Several **short** rows | Packed into one OpenSearch chunk while `estimate_tokens(group) ≤ 600`. Never split mid-row while packing. |
| **One row** (or one huge cell, e.g. email `Body`) whose serialized text is **> 600 tokens** | Flush any open group, then `chunk_text(row_text, 600, 75)` — multiple chunks, `chunk_seq` advances. |
| Packed group estimator drift | Force-split that group with the same chunker. |

So a subset of oversized CSV rows is already handled **after** `csv.DictReader` succeeds.

**What is not handled:** CPython’s csv parser default `field_size_limit` is **131072 bytes (128 KiB)** on this machine (`python3` 3.12.3). A cell bigger than that raises `_csv.Error: field larger than field limit (131072)` **before** G5 runs. That limit is ~128 KiB, not 512 MiB — 512 MiB never gets a chance.

**Required change (shared module, both HTTP complete and folder script):**

In `extract_csv_units`, **before** `DictReader`:

```python
import sys

# Allow a single CSV cell larger than ~512 MiB. Process-global; raise only.
_MIN_CSV_FIELD = 512 * 1024 * 1024 + 1
if csv.field_size_limit() < _MIN_CSV_FIELD:
    csv.field_size_limit(sys.maxsize)
```

Wrap parse errors:

```python
try:
    rows = list(reader)
except csv.Error as exc:
    raise CsvExtractError(f"CSV parse error: {exc}") from exc
```

Do **not** check in a 512 MiB fixture (too large for git). Prove with:

1. Unit: one cell **> 128 KiB** (e.g. 200_000 chars) — must parse (would fail on default limit) and emit `chunk_count > 1`.
2. Unit: `csv.field_size_limit() >= 512 * 1024 * 1024 + 1` after `extract_csv_units` has been called (or after a small `ensure_csv_field_size_limit()` helper).

HTTP upload **file** cap stays **25 MiB** (C3) — a 512 MiB *cell* cannot arrive via `/files/uploads`. Folder CLI must not use that 25 MiB skip (A1), or a local CSV with a 512 MiB+ field would be skipped before parse.

---

## Remaining confusion (assumptions for implementation)

### A1. Size cap

| Assumption | **HTTP upload unchanged:** 25 MiB (`ingest_max_upload_bytes`). **Folder CLI:** do **not** skip on 25 MiB — S8 requires files large enough to hold a CSV cell > 512 MiB. No new CLI max-bytes flag. Still sequential and in-memory (`read_bytes`); a multi-hundred-MiB CSV will use substantial RAM (bytes + decoded str + row dicts). Do not add streaming CSV parse in this slice. Optional stdout warning if `st_size >= 512 MiB`. |

### A2. Continue vs fail-fast

| Assumption | Default **continue-on-error**: a bad PDF must not abort the rest of the tree. `--fail-fast` stops after the first ingest/parse/infra failure (skips for type/hidden are not failures). Exit code **0** if every *attempted* ingest succeeded; **1** if any attempted ingest failed or the folder is missing. Dry-run always **0** if the folder exists. |

### A3. Hidden files and dirs

| Assumption | Skip any file whose **name** starts with `.`. Skip any file that has a **path component** under ROOT starting with `.` (e.g. `docs/.cache/a.txt`). Do not follow symlinks (`follow_symlinks=False` / `rglob` without resolving). |

### A4. Duplicates

| Assumption | **No dedup.** Re-running the script on the same folder creates **new** `file_id`s, new MinIO objects, new chunks. Same basename in different subfolders is fine (`object_store_path` includes `file_id`). Do not hash-compare contents. |

### A5. `original_source`

| Assumption | Store the file’s path **relative to ROOT**, POSIX-style (`subdir/notes.txt`). HTTP uploads keep `original_source=null`. Folder ingest is still `ingestion_type=local`; the relative path is ops provenance only. Do not store absolute host paths. |

### A6. Empty / unreadable / parse errors

| Assumption | Same as API: empty TXT/PDF, bad CSV, textless PDF → treat as **failed file** (not skipped-type). C6 compensation. Continue unless `--fail-fast`. |

### A7. Dry-run

| Assumption | `--dry-run` prints the walk classification (ingest / skip-type / skip-hidden) and counts. **No** MinIO / Postgres / OpenSearch writes. |

### A8. Operator environment

| Assumption | Script loads `get_settings()` like other `backend/scripts/*`. Stack must be up (Postgres, MinIO, OpenSearch). No Keycloak token. Uses OS basic `admin` via existing `opensearch_ingest` helpers. |

### A9. Filename collisions in MinIO

| Assumption | `final_object_path(file_id, safe_filename)` already unique per file. Basename-only `safe_filename` (existing `detect.safe_filename`) — nested folders do **not** become MinIO prefixes beyond `local/{file_id}/`. Relative path lives in `original_source` only. |

### A10. Logging

| Assumption | stdout only. One line per file: status, relative path, and on success `file_id` + `chunk_count`. Final summary block. No new logging framework. |

---

## CLI contract

```text
usage: python -m scripts.ingest_folder [-h] [--dry-run] [--fail-fast] folder

Recursively ingest PDF/TXT/CSV files from a local folder.

positional arguments:
  folder       Root directory to walk (must exist)

optional arguments:
  --dry-run    Classify files only; do not write stores
  --fail-fast  Stop on first ingest failure
```

**Example output (success path):**

```text
[skip]  ignored.bin  (unsupported extension)
[ok]    notes.txt  file_id=...  chunks=1
[ok]    reports/q1.pdf  file_id=...  chunks=4
[fail]  empty.pdf  no extractable text

ingested=2  failed=1  skipped_type=1  skipped_hidden=0
```

Do not invent extra flags (`--acl`, `--parallel`, `--types`, `--max-bytes`) in this slice.

---

## Shared helper contract

Proposed: `backend/app/services/ingest/local_file.py`

```python
def ingest_local_bytes(
    db: Session,
    *,
    data: bytes,
    filename: str,
    original_source: str | None = None,
    settings: Settings | None = None,
    store: MinioStore | None = None,
) -> LocalIngestResult:
    """Parse → chunk → MinIO → files row → OS bulk. C6 on failure.

    ``filename`` is used only for safe_filename + file_type detection.
    Caller must already have enforced size cap if desired.
    """
```

`LocalIngestResult`: `file_id`, `file_type`, `size_bytes`, `object_store_path`, `chunk_count`, `uploaded_at`.

**Steps inside (same order as today’s complete):**

1. `name = safe_filename(filename)`; `file_type = detect_file_type(name)` (raise parse/value error if bad).
2. `chunks = build_content_chunks(...)` — existing helper.
3. `file_id = uuid4()`; `object_path = final_object_path(str(file_id), name)`.
4. `store.put_object(object_path, data)`.
5. `INSERT File(...)` — `ingestion_type="local"`, `original_source=original_source`, `size_bytes=len(data)`.
6. `docs = [build_chunk_document(...) for seq, content in enumerate(chunks)]`.
7. `bulk_index_chunks(docs)`.
8. `db.commit()`.
9. On `IngestParseError` / infra error: rollback `files`, `delete_chunks_by_file_id` if indexed, `delete_object` if MinIO written. Re-raise.

**`UploadService.complete` after extract:** keep session ownership, size match vs staging, status `processing`/`completed`/`failed`, staging delete on success. Replace the inline MinIO/PG/OS block with `ingest_local_bytes(...)` (pass `original_source=None` to preserve HTTP behavior). Session `error_message` still set via existing `_compensate` **or** a thin session wrapper around the helper’s exception — do not drop C6 for HTTP.

If wiring `_compensate` gets messy, acceptable split:

- Helper owns **store** compensation (MinIO + OS + `files` rollback).
- `complete()` owns **session** status (`failed` / `completed`) and staging GC.

Prove HTTP still works with `scripts.ingest_proof` after the refactor (at least proofs 4–10).

---

## Folder walker

Proposed: `backend/scripts/ingest_folder.py` (thin CLI) + optional `app/services/ingest/folder_walk.py` if classification deserves unit tests without argparse.

Walk algorithm:

1. Resolve ROOT; fail if missing or not a directory.
2. Recurse files only. Stable order: sort relative paths (deterministic proofs).
3. For each file, classify:
   - `hidden` if any relative part starts with `.`
   - `unsupported` if `detect_file_type` raises
   - else `eligible` (no 25 MiB skip — A1 / S8)
4. Dry-run: print classification; stop.
5. Else: `data = path.read_bytes()`; `ingest_local_bytes(..., filename=path.name, original_source=posix_relative)`.
6. Catch helper errors → `[fail]` line; continue unless `--fail-fast`.

Do **not** import FastAPI routes. Do open one SQLAlchemy session for the run (`get_engine()` + sessionmaker, same as other scripts).

---

## Chunk document shape (unchanged)

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
  "original_source": "nested/export.csv"
}
```

HTTP uploads remain `"original_source": null`. No mapping migration. `chunk_id` / `chunk_seq` only (C9).

---

## Landmines

1. **Do not HTTP-wrap the folder** — violates S2 and wastes staging.
2. **Do not duplicate complete()** — two pipelines will drift (chunk size, C6, doc shape).
3. **No auto-ACL** — empty arrays only (G3).
4. **No user JWT for OpenSearch** — basic `admin` via existing helper.
5. **No FastAPI embeddings.**
6. **Always chunk** (600/75). Do not skip for “small files” except when extractors already emit one unit.
7. **Never `_empty` in ACL fields.**
8. **No filename/status/uploader on `files`** — data-model G8 still holds. Relative path goes in `original_source` only (A5).
9. **No MinIO multipart / nested prefix mirroring the folder tree.**
10. **No new OS mapping fields.**
11. **C6 per file** — a failed file must not leave orphan `files` / searchable chunks / MinIO object.
12. **Do not apply the HTTP 25 MiB cap to the folder CLI** — that would skip CSVs whose cells are > 512 MiB (S8 / A1).
13. **Do not follow symlinks** — avoids escaping ROOT.
14. **Do not break HTTP proofs** — after extract, re-run `ingest_proof` (or a subset) before declaring the script done.
15. **Do not add `upload_sessions` for folder files** — they were never uploaded via the API.
16. **Do not widen file types** (docx, xlsx, images, OCR) — G1.
17. **Do not start the connector pipeline** — this is still `ingestion_type=local`.
18. **Do not leave `csv.field_size_limit` at 128 KiB** — huge cells die in DictReader before G5 chunking.
19. **Do not add a second CSV splitter** — oversized rows already go through `chunk_text`. Only raise the parser field limit.

---

## Proofs (run after implementation)

Fixture tree (create under `backend/tests/fixtures/ingest_folder/` or a temp dir in the proof script — gitignore large binaries; tiny files only):

```text
ROOT/
  notes.txt                 # short text
  nested/q1.pdf             # text PDF (reuse ingest_proof PDF builder if needed)
  nested/export.csv         # short rows
  skip.me.exe
  .hidden.txt
  nested/.cache/x.txt
```

Plus a generated textless PDF. Do **not** check in a 512 MiB CSV.

| # | Test | Expect |
| --- | --- | --- |
| 1 | Missing folder | exit 1, no writes |
| 2 | `--dry-run` on fixture | lists eligible pdf/txt/csv; skips exe + hidden; **zero** new `files` rows |
| 3 | Real run on fixture | 3 ingested (txt, pdf, csv); exe skipped; hidden skipped |
| 4 | Postgres | 3 new `files`; `file_acl` count 0 for those ids; `ingestion_type=local` |
| 5 | MinIO | objects at `local/{file_id}/{basename}` only — **not** `local/{file_id}/nested/...` |
| 6 | OpenSearch | chunks exist; embedding len 384; ACL `[]`; `chunk_id`/`chunk_seq`; `original_source` relative (`notes.txt`, `nested/q1.pdf`, `nested/export.csv`) |
| 7 | Nested CSV packing | column names in content (same as ingest_proof 9) |
| 8 | Textless PDF in tree | `[fail]`; continue; no `files` row; remaining files still ingested |
| 9 | CSV cell > 128 KiB (unit, no Docker) | parses (default limit would fail); `chunk_count > 1`; after extract `csv.field_size_limit() >= 512 MiB + 1` |
| 10 | `--fail-fast` with textless PDF first (sorted path) | stops; later eligible files not ingested |
| 11 | Re-run same folder | **new** file_ids (A4); previous rows remain |
| 12 | HTTP still works | `uv run python -m scripts.ingest_proof` proofs 4–10 still PASS (refactor did not break complete). HTTP still **413** on file > 25 MiB. |
| 13 | Unit: walker classification | hidden / unsupported / eligible — no Docker; a file just over 25 MiB is **eligible** |

Proof driver: `uv run python -m scripts.ingest_folder_proof` (new). **Not** part of `init_services`. Offline walker checks can live in `scripts.ingest_folder_unit_checks` or extend `ingest_unit_checks` — prefer a **new** small module so Task 4 checks stay focused.

---

## Tasks to perform (implementation checklist)

Check a box only after that step has been **run**.

### 0. Human lock

- [x] S1–S8 accepted as written (or overridden in this file)
- [x] A1–A10 assumptions accepted or overridden

### A. Extract shared ingest-from-bytes + CSV field limit

- [x] `csv_extract.py`: raise `csv.field_size_limit` to `sys.maxsize` when below 512 MiB + 1; wrap `csv.Error` as `CsvExtractError`
- [x] Unit: cell > 128 KiB parses and is chunked; `field_size_limit >= 512 MiB + 1` (proof 9)
- [x] Add `app/services/ingest/local_file.py` (`ingest_local_bytes` + result type + C6)
- [x] Refactor `UploadService.complete` to call it (`original_source=None`)
- [x] Existing offline unit checks still pass: `uv run python -m scripts.ingest_unit_checks`
- [x] HTTP proofs 4–10 still pass with stack up: `uv run python -m scripts.ingest_proof`

### B. Folder walk + CLI

- [x] Walk + classify (hidden, type, stable sort) — **no** 25 MiB skip
- [x] `scripts/ingest_folder.py` argparse: folder, `--dry-run`, `--fail-fast`
- [x] Sequential ingest; stdout lines + summary; exit codes (A2)
- [x] `original_source` = relative POSIX path (A5)

### C. Proofs

- [x] Fixture tree (tiny files; generate PDF in the proof like `ingest_proof.py`)
- [x] Proof table 1–11, 13
- [x] Proof 12: HTTP ingest_proof subset after refactor

### D. Hygiene

- [x] No React / no new API routes / no auto ACL / no FastAPI embeddings / no new OS fields
- [x] No `upload_sessions` for folder ingest
- [x] No connector / `ingestion_type` CHECK change
- [x] Do not modify `scripts/ingest_proof.py` except imports if the helper path moves
- [x] After ship: short summary in `prompts/summary/` **only if the human asks** (this file stays the working plan)

---

## Files to create / touch

| Path | Change |
| --- | --- |
| `backend/app/services/ingest/csv_extract.py` | Raise `csv.field_size_limit`; wrap `csv.Error` |
| `backend/scripts/ingest_unit_checks.py` | Add large-cell CSV test (proof 9) |
| `backend/app/services/ingest/local_file.py` | **NEW** shared ingest-from-bytes + C6 |
| `backend/app/services/ingest/__init__.py` | Export helper if useful; keep `build_content_chunks` |
| `backend/app/services/upload.py` | `complete()` delegates to helper |
| `backend/scripts/ingest_folder.py` | **NEW** CLI |
| `backend/scripts/ingest_folder_proof.py` | **NEW** live proof driver |
| `backend/scripts/ingest_folder_unit_checks.py` | **NEW** walker classification (optional if proof 13 is inline) |
| `prompts/cursor_summary/14_ingestion_script.md` | **this file** |

**Do not touch:** OpenSearch mapping JSON, `init_services` product path, frontend, Alembic (no schema change), `file_acl` writers, connector proposal.

---

## Out of scope

- React bulk-folder picker or `/upload` changes
- Resume / `upload_sessions` for the script
- Parallel ingest
- Content-hash dedup / upsert on re-run
- Granting ACL after ingest (admin UI already exists)
- File types beyond pdf/txt/csv; OCR
- Following symlinks; archive unpack (zip/tar)
- Deleting previously ingested files
- Airbyte / Kafka / Spark connector pipeline
- Raising the **HTTP** 25 MiB upload cap (CLI is uncapped; API stays C3)
- Streaming / out-of-core CSV parse (v1 still `read_bytes` + `list(reader)`)
- Mapping JWT users to `files_writer` (Task 7)

---

## How to implement (suggested order)

1. Raise `csv.field_size_limit` in `csv_extract.py`; add the >128 KiB cell unit check.
2. Extract `ingest_local_bytes` and point `complete()` at it.
3. Re-run unit checks + HTTP ingest proofs (stop if HTTP broke).
4. Implement walker + CLI with `--dry-run` first (easy to verify classification).
5. Wire eligible files to the helper.
6. Add folder proofs 1–11, 13; confirm proof 12 still green.
7. Manual spot-check: MinIO console / `files` table / OS `_search` on one `file_id`.

Stack must be up (`./start-dev.sh` or equivalent). Same env as Task 4 proofs.

---

## Follow-on (not this slice)

| Later | Relationship |
| --- | --- |
| Admin ACL | Folder-ingested files need grants before search hits (same as `/upload`) |
| Connectors | Different `ingestion_type` / `original_source` semantics; do not overload this script |
| Dedup / re-ingest | Would need source identity; A4 explicitly skipped |

---

## Changelog

| Date | Change |
| --- | --- |
| 13 Sep 2026 | Plan + task checklist for local recursive folder ingest script. |
| 13 Sep 2026 | S8: CSV cells > ~512 MiB. Confirmed G5 already chunks oversized rows; raise `csv.field_size_limit`. Folder CLI drops 25 MiB skip. |
| 13 Sep 2026 | Implemented: shared `ingest_local_bytes`, folder CLI, CSV field limit; proofs 1–13 PASS. Product summary: `prompts/summary/14_ingest_script.md`. |
