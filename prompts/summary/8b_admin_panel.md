# Admin panel 6b — File ACL + OpenSearch sync

**Implemented 30 August 2026.** Task **6b** from `prompts/cursor_summary/9b_admin_panel.md`. Together with **6a** (`prompts/summary/8a_admin_panel.md`), overview **Task 6** is complete.

Identity CRUD is unchanged (9a). This slice adds admin file inventory, role/group ACL assign/revoke, durable `acl_sync_jobs`, OpenSearch `allowed_*` sync via basic `admin`, and the Admin **Files (ACL)** tab.

---

## What shipped

### A. Schema + sync core

| Piece | Location |
| --- | --- |
| Migration | `backend/alembic/versions/b2c3d4e5f6a7_acl_sync_jobs.py` |
| Model | `backend/app/models/acl_job.py` (`AclSyncJob`) |
| PG ACL mutate + recompute | `backend/app/services/file_acl_admin.py` |
| Enqueue / worker / retry / startup interrupt | `backend/app/services/acl_sync.py` |
| App lifespan | `backend/app/main.py` — `running` → `failed` + `interrupted` on startup |

**Flow (G6):** mutate Postgres `file_acl` → commit → insert `acl_sync_jobs` (`queued`) → `BackgroundTasks` worker recomputes full `allowed_roles` / `allowed_groups` → OpenSearch `update_by_query` as basic **`admin`** with `refresh=true` (same painless shape as G3 seed).

Roles/groups only (G3). System principals and `_empty` rejected with **400**. No Celery/Redis (G2). G3 seed script left intact for CI.

### B. Admin ACL API

| Piece | Location |
| --- | --- |
| Schemas | `backend/app/schemas/admin_acl.py` |
| Routes | `backend/app/api/routes/admin_acl.py` (mounted in `app/api/router.py`) |

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/admin/files` | All files (not ACL-filtered); display name = basename |
| GET | `/admin/files/{id}/acl` | List role/group grants |
| PUT | `/admin/files/{id}/acl` | Replace-all + enqueue (`acl_job_id`) |
| POST | `/admin/files/{id}/acl` | Upsert one + enqueue |
| DELETE | `/admin/files/{id}/acl/{acl_id}` | Revoke + enqueue |
| GET | `/admin/acl-jobs/{id}` | Job progress |
| GET | `/admin/acl-jobs` | Filter by `file_id` / `status` |
| POST | `/admin/acl-jobs/{id}/retry` | failed → queued + re-run |

Non-admin → **403**. Missing file → **404**. Enqueue fail after PG commit → **503**.

### C. React Files (ACL)

| Piece | Location |
| --- | --- |
| API client | `frontend/src/api/admin.ts` (+ `apiPutJson` in `client.ts`) |
| Page | `frontend/src/pages/Admin.tsx` — tab **Files (ACL)** |

Pick file → edit grants (role/group + viewer|editor) → Save → poll job ~1s until succeeded/failed; retry on failure. Role/group pickers reuse 9a lists (`include_system=false`).

### D. Proof driver

`backend/scripts/admin_acl_proof.py` — proofs **1–9**. Run:

```bash
cd backend
uv run python -m scripts.admin_acl_proof
```

Needs at least one ingested file and API on `:8000`.

---

## Proofs run (30 Aug 2026)

| # | Result |
| --- | --- |
| 1 | searcher `GET /admin/files` → **403** |
| 2 | realm-admin list → **200**, total includes all uploads |
| 3 | `PUT` grant `search-user` → `acl_job_id`; job **succeeded**; OS `allowed_roles` contains `search-user` |
| 4 | searcher `GET /files` lists file; `POST /search` hits content |
| 5 | Revoke all → OS empty; searcher list miss |
| 6 | Grant `engineering` → admin lists; searcher without group miss |
| 7 | Grant `_empty` → **400** |
| 8 | Force job `failed` → `POST .../retry` → **succeeded** |
| 9 | `/health` + `/auth/admin-ping` → **200** |
| 10 | React smoke — **human** (see guide below) |

Manual sync proof during build: job `succeeded`, `updated_chunks=152` on a known file.

Frontend `bun run build` succeeded after UI changes.

---

## Guide to test the changes

### Prerequisites

1. Compose stack up (Postgres, Keycloak, OpenSearch, MinIO).
2. Backend + frontend via `./start-dev.sh` (`:8000` / `:5173`).
3. Alembic at head: `cd backend && uv run alembic upgrade head` (adds `acl_sync_jobs`).
4. At least one uploaded file (Upload page or prior ingest).
5. 9a identity APIs working (roles/groups for pickers).

### Automated API proofs

```bash
cd backend
uv run python -m scripts.admin_acl_proof
```

Expect `=== all admin ACL proofs passed ===`.

### Manual API spot checks (optional)

```bash
export KC=http://localhost:8080/realms/enterprise-search-realm/protocol/openid-connect/token
export ADMIN=$(curl -s -X POST "$KC" -d 'grant_type=password&client_id=api-client&client_secret=api-client-secret&username=realm-admin&password=adminpass' | jq -r .access_token)
export SEARCHER=$(curl -s -X POST "$KC" -d 'grant_type=password&client_id=api-client&client_secret=api-client-secret&username=searcher&password=searcherpass' | jq -r .access_token)

# inventory
curl -s -o /dev/null -w "%{http_code}\n" -H "Authorization: Bearer $SEARCHER" http://localhost:8000/admin/files   # 403
curl -s -H "Authorization: Bearer $ADMIN" 'http://localhost:8000/admin/files?limit=5' | jq .

# grant search-user on a file (replace FILE_ID and ROLE_ID)
curl -s -X PUT -H "Authorization: Bearer $ADMIN" -H 'Content-Type: application/json' \
  http://localhost:8000/admin/files/$FILE_ID/acl \
  -d "{\"grants\":[{\"principal_type\":\"role\",\"principal_id\":\"$ROLE_ID\",\"permission\":\"viewer\"}]}" | jq .

# poll job
curl -s -H "Authorization: Bearer $ADMIN" http://localhost:8000/admin/acl-jobs/$JOB_ID | jq .
```

### Human: React smoke (proof 10)

1. Open http://localhost:5173 → login as **`realm-admin` / `adminpass`**.
2. Navbar **Admin** → `/admin`. Confirm tabs **Users | Roles | Groups | Files (ACL)**.
3. **Files (ACL):** select a file that searcher currently cannot see (or clear grants first).
4. Add grant: type **role**, principal **search-user**, permission **viewer** → **Save ACL**.
5. Confirm sync job status moves `queued` → `running` → `succeeded` (chunk counts shown).
6. Logout → login as **`searcher` / `searcherpass`** → **View files** lists that file; **Search** finds its content.
7. Back as realm-admin: clear grants (remove all → Save) → job succeeds → searcher no longer lists/searches the file.
8. Optional: force a failed job in DB and use **Retry sync** in the UI.

If OpenSearch sync stays failed, check backend logs and that `OPENSEARCH_INITIAL_ADMIN_PASSWORD` is set for basic `admin` auth.

---

## Intentionally out of scope (6b)

- Identity create/update (9a)
- Celery/Redis / multi-worker `SKIP LOCKED` (Task 7)
- User-principal ACL UI; bulk ACL across files
- Auto-ACL on upload; admin bypass on product Search/View
- Role rename; user hard-delete; connectors

---

## Follow-on

| Next | Needs from 6b |
| --- | --- |
| Task 7 Hardening | Dual-write repair; fleet-safe job locking |
| Day-to-day ops | Prefer Admin ACL UI over `seed_file_acl_for_proofs.py` for real files |

---

## Files touched (summary)

```
backend/alembic/versions/b2c3d4e5f6a7_acl_sync_jobs.py
backend/app/models/acl_job.py
backend/app/models/__init__.py
backend/app/services/file_acl_admin.py
backend/app/services/acl_sync.py
backend/app/schemas/admin_acl.py
backend/app/api/routes/admin_acl.py
backend/app/api/router.py
backend/app/main.py
backend/scripts/admin_acl_proof.py
frontend/src/api/client.ts
frontend/src/api/admin.ts
frontend/src/pages/Admin.tsx
prompts/summary/8b_admin_panel.md          # this file
prompts/cursor_summary/2_project_overview_tasks.md  # Task 6 boxes
prompts/cursor_summary/9_admin_panel.md             # index status
prompts/cursor_summary/9b_admin_panel.md            # checklist
```
