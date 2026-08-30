# Admin panel 6a — Identity (users / roles / groups)

Working notes to implement **Task 6a (Admin identity)** from `prompts/cursor_summary/2_project_overview_tasks.md` Task 6. Sibling plan: **`9b_admin_panel.md`** (file ACL + OpenSearch sync jobs). Index: `9_admin_panel.md`.

Auth is live (`prompts/summary/2_auth_layer.md`). Postgres identity mirror exists (`prompts/summary/3_data_modeling.md`). Search + View/Open are live (`prompts/summary/7_search_view_api.md`). This file is the source of truth for the **identity** half only. Do not invent a second ACL model, start file ACL / `acl_sync_jobs`, auto-grant on upload, or FastAPI-side embeddings.

**Agent rules while implementing**
- Run and execute code to confirm it works before moving on.
- Do not proceed past a broken step; fix it first.
- Where something cannot be verified in this environment, leave a clear human check and wait for feedback.
- Do **not** implement file ACL assign, `update_by_query` progress UI, `acl_sync_jobs`, or OpenSearch ACL denorm (that is **9b**).
- Treat **Locked decisions** in this file as law.
- Reuse Keycloak Admin patterns from `init_services/keycloak.py`; product code lives under `app/services/keycloak_admin.py` (importable without running init).

**Human locks (30 Aug 2026):** G1 = split into 9a / 9b. G5, G7, G8 locked. C1–C5, C9–C10 (identity tabs), C12 (identity errors) locked. C2/C3: permanent password (`temporary=false`).

---

## What “done” means

A signed-in realm **`admin`** can:

1. **List / create / update** users, realm roles, and groups via FastAPI.
2. Each write hits **Keycloak Admin API first**, then upserts the **Postgres mirror** (compensate if PG fails after KC success).
3. React `/admin` shows **Users | Roles | Groups** (Files/ACL tab may stay placeholder until 9b).
4. **Non-admin** → **403** on `/admin/users*`, `/admin/roles*`, `/admin/groups*`.

| Actor | What they may do in 6a |
| --- | --- |
| FastAPI | `/admin/users*`, `/admin/roles*`, `/admin/groups*` — `require_admin` |
| React `/admin` | Users, Roles, Groups sections |
| Keycloak | Create/update via **service-account** `api-client` |
| Postgres | Identity mirror upsert only |
| OpenSearch | **Unchanged** (no ACL writes in 6a) |
| `init_services` | Identity mirror remains recovery path if PG drifts |

**Not done in 6a:** making uploads searchable; file privilege UI; ACL sync jobs.

---

## Current state (do not re-scaffold)

- `require_admin` + `GET /auth/admin-ping`; React `AdminRoute`; `/admin` placeholder.
- Tables: `users`, `roles`, `groups`, `user_roles`, `user_groups` (Keycloak UUIDs as PKs); `is_system` on roles/groups.
- `init_services/identity_sync.py` one-way KC → PG. Keycloak wins on disagreement.
- Seed: `realm-admin` (`admin`+`search-user`, `engineering`); `searcher` (`search-user`, `_empty`).
- Request auth stays on **JWT**. Do not resolve roles from Postgres for authz.
- No `/admin/*` product routes beyond `admin-ping`.

---

## Dependency map (6a)

```
Keycloak Admin API ◄── create/update user|role|group|membership
        │
        ▼
Postgres mirror (users/roles/groups/memberships)
```

JWT role/group claims update on next login/token after membership changes. File search visibility is **unchanged** until 9b grants + OS sync.

---

## Locked decisions (relevant to 6a)

### G1. Split

| | |
| --- | --- |
| Status | **LOCKED** |
| Decision | Task 6 is two plans: **9a identity** then **9b ACL+jobs**. Flip overview Task 6 only when both complete. |

### G5. Dual-write order — identity

| | |
| --- | --- |
| Status | **LOCKED** |
| Decision | **Keycloak first, then Postgres.** KC fail → no PG write. KC ok + PG fail → compensate KC delete/rollback when safe; else **503** + “orphan in Keycloak — re-run identity mirror”. Never leave PG ahead of KC on creates. Membership replace: set KC mappings, then replace `user_roles` / `user_groups`. |

### G7. Role / group rename

| | |
| --- | --- |
| Status | **LOCKED** |
| Decision | **Forbid rename** (`name` immutable). PATCH role `description` only. |

### G8. User delete

| | |
| --- | --- |
| Status | **LOCKED** |
| Decision | **No hard delete.** `enabled=false` (KC disable + PG). Role/group delete: only if no `file_acl` refs (`ON DELETE RESTRICT`) → else **409**; no system/`_empty` delete. |

### C1. Prefix + auth

| | |
| --- | --- |
| Status | **LOCKED** |
| Decision | `/admin/...`, `require_admin`. Non-admin **403**; unauthenticated **401**. |

### C2. Create user

| | |
| --- | --- |
| Status | **LOCKED** |

```json
{
  "username": "alice",
  "email": "alice@example.com",
  "password": "ChangeMe!",
  "enabled": true,
  "role_names": ["search-user"],
  "group_names": ["engineering"]
}
```

- Username required, unique. Email optional.
- Require ≥1 of `search-user` \| `admin` in `role_names`.
- Never assign group `_empty` via API.
- Password: KC reset-password with **`temporary=false`** (permanent). No self-service change-password.
- Response DTO never includes password.

### C3. Update user

| | |
| --- | --- |
| Status | **LOCKED** |
| Decision | PATCH: `email`, `enabled`, `role_names` (replace), `group_names` (replace), optional `password` (`temporary=false`). Username immutable. |

### C4. Create role / group

| | |
| --- | --- |
| Status | **LOCKED** |

```json
// POST /admin/roles
{ "name": "finance", "description": "Finance readers" }

// POST /admin/groups
{ "name": "finance-team" }
```

- Reject reserved / system names (`_empty`, `offline_access`, `uma_authorization`, `default-roles-*`).
- New roles are **not** mapped to OpenSearch `files_searcher`. Users still need `search-user` for OS backend role; custom role names are for later DLS ACL matching (9b).
- Groups flat; `path` from KC; `is_system=false`.

### C5. List (identity pickers)

| | |
| --- | --- |
| Status | **LOCKED** |
| Decision | `GET /admin/users?limit&offset&q?`, `GET /admin/roles?include_system=false`, `GET /admin/groups?include_system=false`. (`GET /admin/files` is **9b**.) |

### C9. Keycloak product client

| | |
| --- | --- |
| Status | **LOCKED** |
| Decision | `app/services/keycloak_admin.py` — client_credentials on `api-client`. Never use end-user Bearer for Admin API. |

### C10. Frontend (6a scope)

| | |
| --- | --- |
| Status | **LOCKED** (partial) |
| Decision | `/admin` tabs **Users | Roles | Groups**. Reuse `AppShell` / existing Tailwind. Files/ACL tab = placeholder or hidden until 9b. |

### C12. Errors (identity)

| | |
| --- | --- |
| Status | **LOCKED** |
| Decision | KC/PG username or name conflict → **409**. Missing id → **404**. System principal mutate/delete → **400**. |

---

## Architecture (6a)

```
React /admin (AdminRoute) — Users | Roles | Groups
  │ Bearer user JWT (admin)
  ▼
FastAPI /admin/users|roles|groups
  → Keycloak Admin API (api-client client_credentials)
  → Postgres mirror upsert
```

```
Sources of truth
────────────────────────────────
Users / roles / groups  → Keycloak (PG is mirror)
Request authz           → JWT
Admin capability        → realm role admin
```

---

## API contract (6a)

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/admin/users` | list + optional `q` |
| POST | `/admin/users` | create C2 |
| GET | `/admin/users/{id}` | detail |
| PATCH | `/admin/users/{id}` | update C3 |
| GET | `/admin/roles` | `include_system` default false |
| POST | `/admin/roles` | create C4 |
| GET | `/admin/roles/{id}` | detail |
| PATCH | `/admin/roles/{id}` | description only |
| DELETE | `/admin/roles/{id}` | 409 if ACL refs; no system |
| GET | `/admin/groups` | `include_system` default false |
| POST | `/admin/groups` | create C4 |
| GET | `/admin/groups/{id}` | detail |
| DELETE | `/admin/groups/{id}` | 409 if ACL refs; no `_empty` |

### Out of scope in 6a

- `/admin/files*`, `/admin/acl-jobs*` (9b)
- User hard-delete; role/group rename
- Self-service change-password
- File ACL / OpenSearch writes

---

## Module layout (6a)

```
backend/app/
  api/routes/admin_identity.py
  api/router.py                   # include identity router
  schemas/admin_identity.py
  services/
    keycloak_admin.py             # client_credentials + CRUD wrappers
    identity_admin.py             # KC + PG orchestration + compensate
  api/deps.py                     # require_admin (exists)

frontend/src/
  api/admin.ts                    # identity client calls (extend in 9b)
  pages/Admin.tsx                 # Users | Roles | Groups
  components/admin/               # optional forms/tables

backend/scripts/
  admin_identity_proof.py         # proofs 1–8 (+ ping/health)
```

No Alembic required in 6a unless a gap appears (identity tables already exist).

---

## Landmines (6a)

1. **Postgres-first create** — strands PG without login. **KC first** (G5).
2. **Auth from PG mirror** — stale. Keep JWT for `require_admin`.
3. **Mapping new roles to `files_searcher`** — do not. Need `search-user` for OS mapping.
4. **Granting `_empty` via API** — reject.
5. **Renaming roles/groups** — forbid (G7); names are DLS/JWT keys.
6. **Blind KC compensate delete** — if sessions may exist, prefer repair-mirror messaging; log orphan IDs.
7. **Starting 9b work in this slice** — out of scope.

---

## Proofs (6a)

| # | Test | Expect |
| --- | --- | --- |
| 1 | `GET /admin/users` as searcher | 403 |
| 2 | `GET /admin/users` as realm-admin | 200 includes seed users |
| 3 | `POST /admin/roles` create `qa-role` | 201; KC + PG; `is_system=false` |
| 4 | `POST /admin/groups` create `qa-group` | 201; KC + PG |
| 5 | `POST /admin/users` create `qa-user` with `search-user` + `qa-group` | 201; token has roles/groups (password grant or UI login); password permanent |
| 6 | Second create same username | 409 |
| 7 | `PATCH` role rename / change `name` | 400/422 (forbidden) |
| 8 | `DELETE` role that has `file_acl` row | 409 (if such row exists; else delete ok then recreate) |
| 9 | `/auth/admin-ping` + `/health` | 200 |
| 10 | React smoke: create role + user | manual |

Proof driver: `uv run python -m scripts.admin_identity_proof` — **not** `init_services`.

---

## Tasks to perform (6a checklist)

Check a box only after that step has been **run**.

### 0. Human lock

- [x] G1 locked: 9a then 9b
- [x] G5, G7, G8 + C1–C5, C9, C10 (identity), C12 locked
- [x] Permanent password (C2/C3)

### A. Keycloak admin client

- [x] `services/keycloak_admin.py` client_credentials + user/role/group/membership helpers
- [x] Prove token fetch against live Keycloak

### B. Identity Admin API

- [x] Schemas + `identity_admin.py` (KC then PG, compensate)
- [x] Routes: users/roles/groups as contracted
- [x] Filter `is_system` on list defaults; reject `_empty` assign
- [x] Proofs 1–9

### C. React Admin (identity)

- [x] `api/admin.ts` identity methods
- [x] `Admin.tsx`: Users, Roles, Groups (create/edit; no rename)
- [ ] Proof 10 manual

### D. Hygiene

- [x] No file ACL / jobs / auto-ACL on upload
- [x] Write summary e.g. `prompts/summary/8a_admin_identity.md` when done
- [x] Do **not** flip full Task 6 in overview until 9b done; optional note “6a done”

---

## Recommended execution order

1. Keycloak admin client + token proof.
2. Identity API + proofs 1–9.
3. React Users/Roles/Groups.
4. Summary writeup → start **9b**.

---

## Explicitly out of scope (6a)

- Everything in `9b_admin_panel.md` (ACL, jobs, admin file inventory, OS sync)
- Celery/Redis; connectors; `owner`/`deleter`; native hybrid 3.9
- Self-service change-password; user hard-delete; role/group rename

---

## Follow-on

| Next | Needs from 6a |
| --- | --- |
| **9b** | Working `/admin` identity APIs + roles/groups pickers for ACL UI; `keycloak_admin` / mirror discipline |
| Task 7 | Identity repair CLI if orphans occur |

---

## Changelog

| Date | Change |
| --- | --- |
| 30 Aug 2026 | Split from `9_admin_panel.md` into **9a** (identity) per locked G1. |
