# 10a — ACL UI update (File Access UI / 12a)

**Dumped 31 August 2026.** Full record of the Admin **File Access UI** pass implemented from `prompts/cursor_summary/12a_file_access_ui.md`.

| | |
| --- | --- |
| Phase ID | **12a** (index: `prompts/cursor_summary/12_acl_ui.md`) |
| Short summary | also `prompts/summary/12a_file_access_ui.md` |
| Prerequisite | 6a identity admin + 6b single-file ACL (`8a` / `8b` summaries) |
| Sibling not done | **12b** member assignment UI |

---

## Goal

Let a realm **`admin`**:

1. Use Admin tab **Access** (renamed from “Files (ACL)”).
2. Browse files in a selectable table with name search + has-access filter; see grant summary chips per file.
3. **Manage access** on one file: roles/groups with Viewer/Editor; add/remove draft; Save (PUT replace-all); sync status.
4. Multi-select → **Grant access** / **Revoke access** → bulk API → job tray.
5. On **Roles** / **Groups**: **File access** list + **Grant files…** (principal locked) + per-row Remove.

Mental model:

```
File → who (roles/groups) can access it     = Access tab
Role/Group → which files it can access      = File access section
User → file access                          = via membership (12b), not direct ACL
```

---

## Locked decisions implemented

| ID | Decision |
| --- | --- |
| FA1 | 12a = file access only; no membership APIs / Users bulk assign |
| FA2 | Tab label **Access**; route stays `/admin` |
| FA3 | Principals = roles & groups only; no user-to-file; pickers `include_system=false`; reject system / `_empty` |
| FA4 | Bulk default **upsert**; **replace** needs `confirm_replace: true`; **revoke** matches type+id |
| FA5 | Max **100** `file_ids` per bulk request |
| FA6 | Per-file commit + enqueue; `results[]` + `failed[]`; no rollback of successes |
| FA7 | Manage Save = existing **PUT** replace-all for that file |
| FA8 | Default permission **viewer**; labels Viewer / Editor |
| C-FA1 | All new routes under `/admin/...`, `require_admin` |
| C-FA5 | Reuse existing job APIs; poll many `acl_job_id`s |
| C-FA6 | No Members tabs; no Check-access modal |
| C-FA7 | Validation 400; missing role/group for file-grants 404; enqueue fail after PG → that file in `failed[]`, HTTP 200 |

Inherited: G2 (no Celery), G3 (roles/groups only), G4 (viewer|editor), G6 (PG then OS job).

---

## Backend changes

### Service — `backend/app/services/file_acl_admin.py`

Extended (did not duplicate `acl_sync`):

| Helper | Behavior |
| --- | --- |
| `list_all_files(..., q, has_acl)` | Case-insensitive substring on `object_store_path`; `has_acl` via exists on role/group `file_acl`; returns `access_total` + up to 2 `access_preview` grants |
| `delete_grants_for_principals` | Delete by type+id; permission ignored; missing = no-op |
| `upsert_grants` | Upsert each grant on one file |
| `validate_bulk_request` | Empty/over-100 file_ids; mode rules; whole-request grant validation (**400** before mutate); dedupe ids |
| `apply_bulk_to_file` | upsert / replace / revoke for one file in current txn |
| `list_grants_for_role` / `list_grants_for_group` | Join `File`; 404 if missing/system/`_empty`; paginated; `updated_at` = ACL `created_at` |

Constants: `BULK_MAX_FILES = 100`.

Existing kept: `list_grants`, `replace_all_grants`, `upsert_one_grant`, `delete_grant`, `_validate_grant` (system/`_empty` rejection).

**No Alembic** — optional `ix_file_acl_role_id` / `group_id` skipped at current scale.

### Schemas — `backend/app/schemas/admin_acl.py`

- `AccessPreviewOut`
- `AdminFileOut` + `access_total`, `access_preview`
- `BulkAclRequest` / `BulkAclResult` / `BulkAclFailed` / `BulkAclResponse`
- `FileGrantItemOut` / `FileGrantListResponse`
- Existing grant/job schemas unchanged

### Routes — `backend/app/api/routes/admin_acl.py`

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/admin/files` | Query: `limit`, `offset`, optional `q`, `has_acl` |
| POST | `/admin/files/acl:bulk` | Body: `file_ids`, `mode`, `grants`, `confirm_replace` |
| GET | `/admin/roles/{role_id}/file-grants` | `limit`/`offset` |
| GET | `/admin/groups/{group_id}/file-grants` | `limit`/`offset` |
| GET/PUT/POST/DELETE | `/admin/files/{id}/acl…` | Unchanged single-file |
| GET/POST | `/admin/acl-jobs…` | Unchanged |

Bulk loop: validate once → per file mutate → `_bulk_commit_and_enqueue` (enqueue fail → `failed[]` entry, not HTTP 503).

Mounted via existing `app/api/router.py` (`admin_acl` after `admin_identity`).

---

## Bulk API contract

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

| Mode | Behavior |
| --- | --- |
| `upsert` | grants required non-empty; add/update named principals; leave others |
| `replace` | requires `confirm_replace: true`; full replace-all (`[]` clears); else **400** |
| `revoke` | grants required non-empty; delete matching principals; missing = no-op |

Response **200**:

```json
{
  "results": [{ "file_id": "...", "grants": [...], "acl_job_id": "..." }],
  "failed": [{ "file_id": "...", "error": "human readable" }]
}
```

---

## Frontend changes

### API client — `frontend/src/api/admin.ts`

- `listAdminFiles({ limit, offset, q, has_acl })` + `access_total` / `access_preview` on `AdminFile`
- `bulkFileAcl`, `listRoleFileGrants`, `listGroupFileGrants`
- `deleteFileAcl` (JSON body via new helper)
- Kept: `getFileAcl`, `replaceFileAcl`, `getAclJob`, `retryAclJob`

### Client helper — `frontend/src/api/client.ts`

- `apiDeleteJson<T>` for DELETE responses with JSON (ACL delete returns grants + `acl_job_id`)

### Admin shell — `frontend/src/pages/Admin.tsx`

- Slim orchestration only
- Tab **Access** (`tab === 'access'`)
- Copy: “file access” not “file ACL”

### Panels — `frontend/src/pages/admin/`

| File | Role |
| --- | --- |
| `AccessPanel.tsx` | Toolbar (search / has ACL / reload), selection, Grant/Revoke, table + Manage panel + JobTray |
| `RolesPanel.tsx` | Create/edit/delete + **File access** section |
| `GroupsPanel.tsx` | Create/delete + **File access** section |
| `UsersPanel.tsx` | Extracted only; **no** 12b membership bulk UI |

### Shared components — `frontend/src/components/admin/`

| Component | Responsibility |
| --- | --- |
| `styles.ts` | Shared `inputClass` / `labelClass`, `permissionLabel`, `formatBytes` |
| `PrincipalPicker.tsx` | Multi-select roles+groups, search, chips; optional locked principal |
| `PermissionSelect.tsx` | Viewer \| Editor |
| `ImpactPreview.tsx` | Impact summary strings for grant/revoke |
| `JobTray.tsx` / `SyncStatusBadge` | Poll job ids ~1s; Retry failed |
| `FileAccessTable.tsx` | Checkbox table + access summary + Manage |
| `ManageAccessPanel.tsx` | Right panel draft grants → Save PUT; Cancel reload |
| `GrantAccessModal.tsx` | Multi-file grant (upsert default / replace + checkbox) |
| `RevokeAccessModal.tsx` | Multi-file revoke |
| `GrantFilesModal.tsx` | From Role/Group: file multi-picker + locked principal → bulk upsert |

UI copy rules: “access” not “ACL”; “role/group” not “principal”; “Add or update access” / “Replace all access”.

---

## Proofs & verification

### Automated — `backend/scripts/admin_file_access_proof.py`

```bash
cd backend
uv run python -m scripts.admin_file_access_proof
```

| # | Expect |
| --- | --- |
| 1 | Bulk as searcher → **403** |
| 2 | Bulk upsert 1 role onto 2 files → results + jobs + OS `allowed_roles` |
| 3 | Bulk revoke → grants gone; OS updated |
| 4 | Replace without `confirm_replace` → **400**; no PG change |
| 5 | 101 `file_ids` → **400** |
| 6 | Unknown + good id → `results` / `failed` split |
| 7 | `GET .../roles/{id}/file-grants` lists file |
| 8 | `GET /admin/files?q&has_acl=true` filters |
| 9 | Grant `_empty` → **400** before mutate |
| 10 | `/health` + `/auth/admin-ping` → **200** |

**Status (31 Aug 2026):** proofs 1–10 passed against live stack (≥2 ingested files). Frontend `bun run build` clean.

### Human — proof 11 + UI guide

**Accounts (local seed):**

| User | Password | Expect |
| --- | --- | --- |
| `realm-admin` | `adminpass` | Admin + Access |
| `searcher` | `searcherpass` | No Admin ACL |

**Prereqs:** `docker compose up -d`, `./start-dev.sh`, http://localhost:5173, ≥2 files ingested.

**Checklist:**

1. **Access tab** — label Access; checkbox table with Access summary / Sync / Manage.
2. **Search / filter** — `q` narrows; Has access Yes/No; Reload.
3. **Manage access** — add role/group + Viewer → Save access → sync succeeded; summary chips update; Cancel reloads draft.
4. **Bulk grant** — select 2+ files → Grant access… → Add or update → Confirm → Job tray; optional Replace requires warning checkbox.
5. **Bulk revoke** — same selection → Revoke → Confirm → summaries toward “No access”.
6. **Roles File access** — select role → list grants → Grant files… → Remove row.
7. **Groups File access** — same for a group.
8. **Negative** — searcher cannot use Admin ACL; pickers hide system/`_empty`.

---

## Explicitly out of scope (this dump)

- Everything in `12b_member_assignment_ui.md` (membership APIs, Users bulk “Add to…”)
- Check-access / effective permissions explorer
- Access matrix / CSV export
- Celery / Redis; changing OpenSearch DLS
- User-principal file ACL in product UI
- Alembic indexes on `file_acl(role_id|group_id)`
- Task 7 SKIP LOCKED / repair CLI

---

## Follow-on

| Next | Needs from this update |
| --- | --- |
| **12b** | Stable Access UX + reuse `PrincipalPicker` |
| Task 7 | Bulk job volume may motivate SKIP LOCKED |

Index status: `prompts/cursor_summary/12_acl_ui.md` → 12a **Done**, 12b still plan-ready.

---

## File inventory (touched / added)

```
backend/app/services/file_acl_admin.py          # EXTEND
backend/app/schemas/admin_acl.py                # EXTEND
backend/app/api/routes/admin_acl.py             # EXTEND
backend/scripts/admin_file_access_proof.py      # NEW

frontend/src/api/admin.ts                       # EXTEND
frontend/src/api/client.ts                      # EXTEND apiDeleteJson
frontend/src/pages/Admin.tsx                    # SLIM + Access tab
frontend/src/pages/admin/AccessPanel.tsx        # NEW
frontend/src/pages/admin/RolesPanel.tsx         # NEW (+ File access)
frontend/src/pages/admin/GroupsPanel.tsx        # NEW (+ File access)
frontend/src/pages/admin/UsersPanel.tsx         # NEW (extract)
frontend/src/components/admin/styles.ts         # NEW
frontend/src/components/admin/PrincipalPicker.tsx
frontend/src/components/admin/PermissionSelect.tsx
frontend/src/components/admin/ImpactPreview.tsx
frontend/src/components/admin/JobTray.tsx
frontend/src/components/admin/FileAccessTable.tsx
frontend/src/components/admin/ManageAccessPanel.tsx
frontend/src/components/admin/GrantAccessModal.tsx
frontend/src/components/admin/RevokeAccessModal.tsx
frontend/src/components/admin/GrantFilesModal.tsx

prompts/summary/12a_file_access_ui.md           # short summary
prompts/summary/10a_acl_ui_update.md            # this dump
prompts/cursor_summary/12_acl_ui.md             # status → 12a done
```
