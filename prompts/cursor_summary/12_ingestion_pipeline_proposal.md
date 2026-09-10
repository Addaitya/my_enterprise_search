# Multi-connector ingestion pipeline — architecture proposal

Working proposal for **connector-based ingestion** (SharePoint, Google Drive, S3/MinIO) driven by `prompts/instructions/2_Ingestion_pipeline.md`. This is analysis + plan only — **not** an implementation checklist until human gates are locked.

Local upload → chunk → MinIO → OpenSearch is already live (`prompts/summary/5_local_ingestion_setup.md`). Search, View/Open, and Admin ACL are live. Connectors were explicitly deferred in the product brief (`prompts/cursor_summary/2_project_overview_tasks.md`).

---

## 1. Current product baseline (do not break)

| Layer | Today |
| --- | --- |
| FastAPI | Resumable local upload (`/files/uploads/*`), search, view/open, admin ACL |
| Postgres | `files` + `file_acl` + identity mirror + `upload_sessions` + `acl_sync_jobs` |
| MinIO | Bucket `enterprise-search-files`; originals at `local/{file_id}/{safe_name}` |
| OpenSearch | Chunks in `enterprise-search-chunks`; ingest pipeline embeds; DLS on `allowed_*` |
| Compose | Postgres, Keycloak, OpenSearch 3.8, MinIO (+ dashboards). **No** Airbyte / Kafka / Spark / Tika |

**Hard invariants that connectors must honor**

1. User JWT never writes OpenSearch; writes use basic `admin` / later `files_writer`.
2. No auto `file_acl` on ingest (admin assigns roles/groups later) — unless a **future** connector ACL-import slice is explicitly scoped.
3. Chunks omit `embedding`; OS pipeline fills 384-dim MiniLM vectors.
4. Chunk identity stays `chunk_id` + `chunk_seq` (`{file_id}:{seq:06d}` = `_id`).
5. View/Open streams MinIO via Postgres ACL using `files.object_store_path`.
6. `ingestion_type` CHECK today is **`'local'` only** — must widen for connectors.
7. `original_source` exists but is unused for local (`null`).

---

## 2. Stated requirement (from instructions)

**Goal:** Multi-connector pipeline that pulls from SharePoint, Google Drive, and S3/MinIO, widens supported file types, and lands searchable chunks + viewable originals with the same ACL/search model as local ingest.

**Named stack**

| Component | Role in the brief |
| --- | --- |
| Airbyte | Poll sources every *n* minutes; dump into MinIO (S3); same file may be re-updated |
| Kafka | Events to start / complete processing |
| Spark + Tika | Document processing + “cluster creation” (ambiguous — see C7) |
| MinIO | Data lake — dump everything, process later |

**Stated happy path**

1. New file appears in SharePoint.
2. Airbyte incremental sync notices it → writes into MinIO.
3. *Somehow* a Kafka event starts processing.
4. Spark + Tika process → final chunks dumped to S3/MinIO.
5. Event to push chunks to OpenSearch.
6. File metadata updated in DB, including `object_store_path` (what users Open/view).
7. Chunks read from S3 and indexed into OpenSearch.

---

## 3. Flow verification (is the brief right?)

**Verdict: directionally correct, but two steps are wrong or incomplete as written.**

| Step | Verdict | Why |
| --- | --- | --- |
| Airbyte → MinIO raw files | **Correct** | SharePoint / Google Drive / S3 sources support **Copy Raw Files** into S3-compatible destinations (MinIO via S3 connector). Best fit for binary originals. |
| Poll every *n* minutes | **Correct for Airbyte** | Airbyte is **batch/scheduled**, not a continuous stream for Drive/SharePoint. |
| “Somehow” Kafka after dump | **Under-specified → fixable** | Prefer **MinIO bucket notifications → Kafka** on `ObjectCreated` under a raw prefix. Do **not** rely on Airbyte sync-success webhooks alone (noisy, not per-file, Slack-oriented payloads). |
| Spark + Tika → chunk objects in S3 | **Partially wrong for this product** | Today chunks live as **OpenSearch documents**, not as objects the user opens. Storing chunk text blobs in MinIO is optional cache/debug only. Prefer: extract → chunk in worker → **bulk index OS**; keep **one original object** in the view bucket. |
| Event → push to OpenSearch | **Correct as a stage** | Decouple “raw arrived” from “indexed”. |
| DB row with `object_store_path` | **Correct and mandatory** | Open/view already depends on Postgres + MinIO path. |
| Re-updated same file | **Must design for** | Need stable source identity → upsert `files`, replace OS chunks for that `file_id`, overwrite or version object path. |

**Recommended corrected flow**

```
SharePoint / Drive / S3
        │  Airbyte scheduled sync (Copy Raw Files)
        ▼
MinIO  lake/raw/{source}/{external_id}/…     ← not user-facing
        │  MinIO notification (s3:ObjectCreated:*)
        ▼
Kafka  ingest.raw.created                     ← key = object path / content hash
        │
        ▼
Processor (Tika extract + existing 600/75 chunker; Spark later if volume needs it)
        │
        ├─ MinIO  files/{ingestion_type}/{file_id}/{safe_name}   ← user-facing original
        ├─ Postgres INSERT/UPSERT files (+ original_source URL/id)
        └─ OpenSearch bulk chunks (omit embedding; empty allowed_*)
        │
        ▼
Kafka  ingest.indexed.completed               ← optional; ACL/admin UI can poll PG
```

Local upload stays on the existing FastAPI path and **does not** need Airbyte. Optionally it can emit the same `ingest.indexed.completed` event for uniformity.

---

## 4. Key questions — answers + proposals

### Q1. Can we make Airbyte ingestion event-based?

| | |
| --- | --- |
| **Short answer** | **Not truly.** Airbyte is scheduled/batch ELT. Drive/SharePoint connectors poll on a sync schedule. CDC “event” mode exists mainly for **databases**, not file SaaS sources. |
| **What exists** | Incremental cursor syncs; sync-success/failure **notifications** (webhooks) for ops — not a per-file ingest trigger with rich payload. |
| **Proposal (C1)** | Keep Airbyte on a **cron** (e.g. every 5–15 min for OSS). Make the **processing** pipeline event-based via **MinIO → Kafka**. If near-real-time source push is required later, add source webhooks / Graph subscriptions **outside** Airbyte for those connectors. |

### Q2. Same MinIO bucket for end-user Open as the lake dump?

| | |
| --- | --- |
| **Short answer** | **Same cluster/bucket is fine; different key prefixes (or two buckets) are required.** |
| **Why** | Airbyte raw layout ≠ product `object_store_path`. Mixing them risks exposing lake paths, broken display names, and accidental re-process loops. |
| **Proposal (C2)** | One bucket `enterprise-search-files` (reuse compose): prefixes `lake/raw/…` (Airbyte only) and `files/{type}/{file_id}/…` (user Open). Notifications only on `lake/raw/`. Processor **copies/promotes** to `files/…` after successful parse (or streams once and writes final). Local upload keeps `local/{file_id}/…`. |

### Q3. Kafka as message queue referencing S3 path?

| | |
| --- | --- |
| **Short answer** | **Yes — preferred.** |
| **Proposal (C3)** | Kafka messages carry **pointers + metadata**, not file bytes: `bucket`, `object_key`, `source`, `external_id`, `etag`/`content_hash`, `event_time`, `op` (`upsert`\|`delete`). Consumer downloads from MinIO. Idempotent by `(source, external_id)` or content hash. |

### Q4. Is the stated flow right?

See §3. **Airbyte → lake → event → process → PG + user object + OS** is right. **Persisting chunks as the primary S3 artifact** and **treating Airbyte as event-native** are not.

### Q5. Separate ingestion server vs same FastAPI backend?

| | |
| --- | --- |
| **Proposal (C4)** | **Separate worker service** in the same repo/compose network; **not** inline on FastAPI request threads. FastAPI stays API/ACL/search/upload. Worker(s) consume Kafka (or later a queue). Shared Python libs: chunker, MinIO client, OS bulk, Postgres models. Do **not** put Airbyte/Spark UI inside the React app. |
| **Why** | Heavy Tika/OCR jobs would block upload/search. Matches existing pattern of background ACL sync, but connectors need isolation + retry. |

---

## 5. Requirement confusion register

Each item: **confusion → proposal (assumption until human locks)**.

### C1. Airbyte “event-based” vs schedule

- **Confusion:** Brief asks if Airbyte can be event-based; also says “every n minutes.”
- **Proposal:** Scheduled Airbyte syncs + event-driven **downstream** processing. Document latency = sync interval + process time.

### C2. One bucket vs two; lake vs view paths

- **Confusion:** “Dump everything into MinIO” vs “object path users view.”
- **Proposal:** Same bucket, **two prefixes** (`lake/raw/` vs `files/` + existing `local/`). View API only serves paths stored on `files.object_store_path` under `local/` or `files/`.

### C3. Kafka message contents

- **Confusion:** “Events for start complete ingestion” — payload undefined.
- **Proposal:** Two topics: `ingest.raw.created`, `ingest.file.completed`. Pointer-only JSON; no binary. Completion event includes `file_id`, `chunk_count`, `status`.

### C4. Same backend vs separate server

- **Confusion:** Monolith vs new service.
- **Proposal:** New Compose service `ingestion-worker` (Python). Shared `backend/app/services/*` packages. FastAPI may expose **admin** endpoints to pause connectors / reprocess by `file_id`, but not run Tika inline.

### C5. Spark — required now?

- **Confusion:** “Spark and Tika” listed together; “cluster creation” unclear (Spark cluster? OpenSearch index? chunk clusters?).
- **Proposal:** **Phase 1 without Spark.** Use **Apache Tika** (server or embedded via `tika-python` / REST) + existing Python chunker (600/75). Introduce Spark **only** when file volume or CPU needs horizontal batch (Phase 3). “Cluster creation” interpreted as **compute cluster** for Spark — defer.

### C6. Where do chunks live?

- **Confusion:** “Create final chunks and dump into S3” then “extracted from S3 and pushed to OpenSearch.”
- **Proposal:** Chunks are **OpenSearch documents** (current model). Optional write of extracted text / chunk JSON under `lake/derived/{file_id}/` for audit — **not** used by Open/view.

### C7. File type expansion scope

- **Confusion:** “File type variety must increase significantly” — no allowlist.
- **Proposal Phase 1 types:** keep pdf/txt/csv; add **docx, pptx, xlsx, html, md, rtf, odt** via Tika. Images: **metadata only** or skip until OCR phase. Reject executables/archives as searchable content (optionally unpack zip in Phase 2).

### C8. ACL for connector files

- **Confusion:** Drive/SharePoint have native ACLs; product uses role/group `file_acl`.
- **Proposal:** Phase 1 — **same as local**: index with empty `allowed_*`, admin grants later. Phase 2 — optional Airbyte “replicate permissions” → map source principals to Keycloak groups/roles (large design; out of Phase 1).

### C9. `ingestion_type` / `original_source` schema

- **Confusion:** CHECK only `'local'`; `original_source` unused.
- **Proposal:** Widen CHECK to `'local' | 'sharepoint' | 'google_drive' | 's3'`. Store `original_source` as stable URI or `source:external_id` string. Add unique index on `(ingestion_type, original_source)` where `original_source IS NOT NULL` for upsert.

### C10. Dedup / re-update semantics

- **Confusion:** “Same file could be re-updated” — replace vs version?
- **Proposal:** Upsert by `(ingestion_type, original_source)`. On change (etag/hash): overwrite MinIO user object (same or new path under same `file_id`), delete-by-query old OS chunks, re-bulk, bump `updated_at`. Do **not** create a new `file_id` (preserves ACL rows).

### C11. Deletes in source

- **Confusion:** Not mentioned.
- **Proposal:** Phase 1 — ignore source deletes (orphan files remain searchable until admin deletes). Phase 2 — Airbyte/incremental delete markers → soft-delete PG + delete OS + optional MinIO delete.

### C12. S3 as both source and lake

- **Confusion:** S3/MinIO is a **source** and the **lake**.
- **Proposal:** Distinct prefixes/buckets: e.g. customer `s3://corp-docs/` (Airbyte source) → `lake/raw/s3/…` (destination). Never sync `lake/` back onto itself.

### C13. Who triggers OpenSearch push — Spark job or always-on consumer?

- **Confusion:** Brief implies batch Spark then another event.
- **Proposal:** Single worker pipeline: consume raw event → process → write PG/MinIO/OS → emit completed. No second mandatory hop unless indexing is split for scale.

### C14. Auth to SharePoint / Drive

- **Confusion:** Credentials, tenant, folder scope undefined.
- **Proposal:** Airbyte connection config via secrets (env / Docker secrets). One connection per source site/folder for v1. Document OAuth vs service account per connector docs.

### C15. Relationship to local `/upload`

- **Confusion:** Replace or coexist?
- **Proposal:** **Coexist forever.** Local = interactive product path. Connectors = system path. Shared indexing helpers only.

### C16. Ops surface (UI)

- **Confusion:** None specified.
- **Proposal:** Phase 1 — Airbyte UI + worker logs + Postgres `ingestion_jobs` table. Phase 2 — Admin tab “Ingestion” (job status, last sync, reprocess).

---

## 6. Proposed target architecture

### 6.1 Components (Compose additions)

| Service | Role |
| --- | --- |
| `airbyte` (abctl / docker compose OSS) | Scheduled sync SharePoint, Drive, S3 → MinIO |
| `kafka` + `zookeeper` or KRaft | Topics for raw/completed/failed |
| `tika` | Apache Tika Server for multi-format extract |
| `ingestion-worker` | Kafka consumer; promote object; chunk; PG; OS |
| Existing | FastAPI, Postgres, MinIO, OpenSearch, Keycloak |

**Deferred:** Spark / YARN / K8s Spark operator until C5 scale trigger.

### 6.2 MinIO layout

```
enterprise-search-files/
  local/{file_id}/{safe_name}           # existing uploads (user-facing)
  files/sharepoint/{file_id}/{name}     # connector originals (user-facing)
  files/google_drive/{file_id}/{name}
  files/s3/{file_id}/{name}
  lake/raw/sharepoint/…                 # Airbyte dump (not user-facing)
  lake/raw/google_drive/…
  lake/raw/s3/…
  lake/derived/{file_id}/extract.json   # optional
```

### 6.3 Kafka topics (proposal)

| Topic | Producer | Consumer | Payload (sketch) |
| --- | --- | --- | --- |
| `ingest.raw.created` | MinIO notify | worker | `{bucket,key,etag,size,source_hint}` |
| `ingest.file.completed` | worker | optional listeners | `{file_id,chunk_count,status}` |
| `ingest.file.failed` | worker | ops / DLQ | `{key,error,attempt}` |

### 6.4 Worker processing steps

1. Read event; skip if key not under `lake/raw/` or already processed (etag match).
2. Download object; detect type (extension + Tika MIME).
3. Extract text (Tika); fail → `failed` job + no OS docs.
4. Chunk with **existing** `chunker.py` (600 / 75) — keep product consistency.
5. Allocate or resolve `file_id` via `(ingestion_type, original_source)`.
6. `put_object` to user-facing path; upsert `files`; compensate on failure (same C6 spirit as local ingest).
7. Bulk OS chunks: `ingestion_type` set; `original_source` set; `allowed_*=[]`.
8. Emit `ingest.file.completed`.

### 6.5 Schema changes (Alembic)

| Change | Why |
| --- | --- |
| Widen `ck_files_ingestion_type` | Connector types |
| Unique `(ingestion_type, original_source)` partial | Upsert / re-update |
| Table `ingestion_jobs` | Status, attempts, raw_key, file_id, error (ops + idempotency) |
| Optional `files.content_hash` | Skip no-op reprocessing |

**Do not** add `original_filename` unless product revisits data-model G8; display name remains basename of `object_store_path`.

### 6.6 OpenSearch

- No mapping migration required if we only reuse existing fields.
- Set `ingestion_type` / `original_source` on connector chunks.
- Re-index path: delete-by-query `file_id` then bulk (preserve ACL fields if re-processing after grants — **reload allowed_* from Postgres** on reprocess).

---

## 7. Phased implementation plan

### Phase 0 — Decisions (human gate)

Lock C1–C16 (or override). Especially: **no Spark in Phase 1**, **prefix split**, **empty ACL**, **upsert by original_source**.

### Phase 1 — Skeleton (MVP connector path)

**Goal:** One source (recommend **S3/MinIO folder** or **Google Drive** first — simpler creds than SharePoint) → lake → Kafka → worker → searchable file.

| # | Task |
| --- | --- |
| 1.1 | Add Kafka (+ UI optional) to `docker-compose.yml`; document ports/env |
| 1.2 | Configure MinIO bucket notifications → `ingest.raw.created` for `lake/raw/**` |
| 1.3 | Add Tika server container; thin client wrapper in `backend/app/services/ingest/tika_client.py` |
| 1.4 | Alembic: widen `ingestion_type`; `ingestion_jobs`; partial unique on `original_source` |
| 1.5 | Extract shared “index file bytes” from `upload.py` into `services/ingest/pipeline.py` (local + connector) |
| 1.6 | Implement `ingestion-worker` entrypoint: consume → process → PG/MinIO/OS |
| 1.7 | Manual proof: `mc cp` into `lake/raw/s3/...` → event → chunks + Open path works |
| 1.8 | Docs: runbook in summary; do not expand file types yet beyond pdf/txt/csv if Tika lagging |

### Phase 2 — Airbyte + second source

| # | Task |
| --- | --- |
| 2.1 | Deploy Airbyte OSS; S3 destination → MinIO `lake/raw/{source}/` with **Copy Raw Files** |
| 2.2 | Google Drive source connection (single folder); schedule 10 min |
| 2.3 | SharePoint source connection (one site/drive); schedule 10 min |
| 2.4 | Map Airbyte metadata → `original_source` / etag in worker (may need metadata sidecar records) |
| 2.5 | Expand allowlist via Tika (C7 Phase 1 types); reject/skip unsupported with job error |
| 2.6 | Re-update proof: change file in Drive → sync → same `file_id`, new chunks, ACL preserved |
| 2.7 | Admin read-only `GET /admin/ingestion-jobs` (optional but high value) |

### Phase 3 — Hardening / scale

| # | Task |
| --- | --- |
| 3.1 | DLQ + retry/backoff; poison-message quarantine prefix |
| 3.2 | Source delete handling (C11) |
| 3.3 | Optional Spark batch for backfill of large historical lakes |
| 3.4 | Connector ACL import design (separate proposal) |
| 3.5 | OCR for scans (Tika + Tesseract / VLM) |
| 3.6 | Metrics: lag, fail rate, files/hour |

---

## 8. Task backlog (implementation-ready once gates lock)

Ordered for a single agent/team stream after Phase 0 lock:

1. **Human lock** C1–C16 (table in §10).
2. Compose: Kafka + Tika (+ volume/network).
3. MinIO notify wiring script in `init_services` or `setup/`.
4. Schema migration (`ingestion_type`, jobs, unique source key).
5. Refactor local complete-path to call shared `pipeline.index_file(...)`.
6. Worker service + Dockerfile + `docker compose` dependency on Kafka/MinIO/OS/PG.
7. End-to-end proof script `scripts/connector_ingest_proof.py` (put lake object → assert PG/OS/MinIO user path).
8. Airbyte install runbook + first Drive or S3 connection.
9. File-type matrix tests (docx/pptx/…).
10. Summary writeup under `prompts/summary/` when Phase 1 ships.

---

## 9. Landmines

1. **Airbyte webhook ≠ per-file ingest trigger** — use MinIO events.
2. **Notification loops** — never notify on `files/` or `local/` puts that the worker writes; only `lake/raw/`.
3. **Auto-ACL** — do not grant from connector in Phase 1.
4. **User JWT OS writes** — worker uses basic admin / `files_writer`.
5. **New `file_id` on every sync** — destroys ACL; upsert instead.
6. **Chunk objects as user Open targets** — wrong; originals only.
7. **Spark tax too early** — ops cost dominates this repo’s current scale.
8. **Syncing lake onto itself** when S3 is a source.
9. **25 MiB local cap** vs Airbyte **~1GB** raw file — decide worker max size (propose **100 MiB** Phase 1; larger → skip + job error).
10. **MiniLM 512 vs chunk 600** — unchanged product lock; monitor.
11. **`ingestion_type` CHECK** — forgetting migration breaks connector inserts.
12. **Reprocess after ACL** — must re-apply `allowed_*` from Postgres, not reset to `[]`.

---

## 10. Human gate checklist

Please lock or override:

| ID | Proposal default | Lock? |
| --- | --- | --- |
| C1 | Airbyte scheduled; events via MinIO→Kafka | |
| C2 | One bucket; `lake/raw/` vs `files/`+`local/` | |
| C3 | Kafka pointer messages | |
| C4 | Separate `ingestion-worker` | |
| C5 | No Spark in Phase 1; Tika + Python chunker | |
| C6 | Chunks only in OpenSearch (derived lake optional) | |
| C7 | Phase 1 types: + office/html/md via Tika | |
| C8 | Empty ACL until admin (no source ACL import) | |
| C9 | Widen `ingestion_type`; unique source key | |
| C10 | Upsert same `file_id` on re-update | |
| C11 | Ignore source deletes in Phase 1 | |
| C12 | Separate source vs lake prefixes | |
| C13 | Single worker pipeline (no dual Spark→OS hop) | |
| C14 | Secrets via env; one folder/site per connection | |
| C15 | Keep local `/upload` | |
| C16 | Airbyte UI + `ingestion_jobs`; Admin UI later | |
| Extra | Worker max file size **100 MiB** | |
| Extra | First connector: **Google Drive** or **S3** before SharePoint | |

---

## 11. Research notes (brief)

- Airbyte file sources (SharePoint, Google Drive, S3) support **Copy Raw Files** into S3 destinations; MinIO works as S3-compatible endpoint. Metadata streams describe files; binaries land as objects.
- Airbyte **Kafka destination** exists but is for record streams, not a substitute for MinIO raw + path events; prefer MinIO notifications for “file arrived.”
- Airbyte sync notifications are operational (success/fail), not a clean file-level CDC bus for Drive/SharePoint.
- MinIO supports `notify_kafka` + `mc event add` for `s3:ObjectCreated:*`.
- Tika (esp. server / pipes) is the pragmatic multi-format extractor; Spark is for volume, not format coverage.

---

## 12. Explicit non-goals (this proposal)

- Replacing local resumable upload.
- Implementing connector ACL mapping in Phase 1.
- Changing hybrid search / DLS model.
- Embedding generation in the worker.
- Production K8s Spark operator.
- Rewriting Admin or Search UI except optional jobs list.

---

## Changelog

| Date | Change |
| --- | --- |
| 5 Sep 2026 | Initial proposal from `2_Ingestion_pipeline.md` + project summaries; web research on Airbyte/MinIO/Kafka/Tika. |
