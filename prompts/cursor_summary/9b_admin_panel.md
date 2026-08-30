# Admin panel 6b — File ACL + OpenSearch sync

Working notes to implement **Task 6b (Admin file privileges + ACL sync)** from `prompts/cursor_summary/2_project_overview_tasks.md` Task 6. Sibling plan: **`9a_admin_panel.md`** (identity). Index: `9_admin_panel.md`.

**Prerequisite:** 9a identity APIs + Users/Roles/Groups Admin tabs should be live (or at least roles/groups list endpoints for pickers). Auth, ingest, search/view are live (summaries 2–5, 7).

This file is the source of truth for **file ACL assign/revoke + durable OpenSearch `allowed_*` sync + progress UI**. Do not invent a second ACL model, auto-grant on upload, admin bypass of product list/search ACL, Celery/Redis, or FastAPI-side embeddings.

**Agent rules while implementing**
- Run and execute code to confirm it works before moving on.
- Do not proceed past a broken step; fix it first.
- Where something cannot be verified in this environment, leave a clear human check and wait for feedback.
- Do **not** re-build identity CRUD (9a). Do not start connectors, `owner`/`deleter`, or Task 7 multi-worker locking beyond startup `interrupted` handling.
- Treat **Locked decisions** in this file as law.
- Promote G3 seed’s `update_by_query` shape from `scripts/seed_file_acl_for_proofs.py` into `app/services/acl_sync.py` — keep the seed script for CI.

**Human locks (30 Aug 2026):** G1 = 9a then 9b. G2–G4, G6 locked. C5 (`/admin/files`), C6–C8, C10 (Files tab), C11–C12 locked.

---

## What “done” means

A signed-in realm **`admin`** can:

1. **Inventory** all files via `GET /admin/files` (not ACL-filtered).
2. **Assign / revoke** viewer|editor grants on a file to **roles and groups only**.
3. After PG commit, an **`acl_sync_jobs`** row is enqueued; a BackgroundTasks worker recomputes full `allowed_roles` / `allowed_groups` and runs OpenSearch `update_by_query` as basic `admin`.
4. Admin UI **Files (ACL)** tab shows grants + job progress (poll until succeeded/failed); retry failed jobs.
5. After a successful grant, product Search / View files behave correctly for matching JWT principals (closes “upload works, search empty”).

| Actor | What they may do in 6b |
| --- | --- |
| FastAPI | `/admin/files*`, `/admin/files/{id}/acl*`, `/admin/acl-jobs*` — `require_admin` |
| React `/admin` | Files (ACL) tab + job poll (identity tabs already from 9a) |
| Postgres | `file_acl` mutate + `acl_sync_jobs` |
| OpenSearch | `update_by_query` as **basic `admin` only** |
| Keycloak | **Not** written in 6b |

---

## Current state (do not re-scaffold)

From Tasks 0–5 + expected 9a:

- `files` + `file_acl` (viewer|editor; exactly one principal FK). Ingest never auto-grants; chunks start with empty `allowed_*`.
- Task 5 list/open: JWT names vs `file_acl`; realm `admin` does **not** bypass product ACL.
- G3 `seed_file_acl_for_proofs.py`: upsert ACL + `update_by_query` — reference only.
- Client hybrid `POST /search` with user JWT + DLS (3.8).
- No Celery/Redis.
- After 9a: `/admin/users|roles|groups` + identity UI; roles/groups list with `include_system=false` for pickers.

---

## Dependency map (6b)

```
Postgres file_acl  ──recompute names──► OpenSearch allowed_* (update_by_query job)
        │                                      │
        ▼                                      ▼
   List / Open (Task 5)                 Search DLS hits (Task 5)
```

| Capability | Needs PG `file_acl`? | Needs OS sync job? |
| --- | --- | --- |
| Admin inventory `/admin/files` | No | No |
| Grant/revoke | **Yes** | **Yes** |
| List/Open after grant | **Yes** | No |
| Search hits after grant | Indirect | **Yes** |

---

## Locked decisions (relevant to 6b)

### G1. Split

| | |
| --- | --- |
| Status | **LOCKED** |
| Decision | Implement after 9a. Overview Task 6 flips when **9a + 9b** both done. |

### G2. Job runtime

| | |
| --- | --- |
| Status | **LOCKED** |
| Decision | **No Celery/Redis.** Durable `acl_sync_jobs` + FastAPI `BackgroundTasks` (or thread). On app startup: mark `running` → `failed` with `interrupted`. UI uses job + poll — do not block HTTP on large `update_by_query`. |

### G3. ACL principals

| | |
| --- | --- |
| Status | **LOCKED** |
| Decision | Roles and groups only. Hide `is_system=true` (incl. `_empty`). Never write `_empty` into `file_acl` or `allowed_groups`. No product `user_id` grants. Reject `principal_type=user` and system ids → **400**. |

### G4. Permission verbs

| | |
| --- | --- |
| Status | **LOCKED** |
| Decision | Default **`viewer`**. Accept `viewer` \| `editor`. Both contribute the same principal **name** to OS `allowed_*`. One row per (file, principal). |

### G6. Dual-write ACL ↔ OS

| | |
| --- | --- |
| Status | **LOCKED** |
| Decision | **Postgres first**, then enqueue job. Recompute **full** name sets from all grants on that file. `update_by_query` as basic `admin` with `refresh=true`. OS fail → job `failed`; PG stays correct (List/Open work; Search lags until retry). |

### C5. Admin file list

| | |
| --- | --- |
| Status | **LOCKED** |
| Decision | `GET /admin/files?limit&offset` = **all** files. Display name = basename of `object_store_path`. |

### C6. File ACL API

| | |
| --- | --- |
| Status | **LOCKED** |

```http
GET    /admin/files/{file_id}/acl
PUT    /admin/files/{file_id}/acl          # replace-all
POST   /admin/files/{file_id}/acl          # upsert one
DELETE /admin/files/{file_id}/acl/{acl_id}
```

```json
{
  "grants": [
    { "principal_type": "role", "principal_id": "<role uuid>", "permission": "viewer" },
    { "principal_type": "group", "principal_id": "<group uuid>", "permission": "editor" }
  ]
}
```

- Empty `grants` clears role/group ACL and syncs OS to `[]`,`[]`.
- Response includes `acl_job_id` when sync enqueued.

### C7. Recompute `allowed_*`

| | |
| --- | --- |
| Status | **LOCKED** |

```
allowed_roles  = sorted unique Role.name for file_acl rows with role_id set
allowed_groups = sorted unique Group.name for file_acl rows with group_id set
```

Ignore user-principal rows. Never `_empty`. Painless set both arrays (same as G3 seed).

### C8. Job model + API

| | |
| --- | --- |
| Status | **LOCKED** |

Table `acl_sync_jobs`: `id`, `file_id`, `status` (`queued`\|`running`\|`succeeded`\|`failed`), `total_chunks`, `updated_chunks`, `error`, timestamps, optional `created_by_user_id`.

```http
GET  /admin/acl-jobs/{job_id}
GET  /admin/acl-jobs?file_id=&status=&limit&offset
POST /admin/acl-jobs/{job_id}/retry    # failed → queued
```

Poll ~1s while `queued|running`. Multiple queued jobs per `file_id` OK (FIFO; later job sees latest PG).

### C10. Frontend (6b scope)

| | |
| --- | --- |
| Status | **LOCKED** (partial) |
| Decision | Add **Files (ACL)** to `/admin`: pick file → edit grants → save → poll job. Reuse 9a shell/tabs. |

### C11. G3 seed

| | |
| --- | --- |
| Status | **LOCKED** |
| Decision | Keep `seed_file_acl_for_proofs.py` for CI. 6b proofs call **Admin HTTP APIs**. |

### C12. Errors (ACL)

| | |
| --- | --- |
| Status | **LOCKED** |
| Decision | Missing file → **404**. System principal → **400**. Enqueue failure after PG commit → **503** (PG changed, sync not queued). |

---

## Architecture (6b)

```
React /admin — Files (ACL)
  │ Bearer admin JWT
  ▼
FastAPI /admin/files|acl|acl-jobs
  → Postgres file_acl commit
  → insert acl_sync_jobs (queued)
  → BackgroundTasks worker
        recompute allowed_* from PG
        update_by_query as basic admin
        update job status / counts
```

```
Sources of truth
────────────────────────────────
File grants           → Postgres file_acl
Search-time ACL copy  → OpenSearch allowed_* (derived)
List/Open authz       → Postgres + JWT (Task 5)
Admin capability      → realm role admin
```

---

## API contract (6b)

### Files inventory + ACL

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/admin/files` | all files |
| GET | `/admin/files/{id}/acl` | list grants |
| PUT | `/admin/files/{id}/acl` | replace-all + enqueue |
| POST | `/admin/files/{id}/acl` | upsert one + enqueue |
| DELETE | `/admin/files/{id}/acl/{acl_id}` | revoke + enqueue |

### Jobs

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/admin/acl-jobs/{id}` | progress |
| GET | `/admin/acl-jobs` | filter |
| POST | `/admin/acl-jobs/{id}/retry` | failed only |

### Out of scope in 6b

- Identity CRUD (9a)
- Per-user ACL in UI; bulk ACL across many files
- Celery; OS security role management from UI
- Auto-ACL on upload; admin bypass on product Search/View

---

## Module layout (6b)

```
backend/alembic/versions/
  <rev>_acl_sync_jobs.py

backend/app/
  api/routes/admin_acl.py         # files inventory, acl, jobs
  api/router.py                   # include
  schemas/admin_acl.py
  models/acl_job.py               # AclSyncJob
  models/__init__.py
  services/
    file_acl_admin.py             # PG mutate + recompute names
    acl_sync.py                   # enqueue, worker, update_by_query, retry

frontend/src/
  api/admin.ts                    # EXTEND: files, acl, jobs
  pages/Admin.tsx                 # ADD Files (ACL) tab + poll

backend/scripts/
  admin_acl_proof.py              # proofs below
```

Reuse: `file_access.display_name_from_path`; G3 seed script body; 9a `include_system=false` role/group lists for pickers. Do **not** use `list_visible_files` for admin inventory.

---

## Landmines (6b)

1. **User JWT for `update_by_query`** — forbidden; use basic `admin`.
2. **Admin sees all on product `/files`** — do not change Task 5 bypass; inventory is `/admin/files` only.
3. **Auto-ACL on upload** — still forbidden.
4. **Granting `_empty` / system** — reject.
5. **OS-first ACL** — wrong; PG first (G6).
6. **Incremental allowed_* patches** — always full recompute (C7).
7. **Blocking HTTP on large files** — use job + poll (G2).
8. **Forgetting refresh** — `refresh=true` (match G3 seed).
9. **Editor vs viewer OS fields** — none; same name arrays.
10. **Dual workers** — single-process BackgroundTasks for v1; Task 7 may add `SKIP LOCKED`.

---

## Proofs (6b)

| # | Test | Expect |
| --- | --- | --- |
| 1 | `GET /admin/files` as searcher | 403 |
| 2 | `GET /admin/files` as realm-admin | 200 all files (incl. no-ACL uploads) |
| 3 | `PUT` ACL: grant `search-user` viewer on file F | 200 + `acl_job_id`; job → succeeded; OS `allowed_roles` contains `search-user` |
| 4 | searcher `GET /files` lists F; `POST /search` finds F content | hit (client hybrid) |
| 5 | Revoke all grants on F | job succeeded; OS empty; searcher list/search miss F |
| 6 | Grant `engineering` on F; realm-admin search hits; searcher without group miss (unless role grant) | DLS-aligned |
| 7 | Reject grant to `_empty` | 400 |
| 8 | `POST /admin/acl-jobs/{id}/retry` after forced failure | re-runs to succeeded |
| 9 | `/auth/admin-ping` + `/health` | 200 |
| 10 | React smoke: grant ACL; see progress; searcher sees file | manual |

Needs an ingested file (upload first). Proof driver: `uv run python -m scripts.admin_acl_proof`.

---

## Tasks to perform (6b checklist)

Check a box only after that step has been **run**.

### 0. Prerequisites + locks

- [x] 9a identity APIs available (roles/groups list for pickers)
- [x] G1–G4, G6 + C5–C8, C10–C12 locked
- [x] No Celery (G2)

### A. Schema + sync core

- [x] Alembic `acl_sync_jobs` (+ indexes `file_id`, `status`)
- [x] Model `AclSyncJob`; export
- [x] `file_acl_admin.py` + `acl_sync.py` (recompute, `update_by_query`, startup interrupted)
- [x] Prove one sync against a known `file_id` (script or route)

### B. Admin ACL API

- [x] Schemas + routes: `/admin/files`, ACL, jobs, retry
- [x] Proofs 1–9

### C. React Files (ACL)

- [x] Extend `api/admin.ts`
- [x] Files tab: grants editor + job poll
- [ ] Proof 10 manual

### D. Hygiene

- [x] No auto-ACL; no product ACL bypass; leave G3 seed intact
- [x] Summary e.g. `prompts/summary/8b_admin_panel.md`
- [x] Flip Task 6 boxes in `2_project_overview_tasks.md` (9a + 9b both done)
- [x] Update index `9_admin_panel.md` status

---

## Recommended execution order

1. Confirm 9a pickers work.
2. Alembic + `acl_sync` worker + one manual sync proof.
3. ACL HTTP API + proofs 1–9.
4. React Files tab + proof 10.
5. Summaries + flip Task 6.

---

## Explicitly out of scope (6b)

- Identity create/update (9a)
- Celery/Redis / multi-worker fleet
- User-principal ACL UI; role rename; user hard-delete
- Auto `file_acl` on upload; admin bypass on Search/View/Open
- Connectors; `owner`/`deleter`; native hybrid 3.9
- Deleting `proof-*` fixtures

---

## Follow-on

| Task | Needs from 6b |
| --- | --- |
| 7 Hardening | Dual-write repair; `FOR UPDATE SKIP LOCKED`; search users remain OS read-only |
| Day-to-day | Admin ACL UI replaces reliance on G3 seed for real files |
| Connectors | May use `file_acl.user_id`; widen permission CHECK |

---

## Changelog

| Date | Change |
| --- | --- |
| 30 Aug 2026 | Split from `9_admin_panel.md` into **9b** (file ACL + sync) per locked G1. |
| 30 Aug 2026 | **Implemented** — summary `prompts/summary/8b_admin_panel.md`; proofs 1–9 automated; Proof 10 human. |
