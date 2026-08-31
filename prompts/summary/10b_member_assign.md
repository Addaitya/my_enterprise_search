# 10b — Member Assignment UI (12b)

**Implemented 31 August 2026.** Source of truth: `prompts/cursor_summary/12b_member_assignment_ui.md`. Index: `prompts/cursor_summary/12_acl_ui.md`. Sibling **12a** (file access) is done — see `prompts/summary/12a_file_access_ui.md` / `10a_acl_ui_update.md`.

| | |
| --- | --- |
| Phase ID | **12b** |
| Prerequisite | 12a Access tab + bulk file grants; 6a identity APIs |
| Out of scope | File ACL changes, Check-access explorer, role/group rename, hard delete users |

---

## Goal

Let a realm **`admin`**:

1. Open a **role** or **group** and see a **Members** list.
2. **Add members** (multi-select users) — additive only.
3. **Remove members** (one or many) with MA4 safety (`search-user` and/or `admin` must remain).
4. On **Users** table: multi-select → **Add to role…** / **Add to group…**.
5. User create/edit: chip multi-select for roles/groups (still PATCH replace).
6. After membership changes, show notice that users must **re-login / refresh token** before search JWT roles/groups update (MA7).

Mental model:

```
Role/Group → who is a member          = Members section (12b)
Users → bulk add to role/group        = Users selection bar (12b)
File → who (roles/groups) can access  = Access tab (12a, unchanged)
```

---

## Locked decisions implemented

| ID | Decision |
| --- | --- |
| MA1 | Identity membership only; no new file ACL endpoints |
| MA2 | Both Role/Group→Members and Users→bulk Add |
| MA3 | Add additive; remove subtractive; never replace via member APIs |
| MA4 | After role remove, remaining must include `search-user` and/or `admin` → else `failed[]` |
| MA5 | Per user: Keycloak first, then Postgres mirror |
| MA6 | Max **100** `user_ids` per request → **400** |
| MA7 | UI notice: re-login/refresh before search reflects membership |
| C-MA1 | `require_admin`; non-admin **403** |
| C-MA2 | GET members with `q` / limit / offset |
| C-MA3 | POST add → `results[]` + `failed[]` |
| C-MA4 | `POST .../members:remove` (not DELETE-with-body) |
| C-MA5 | Members sections + Users bulk + chips; Check-access out |
| C-MA6 | Validation 400; missing 404; partial success HTTP 200 |

---

## Backend changes

### Keycloak — `backend/app/services/keycloak_admin.py`

| Helper | Behavior |
| --- | --- |
| `add_user_realm_role(user_id, role_name)` | POST role-mapping if absent; no-op if present |
| `remove_user_realm_role(user_id, role_name)` | DELETE mapping if present |
| `join_user_group(user_id, group_name)` | PUT group; leaves `_empty` when joining product group |
| `leave_user_group(user_id, group_name)` | DELETE group; joins `_empty` if no product groups left |

Existing `replace_user_*` unchanged (still used by create/PATCH user).

### Identity service — `backend/app/services/identity_admin.py`

| Method | Behavior |
| --- | --- |
| `list_role_members` / `list_group_members` | PG join `user_roles` / `user_groups` → `UserOut`; `q` on username/email |
| `add_users_to_role` / `remove_users_from_role` | Per-user KC then PG; collect `failed[]` |
| `add_users_to_group` / `remove_users_from_group` | Same; reject `_empty` / system group whole-request **400** |
| `_normalize_user_ids` | Dedupe; empty → 400; >100 → 400 |
| MA4 | On role remove, check remaining product roles before KC mutate |

Group leave with no remaining product groups mirrors `_empty` in PG (matches KC helper).

### Schemas — `backend/app/schemas/admin_identity.py`

- `MEMBERS_MAX_USERS = 100`
- `MembersMutationRequest` — `user_ids: list[UUID]` (min 1; max enforced in service for HTTP 400)
- `MembersFailed` / `MembersMutationResponse`

### Routes — `backend/app/api/routes/admin_identity.py`

| Method | Path |
| --- | --- |
| GET | `/admin/roles/{role_id}/members` |
| POST | `/admin/roles/{role_id}/members` |
| POST | `/admin/roles/{role_id}/members:remove` |
| GET | `/admin/groups/{group_id}/members` |
| POST | `/admin/groups/{group_id}/members` |
| POST | `/admin/groups/{group_id}/members:remove` |

All `require_admin`. List response reuses `UserListResponse`.

**No Alembic.** No file ACL changes.

---

## Frontend changes

### API client — `frontend/src/api/admin.ts`

- `listRoleMembers` / `addRoleMembers` / `removeRoleMembers`
- `listGroupMembers` / `addGroupMembers` / `removeGroupMembers`
- `MembersMutationResponse` type

### New components — `frontend/src/components/admin/`

| File | Role |
| --- | --- |
| `UserPicker.tsx` | Async search `/admin/users?q=`, multi chips |
| `RolePicker.tsx` | Chip multi (or single for bulk) |
| `GroupPicker.tsx` | Chip multi/single; excludes `is_system` / `_empty` |
| `AddMembersModal.tsx` | Add users to one role/group |
| `BulkAddToPrincipalModal.tsx` | Selected users → one role or group |
| `MembersSection.tsx` | Search + table + add/remove for Roles/Groups panels |

`ImpactPreview`: `buildAddMembersImpact`, `TOKEN_REFRESH_NOTICE`.

### Panels

| File | Change |
| --- | --- |
| `RolesPanel.tsx` | Stacked **Members** above existing File access |
| `GroupsPanel.tsx` | Same; system/`_empty` Members not manageable |
| `UsersPanel.tsx` | Chip Role/Group pickers; row checkboxes; sticky **Add to role/group…** bar |

---

## Proofs

Driver: `backend/scripts/admin_member_assignment_proof.py`

```bash
cd backend
uv run python -m scripts.admin_member_assignment_proof
```

| # | Test | Result (31 Aug 2026) |
| --- | --- | --- |
| 1 | GET role members as searcher | **403** |
| 2 | Create 2 users (`search-user`); POST add to `engineering` | **200**; KC+PG agree |
| 3 | Re-add same users | **200** no-op |
| 4 | `members:remove` from engineering | Removed; still have `search-user` |
| 5 | Remove last `search-user` | User in `failed[]`; role kept |
| 6 | Add to `_empty` | **400** |
| 7 | 101 `user_ids` | **400** |
| 8 | Unknown + good id | Partial `results`/`failed` |
| 9 | `/health` + `/auth/admin-ping` | **200** |
| 10 | React smoke | **Human** — see guide below |

All automated proofs **1–9 passed** against live stack.

---

## Human test guide (proof 10)

Prerequisites: `./start-dev.sh` (or stack) up; login as realm **admin**.

### A. Roles → Members

1. Open `/admin` → **Roles**.
2. Click a product role (e.g. `search-user` or a custom role).
3. Confirm **Members** section appears above **File access**.
4. **Add members…** → search/select ≥2 users → Confirm.
5. Expect green notice: `Added N users to {role}. Failed: 0.` plus re-login sentence.
6. Members table lists those users.
7. Select one row → **Remove selected…** → confirm gone.
8. For a user who only has `search-user`: open Members on role `search-user` → Remove that user → expect failed / error toast; user still has the role after Reload.

### B. Groups → Members

1. **Groups** → select `engineering` (or another product group).
2. Add members / remove members same as roles.
3. System / `_empty` (if ever selected): Members manage disabled / not usable.

### C. Users bulk + chips

1. **Users** tab: create/edit form shows **chip** Role/Group pickers (not checkbox walls).
2. Check ≥2 users → sticky bar **Add to role…** / **Add to group…**.
3. Pick target → Confirm → notice includes re-login text; reload table shows new membership.
4. Clear selection; edit one user with chips; Save still uses PATCH replace.

### D. Token freshness

1. As an affected non-admin user: **re-login** (or wait for token refresh).
2. `GET /auth/me` (or UI) shows updated `roles` / `groups`.
3. Do **not** expect search ACL visibility to change until JWT refreshes.

### E. Auth

1. As `search-user` (non-admin): member list/add/remove endpoints → **403** (proof 1 covers GET).

---

## Landmines honored

1. No PG-first membership writes.
2. Member add does not call `replace_user_*` / `_replace_pg_memberships`.
3. Removing last `search-user|admin` fails that user only.
4. `_empty` rejected for member manage.
5. UI does not claim instant search ACL update.
6. No client-only loop of PATCH replace for bulk assign.
7. No 12a file ACL rework.
8. No hard delete users.

---

## Files touched

### Backend

- `backend/app/services/keycloak_admin.py`
- `backend/app/services/identity_admin.py`
- `backend/app/schemas/admin_identity.py`
- `backend/app/api/routes/admin_identity.py`
- `backend/scripts/admin_member_assignment_proof.py` (new)

### Frontend

- `frontend/src/api/admin.ts`
- `frontend/src/pages/admin/RolesPanel.tsx`
- `frontend/src/pages/admin/GroupsPanel.tsx`
- `frontend/src/pages/admin/UsersPanel.tsx`
- `frontend/src/components/admin/UserPicker.tsx` (new)
- `frontend/src/components/admin/RolePicker.tsx` (new)
- `frontend/src/components/admin/GroupPicker.tsx` (new)
- `frontend/src/components/admin/AddMembersModal.tsx` (new)
- `frontend/src/components/admin/BulkAddToPrincipalModal.tsx` (new)
- `frontend/src/components/admin/MembersSection.tsx` (new)
- `frontend/src/components/admin/ImpactPreview.tsx`

### Docs

- `prompts/summary/10b_member_assign.md` (this file)
- `prompts/cursor_summary/12_acl_ui.md` (status → 12b Done)

---

## Follow-on (unchanged)

| Item | Notes |
| --- | --- |
| Check access API/UI | `GET /admin/access/check?user_id=&file_id=` |
| Effective file count on user row | Convenience |
| Audit CSV | Optional |
| Task 7 | Repair + SKIP LOCKED |

---

## Changelog

| Date | Change |
| --- | --- |
| 31 Aug 2026 | Implemented 12b end-to-end; proofs 1–9 green; human guide for proof 10. |
