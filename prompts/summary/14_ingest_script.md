# 14 — Local folder ingestion script

**Implemented 13 September 2026.** Source of truth: `prompts/cursor_summary/14_ingestion_script.md`.

Builds on Task 4 HTTP ingest (`prompts/summary/5_local_ingestion_setup.md`). Search, View/Open, and Admin ACL are already live. This slice adds an **ops CLI** that walks a folder and ingests PDF/TXT/CSV through the **same bytes → MinIO + `files` + OpenSearch** path as `/files/uploads/.../complete`. Connectors remain later.

---

## What “done” means (this slice)

An operator with the stack up can run:

```bash
cd backend
uv run python -m scripts.ingest_folder /path/to/folder
```

Every **PDF / TXT / CSV** under that folder (nested included) is ingested **exactly like a successful HTTP complete**:

| Store | Result per file |
| --- | --- |
| MinIO | One full object at `local/{file_id}/{safe_name}` (basename only — not a nested prefix) |
| Postgres | One `files` row; **no** `file_acl`; **no** `upload_sessions` row |
| OpenSearch | Chunks in `enterprise-search-chunks`; omit `embedding` (pipeline fills **384-dim**); `allowed_roles: []`, `allowed_groups: []`; `ingestion_type=local`; `original_source` = path relative to the folder root |

Unsupported types and parse failures are **reported and skipped / failed** (default continue-on-error). The process prints a summary. HTTP upload still enforces **25 MiB**; React `/upload` is unchanged. The folder CLI does **not** skip on 25 MiB.

---

## Architecture

```
CLI  uv run python -m scripts.ingest_folder ROOT [--dry-run] [--fail-fast]
        │
        ├─ os.walk (no symlink follow) → classify hidden / unsupported / eligible
        └─ for each eligible file (sequential):
                  read bytes
                        │
                        ▼
              ingest_local_bytes(...)     ← shared helper
                        │
                        ├─ detect file_type from extension
                        ├─ build_content_chunks(...)   (600 / 75; CSV pack + G5)
                        ├─ MinIO put_object → local/{file_id}/{safe_name}
                        ├─ Postgres INSERT files (no file_acl)
                        └─ OpenSearch bulk as basic admin
                              (C6 compensate on failure)

UploadService.complete()  ──calls──►  same ingest_local_bytes(...)
   (after reading staging; still owns session status / staging GC)
```

**Why not HTTP:** files are already on disk; ranged PUTs and JWTs add nothing; `upload_sessions` + staging would be waste. Direct service call (S2).

---

## What shipped

### A. CSV field limit (S8)

`backend/app/services/ingest/csv_extract.py`

- `ensure_csv_field_size_limit()` raises CPython `csv.field_size_limit` to `sys.maxsize` when it is below **512 MiB + 1**.
- `csv.Error` from `DictReader` is wrapped as `CsvExtractError`.
- Oversized-row **chunking is unchanged** (G5 already calls `chunk_text` 600/75 after parse). This only lets huge cells **parse**.

Shared by HTTP complete and the folder CLI (both go through `extract_csv_units`). HTTP **file** cap stays 25 MiB — a 512 MiB cell cannot arrive via `/files/uploads`.

### B. Shared ingest-from-bytes

**New** `backend/app/services/ingest/local_file.py`:

- `ingest_local_bytes(db, *, data, filename, original_source=None, ...)` → `LocalIngestResult`
- Order: parse/chunk → `file_id` → MinIO `put_object` → INSERT `files` → OS `_bulk` (`refresh=wait_for`) → `db.commit()`
- `_bulk` retries up to 5 times on **transient** `circuit_breaking_exception` and HTTP 429/503 (embedding pipeline can trip the parent memory breaker on a 2 GiB heap). Mapping errors are not retried. Chunk `_id`s make retries idempotent.
- C6 on any failure: rollback `files`, delete OS docs if indexed, delete MinIO object if written
- HTTP passes `original_source=None`; folder CLI passes POSIX path relative to ROOT

`build_chunk_document` now accepts `original_source` (default `None`) so HTTP docs stay `"original_source": null`.

### C. HTTP complete refactor

`UploadService.complete()` reads staging, size-checks, then calls `ingest_local_bytes(..., original_source=None)`.

- Helper owns **store** compensation (MinIO + OS + `files`)
- `complete()` owns **session** status (`processing` / `completed` / `failed`) and staging GC (delete on success; leave staging on failure for debug)

No API route, schema, or React change.

### D. Folder walk + CLI

| Piece | Role |
| --- | --- |
| `app/services/ingest/folder_walk.py` | Classify hidden / unsupported / eligible; stable sort; no 25 MiB skip; do not follow symlinks |
| `scripts/ingest_folder.py` | argparse CLI + sequential ingest + stdout lines + summary |

**CLI contract:**

```text
usage: python -m scripts.ingest_folder [-h] [--dry-run] [--fail-fast] folder
```

| Flag / arg | Behavior |
| --- | --- |
| `folder` | Required; must exist and be a directory; else exit **1** |
| `--dry-run` | Print classification only; **no** store writes; exit **0** if folder exists |
| `--fail-fast` | Stop after first ingest/parse/infra failure (type/hidden skips are not failures) |

Exit **0** if every *attempted* ingest succeeded; **1** if any attempted ingest failed or the folder is missing.

**Stdout (real run):**

```text
[skip]  ignored.bin  (unsupported extension)
[ok]    notes.txt  file_id=...  chunks=1
[fail]  empty.pdf  PDF has no extractable text (OCR not supported)

ingested=2  failed=1  skipped_type=1  skipped_hidden=0
```

`--dry-run` uses `[ingest]` for eligible files. Files ≥ 512 MiB get an optional `[warn]` then still ingest (in-memory `read_bytes`).

**Classification (A3):** skip if any relative path component starts with `.`. Skip unsupported extensions via `detect_file_type`. Do not follow file or directory symlinks.

**Provenance (A5):** `original_source` = path relative to ROOT, POSIX (`nested/export.csv`). Never an absolute host path.

**Duplicates (A4):** re-running the same folder creates **new** `file_id`s. No content-hash dedup.

**ACL (S5 / G3):** never insert `file_acl`. Chunks get empty arrays. Files are not searchable until an admin grants ACL in the existing UI.

### E. Proofs / unit checks

| Module | Role |
| --- | --- |
| `scripts/ingest_unit_checks.py` | Existing chunker/CSV checks **plus** cell > 128 KiB (proof 9) |
| `scripts/ingest_folder_unit_checks.py` | Walker classification (proof 13); 25 MiB+ still eligible; symlink skip; CSV cell |
| `scripts/ingest_folder_proof.py` | Live proofs 1–12 (9 and 13 also run offline first) |

`scripts/ingest_proof.py` was **not** modified.

---

## Locked decisions honored

| ID | Decision |
| --- | --- |
| S1 | `python -m scripts.ingest_folder <folder>`; argparse; folder positional required |
| S2 | Direct Python services; not HTTP; not initiate / ranged PUT |
| S3 | Shared `ingest_local_bytes`; HTTP complete calls it |
| S4 | pdf / txt / csv only; other extensions skipped |
| S5 | No `file_acl`; ACL arrays `[]`; never `_empty` |
| S6 | Sequential, inline, one file at a time |
| S7 | One MinIO `put_object`; `chunk_id` = `{file_id}:{seq:06d}`; omit embedding; `ingestion_type=local` |
| S8 | Raise `csv.field_size_limit`; keep G5 chunker; CLI not capped at 25 MiB |
| A1–A10 | Size cap, continue vs fail-fast, hidden, no dedup, relative `original_source`, dry-run, no Keycloak, basename MinIO path, stdout-only |

---

## Files created / touched

| Path | Change |
| --- | --- |
| `backend/app/services/ingest/csv_extract.py` | Raise field limit; wrap `csv.Error` |
| `backend/app/services/ingest/local_file.py` | **NEW** shared ingest-from-bytes + C6 |
| `backend/app/services/ingest/folder_walk.py` | **NEW** walk + classify |
| `backend/app/services/opensearch_ingest.py` | Optional `original_source` on chunk docs; retry `_bulk` on transient circuit-breaker / 429 / 503 |
| `backend/app/services/upload.py` | `complete()` delegates to helper |
| `backend/scripts/ingest_folder.py` | **NEW** CLI |
| `backend/scripts/ingest_folder_proof.py` | **NEW** live proof driver |
| `backend/scripts/ingest_folder_unit_checks.py` | **NEW** offline walker checks |
| `backend/scripts/ingest_unit_checks.py` | Large-cell CSV test (proof 9) |

**Not touched:** OpenSearch mapping JSON, `init_services` product path, frontend, Alembic, `file_acl` writers, API routes, `scripts/ingest_proof.py`.

---

## Automated proofs already run (13 September 2026)

Offline:

```bash
cd backend
uv run python -m scripts.ingest_unit_checks
uv run python -m scripts.ingest_folder_unit_checks
```

**PASS** (including CSV cell > 128 KiB → `chunk_count > 1` and `csv.field_size_limit() >= 512 MiB + 1`; walker hidden/unsupported/eligible; file just over 25 MiB is eligible).

Live (stack + API up):

```bash
cd backend
uv run python -m scripts.ingest_folder_proof
```

| # | Test | Result |
| --- | --- | --- |
| 1 | Missing folder | **PASS** exit 1, no writes |
| 2 | `--dry-run` | **PASS** lists pdf/txt/csv; skips exe + hidden; zero new `files` rows |
| 3 | Real run | **PASS** ingested=3; exe skipped; hidden skipped |
| 4 | Postgres | **PASS** 3 new `files`; `file_acl` 0; `ingestion_type=local`; no `upload_sessions` |
| 5 | MinIO | **PASS** `local/{file_id}/{basename}` only |
| 6 | OpenSearch | **PASS** embedding len 384; ACL `[]`; relative `original_source` |
| 7 | Nested CSV packing | **PASS** column names in content; `chunk_count < 30` |
| 8 | Textless PDF in tree | **PASS** `[fail]`; continue; no `files` row for it; remaining ingested |
| 9 | CSV cell > 128 KiB (unit) | **PASS** (offline) |
| 10 | `--fail-fast` (empty.pdf first) | **PASS** stops; later eligible files not ingested |
| 11 | Re-run same folder | **PASS** new `file_id`s; previous rows remain |
| 12 | HTTP still works | **PASS** ingest_proof 3–10 (413 oversize + complete path) |
| 13 | Walker classification | **PASS** (offline) |

---

## Human guide to test

### 0. Stack

Postgres, MinIO, OpenSearch, Keycloak up; API on `:8000` for HTTP checks.

```bash
# from repo root — if the stack is down
docker compose up -d postgres minio opensearch keycloak
cd backend && uv run python ../setup/python/wait_ready.py
uv run alembic upgrade head
uv run python -m init_services   # only needed on a fresh / unconfigured stack

# API (separate terminal) — needed for HTTP upload regression, not for the folder CLI
cd backend && uv run python -c "from app.main import run; run()"
# or from repo root: ./start-dev.sh
```

Folder ingest uses **no JWT**. HTTP upload still needs a signed-in user.

### 1. Offline (no Docker)

```bash
cd backend
uv run python -m scripts.ingest_unit_checks
uv run python -m scripts.ingest_folder_unit_checks
```

Expect `all unit checks passed` / `all folder unit checks passed`.

### 2. Dry-run (no writes)

Create a small tree (or reuse any folder of pdf/txt/csv plus junk):

```bash
mkdir -p /tmp/ingest-demo/nested/.cache
echo 'hello folder ingest' > /tmp/ingest-demo/notes.txt
echo 'From,To,Subject,Body
a@co,b@co,Hi,Short' > /tmp/ingest-demo/nested/export.csv
echo 'MZ' > /tmp/ingest-demo/skip.me.exe
echo 'secret' > /tmp/ingest-demo/.hidden.txt
echo 'cached' > /tmp/ingest-demo/nested/.cache/x.txt
# optional: copy a real text PDF to /tmp/ingest-demo/nested/q1.pdf

cd backend
uv run python -m scripts.ingest_folder /tmp/ingest-demo --dry-run
```

Expect `[ingest]` for `notes.txt` / `nested/export.csv` (and pdf if present); `[skip]` for `.exe` and hidden paths; summary `ingested=0`. Confirm Postgres `files` count did not change.

### 3. Real ingest

```bash
cd backend
uv run python -m scripts.ingest_folder /tmp/ingest-demo
```

Expect `[ok]` lines with `file_id` + `chunks`, plus a summary `ingested=N  failed=0  skipped_type=1  skipped_hidden=2`.

Copy a `file_id` from stdout for the next checks.

### 4. Postgres

```bash
# credentials from repo-root .env (APP_USER / APP_PASSWORD / APP_DB)
docker exec -it postgres psql -U app_user -d app -c \
  "SELECT id, file_type, ingestion_type, original_source, object_store_path
   FROM files ORDER BY uploaded_at DESC LIMIT 10;"
```

Check:

- `ingestion_type = local`
- `original_source` is relative (`notes.txt`, `nested/export.csv`) — not an absolute host path
- `object_store_path` is `local/<uuid>/<basename>` — **not** `local/<uuid>/nested/...`

```bash
docker exec -it postgres psql -U app_user -d app -c \
  "SELECT count(*) FROM file_acl WHERE file_id = '<file_id>';"
docker exec -it postgres psql -U app_user -d app -c \
  "SELECT count(*) FROM upload_sessions WHERE file_id = '<file_id>';"
```

Both counts must be **0**.

### 5. MinIO

Console: `http://localhost:9001` (root user/password from `.env`). Bucket `enterprise-search-files`. Object key = `local/{file_id}/{basename}`.

### 6. OpenSearch

```bash
# password: OPENSEARCH_INITIAL_ADMIN_PASSWORD in .env
curl -s -u admin:"$OPENSEARCH_INITIAL_ADMIN_PASSWORD" \
  'http://localhost:9200/enterprise-search-chunks/_search?pretty' \
  -H 'Content-Type: application/json' \
  -d '{"query":{"term":{"file_id":"<file_id>"}},"size":3}'
```

Check each hit:

- `embedding` length **384**
- `allowed_roles` / `allowed_groups` are `[]` (not `"_empty"`)
- `chunk_id` / `chunk_seq` present; `_id` equals `chunk_id`
- `ingestion_type` = `local`
- `original_source` matches the relative path from step 3
- CSV content includes `From:` / `Subject:` style column names

### 7. Search UI (expected empty until ACL)

Sign in as `searcher`. Search for text from `notes.txt`. Hits should **not** include the new file until an admin grants ACL on **Access Control(Admin) → file access** (same as HTTP `/upload`). After a grant, search should return chunks.

### 8. Continue-on-error vs `--fail-fast`

Add a textless/blank PDF named so it sorts first, e.g. `empty.pdf` at the folder root.

Default (continue):

```bash
uv run python -m scripts.ingest_folder /tmp/ingest-demo
```

Expect `[fail] empty.pdf ...`, remaining eligible files `[ok]`, exit **1**.

Fail-fast:

```bash
uv run python -m scripts.ingest_folder /tmp/ingest-demo --fail-fast
```

Expect stop after `empty.pdf`; later pdf/txt/csv **not** ingested; exit **1**.

### 9. Re-run creates duplicates

Run the same folder again. New `file_id`s appear; previous Postgres/MinIO/OS rows remain. There is no dedup in this slice.

### 10. HTTP upload still capped at 25 MiB

Folder CLI will ingest a local `.txt` larger than 25 MiB (do not use a huge file unless you have RAM). The **browser / API** must still reject files over 25 MiB:

- UI `/upload` → 413 on initiate
- or `cd backend && uv run python -m scripts.ingest_proof` (proof 3 is oversize → 413; proofs 4–10 cover complete)

### 11. Automated live driver (optional, writes sample files into the DB)

```bash
cd backend
uv run python -m scripts.ingest_folder_proof
```

Expect `=== all runnable folder ingest proofs passed ===`. This **does** insert proof files into Postgres/MinIO/OpenSearch (throwaway `file_id`s, empty ACL).

### CSV huge-cell note

Do **not** check in or routinely ingest a 512 MiB CSV. The parser limit is raised so a single cell larger than ~512 MiB *can* parse; G5 then splits the serialized row into 600/75 chunks. The unit test uses a **200_000 character** cell (enough to beat the old 128 KiB `field_size_limit`). A multi-hundred-MiB file is sequential and fully in memory (`read_bytes` + decoded str + row dicts).

---

## Out of scope (unchanged)

- React bulk-folder picker or `/upload` changes
- `upload_sessions` for the script
- Parallel ingest; content-hash dedup
- Auto ACL after ingest
- File types beyond pdf/txt/csv; OCR
- Following symlinks; zip/tar unpack
- Connector pipeline / new `ingestion_type`
- Raising the **HTTP** 25 MiB cap
- Streaming / out-of-core CSV parse
- Mapping JWT users to `files_writer` (Task 7)

---

## Follow-on

| Later | Relationship |
| --- | --- |
| Admin ACL | Folder-ingested files need grants before search hits (same as `/upload`) |
| Connectors | Different `ingestion_type` / `original_source` semantics; do not overload this script |
| Dedup / re-ingest | Would need source identity; A4 explicitly skipped |
