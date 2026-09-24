# Data model

Shipped Task 2. Source: `prompts/summary/3_data_modeling.md`. Later tables (`upload_sessions`, `acl_sync_jobs`, `search_query_metrics`) are in the ingest, admin ACL, and dashboard notes.

## Sources of truth

- Keycloak authenticates users, realm roles, groups, and memberships.
- Postgres is a one-way identity mirror plus `files` and `file_acl`. If they disagree, Keycloak wins; re-run the mirror. File ACL is not in Keycloak.
- OpenSearch holds chunks, embeddings, and denormalized `allowed_roles` / `allowed_groups`.
- MinIO holds original bytes at `object_store_path`.
- The JWT is request auth. Do not load roles from Postgres in `get_current_user`.

Admin capability is the realm role `admin`. There is no `admin_grants` table. The admin role does not bypass file ACL.

## Tables

| Table | Notes |
| --- | --- |
| `users` | PK is the Keycloak user UUID (`JWT sub`). Username unique. No password. |
| `roles` | Realm role UUID. `name` is the JWT/DLS string. `is_system` for built-ins. |
| `groups` | Group UUID. `name` unique (`full.path: false`). `_empty` is `is_system`. No `parent_id`. |
| `user_roles`, `user_groups` | Composite PKs. `ON DELETE CASCADE`. Direct membership only. |
| `files` | `uuid4`. `object_store_path`, `file_type`, `size_bytes`, `ingestion_type`, `original_source`, timestamps. No chunks, filename, MIME, status, or uploader. |
| `file_acl` | Exactly one of `user_id`, `role_id`, `group_id`. Permission `viewer` or `editor` (VARCHAR + CHECK, not a PG ENUM). Role/group FKs `ON DELETE RESTRICT`. File FK `ON DELETE CASCADE`. Partial unique indexes per principal. |

`file_acl.user_id` exists for later connectors. v1 product grants target roles and groups. Never grant ACL to `_empty` or system principals.

No auto `file_acl` on upload. A file with no role or group grant is not searchable or listable. Editor implies viewer at query time. One row per principal.

## Identity mirror

`init_services/identity_sync.py` runs after Keycloak configure. Realm roles only (no client roles). Upsert roles, flattened groups, users, then replace direct memberships. Users missing in Keycloak are warned and not deleted. Roles or groups missing in Keycloak are deleted unless `file_acl` RESTRICT blocks it.

Alembic is not invoked from `init_services`. Fresh machines: `cd backend && uv run alembic upgrade head` before `uv run python -m init_services`.

```
users 1──* user_roles *──1 roles
users 1──* user_groups *──1 groups
files 1──* file_acl
file_acl → exactly one of users | roles | groups
```
