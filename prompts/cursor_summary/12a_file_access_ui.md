# 12a — File Access UI

Working notes to implement **File Access UI** (Admin ACL UX pass 1). Sibling: **`12b_member_assignment_ui.md`** (multi-user → role/group). Index: **`12_acl_ui.md`**.

**Prerequisite:** 6a + 6b done (`9a` / `9b`). Existing `GET/PUT/POST/DELETE /admin/files/{id}/acl` and `acl_sync_jobs` work. Do **not** start 12b membership APIs in this pass.

This file is the source of truth for **Access tab redesign + multi-file grant/revoke + principal → file-grants list**. Do not invent user-principal file ACL, Celery, folder inheritance, or auto-grant on upload.

**Agent rules while implementing**
- Run and execute code to confirm it works before moving on.
- Do not proceed past a broken step; fix it first.
- Where something cannot be verified in this environment, leave a clear human check and wait for feedback.
- Do **not** implement member assignment APIs or Users bulk “Add to role/group” (that is **12b**).
- Treat **Locked decisions** in this file as law.
- Reuse `file_acl_admin` / `acl_sync` — extend; do not duplicate sync logic.

**Human locks (31 Aug 2026):** FA1–FA8, C-FA1–C-FA7 locked as written below.

---

## What “done” means

A signed-in realm **`admin`** can:

1. Open Admin tab **Access** (renamed from “Files (ACL)”).
2. Browse files in a **selectable table** with name search; see a short grant summary per file.
3. Open **Manage access** on one file: Drive-like list of roles/groups with Viewer/Editor; add/remove; save; see sync status.
4. Select **multiple files** → **Grant access** → pick one or more roles/groups + permission → confirm impact preview → upsert grants → watch jobs.
5. Select multiple files → **Revoke access** → pick roles/groups to remove → confirm → sync jobs.
6. On **Roles** / **Groups** panels: open a **File access** section listing files granted to that role/group, with a **Grant files…** action that reuses the same bulk grant flow (principal pre-filled).

| Actor | What they may do in 12a |
| --- | --- |
| FastAPI | Bulk ACL + file-grants-by-principal + optional file list filters — `require_admin` |
| React `/admin` | Access tab + Role/Group File access section; **no** Members bulk UI |
| Postgres | `file_acl` mutate (existing rules) |
| OpenSearch | Existing `acl_sync` worker only |
| Keycloak | **Not written** in 12a |

---

## Current state (do not re-scaffold)

From 6b (`frontend/src/pages/Admin.tsx` FilesAclPanel):

- Left list: pick **one** file.
- Right form: grant **rows** (`type` / `principal` / `permission` selects) → Save ACL → poll one job.
- APIs: single-file replace/upsert/delete + job get/retry.
- Roles/Groups tabs: create/delete only — **no** file-grants list.

Pain: CRUD mirrors `file_acl`; cannot grant many files at once; cannot see “what can `engineering` open?”

---

## Locked decisions (12a)

### FA1. Phase boundary

| | |
| --- | --- |
| Status | **LOCKED** |
| Decision | **12a = file access UX only.** Membership add/remove APIs and Users bulk assign are **12b**. Role/Group panels may gain a **File access** section in 12a, but **not** a Members manager. |

### FA2. Tab rename

| | |
| --- | --- |
| Status | **LOCKED** |
| Decision | Rename Admin tab label **`Files (ACL)` → `Access`**. Route stays `/admin` (tab state). |

### FA3. Principals for file grants

| | |
| --- | --- |
| Status | **LOCKED** |
| Decision | Same as G3: **roles and groups only**. UI copy says “Roles & groups with access”, never “Add user to file”. Pickers use `include_system=false`. Reject `_empty` / system. |

### FA4. Bulk default mode

| | |
| --- | --- |
| Status | **LOCKED** |
| Decision | Bulk **Grant access** default = **`upsert`** (add/update named principals; leave other grants intact). **`replace`** only if admin explicitly chooses it and confirms (`confirm_replace: true`). **`revoke`** removes listed principals from each selected file. |

### FA5. Bulk size cap

| | |
| --- | --- |
| Status | **LOCKED** |
| Decision | Max **`100`** `file_ids` per bulk request. Over → **400** with clear message. |

### FA6. Partial failure

| | |
| --- | --- |
| Status | **LOCKED** |
| Decision | Process files **independently** (own DB transaction + enqueue per file). Return `results[]` + `failed[]`. Do not roll back successful files when later ones fail. |

### FA7. Single-file save behavior

| | |
| --- | --- |
| Status | **LOCKED** |
| Decision | Manage-access drawer keeps an explicit **Save** that calls existing **`PUT /admin/files/{id}/acl`** (replace-all for that file’s draft). Bulk modal is one-shot confirm (no draft across files). |

### FA8. Permission default

| | |
| --- | --- |
| Status | **LOCKED** |
| Decision | Default **`viewer`**. Labels: **Viewer** / **Editor** (not raw enum as primary text). |

### C-FA1. Auth prefix

| | |
| --- | --- |
| Status | **LOCKED** |
| Decision | All new routes under `/admin/...`, `require_admin`. Non-admin **403**; unauthenticated **401**. |

### C-FA2. Bulk ACL API

| | |
| --- | --- |
| Status | **LOCKED** |

```http
POST /admin/files/acl:bulk
```

Request:

```json
{
  "file_ids": ["<uuid>", "<uuid>"],
  "mode": "upsert" | "replace" | "revoke",
  "grants": [
    {
      "principal_type": "role" | "group",
      "principal_id": "<uuid>",
      "permission": "viewer" | "editor"
    }
  ],
  "confirm_replace": false
}
```

Rules:

| Mode | `grants` | Behavior |
| --- | --- | --- |
| `upsert` | required, non-empty | For each file: upsert each grant (same as today’s POST-one, repeated). Other existing grants stay. |
| `replace` | required (may be `[]` to clear) | Requires `confirm_replace: true` else **400**. Full replace-all per file (same as PUT). |
| `revoke` | required, non-empty | For each file: delete grants matching those principals (match on type+id); ignore permission field for matching. Missing grant on a file = no-op success for that principal. |

Response **200**:

```json
{
  "results": [
    {
      "file_id": "<uuid>",
      "grants": [ /* current grants after mutate */ ],
      "acl_job_id": "<uuid>|null"
    }
  ],
  "failed": [
    { "file_id": "<uuid>", "error": "human readable" }
  ]
}
```

- Empty `file_ids` → **400**.
- Duplicate ids in `file_ids` → dedupe preserving order.
- Unknown file id → that id in `failed` with not-found message (other files still processed).
- System / `_empty` principal → that file’s op fails into `failed` (or reject whole request with **400** if any grant is illegal — **prefer whole-request 400** before mutating any file when validation fails on grants).

### C-FA3. File grants by principal

| | |
| --- | --- |
| Status | **LOCKED** |

```http
GET /admin/roles/{role_id}/file-grants?limit=50&offset=0
GET /admin/groups/{group_id}/file-grants?limit=50&offset=0
```

Response:

```json
{
  "items": [
    {
      "acl_id": "<uuid>",
      "file_id": "<uuid>",
      "display_name": "report.pdf",
      "file_type": "pdf",
      "permission": "viewer",
      "updated_at": "<iso>"
    }
  ],
  "total": 12,
  "limit": 50,
  "offset": 0
}
```

- Missing role/group → **404**.
- System role/group may **404** or empty — do not expose `_empty` grants (there should be none).

### C-FA4. File list query params

| | |
| --- | --- |
| Status | **LOCKED** |
| Decision | Extend `GET /admin/files` with optional `q` (case-insensitive substring on display name / basename of `object_store_path`) and optional `has_acl=true|false`. Keep `limit`/`offset`. Backward compatible when omitted. |

### C-FA5. Jobs

| | |
| --- | --- |
| Status | **LOCKED** |
| Decision | Reuse existing job APIs. UI may poll many `acl_job_id`s. No new job table. Cap concurrent UI polls reasonably (e.g. poll all active ids every 1s). |

### C-FA6. Frontend scope (12a)

| | |
| --- | --- |
| Status | **LOCKED** |
| Decision | Access tab + shared pickers used by Access + Role/Group **File access** section. Do not build Members tabs. Do not add Check-access modal. |

### C-FA7. Errors

| | |
| --- | --- |
| Status | **LOCKED** |
| Decision | Validation → **400**. Missing role/group for file-grants GET → **404**. Enqueue failure after PG commit on a file → that file in `failed` with sync-not-queued message (PG grant still applied — same spirit as 9b C12 **503** for single-file; for bulk use `failed[]` entry, HTTP still **200** if any result/failed arrays returned). If **all** file_ids invalid before any work, **400** is OK. |

---

## Architecture (12a)

```
React /admin — Access | (Roles/Groups File access section)
  │ Bearer admin JWT
  ▼
FastAPI
  POST /admin/files/acl:bulk
  GET  /admin/roles|groups/{id}/file-grants
  GET  /admin/files?q&has_acl          (extended)
  + existing single-file ACL + jobs
  → file_acl_admin (extend with bulk helpers)
  → acl_sync.enqueue per mutated file
```

```
Mental model for admins
────────────────────────────────
File → who (roles/groups) can access it     = Access tab
Role/Group → which files it can access      = File access section
User → file access                          = via membership (12b), not direct ACL
```

---

## UI specification (unambiguous)

### Access tab layout

```
[ Access ]

Toolbar: [Search files……] [has ACL ▾ All/Yes/No] [Reload]
         when selection>0: [Grant access…] [Revoke access…]  “N selected” [Clear]

Table columns:
  ☐ | Name | Type | Size | Access summary | Sync |  [Manage]
```

**Access summary cell:** up to 2 chips `name · Viewer|Editor`, then `+K more`, or “No access”.

**Sync cell:** show latest known job for that file if UI has one in memory; otherwise blank / “—”. After bulk, update from `acl_job_id`.

**Manage** (single row or when exactly one selected): opens **Manage access** panel (right drawer or right column — pick one and stay consistent; prefer **right panel** below toolbar on large screens to match current two-pane habit).

### Manage access (single file)

1. Title: file `display_name`.
2. Subtitle: “Roles & groups with access”.
3. List current grants: name, type badge (Role/Group), permission select, Remove.
4. Add row: **PrincipalPicker** (search roles+groups, multi OK but adding applies as multiple draft rows) + permission + Add to draft.
5. Buttons: **Save access** (PUT replace-all from draft), **Cancel** (reload grants).
6. Below: SyncStatus for last job (poll while queued/running; Retry if failed).
7. Empty: “No roles or groups can search this file yet.”

**Do not** show user pickers here.

### Grant access modal (multi-file)

1. Title: `Grant access to N files`.
2. Collapsed chip list of file names (expand to scroll full list).
3. PrincipalPicker (required ≥1).
4. PermissionSelect default Viewer.
5. Mode: radio **Add or update access** (`upsert`, default) | **Replace all access** (`replace` — shows warning + requires checkbox “I understand this removes other grants on each file”).
6. **Impact preview** text, e.g. `Add Viewer for engineering, finance on 12 files (up to 12 search-index sync jobs).`
7. Primary: **Confirm** → call bulk API → close modal → show Job tray / notices.
8. Disable Confirm when no principals, or replace without checkbox.

### Revoke access modal

1. Title: `Revoke access from N files`.
2. PrincipalPicker (required ≥1) — “Remove these roles/groups from selected files”.
3. Impact preview.
4. Confirm → `mode: revoke`.

### Role / Group — File access section

On Roles and Groups panels, when a role/group is selected or listed with an expand/detail:

- Heading: **File access**
- Table from `GET .../file-grants`
- Button **Grant files…** → modal: File multi-picker (from `GET /admin/files`) + permission → bulk `upsert` with principal pre-filled (single principal, locked in UI).
- Optional per-row **Remove**: call existing `DELETE /admin/files/{file_id}/acl/{acl_id}` then refresh list + poll job if response includes job (single DELETE already enqueues).

Keep existing create/delete role/group controls.

### Shared components to add

| Component | Responsibility |
| --- | --- |
| `PrincipalPicker` | Multi-select roles+groups, search by name, chips, no system |
| `PermissionSelect` | Viewer \| Editor |
| `ImpactPreview` | Renders count summary string |
| `SyncStatusBadge` / `JobTray` | Poll multiple job ids; Retry failed |
| `FileAccessTable` | Checkbox table used by Access tab |

Place under `frontend/src/components/admin/`.

### Copy rules

| Avoid in UI | Use |
| --- | --- |
| principal | role / group |
| ACL | access |
| upsert | Add or update access |
| replace-all | Replace all access |

---

## API contract summary (12a)

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/admin/files` | + `q`, `has_acl` |
| POST | `/admin/files/acl:bulk` | FA4–FA6, C-FA2 |
| GET | `/admin/roles/{id}/file-grants` | C-FA3 |
| GET | `/admin/groups/{id}/file-grants` | C-FA3 |
| *(existing)* | single-file ACL + jobs | unchanged semantics |

### Out of scope in 12a

- `/admin/roles/{id}/members` and any membership mutate
- Users table bulk actions
- Check-access API
- Celery; changing G3/G4/G6

---

## Module layout (12a)

```
backend/app/
  api/routes/admin_acl.py          # EXTEND: bulk + file list filters
  api/routes/admin_identity.py     # EXTEND: file-grants GET on roles/groups
                                   #   OR keep file-grants on admin_acl router
                                   #   under /admin/roles|groups/... — either OK,
                                   #   prefer admin_acl or thin handlers calling file_acl_admin
  schemas/admin_acl.py             # EXTEND bulk + file-grant list schemas
  services/file_acl_admin.py       # EXTEND bulk upsert/replace/revoke helpers;
                                   #   list_file_grants_for_role/group

frontend/src/
  api/admin.ts                     # EXTEND client methods
  pages/Admin.tsx                  # wire tabs; slim panels
  pages/admin/AccessPanel.tsx      # NEW (extract from FilesAclPanel)
  pages/admin/RolesPanel.tsx       # EXTRACT + File access section
  pages/admin/GroupsPanel.tsx      # EXTRACT + File access section
  components/admin/
    PrincipalPicker.tsx
    PermissionSelect.tsx
    ImpactPreview.tsx
    JobTray.tsx
    FileAccessTable.tsx
    ManageAccessPanel.tsx
    GrantAccessModal.tsx
    RevokeAccessModal.tsx

backend/scripts/
  admin_file_access_proof.py       # NEW proofs 1–N below
```

No Alembic required unless a helpful index appears (optional `file_acl(role_id)`, `file_acl(group_id)` if missing — check before adding).

---

## Landmines (12a)

1. **Offering user-to-file grants** — forbidden (G3 / FA3).
2. **Defaulting bulk to replace** — wipe risk; default upsert (FA4).
3. **One giant transaction for 100 files** — forbidden; per-file commit (FA6).
4. **Blocking HTTP on `update_by_query`** — still enqueue + poll (G2).
5. **Client-only “bulk”** looping PUT without progress/partial handling — allowed as prototype only; ship **server bulk** for done.
6. **Starting 12b membership work** — out of scope.
7. **Forgetting refresh on OS sync** — worker already does; don’t bypass `acl_sync`.
8. **Showing system/`_empty` in pickers** — never.

---

## Proofs (12a)

Proof driver: `uv run python -m scripts.admin_file_access_proof`

| # | Test | Expect |
| --- | --- | --- |
| 1 | `POST /admin/files/acl:bulk` as searcher | 403 |
| 2 | Bulk upsert 1 role onto 2 known files as admin | 200; both in `results`; each has grant; each `acl_job_id`; jobs → succeeded; OS `allowed_roles` contains role name |
| 3 | Bulk revoke that role from same 2 files | grants gone; jobs succeeded; OS arrays updated |
| 4 | Bulk replace without `confirm_replace` | 400; no PG change |
| 5 | Bulk with `file_ids` length 101 | 400 |
| 6 | Bulk including unknown file id + one good id | good in `results`, bad in `failed` |
| 7 | `GET /admin/roles/{id}/file-grants` after grant | lists file with permission |
| 8 | `GET /admin/files?q=<basename>&has_acl=true` | filters correctly |
| 9 | Grant `_empty` / system principal in bulk | 400 before mutate |
| 10 | `/auth/admin-ping` + `/health` | 200 |
| 11 | React smoke: multi-select grant + Manage access save + role File access list | manual |

Needs ≥2 ingested files. Reuse seed users/roles from identity proofs.

---

## Tasks to perform (12a checklist)

Check a box only after that step has been **run** / verified.

### 0. Prerequisites + locks

- [ ] Confirm 6a/6b APIs live (`/admin/files`, ACL, jobs, roles/groups list)
- [ ] Read this file end-to-end; FA1–FA8 + C-FA1–C-FA7 treated as law
- [ ] Confirm **not** implementing 12b membership endpoints

### A. Backend — file_acl_admin helpers

- [ ] Add `bulk_apply(file_ids, mode, grants, confirm_replace) -> results/failed` using existing upsert/replace/delete primitives
- [ ] Add `list_grants_for_role(role_id, limit, offset)` and `list_grants_for_group(...)`
- [ ] Extend `list_all_files` with `q` and `has_acl`
- [ ] Unit/script smoke: bulk upsert two files in one call against live DB (or via proof script step)

### B. Backend — HTTP

- [ ] Schemas for bulk request/response + file-grant list
- [ ] `POST /admin/files/acl:bulk`
- [ ] `GET /admin/roles/{id}/file-grants` and `GET /admin/groups/{id}/file-grants`
- [ ] `GET /admin/files` query params
- [ ] Proofs 1–10 automated

### C. Frontend — shared pieces

- [ ] `PrincipalPicker`, `PermissionSelect`, `ImpactPreview`, `JobTray`
- [ ] `api/admin.ts`: `bulkFileAcl`, `listRoleFileGrants`, `listGroupFileGrants`, `listAdminFiles` params

### D. Frontend — Access tab

- [ ] Rename tab to **Access**
- [ ] Replace FilesAclPanel with Access table + selection + Manage access panel
- [ ] Grant access modal + Revoke access modal wired to bulk API
- [ ] Job tray / per-file sync after bulk
- [ ] Client search uses `q` (and `has_acl` if control present)

### E. Frontend — Role/Group File access

- [ ] File access section on Roles panel + Groups panel
- [ ] Grant files… modal (principal locked)
- [ ] Remove grant via existing DELETE

### F. Hygiene

- [ ] No membership APIs; no user-principal file grants; no Celery
- [ ] Proof 11 human
- [ ] Summary e.g. `prompts/summary/12a_file_access_ui.md`
- [ ] Update index `12_acl_ui.md` status → 12a done
- [ ] Do **not** mark 12b done

---

## Recommended execution order

1. Backend helpers + bulk route + proofs 1–10.
2. Shared React pickers + API client.
3. Access tab (table + manage + modals + jobs).
4. Role/Group File access section.
5. Summary → unlock **12b**.

---

## Explicitly out of scope (12a)

- Everything in `12b_member_assignment_ui.md`
- Check-access / effective permissions explorer
- Access matrix / CSV export
- Task 7 SKIP LOCKED / repair CLI
- Changing OpenSearch DLS shape or permission verbs

---

## Follow-on

| Next | Needs from 12a |
| --- | --- |
| **12b** | Stable Access UX + `PrincipalPicker` reuse; file-grants lists optional for copy |
| Task 7 | Bulk job volume may motivate SKIP LOCKED |

---

## Changelog

| Date | Change |
| --- | --- |
| 31 Aug 2026 | Created as **12a File Access UI** split from combined `12_acl_ui.md` proposal. |
