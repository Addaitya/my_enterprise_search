# 12b — Member Assignment UI

Working notes to implement **Member Assignment UI** (Admin ACL UX pass 2). Sibling: **`12a_file_access_ui.md`** (file grants). Index: **`12_acl_ui.md`**.

**Prerequisite:** **12a done** (Access tab + bulk file grants live). 6a identity APIs live. Do **not** rework bulk file ACL in this pass except tiny reuse of pickers.

This file is the source of truth for **multi-user → role/group assignment**, **Role/Group Members tabs**, and **Users table bulk “Add to role/group”**. Do not invent per-user `file_acl`, rename roles/groups, or hard-delete users.

**Agent rules while implementing**
- Run and execute code to confirm it works before moving on.
- Do not proceed past a broken step; fix it first.
- Where something cannot be verified in this environment, leave a clear human check and wait for feedback.
- Do **not** expand file ACL bulk semantics (that is **12a**).
- Treat **Locked decisions** in this file as law.
- Membership writes stay **Keycloak first, then Postgres** (G5). Reuse `keycloak_admin` / `identity_admin`.

**Human locks (31 Aug 2026):** MA1–MA7, C-MA1–C-MA6 locked as written below.

---

## What “done” means

A signed-in realm **`admin`** can:

1. Open a **role** or **group** and see a **Members** list (users who currently have that role/group).
2. **Add members**: multi-select users → confirm → all selected users gain that role/group.
3. **Remove members**: remove one or many users from that role/group (with safety rules below).
4. On **Users** table: multi-select users → **Add to role…** / **Add to group…** → pick target → confirm.
5. Keep existing single-user create/edit; improve role/group fields to chip multi-select (reuse picker pattern from 12a if present).
6. After membership changes, UI shows a clear notice that **users must re-login / refresh token** before search JWT `roles`/`groups` update.

| Actor | What they may do in 12b |
| --- | --- |
| FastAPI | Role/group member list + add/remove — `require_admin` |
| React `/admin` | Members tabs + Users bulk bar |
| Keycloak | Membership mappings via service account |
| Postgres | Mirror `user_roles` / `user_groups` |
| OpenSearch / `file_acl` | **Unchanged** in 12b |

---

## Current state (do not re-scaffold)

From 6a:

- Membership only via `POST/PATCH /admin/users` with full `role_names` / `group_names` **replace**.
- Roles/Groups UI: create / description / delete — **no members list**.
- Users UI: edit one user; checkbox walls for roles/groups.

Pain: cannot answer “who is in `engineering`?” without scanning all users; cannot assign 10 users to a group in one action.

---

## Locked decisions (12b)

### MA1. Phase boundary

| | |
| --- | --- |
| Status | **LOCKED** |
| Decision | **12b = identity membership UX only.** No new file ACL endpoints. May reuse `PrincipalPicker`-style UX for role/group chips on the user form. |

### MA2. Direction of assignment

| | |
| --- | --- |
| Status | **LOCKED** |
| Decision | Support **both**:
| | 1. Role/Group → **Members** (add/remove users)
| | 2. Users table → bulk **Add to role/group**
| | Single-user edit remains replace-oriented via existing PATCH. |

### MA3. Add is additive; remove is subtractive

| | |
| --- | --- |
| Status | **LOCKED** |
| Decision | Member **POST add** only **adds** the target role/group to each user (does not strip other roles/groups). Member **DELETE remove** only removes that membership. Never replace the user’s full role set unless using existing user PATCH. |

### MA4. Safety constraints on remove

| | |
| --- | --- |
| Status | **LOCKED** |
| Decision | After any remove, each affected user must still have **`search-user` and/or `admin`** among remaining realm roles (same rule as C2/C3 create/update). If remove would violate → that user goes to `failed[]` (or whole request **400** if validating up front for a single-user remove). Prefer **per-user failed** for bulk. Cannot remove memberships from system-only edge cases incorrectly — never assign/remove `_empty` via these APIs. |

### MA5. Dual-write order

| | |
| --- | --- |
| Status | **LOCKED** |
| Decision | For each user: **Keycloak membership update first**, then Postgres mirror. KC fail → no PG change for that user. KC ok + PG fail → compensate or **503**-style failed entry with orphan guidance (same spirit as 6a G5). Process users independently in bulk (partial success OK). |

### MA6. Bulk size cap

| | |
| --- | --- |
| Status | **LOCKED** |
| Decision | Max **`100`** `user_ids` per add/remove request. Over → **400**. |

### MA7. Token freshness notice

| | |
| --- | --- |
| Status | **LOCKED** |
| Decision | After successful membership changes, UI **must** show notice: search/list ACL visibility for those users updates on **next token** (re-login or refresh). Do not claim instant search change. |

### C-MA1. Auth

| | |
| --- | --- |
| Status | **LOCKED** |
| Decision | `/admin/...`, `require_admin`. Non-admin **403**. |

### C-MA2. List members

| | |
| --- | --- |
| Status | **LOCKED** |

```http
GET /admin/roles/{role_id}/members?limit=50&offset=0&q=
GET /admin/groups/{group_id}/members?limit=50&offset=0&q=
```

Response:

```json
{
  "items": [
    {
      "id": "<user uuid>",
      "username": "alice",
      "email": "a@x.com",
      "enabled": true,
      "role_names": ["search-user"],
      "group_names": ["engineering"]
    }
  ],
  "total": 3,
  "limit": 50,
  "offset": 0
}
```

- Missing role/group → **404**.
- `q` filters username/email (same style as user list).
- System role `admin` / `search-user` members lists are allowed (admins need them).
- Do not expose `_empty` group members API as a management target: GET on `_empty` → **404** or **400**.

### C-MA3. Add members

| | |
| --- | --- |
| Status | **LOCKED** |

```http
POST /admin/roles/{role_id}/members
POST /admin/groups/{group_id}/members
```

Request:

```json
{ "user_ids": ["<uuid>", "<uuid>"] }
```

Response **200**:

```json
{
  "results": [ /* UserOut for each success */ ],
  "failed": [ { "user_id": "<uuid>", "error": "…" } ]
}
```

Rules:

- Empty `user_ids` → **400**.
- Dedupe ids.
- Unknown user → `failed`.
- User already has membership → success no-op (still in `results`).
- Target is system-forbidden group `_empty` → **400** whole request.
- Adding role `admin` / `search-user` is allowed.

### C-MA4. Remove members

| | |
| --- | --- |
| Status | **LOCKED** |

```http
DELETE /admin/roles/{role_id}/members
DELETE /admin/groups/{group_id}/members
```

Request body (same JSON as add):

```json
{ "user_ids": ["<uuid>"] }
```

(FastAPI: use body on DELETE or offer `POST .../members:remove` if clients struggle — **prefer** `POST /admin/roles/{id}/members:remove` with same body if DELETE-with-body is awkward; pick one and document in OpenAPI. **Locked preference:** `POST .../members:remove` for practicality.)

**Final locked paths:**

```http
POST /admin/roles/{role_id}/members:remove
POST /admin/groups/{group_id}/members:remove
```

Same request/response shape as add. Apply MA4 safety.

### C-MA5. Frontend scope (12b)

| | |
| --- | --- |
| Status | **LOCKED** |
| Decision | Roles + Groups **Members** tab/section; Users table selection bar; chip multi-select on user form. No Check-access product unless time left — **default out of scope** (see Follow-on). |

### C-MA6. Errors

| | |
| --- | --- |
| Status | **LOCKED** |
| Decision | Validation → **400**. Missing role/group → **404**. Per-user KC/constraint failures → `failed[]` with HTTP **200** when any processing occurred. All ids invalid / empty → **400**. |

---

## Architecture (12b)

```
React /admin — Roles/Groups Members | Users bulk bar
  │ Bearer admin JWT
  ▼
FastAPI /admin/roles|groups/.../members*
  → identity_admin / keycloak_admin
       KC role-mapping or group membership
       then PG user_roles / user_groups
```

```
Sources of truth
────────────────────────────────
Membership     → Keycloak (PG mirror)
File visibility→ unchanged until JWT refreshes + existing file grants (12a)
```

---

## UI specification (unambiguous)

### Roles panel — Members section

When viewing a role (select row / detail):

```
[ Overview ]  [ Members ]  [ File access ]   ← File access already from 12a
```

If tabs are heavy, use stacked sections: Overview, then Members, then File access. **Must** have a dedicated Members block.

**Members block:**

1. Search box (`q`) + Reload.
2. Table: username | email | enabled | roles summary | groups summary | Remove.
3. Toolbar: **Add members…**
4. Multi-select rows → **Remove selected…** (confirm dialog listing usernames).

**Add members modal:**

1. Title: `Add members to role {name}`.
2. `UserPicker` multi-select (search `/admin/users?q=`).
3. Impact preview: `Add role search-user to N users.`
4. Confirm → `POST .../members` → show results + failed + MA7 notice.

**Remove confirm:**

- Warn if removing `admin` or `search-user` from users who might lose required role (server enforces; show server errors in failed list).

### Groups panel — Members section

Same as roles, targeting group APIs. Ban managing `_empty` (hide system groups from picker; if shown, disable Members manage).

### Users panel upgrades

1. Replace role/group **checkbox walls** with chip multi-select (same data: `role_names` / `group_names` on create/update). Still uses existing create/PATCH APIs.
2. Table: add checkbox column.
3. When selection > 0, sticky bar:
   - **Add to role…** → RolePicker (single role) → confirm → `POST /admin/roles/{id}/members` with selected user ids.
   - **Add to group…** → GroupPicker (single group) → confirm → group members POST.
4. Do **not** implement bulk remove-from-all-roles in v1 (too dangerous). Remove stays on Members section.

### UserPicker / RolePicker / GroupPicker

| Component | Behavior |
| --- | --- |
| `UserPicker` | Async search, multi, chips, shows username+email |
| `RolePicker` | Single or multi as needed; `include_system=false` for file-adjacent; for membership **allow** assigning `search-user` / `admin` (include those product roles). Exclude technical KC composites not in PG mirror. |
| `GroupPicker` | Exclude `_empty` / `is_system=true` |

Reuse 12a patterns where possible.

### Copy

| Event | Message |
| --- | --- |
| Add success | `Added N users to {role\|group}. Failed: K.` |
| After any success | `Users must refresh their session (re-login) before search reflects new roles/groups.` |

---

## API contract summary (12b)

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/admin/roles/{id}/members` | list + q |
| POST | `/admin/roles/{id}/members` | add |
| POST | `/admin/roles/{id}/members:remove` | remove |
| GET | `/admin/groups/{id}/members` | list + q |
| POST | `/admin/groups/{id}/members` | add |
| POST | `/admin/groups/{id}/members:remove` | remove |

Existing user PATCH replace remains for single-user edit.

### Out of scope in 12b

- File ACL bulk changes
- Check-access explorer (follow-on)
- Bulk disable users
- Role/group rename; hard delete users
- Mapping new roles to OpenSearch `files_searcher` (still need `search-user`)

---

## Module layout (12b)

```
backend/app/
  api/routes/admin_identity.py     # EXTEND member list/add/remove
  schemas/admin_identity.py        # EXTEND member payloads
  services/identity_admin.py       # EXTEND add/remove role|group for many users
  services/keycloak_admin.py       # EXTEND helpers if missing (role mapping / group join)

frontend/src/
  api/admin.ts                     # EXTEND member client calls
  pages/admin/RolesPanel.tsx       # Members section
  pages/admin/GroupsPanel.tsx      # Members section
  pages/admin/UsersPanel.tsx       # chips + bulk bar
  components/admin/
    UserPicker.tsx
    RolePicker.tsx                 # if not already
    GroupPicker.tsx
    AddMembersModal.tsx
    BulkAddToPrincipalModal.tsx

backend/scripts/
  admin_member_assignment_proof.py
```

No Alembic expected.

---

## Landmines (12b)

1. **PG-first membership** — forbidden; KC first (MA5 / G5).
2. **Replace-all via “add members”** — forbidden; additive only (MA3).
3. **Removing last of search-user|admin** — must fail that user (MA4).
4. **Assigning `_empty`** — reject.
5. **Claiming search updates immediately** — false; show MA7 notice.
6. **Client-only loop of PATCH replace** as the shipped bulk path — races/clobbers; ship dedicated add/remove APIs.
7. **Re-opening 12a bulk ACL** — out of scope unless bugfix.
8. **Deleting users** — still no hard delete (G8).

---

## Proofs (12b)

Proof driver: `uv run python -m scripts.admin_member_assignment_proof`

| # | Test | Expect |
| --- | --- | --- |
| 1 | `GET /admin/roles/{id}/members` as searcher | 403 |
| 2 | Create 2 users with `search-user` only; `POST` add both to group `engineering` | 200; both in group members list; KC+PG agree |
| 3 | `POST` add same users again | 200 no-op success |
| 4 | `POST members:remove` both from `engineering` | removed; still have `search-user` |
| 5 | User with only `search-user`; remove `search-user` via members:remove | that user in `failed`; still has role |
| 6 | Add users to `_empty` | 400 |
| 7 | `user_ids` length 101 | 400 |
| 8 | Unknown user id mixed with good | good in results, bad in failed |
| 9 | `/auth/admin-ping` + `/health` | 200 |
| 10 | React smoke: Members add/remove + Users bulk Add to group + re-login notice | manual |

---

## Tasks to perform (12b checklist)

Check a box only after that step has been **run** / verified.

### 0. Prerequisites + locks

- [ ] Confirm **12a** Access tab + bulk file grants done (or explicitly waived by human)
- [ ] Confirm 6a `identity_admin` / `keycloak_admin` patterns
- [ ] Read this file; MA1–MA7 + C-MA1–C-MA6 as law
- [ ] Confirm **not** changing file ACL bulk APIs

### A. Keycloak + identity service

- [ ] Helpers: list users with role X / in group Y (prefer PG mirror join for list; verify against KC if needed)
- [ ] Helpers: add realm role to user; remove realm role; join group; leave group
- [ ] `identity_admin.add_users_to_role`, `remove_users_from_role`, same for group — per-user KC then PG; collect failed
- [ ] Enforce MA4 on remove

### B. HTTP API

- [ ] Schemas + routes for list/add/remove (C-MA2–C-MA4)
- [ ] Proofs 1–9 automated

### C. Frontend — Members

- [ ] Roles Members section + Add/Remove modals
- [ ] Groups Members section + Add/Remove modals
- [ ] MA7 notice after success

### D. Frontend — Users bulk + chips

- [ ] Chip multi-select on create/edit user form
- [ ] Users table checkboxes + Add to role/group bulk bar
- [ ] Wire to member APIs

### E. Hygiene

- [ ] No file ACL changes; no `_empty`; no hard delete
- [ ] Proof 10 human
- [ ] Summary e.g. `prompts/summary/12b_member_assignment_ui.md`
- [ ] Update index `12_acl_ui.md` status → 12b done

---

## Recommended execution order

1. Identity service add/remove + list members via PG.
2. HTTP + proofs 1–9.
3. Roles/Groups Members UI.
4. Users bulk bar + chip form.
5. Summary.

---

## Explicitly out of scope (12b)

- Everything exclusive to `12a_file_access_ui.md` (except consuming File access section already shipped)
- Check-access / “why can user see file?” explorer
- Access matrix / CSV
- Task 7 job fleet hardening
- Auto-ACL on upload; user-principal file grants

---

## Follow-on (after 12a + 12b)

| Item | Notes |
| --- | --- |
| Check access API/UI | `GET /admin/access/check?user_id=&file_id=` — explain via roles/groups + grants |
| Effective file count on user row | Convenience |
| Audit CSV | Optional compliance |
| Task 7 | Repair + SKIP LOCKED |

---

## Changelog

| Date | Change |
| --- | --- |
| 31 Aug 2026 | Created as **12b Member Assignment UI** split from combined `12_acl_ui.md` proposal. |
