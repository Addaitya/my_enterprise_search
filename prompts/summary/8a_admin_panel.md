# Admin panel 6a — Identity (users / roles / groups)

**Implemented 30 August 2026.** Task **6a** from `prompts/cursor_summary/9a_admin_panel.md`. File ACL / OpenSearch sync (**6b** / `9b_admin_panel.md`) is **not** in this slice. Do **not** flip overview Task 6 until 6b lands.

Auth stays JWT-based (`require_admin`). Identity writes are **Keycloak first, then Postgres mirror** (G5). OpenSearch ACL fields are unchanged.

---

## What shipped

### A. Keycloak product admin client

| Piece | Location |
| --- | --- |
| Client | `backend/app/services/keycloak_admin.py` |
| Auth | `api-client` **client_credentials** (never end-user Bearer) |
| Init grant | `init_services/keycloak.py` → `_ensure_api_client_service_account_roles` |

Service account receives `realm-management` roles: `manage-users`, `view-users`, `query-users`, `query-groups`, `manage-realm`, `view-realm`. Re-run `uv run python -m init_services` (or at least Keycloak configure) on fresh stacks so Admin API calls are not 403.

User create sets `firstName` / `lastName` and clears `requiredActions` so Keycloak 26 **VERIFY_PROFILE** does not block password-grant (`Account is not fully set up`). Passwords use `temporary=false` (C2/C3).

Empty product `group_names` → user joins sentinel `_empty` in KC (and PG mirror) for DLS JWT shape; API never accepts `_empty` in request bodies; responses strip `_empty`.

### B. Identity Admin API

| Piece | Location |
| --- | --- |
| Schemas | `backend/app/schemas/admin_identity.py` |
| Orchestration | `backend/app/services/identity_admin.py` |
| Routes | `backend/app/api/routes/admin_identity.py` (mounted in `app/api/router.py`) |

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/admin/users` | `limit`, `offset`, optional `q` |
| POST | `/admin/users` | C2; ≥1 of `search-user`\|`admin`; no password in response |
| GET | `/admin/users/{id}` | detail + memberships |
| PATCH | `/admin/users/{id}` | email / enabled / roles / groups / optional password; username immutable |
| GET | `/admin/roles` | `include_system` default **false** |
| POST | `/admin/roles` | reject reserved/system names |
| GET/PATCH/DELETE | `/admin/roles/{id}` | PATCH description only (`extra=forbid` → rename **422**); DELETE **409** if `file_acl` refs; no system delete |
| GET | `/admin/groups` | `include_system` default **false** |
| POST | `/admin/groups` | reject `_empty` / reserved |
| GET/DELETE | `/admin/groups/{id}` | DELETE **409** if ACL refs; no `_empty` delete |

Non-admin → **403**; unauthenticated → **401**. KC/PG name conflicts → **409**. PG fail after KC create → compensate delete when safe, else **503** + orphan hint.

### C. React Admin UI

| Piece | Location |
| --- | --- |
| API client | `frontend/src/api/admin.ts` (+ `apiPatchJson` in `client.ts`) |
| Page | `frontend/src/pages/Admin.tsx` — tabs **Users \| Roles \| Groups** |

Files/ACL tab deferred (label: “coming in 6b”). Create/edit users; create roles + edit description (no rename); create/delete groups. Reuses `AppShell` / existing dark Tailwind look.

### D. Proof driver

`backend/scripts/admin_identity_proof.py` — proofs **1–9** (+ client_credentials). Run:

```bash
cd backend
uv run python -m init_services.keycloak   # ensure api-client Admin roles
uv run python -m scripts.admin_identity_proof
```

---

## Proofs run (30 Aug 2026)

| # | Result |
| --- | --- |
| A | client_credentials token OK |
| 1 | searcher `GET /admin/users` → **403** |
| 2 | realm-admin list includes `realm-admin`, `searcher` |
| 3 | `POST /admin/roles` `qa-role` → **201**, `is_system=false` |
| 4 | `POST /admin/groups` `qa-group` → **201** |
| 5 | `POST /admin/users` `qa-user` → **201**; password-grant + `/auth/me` has `search-user` + `qa-group` |
| 6 | duplicate username → **409** |
| 7 | PATCH role with `name` → **422** |
| 8 | DELETE role with `file_acl` → **409** |
| 9 | `/health` + `/auth/admin-ping` → **200** |
| 10 | React smoke — **human** (see guide below) |

Frontend `bun run build` succeeded after UI changes.

---

## Guide to test the changes

### Prerequisites

1. Compose stack up (Postgres, Keycloak, OpenSearch, MinIO).
2. Backend + frontend: `./start-dev.sh` or equivalent (`:8000` / `:5173`).
3. Once after pull: `cd backend && uv run python -m init_services` (or Keycloak configure) so `api-client` has Admin roles.
4. Identity mirror already populated (`users` / `roles` / `groups`).

### Automated API proofs

```bash
cd backend
uv run python -m scripts.admin_identity_proof
```

Expect `=== all admin identity proofs passed ===`. Re-runnable: cleans prior `qa-user` / `qa-role` / `qa-group`.

### Manual API spot checks (optional)

```bash
# tokens
export KC=http://localhost:8080/realms/enterprise-search-realm/protocol/openid-connect/token
export ADMIN=$(curl -s -X POST "$KC" -d 'grant_type=password&client_id=api-client&client_secret=api-client-secret&username=realm-admin&password=adminpass' | jq -r .access_token)
export SEARCHER=$(curl -s -X POST "$KC" -d 'grant_type=password&client_id=api-client&client_secret=api-client-secret&username=searcher&password=searcherpass' | jq -r .access_token)

curl -s -o /dev/null -w "%{http_code}\n" -H "Authorization: Bearer $SEARCHER" http://localhost:8000/admin/users   # 403
curl -s -H "Authorization: Bearer $ADMIN" http://localhost:8000/admin/roles | jq .
curl -s -H "Authorization: Bearer $ADMIN" http://localhost:8000/admin/groups | jq .
```

### Human: React smoke (proof 10)

1. Open http://localhost:5173 → login as **`realm-admin` / `adminpass`**.
2. Navbar **Admin** → `/admin`. Confirm tabs **Users | Roles | Groups**.
3. **Roles:** create e.g. `ui-role` with a description; edit description only; confirm name is not editable.
4. **Groups:** create e.g. `ui-group`.
5. **Users:** create a user with password, `search-user`, and `ui-group`. Confirm it appears in the table.
6. Edit that user (toggle enabled / change groups). Optional: set a new password.
7. Logout → login as the new user → confirm `/` search works (has `search-user`).
8. Login as **`searcher` / `searcherpass`** → open `/admin` → expect **Forbidden** (AdminRoute); API calls would be 403.

If anything fails, note: Keycloak Admin 403 usually means service-account roles were not granted — re-run Keycloak configure.

---

## Intentionally out of scope (6a)

- `/admin/files*`, `/admin/acl-jobs*`, OpenSearch `allowed_*` writes, auto-ACL on upload
- User hard-delete; role/group rename
- Self-service change-password
- Mapping new roles onto OpenSearch `files_searcher` (users still need `search-user`)

---

## Follow-on

| Next | Needs from 6a |
| --- | --- |
| **9b** | Working identity APIs + role/group pickers; `keycloak_admin` + mirror discipline |
| Overview Task 6 | Flip only when **6a + 6b** both done |

---

## Files touched (reference)

```
backend/init_services/keycloak.py          # api-client Admin role grant
backend/app/services/keycloak_admin.py     # NEW
backend/app/services/identity_admin.py     # NEW
backend/app/schemas/admin_identity.py      # NEW
backend/app/api/routes/admin_identity.py   # NEW
backend/app/api/router.py
backend/scripts/admin_identity_proof.py    # NEW
frontend/src/api/client.ts                 # apiPatchJson
frontend/src/api/admin.ts                  # NEW
frontend/src/pages/Admin.tsx
prompts/summary/8a_admin_panel.md          # this file
```
