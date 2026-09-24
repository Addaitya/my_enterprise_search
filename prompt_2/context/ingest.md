# HTTP ingest and folder CLI

Shipped local ingest. Sources: `prompts/summary/5_local_ingestion_setup.md`, `prompts/summary/14_ingest_script.md`. Connectors are not built; see `prompt_2/context/connectors.md`.

## HTTP upload

Signed-in `search-user` or `admin`. Session `user_id` must equal JWT `sub` (admins do not take over someone else's session).

| Method | Path | Notes |
| --- | --- | --- |
| POST | `/files/uploads` | 201 initiate. 413 oversize. 415 bad type. |
| PUT | `/files/uploads/{id}` | `Content-Range` sequential parts into a local `.bin`. Incomplete 308. Full 200. |
| GET | `/files/uploads/{id}` | Progress. |
| POST | `/files/uploads/{id}/complete` | Inline process. 201, 422 parse, 502 infra, 409 already done. |
| DELETE | `/files/uploads/{id}` | Cancel. 204. |

Accept `pdf`, `txt`, `csv` only (`file_type` is the extension). Cap 25 MiB (`26_214_400`). Part multiple 256 KiB is advisory. Session TTL 24h. Staging dir `backend/data/upload-staging`.

Extract: pypdf (no OCR; empty PDF → 422), UTF-8 text, CSV via `DictReader` (header, excel dialect). Chunks are 600 tokens with 75 overlap. Estimator is about 4 characters per token. CSV packs consecutive rows into that budget (`ColumnName: value`, blank line between rows, skip empty cells). One oversized row falls through to the text chunker.

Complete path: parse → one MinIO `put_object` at `local/{file_id}/{safe_name}` → INSERT `files` with no `file_acl` → OpenSearch `_bulk` as basic `admin`, omit `embedding`, `refresh=wait_for`. On failure, roll back the `files` row, delete any OS docs, delete the MinIO object, mark the session failed, and leave local staging. `chunk_id` = OpenSearch `_id` = `{file_id}:{chunk_seq:06d}`.

Chunk fields: `file_id`, `chunk_id`, `chunk_seq`, `meta_file_type`, `meta_file_size`, timestamps, `content`, `allowed_roles: []`, `allowed_groups: []`, `object_store_path`, `ingestion_type: local`, `original_source` (null for HTTP).

React `/upload` is multi-file, same type and size rules, Bearer attached. `upload_url` in the initiate response is the Vite `/api/...` shape; FastAPI itself has no `/api` prefix.

`upload_sessions` Alembic revision `a1b2c3d4e5f6`. Statuses: `initiated`, `uploading`, `processing`, `completed`, `failed`, `expired`, `cancelled`.

## Folder CLI

```text
python -m scripts.ingest_folder [--dry-run] [--fail-fast] folder
```

Walks the folder, skips hidden path components and unsupported extensions, does not follow symlinks, and does not apply the 25 MiB HTTP cap (warn at 512 MiB, then still read). `--dry-run` writes nothing. `--fail-fast` stops on the first ingest failure. Exit 0 when every attempted ingest succeeded.

`original_source` is the path relative to the folder root, POSIX. Re-running creates new `file_id`s. There is no content-hash dedup. ACL stays empty until an admin grant.

Shared ingest-from-bytes is used by both HTTP complete and the CLI.
