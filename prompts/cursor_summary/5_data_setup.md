# Data model setup — implementation plan (Task 2)

Working notes to implement **Task 2 (Data model / Postgres)** from `prompts/cursor_summary/2_project_overview_tasks.md`. Auth is already live (`prompts/summary/2_auth_layer.md`). This file is the source of truth for the data-model slice. Do not invent a second identity or ACL model.

**Agent rules while implementing**
- Run and execute code to confirm it works before moving on.
- Do not proceed past a broken step; fix it first.
- Where something cannot be verified in this environment, leave a clear human check and wait for feedback.
- Do **not** start ingest, chunking, MinIO uploads, OpenSearch index/mappings, search UI, or admin CRUD (create user/role/group, assign file privileges). Schema + migration + one-way Keycloak→Postgres mirror only.
- Treat **Locked decisions** as law. For **Remaining confusion**, use the **Assumption** in that row; do not invent a third option.

Human locked G1–G8 on 27 August 2026 (chat). Remaining confusion is recorded below so it is visible, not so implementation blocks.

---

## What “done” means

Postgres `app` has a full Keycloak identity mirror, file metadata, and file ACL. Alembic is at `head`. Request auth **stays on the JWT** (no “load roles from Postgres on every request”). File bytes stay in MinIO; chunks stay in OpenSearch.

| Actor | What they may do in this slice |
| --- | --- |
| Alembic | Create tables in `app` |
| `init_services` | After Keycloak configure, upsert the full identity mirror |
| FastAPI | Unchanged product APIs. Optional: session `Depends` wired, unused by routes except a tiny proof ping |
| React | Unchanged |
| OpenSearch / MinIO | Unchanged |

---

## Current state (do not re-scaffold)

Already in place:

- Postgres 16, database `app`, role `app_user`. Init script: `docker_service_configs/postgres/init-databases.sh`.
- SQLAlchemy 2 + Alembic wired: `app/db/base.py`, `app/db/session.py` (`get_engine`, `get_session`), `alembic/env.py` imports `app.models` and `Base.metadata`. **No models. No `alembic/versions/` directory. No revisions.**
- `init_services/run.py` pings Postgres and prints: run `uv run alembic upgrade head` when models exist. It does not migrate or seed app tables.
- Keycloak is **authentication / identity only**: users `realm-admin`, `searcher`; realm roles `admin`, `search-user`; groups `engineering`, `_empty`. JWT claims `sub`, `roles[]`, `groups[]` (sentinel `_empty` stripped in FastAPI/SPA). Keycloak does **not** store file ACL.
- Auth: FastAPI validates Bearer JWT; `require_admin` checks realm role `admin`. **No Postgres identity lookup.**
- `app/models/__init__.py` is a docstring only: “File ACL and admin capability stay in separate tables.”
- `get_session` is **not** a FastAPI dependency yet.

Keycloak IDs are UUIDs (users, roles, groups). JWT `sub` is the Keycloak user id. DLS matches **names** (`roles`, `groups` claim strings), not UUIDs.

---

## Human gate — decisions (LOCKED 27 Aug 2026)

### G1. Admin dashboard capability — table or Keycloak only?

| | |
| --- | --- |
| Status | **LOCKED** |
| Decision | **No `admin_grants` / `admin_principals` table.** Admin = Keycloak realm role `admin`. Mirror that role in `roles` like any other role. FastAPI keeps `require_admin` on the JWT. |
| Why | Two sources of “who is admin” will drift. Auth is already proven on the role. File ACL stays resource-scoped in `file_acl`; admin stays identity-scoped in Keycloak. |

### G2. File ACL — principals, verbs, local vs later connectors

| | |
| --- | --- |
| Status | **LOCKED** |
| Local v1 | Files are uploaded **manually**. Access control is assigned **manually** (admin UI, Task 6). No auto-ACL from the uploader. |
| Verbs now | **`viewer`** and **`editor`** only. (Replaces the old brief verbs `viewer` / `owner`.) |
| Default for roles | Grants to roles start as **`viewer`**. Admin can later assign **`viewer`** or **`editor`** to a **role** or **group**. |
| Verbs later | Connector ingest will import ACL from source systems. Expected later verbs: **`owner`**, **`viewer`**, **`editor`**, **`deleter`**. Do not implement them now. Schema must not paint us into a PostgreSQL `ENUM` that is painful to extend. |
| Principals now | Admin assigns to **roles and groups**. Search DLS stays `allowed_roles` / `allowed_groups`. |
| Principals later | Source ACLs often include **users**. Keep `file_acl.user_id` (G5) so connector import can store per-user grants without another migration. v1 product code must not require user grants. |
| Search | A file with no role/group grant is **not searchable**. User-only grants (if any later) are not in DLS v1. |

### G3. Default visibility of a newly uploaded file

| | |
| --- | --- |
| Status | **LOCKED** |
| Decision | **No automatic grant** to `search-user`, `engineering`, or “all roles” on upload. File is searchable / listable only after an admin (or a later connector import) inserts `file_acl` rows. |
| Why | Local ACL is manual (G2). Auto-granting `search-user` would make every local file visible to all product users. |

### G4. Identity primary keys

| | |
| --- | --- |
| Status | **LOCKED** |
| Decision | **Keycloak UUID is the Postgres PK** for `users`, `roles`, `groups`. `users.id` = JWT `sub`. No separate `keycloak_id` column. |
| Why | Mirrors, not a second identity. ACL FKs join without a lookup table. Local Keycloak volume reset ⇒ re-run mirror (seed users get new ids; empty files table is expected on a full reset). |

### G5. `file_acl` shape

| | |
| --- | --- |
| Status | **LOCKED** |
| Decision | **Three nullable FKs** (`user_id`, `role_id`, `group_id`) + `permission` + CHECK exactly one FK is set. Partial unique indexes on the non-null principal per file. |
| Why | Real FKs + `ON DELETE RESTRICT` so you cannot delete a mirrored role/group/user that still has grants. |

### G6. What to mirror from Keycloak

| | |
| --- | --- |
| Status | **LOCKED** |
| Decision | **Mirror complete Keycloak auth/identity info** into Postgres: all realm users, all realm roles, all groups, all user↔role and user↔group memberships. Keycloak is authentication only. File rows and `file_acl` live only in Postgres, so the mirror must be complete enough to FK principals and to drive the admin UI. |
| Do not skip | Built-in realm roles (`offline_access`, `uma_authorization`, `default-roles-*`), sentinel group `_empty`, service-account users. Store them. |
| Still not in Keycloak | File metadata and file ACL. Never write those to Keycloak. |
| Client roles | Realm roles only in the JWT/`roles` claim today. See remaining confusion C1. |

### G7. Chunks in Postgres?

| | |
| --- | --- |
| Status | **LOCKED** |
| Decision | **No chunk table and no chunk metadata in Postgres.** Chunking exists to make search fast; keep it behind OpenSearch. Postgres stores **file metadata** (and ACL), **not** file bytes and **not** chunks. |
| Bytes | MinIO (`object_store_path`). |
| Chunks / embeddings | OpenSearch only. |

### G8. `files` columns

| | |
| --- | --- |
| Status | **LOCKED** |
| Decision | File metadata in Postgres is: **`object_store_path`**, **`type`**, **`size`**, **timestamps**, **`ingestion_type`**, **`original_source`**, plus **`id`** as PK. These fields are required. |
| Not in v1 | Do **not** add `original_filename`, `content_type`, `status`, `uploaded_by_user_id`. Human chose the brief set, not the extras. |
| ORM names | Python/SQLAlchemy cannot use attribute `type` cleanly. Column/attribute: `file_type` (brief “type”), `size_bytes` (brief “size”). Same data. |

---

## Remaining confusion (assumptions for implementation)

Human can edit these; implementation uses **Assumption** until then.

### C1. Client roles

Keycloak also has client roles (e.g. on `api-client`). JWT product claims use **realm** roles.

| Assumption | Mirror **realm** users, **realm** roles, groups, memberships only. Do not mirror client roles in v1. |

### C2. “Keep all roles as viewer”

Could mean (a) every upload auto-grants viewer to every role, or (b) the default **permission value** when an admin grants a role is viewer.

| Assumption | **(b)**. Reconciles G2 with G3 (no auto-grant on upload). Admin UI (Task 6) defaults new role/group grants to `viewer`. |

### C3. Does `editor` imply `viewer`?

| Assumption | **Yes**, at query time: view/search/download allowed if `permission IN ('viewer', 'editor')`. Store **one** row per principal; upgrading viewer→editor updates the row. Same pattern later for `owner` / `deleter`. |

### C4. What `editor` is allowed to do (product)

Not needed to create tables. Search DLS is read-only; both viewer and editor names go into `allowed_roles` / `allowed_groups`.

| Assumption | v1 search/view/open: editor ≡ viewer. Mutating the file or ACL is Task 6+ and can distinguish editor later. |

### C5. View files display name

G8 has no `original_filename`. The list UI may only have `object_store_path` / `id`.

| Assumption | Accept for this slice. Task 4/5 may add `original_filename` in a new Alembic revision if the UI needs it. Do not sneak it into this first revision. |

### C6. Nested Keycloak groups

| Assumption | Upsert every group the Admin API returns (including subgroups if present). Membership = direct membership only, matching JWT `full.path: false`. |

### C7. `is_system` on mirrored identity

Complete mirror still needs a way for Task 6 pickers to hide DLS sentinels and Keycloak built-ins.

| Assumption | Keep `is_system`. `_empty` → true. Realm roles `offline_access`, `uma_authorization`, `default-roles-*` → true. Product roles `admin`, `search-user` and group `engineering` → false. **Storage is complete; pickers filter `is_system`.** Never grant `file_acl` to `_empty`. |

---

## Locked decisions (schema / process)

| Topic | Decision |
| --- | --- |
| Databases | App tables in Postgres DB `app` only. Never write the `keycloak` DB. |
| Authn on requests | JWT still. Do not resolve roles/groups from Postgres in `get_current_user`. |
| Admin capability | Keycloak role `admin` only. No `admin_grants` table. |
| File ACL vs admin | Separate. `file_acl` is resource-scoped. Admin is the realm role. |
| File verbs now | `viewer`, `editor`. Editor implies view at **query** time. One row per principal per file. |
| File verbs later | `owner`, `deleter` added via migration (widen CHECK). VARCHAR + CHECK, not PG ENUM. |
| ACL principals | Columns for `user`, `role`, `group`. v1 writes: **role and group**. `user_id` reserved for connector-imported ACL. |
| Local ACL policy | Manual. No default grants on upload. |
| Search DLS (later) | `allowed_roles` / `allowed_groups` **names**. Include principals whose permission is `viewer` **or** `editor`. Do not copy user grants in v1. |
| Identity PK | Keycloak UUID. |
| Identity mirror | **Complete** realm auth info (G6). |
| `file_acl` FKs | Three nullable FKs + CHECK. |
| Chunks | OpenSearch only. Postgres = file metadata + ACL, not bytes, not chunks. |
| `files` columns | `id`, `object_store_path`, `file_type`, `size_bytes`, `uploaded_at`, `updated_at`, `ingestion_type`, `original_source`. |
| Groups | No `parent_id` column in v1; still upsert all groups returned by Keycloak. |
| Time | `timestamptz`. |
| File PK | UUID (`uuid4`), stored as string in later OpenSearch `file_id`. |
| ORM | SQLAlchemy 2 `Mapped` / `mapped_column`. One model module per aggregate, imported from `app.models`. |
| Migrations | Models first, then `alembic revision --autogenerate`, **review the SQL**, then `upgrade head`. |
| Sync this slice | One-way Keycloak → Postgres, idempotent, in `init_services` after `keycloak.configure()`. |
| Dual-write Keycloak+DB on admin create | **Task 6**, not this slice. |
| OpenSearch mapping / ingest | **Task 3 / 4**, not this slice. |

Sources of truth (v1):

```
Keycloak     → authentication: users, realm roles, groups, memberships
Postgres     → identity *mirror* (complete) + files metadata + file_acl
OpenSearch   → chunks + embeddings + denormalized allowed_roles / allowed_groups
MinIO        → original bytes at object_store_path
JWT          → request authn/authz (roles/groups for DLS and require_admin)
```

Postgres identity is a **projection** of Keycloak. If they disagree, Keycloak wins; re-run the mirror. File ACL is **not** in Keycloak.

---

## Out of scope (do not do in this slice)

- Upload, parse, chunk, MinIO put, bulk index
- OpenSearch index, ingest pipeline, model register
- `POST /search`, file stream, View files query
- Admin UI/API to create users/roles/groups or assign file privileges
- Compensating transactions Keycloak ↔ Postgres (Task 6)
- `update_by_query` ACL sync / progress jobs
- Changing DLS or JWT mappers
- Frontend changes
- `owner` / `deleter` permissions (schema comment + CHECK that can widen later)

---

## Target filesystem (create / change)

```
backend/app/models/__init__.py          # import all models so Alembic sees them
backend/app/models/identity.py          # User, Role, Group, UserRole, UserGroup
backend/app/models/file.py              # File, FileAcl
backend/app/db/session.py               # add get_db FastAPI dependency (yield Session)
backend/alembic/versions/               # create; first revision
backend/init_services/identity_sync.py  # Keycloak Admin API → upsert complete mirror
backend/init_services/run.py            # after keycloak.configure(), sync if postgres ready
backend/init_services/keycloak.py       # optional: small list helpers reused by sync (do not duplicate HTTP)
```

No new product routes required. Prefer proving with `alembic` + init_services prints.

---

## Schema

SQLAlchemy names vs tables: `users`, `roles`, `groups`, `user_roles`, `user_groups`, `files`, `file_acl`.

Do not name a column `metadata` (clashes with `Base.metadata`). Do not name a Python attribute `type` — use `file_type`.

### `users`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | UUID PK | Keycloak user id = JWT `sub` |
| `username` | VARCHAR unique not null | `preferred_username` |
| `email` | VARCHAR null | |
| `enabled` | BOOLEAN not null default true | |
| `created_at` / `updated_at` | timestamptz | |

No password hash. No Keycloak secret material. Include service-account users.

### `roles`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | UUID PK | Keycloak realm role id |
| `name` | VARCHAR unique not null | JWT / DLS string |
| `description` | TEXT null | |
| `is_system` | BOOLEAN not null default false | Built-ins true; `admin` / `search-user` false |
| `created_at` / `updated_at` | timestamptz | |

### `groups`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | UUID PK | Keycloak group id |
| `name` | VARCHAR unique not null | JWT claim (`engineering`, `_empty`). `full.path: false` |
| `path` | VARCHAR null | Keycloak `path` e.g. `/engineering` |
| `is_system` | BOOLEAN not null default false | `_empty` → true |
| `created_at` / `updated_at` | timestamptz | |

### `user_roles`

| Column | Type | Notes |
| --- | --- | --- |
| `user_id` | UUID FK `users.id` ON DELETE CASCADE | |
| `role_id` | UUID FK `roles.id` ON DELETE CASCADE | |
| PK | `(user_id, role_id)` | |

### `user_groups`

| Column | Type | Notes |
| --- | --- | --- |
| `user_id` | UUID FK `users.id` ON DELETE CASCADE | |
| `group_id` | UUID FK `groups.id` ON DELETE CASCADE | |
| PK | `(user_id, group_id)` | |

### `files`

Postgres holds **metadata about files**, not bytes and not chunks.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | UUID PK | OpenSearch `file_id` later |
| `object_store_path` | VARCHAR not null unique | MinIO object key |
| `file_type` | VARCHAR not null | Brief `type`. Values e.g. `pdf`, `txt` → OpenSearch `meta_file_type` |
| `size_bytes` | BIGINT not null | Brief `size` → OpenSearch `meta_file_size` |
| `ingestion_type` | VARCHAR not null | CHECK `local` for now; column kept for connectors |
| `original_source` | VARCHAR null | null for local upload; connector id/url later |
| `uploaded_at` | timestamptz not null | |
| `updated_at` | timestamptz not null | bump on metadata/ACL change |

No content, embedding, chunk list, filename, MIME, status, or uploader columns in this revision.

### `file_acl`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | UUID PK | |
| `file_id` | UUID FK `files.id` ON DELETE CASCADE | |
| `user_id` | UUID FK `users.id` ON DELETE RESTRICT null | Reserved for later source ACL; unused by local v1 writes |
| `role_id` | UUID FK `roles.id` ON DELETE RESTRICT null | |
| `group_id` | UUID FK `groups.id` ON DELETE RESTRICT null | |
| `permission` | VARCHAR not null | CHECK `IN ('viewer', 'editor')` now. Later migration adds `owner`, `deleter` |
| `created_at` | timestamptz not null | |

CHECK: exactly one of `user_id`, `role_id`, `group_id` is non-null.

Uniqueness (one grant per principal per file):

- Unique index on `(file_id, user_id)` WHERE `user_id IS NOT NULL`
- Unique index on `(file_id, role_id)` WHERE `role_id IS NOT NULL`
- Unique index on `(file_id, group_id)` WHERE `group_id IS NOT NULL`

Comment on `permission` in the model: local = viewer | editor; connectors may add owner | deleter.

Application rule (later): refuse ACL on `is_system` groups (`_empty`) and prefer not assigning built-in roles. Enforce in services in Task 4/6.

View access helper (later, not this slice):

```sql
-- caller may view/search/open if any matching principal has viewer or editor
```

Resolve JWT `roles` → `roles.name`, JWT `groups` → `groups.name` (and later `sub` → `user_id`). Prefer JWT over joining `user_roles` so a stale mirror cannot hide/show files incorrectly. **Postgres ACL for download uses JWT claims + `file_acl`, not the membership tables.** Membership tables are for admin UI listing.

---

## OpenSearch denormalization (do not implement; schema must not fight this)

When ingest/ACL sync runs later:

1. Load `file_acl` for `file_id`.
2. `allowed_roles` = `roles.name` where `role_id` is set and permission in (`viewer`, `editor`) — and later `owner` / `deleter` if those verbs should still **read**.
3. `allowed_groups` = `groups.name` where `group_id` is set (exclude `is_system`, especially `_empty`).
4. **Do not** copy `user_id` grants into OpenSearch in v1.
5. `update_by_query` all chunks with that `file_id`.

Read DLS does not distinguish viewer vs editor. Difference is a Postgres/admin concern until write APIs exist.

---

## Identity mirror (`init_services/identity_sync.py`)

Idempotent upsert after `keycloak.configure()`. **Complete realm identity** (G6):

1. List **all** realm roles. Upsert `roles`. Set `is_system=true` for `offline_access`, `uma_authorization`, and names starting `default-roles-`.
2. List **all** groups. Upsert `groups`. Set `is_system=true` iff `name == "_empty"`.
3. List **all** users (including service accounts, disabled). Upsert `users` (`enabled` from Keycloak).
4. For each user: GET realm role mappings, GET groups; replace `user_roles` / `user_groups` for that user (delete missing, insert new).

Use Keycloak Admin API via the existing `_admin_client()` pattern. Reuse helpers from `keycloak.py` rather than copying token logic.

Print counts, e.g. `[ok] identity mirror users=N roles=N groups=N` (N will be **> seed-only** because built-ins and service accounts are included). Also print product-seed checks: `realm-admin` / `searcher` present.

**Delete policy this slice:** do not delete Postgres users that disappeared from Keycloak (future file FKs / user ACL). Log a warning. Roles/groups with no `file_acl` FK may be deleted if missing in Keycloak; if RESTRICT blocks, log and skip.

Run order in `run.py`: wait → keycloak.configure → **identity_sync** (needs Postgres + Keycloak) → opensearch → minio.

If Postgres is down, skip sync. If Keycloak is down, skip sync.

Alembic is **not** invoked from init_services. Human/dev runs `cd backend && uv run alembic upgrade head` **before** expecting the mirror to succeed. Mirror should fail clearly if tables are missing (`UndefinedTable`), not create tables itself.

---

## Landmines

### 1. Stale mirror vs JWT

Request path must keep using JWT roles/groups. If admin assigns a Keycloak group and the mirror is stale, **search DLS is still correct** (JWT). Admin UI would show stale members until the next sync. Task 6 writes both sides in one flow.

### 2. DLS names vs UUID FKs

Never put Keycloak UUIDs in `allowed_roles` / `allowed_groups`. Those fields must equal JWT claim strings (`search-user`, `engineering`).

### 3. `_empty` in `file_acl`

Granting viewer/editor to `_empty` would match every user who only has the sentinel group (`searcher`). Forbidden even though the group **is** mirrored.

### 4. File with no role/group grant

Search returns zero hits (G3). Do not “fix” this by stuffing usernames into `allowed_roles`.

### 5. `groups` / `user` reserved words

Table name `groups` is fine in PostgreSQL. Model class `Group`, table `groups`.

### 6. Alembic `env.py` already imports `app.models`

If `__init__.py` does not import `identity` and `file` modules, autogenerate produces an empty migration.

### 7. Autogenerate and CHECK / partial indexes

Alembic often misses CHECK constraints and partial unique indexes. After autogenerate, **add them in the revision** if they are absent.

### 8. `get_session` vs FastAPI

Add `get_db = get_session` (or equivalent). Do not create a second engine.

### 9. UUID type

`postgresql.UUID(as_uuid=True)`. Do not store UUIDs as VARCHAR.

### 10. Seed user ids change on Keycloak reset

After wiping the Keycloak volume, re-mirror. Old `file_acl` FKs will RESTRICT. Local-only.

### 11. Built-in roles as ACL principals

They are mirrored (G6) but must not be default file-ACL targets. Task 6 pickers hide `is_system=true`.

### 12. Permission CHECK vs later verbs

Do not use PostgreSQL ENUM. Widen CHECK in a future revision for `owner` / `deleter`.

---

## Implementation steps

Check a box only after that step has been **run**.

### 0. Human lock

- [x] G1–G8 locked 27 Aug 2026.
- [ ] Remaining confusion C1–C7: using assumptions unless human edits.

### A. Models

- [ ] `app/models/identity.py`: `User`, `Role`, `Group`, `UserRole`, `UserGroup`.
- [ ] `app/models/file.py`: `File`, `FileAcl`. Permission CHECK `viewer` | `editor`. Comment that owner/deleter come later.
- [ ] `app/models/__init__.py` imports every model.
- [ ] CHECK constraints expressed in SQLAlchemy (`CheckConstraint`).

### B. Session

- [ ] FastAPI-friendly `get_db` in `session.py` (can be an alias of `get_session`). No routes required to use it yet.

### C. Alembic

- [ ] Create `backend/alembic/versions/`.
- [ ] `cd backend && uv run alembic revision --autogenerate -m "identity files and file_acl"`
- [ ] Review revision: all tables, FKs, CHECKs, partial unique indexes. Fix by hand if autogenerate omitted indexes/CHECKs.
- [ ] `uv run alembic upgrade head` against live `app` DB.
- [ ] Prove: `\dt` in `app` lists `users`, `roles`, `groups`, `user_roles`, `user_groups`, `files`, `file_acl`.
- [ ] Prove `files` has no chunk/filename/status/uploader columns.
- [ ] Keep `downgrade` correct (drop these tables).

### D. Identity mirror

- [ ] `identity_sync.py` complete-realm upsert. Idempotent second run does not duplicate rows.
- [ ] Hook into `run.py`.
- [ ] `uv run python -m init_services`
- [ ] Prove seed users exist: `realm-admin`, `searcher`. Prove built-in roles **are** present (not skipped). Prove groups include `engineering` and `_empty`.
- [ ] Prove `realm-admin` memberships: roles include `admin` + `search-user`, group `engineering`. `searcher`: `search-user` + `_empty`.
- [ ] Prove `users.id` for `realm-admin` equals JWT `sub` from a password-grant token.

### E. ACL constraint proofs (no product API)

Small `uv run python` snippet or SQL:

- [ ] Insert a dummy `files` row (fake `object_store_path`), `editor` ACL on role `search-user` — succeeds.
- [ ] `viewer` ACL on group `engineering` for the same file — succeeds.
- [ ] Second `viewer` row for the same role+file — unique violation.
- [ ] ACL with `permission='owner'` — CHECK violation (not in v1).
- [ ] ACL with both `user_id` and `role_id` set — CHECK violation.
- [ ] ACL with all principal FKs null — CHECK violation.
- [ ] User-principal ACL row (dummy user + `viewer`) — **succeeds** (column exists for later connectors).
- [ ] Delete the dummy file — `file_acl` rows cascade away.
- [ ] Delete a role that has an ACL row — RESTRICT (must fail). Then delete the ACL and the dummy file so the DB is clean.

Do not leave dummy files in the table.

### F. Hygiene

- [ ] No secrets in models. No frontend changes. No OpenSearch writes.
- [ ] `uv run alembic current` shows the new revision.
- [ ] init_services still succeeds if OpenSearch/MinIO are down (existing skip behaviour).

---

## Proof table (fill when implementing)

| # | Test | Result |
| --- | --- | --- |
| 1 | `alembic upgrade head` | |
| 2 | Tables exist in `app` | |
| 3 | Mirror includes seed + Keycloak built-ins / service accounts | |
| 4 | `realm-admin` id = JWT `sub` | |
| 5 | Duplicate file_acl unique | |
| 6 | CHECK exactly one principal | |
| 7 | CHECK permission rejects `owner` | |
| 8 | CASCADE file delete | |
| 9 | RESTRICT role delete with ACL | |
| 10 | Second `init_services` idempotent | |
| 11 | `/health` and `/auth/me` still work | |

---

## Human checks (environment)

- [ ] Postgres container healthy; `.env` `APP_USER` / `APP_PASSWORD` / `APP_DB` match compose.
- [ ] `cd backend && uv run alembic upgrade head` from a machine that can reach `localhost:5432`.
- [ ] Keycloak already has seed users (auth slice). If not, run init_services Keycloak step first.

---

## Follow-on (not this slice)

| Task | Needs from this schema |
| --- | --- |
| 3 Search platform | `file_id` UUID string; ACL **names** for DLS; viewer and editor both readable |
| 4 Ingest | Insert `files` metadata only; **no** auto `file_acl` (G3). Chunks → OpenSearch only |
| 5 View files / Open | Query `files` + `file_acl` using JWT role/group names; editor implies viewer |
| 6 Admin | Dual-write identity; assign viewer/editor to roles/groups (default viewer); hide `is_system` in pickers |
| Later connectors | Import source ACL onto `user`/`role`/`group` + widen permission CHECK with `owner` / `deleter` |

---

## ER

```
users 1──* user_roles *──1 roles
users 1──* user_groups *──1 groups
files 1──* file_acl
file_acl 0..1 users | 0..1 roles | 0..1 groups   (exactly one)
```

No `files.uploaded_by`. No chunks in Postgres.
