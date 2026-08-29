# Data model — implemented 27 August 2026

This slice is **implemented as of 27 August 2026**. It is Task 2 only: Postgres `app` has a complete Keycloak identity mirror, file metadata, and `file_acl`. Alembic is at `head`. Request auth still uses the JWT. No ingest, no OpenSearch mapping changes, no search UI, no admin CRUD.

Locked G1–G8 from `prompts/cursor_summary/5_data_setup.md` were treated as law. Remaining confusion C1–C7 used the documented **Assumption** in each row.

---

## Sources of truth (unchanged)

```
Keycloak     → authentication: users, realm roles, groups, memberships
Postgres     → identity *mirror* (complete) + files metadata + file_acl
OpenSearch   → chunks + embeddings + denormalized allowed_roles / allowed_groups  (not this slice)
MinIO        → original bytes at object_store_path  (not this slice)
JWT          → request authn/authz (roles/groups for DLS and require_admin)
```

Postgres identity is a **projection** of Keycloak. If they disagree, Keycloak wins; re-run the mirror. File ACL is **not** in Keycloak. Admin capability is still the realm role `admin` (no `admin_grants` table).

---

## What shipped

### A. Models (`backend/app/models/`)

| Table | Module | PK | Notes |
| --- | --- | --- | --- |
| `users` | `identity.py` | Keycloak user UUID (`JWT sub`) | username unique, email nullable, `enabled`, timestamps. No password. |
| `roles` | `identity.py` | Keycloak realm role UUID | `name` unique (JWT/DLS string). `is_system` for built-ins. |
| `groups` | `identity.py` | Keycloak group UUID | `name` unique (`full.path: false`). `path` stored. `_empty` → `is_system`. No `parent_id`. |
| `user_roles` | `identity.py` | `(user_id, role_id)` | `ON DELETE CASCADE` both FKs. |
| `user_groups` | `identity.py` | `(user_id, group_id)` | `ON DELETE CASCADE` both FKs. Direct membership only. |
| `files` | `file.py` | `uuid4` | `object_store_path`, `file_type`, `size_bytes`, `ingestion_type`, `original_source`, timestamps. **No** chunks, filename, MIME, status, uploader. |
| `file_acl` | `file.py` | `uuid4` | Three nullable FKs + CHECK exactly one principal. `permission` VARCHAR CHECK `viewer` \| `editor`. Partial unique indexes per principal. Role/group FKs `ON DELETE RESTRICT`. File FK `ON DELETE CASCADE`. |

`app/models/__init__.py` imports every model so Alembic `env.py` (`from app import models`) sees metadata.

### B. Session

`get_db` in `app/db/session.py` is a FastAPI-friendly alias of `get_session`. Same engine. **No product route uses it yet.**

### C. Alembic

`backend/alembic/versions/`:

| Revision | Role |
| --- | --- |
| `5999ba361973` | No-op placeholder. Local `app` was already stamped with this id from an **out-of-tree** experimental schema (integer role ids, `permissions` / `file_permissions`, `users.keycloak_id`). Those tables were **empty**. |
| `68a730544554` (head) | `DROP TABLE IF EXISTS` leftover names, then create the real schema including CHECKs and partial unique indexes. |

`uv run alembic check` after upgrade: **no drift** vs models.

Alembic is **not** invoked from `init_services`. Fresh machines: `cd backend && uv run alembic upgrade head` **before** expecting the mirror to succeed. Missing tables → `[error] identity tables missing` and exit 1.

### D. Identity mirror (`init_services/identity_sync.py`)

One-way Keycloak → Postgres, after `keycloak.configure()`. Idempotent upsert. Realm roles only (C1: no client roles).

1. All realm roles. `is_system=true` for `offline_access`, `uma_authorization`, `default-roles-*`.
2. All groups (flattened via `/groups/{id}/children`). `is_system=true` iff name `_empty`.
3. All users (paginated `/users` + service-account users from clients).
4. Per user: replace `user_roles` / `user_groups` from direct realm role-mappings and group memberships.
5. Users missing in Keycloak: **warn, do not delete**. Roles/groups missing in Keycloak: delete unless `file_acl` RESTRICT would block.

List helpers live on `init_services/keycloak.py` (`list_all_realm_roles`, `list_all_groups`, `list_all_users`, …) and reuse `_admin_client()`.

Run order: wait → Keycloak configure → **identity mirror** → OpenSearch → MinIO. Skip mirror if Postgres or Keycloak is down. OpenSearch/MinIO down still skipped independently.

Local mirror counts after sync: **users=3** (2 seed + 1 service account), **roles=5** (product `admin`/`search-user` + 3 Keycloak built-ins), **groups=2** (`engineering`, `_empty`).

---

## What was intentionally not done

- No upload, chunking, MinIO put, OpenSearch index/mappings, search API, View files query.
- No admin UI/API to create users/roles/groups or assign file privileges (Task 6).
- No `owner` / `deleter` in the permission CHECK (widen later; not a PG ENUM).
- No `original_filename` / `content_type` / `status` / `uploaded_by_user_id` (G8 / C5).
- No auto `file_acl` on upload (G3).
- `get_current_user` still does **not** load roles from Postgres.
- Frontend unchanged.

---

## Assumptions used (C1–C7)

| Id | Assumption applied |
| --- | --- |
| C1 | Mirror **realm** roles only, not client roles. |
| C2 | Default grant **value** is `viewer` (Task 6). No auto-grant on upload. |
| C3 | Editor implies viewer at **query** time later. One row per principal. |
| C4 | v1 search/view/open: editor ≡ viewer. Not needed for tables. |
| C5 | No display filename column in this revision. |
| C6 | Upsert every group Keycloak returns; membership = direct only. No `parent_id`. |
| C7 | `is_system` stored; pickers will filter later. Never grant ACL to `_empty` (enforce in Task 4/6 services). |

---

## Proofs run 27 August 2026

| # | Test | Result |
| --- | --- | --- |
| 1 | `alembic upgrade head` | `5999ba361973 → 68a730544554` |
| 2 | Tables in `app` | `users`, `roles`, `groups`, `user_roles`, `user_groups`, `files`, `file_acl`. `files` columns: id, object_store_path, file_type, size_bytes, ingestion_type, original_source, uploaded_at, updated_at |
| 3 | Mirror includes seed + built-ins / service accounts | users=3, roles=5 (3 built-in), groups=2, 1 `service-account-*`. `_empty.is_system=true`. `admin`/`search-user` `is_system=false` |
| 4 | `realm-admin` id = JWT `sub` | True (password-grant `api-client` → `GET /auth/me`) |
| 5 | Duplicate `file_acl` unique | `23505` on second role grant for same file |
| 6 | CHECK exactly one principal | `23514` for two FKs and for all-null |
| 7 | CHECK permission rejects `owner` | `23514` |
| 8 | CASCADE file delete | `file_acl` rows gone |
| 9 | RESTRICT role delete with ACL | `23503`; dummy file then deleted; leftover proofs rows = 0 |
| 10 | Second `init_services` idempotent | same counts users=3 roles=5 groups=2; seed memberships unchanged |
| 11 | `/health` and `/auth/me` | 200; `searcher` still non-admin |

CHECKs present: `ck_files_ingestion_type`, `ck_file_acl_permission`, `ck_file_acl_one_principal`. Partial unique indexes: `uq_file_acl_file_user/role/group`.

User-principal ACL insert **succeeds** (column reserved for later connectors). Dummy proof rows were removed.

---

## Self-review

Reviewed against the locked schema, auth-slice invariants, and defect-first criteria. **No P0/P1 findings.** Models match the applied revision (`alembic check` clean). Auth still JWT-only. No product route was taught to load identity from Postgres.

Residual risks (not defects in this slice):

- Direct Keycloak role-mappings do **not** list `default-roles-*` on seed users (the **role row** is mirrored; membership follows Keycloak’s actual assignments). Composite/effective roles are not stored.
- `groups.name` is UNIQUE. Nested Keycloak groups with the same leaf name would collide (no `parent_id` in v1).
- Identity sync is N+1 Admin API calls per user. Fine for this realm; revisit if the realm grows a lot.
- `downgrade()` SQL was written (drop new tables) but **not executed** on the live DB.

---

## Human review points

1. **Placeholder revision `5999ba361973`.** Needed because this machine’s `app` DB was already stamped with an out-of-tree id. Upgrade is a no-op; the next revision drops the empty leftover tables and creates the real schema. Decide whether to keep this forever or squash after every environment has reached `68a730544554`.
2. **Leftover experimental tables were dropped** (`permissions`, `file_permissions`, `role_permissions`, old `users`/`roles`/`files`/`user_roles`). They had **0 rows**. Confirm no other local tool depended on that old shape.
3. **C1–C7 assumptions** — especially C1 (no client roles), C5 (no filename column), C6 (no `parent_id`, unique `groups.name`). Edit the plan if any assumption is wrong; that would be a new Alembic revision, not a silent column add.
4. **`file_acl.user_id` exists but v1 product code must not require user grants.** Task 6 pickers should offer roles/groups only and hide `is_system` (`_empty`, built-in roles).
5. **No auto-ACL on upload (G3).** Ingest (Task 4) must insert `files` metadata only. A file with no role/group grant is not searchable.
6. **Permission CHECK is VARCHAR + CHECK, not ENUM.** Widening to `owner`/`deleter` is a future migration. Do not add a PostgreSQL ENUM.
7. **Fresh clone / new Postgres volume:** run `cd backend && uv run alembic upgrade head` **before** `uv run python -m init_services`. Mirror does not create tables.
8. **Request path must stay on JWT.** Do not “fix” stale admin-UI memberships by resolving roles from Postgres in `get_current_user`.
9. **Postgres collation warning** (`database "app" has no actual collation version`) appears on connect. Cosmetic so far; worth a DBA glance, not a schema bug.
10. **`get_db` is unused by routes.** Optional tiny proof ping was skipped; add it in a later slice if you want a wired-session smoke test in the API.

---

## Follow-on

| Task | Needs from this schema |
| --- | --- |
| 3 Search platform | `file_id` UUID string; ACL **names** for DLS; viewer and editor both readable |
| 4 Ingest | Insert `files` metadata only; **no** auto `file_acl`. Chunks → OpenSearch only |
| 5 View files / Open | Query `files` + `file_acl` using JWT role/group names; editor implies viewer |
| 6 Admin | Dual-write identity; assign viewer/editor to roles/groups (default viewer); hide `is_system` in pickers |
| Later connectors | Import source ACL onto `user`/`role`/`group` + widen permission CHECK |

---

## ER

```
users 1──* user_roles *──1 roles
users 1──* user_groups *──1 groups
files 1──* file_acl
file_acl 0..1 users | 0..1 roles | 0..1 groups   (exactly one)
```

No `files.uploaded_by`. No chunks in Postgres.
