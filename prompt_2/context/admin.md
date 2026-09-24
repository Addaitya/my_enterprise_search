# Admin identity, file ACL, and members

Shipped. Sources: `prompts/summary/8a_admin_panel.md`, `prompts/summary/8b_admin_panel.md`, `prompts/summary/10a_acl_ui_update.md`, `prompts/summary/10b_member_assign.md`. `prompts/summary/12a_file_access_ui.md` is a short duplicate of the 10a dump. 12b did ship (`10b_member_assign.md`).

## Identity API

Admin calls use `api-client` client credentials, never the end-user Bearer, against Keycloak Admin API. The service account needs `realm-management` roles (`manage-users`, `view-users`, `query-users`, `query-groups`, `manage-realm`, `view-realm`). Re-run init on a fresh stack or those calls 403.

| Method | Path | Notes |
| --- | --- | --- |
| GET/POST | `/admin/users` | Create requires at least one of `search-user` or `admin`. No password in the response. |
| GET/PATCH | `/admin/users/{id}` | Username immutable. Optional password `temporary=false`. |
| GET/POST | `/admin/roles` | `include_system` defaults false. Reject reserved names. |
| PATCH/DELETE | `/admin/roles/{id}` | Description only. Rename is 422. Delete 409 if `file_acl` references it. No system delete. |
| GET/POST | `/admin/groups` | Reject `_empty`. |
| DELETE | `/admin/groups/{id}` | 409 if ACL references it. |

Empty product groups put the user in `_empty` in Keycloak and Postgres so the JWT `groups` claim exists. API bodies reject `_empty`; responses strip it. User create sets names and clears `requiredActions` so Keycloak 26 VERIFY_PROFILE does not block login. Keycloak is written first; if Postgres fails after a create, compensate when safe, otherwise 503.

Non-admin → 403. Unauthenticated → 401. Name conflicts → 409.

## Member assignment

Identity membership only. No new file-ACL endpoints. Add is additive and remove is subtractive; member APIs never replace the whole set. Max 100 `user_ids` (400 if more). After a role removal the user must still have `search-user` or `admin`, otherwise that user is in `failed[]`. Keycloak first, then the Postgres mirror. `POST .../members:remove` (not DELETE with a body). Partial success is HTTP 200 with `results[]` and `failed[]`.

Leaving the last product group joins `_empty` again. UI tells the admin to re-login before search reflects the new membership, because DLS reads the JWT.

## File ACL admin

Flow: mutate Postgres `file_acl` → commit → insert `acl_sync_jobs` (`queued`) → background worker recomputes full `allowed_roles` / `allowed_groups` → OpenSearch `update_by_query` as basic `admin` with `refresh=true`. No Celery or Redis. On startup, jobs left `running` become `failed` / `interrupted`.

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/admin/files` | All files, not ACL-filtered. Display name is the basename. |
| GET/PUT/POST | `/admin/files/{id}/acl` | PUT replaces all grants and enqueues. POST upserts one. |
| DELETE | `/admin/files/{id}/acl/{acl_id}` | Revoke and enqueue. |
| GET | `/admin/acl-jobs/{id}` | Progress. POST `.../retry` re-queues a failure. |

Roles and groups only. System principals and `_empty` → 400. Missing file → 404. Enqueue failure after the Postgres commit → 503.

React Admin tabs: Users, Roles, Groups, Access (file ACL). The UI polls the job about once a second. Configuration is a placeholder.
