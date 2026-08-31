# 12a — File Access UI

**Implemented 31 August 2026.** Source of truth: `prompts/cursor_summary/12a_file_access_ui.md`. Sibling **12b** (member assignment) is **not** started.

Builds on 6b admin ACL (`prompts/summary/8b_admin_panel.md`): single-file PUT/POST/DELETE + `acl_sync_jobs` unchanged; this pass adds bulk grant/revoke, principal→file lists, Access tab UX, and Role/Group File access sections.

---

## What shipped

### Backend

| Piece | Location |
| --- | --- |
| Helpers | `backend/app/services/file_acl_admin.py` — `list_all_files(q, has_acl)` + access preview; `validate_bulk_request` / `apply_bulk_to_file`; `delete_grants_for_principals`; `list_grants_for_role` / `list_grants_for_group` |
| Schemas | `backend/app/schemas/admin_acl.py` — bulk + file-grant list + `access_preview` on files |
| Routes | `backend/app/api/routes/admin_acl.py` |

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/admin/files` | + optional `q`, `has_acl`; `access_total` / `access_preview` |
| POST | `/admin/files/acl:bulk` | upsert / replace / revoke; max 100; per-file commit + enqueue |
| GET | `/admin/roles/{id}/file-grants` | paginated |
| GET | `/admin/groups/{id}/file-grants` | paginated |
| *(existing)* | single-file ACL + jobs | unchanged |

Locks honored: roles/groups only; system/`_empty` → whole-request **400** before mutate; replace needs `confirm_replace`; partial `results[]`/`failed[]`; no Celery; no membership APIs.

### Frontend

| Piece | Location |
| --- | --- |
| API client | `frontend/src/api/admin.ts` (+ `apiDeleteJson` in `client.ts`) |
| Admin shell | `frontend/src/pages/Admin.tsx` — tab **Access** (was Files (ACL)) |
| Panels | `pages/admin/AccessPanel.tsx`, `RolesPanel.tsx`, `GroupsPanel.tsx`, `UsersPanel.tsx` |
| Components | `frontend/src/components/admin/*` — PrincipalPicker, PermissionSelect, ImpactPreview, JobTray, FileAccessTable, ManageAccessPanel, Grant/Revoke/GrantFiles modals |

### Proofs

`backend/scripts/admin_file_access_proof.py` — proofs **1–10** automated (passed against live stack).

```bash
cd backend
uv run python -m scripts.admin_file_access_proof
```

**Proof 11 (human):** multi-select Grant access, Manage access Save, Role/Group File access list + Grant files…

---

## Explicitly out of scope (still)

- 12b membership APIs / Users bulk “Add to role/group”
- Check-access explorer
- Alembic indexes on `file_acl(role_id|group_id)` (skipped; optional later)
- Celery / DSL changes

---

## Follow-on

| Next | Needs from 12a |
| --- | --- |
| **12b** | Stable Access UX + `PrincipalPicker` reuse |
| Task 7 | Bulk job volume may motivate SKIP LOCKED |
