---
status: implemented
title: Pass 1 — ingest-service auth and schema
date: 2026-09-28
notes: Implemented with the internal ingest slice. Product truth is prompt_2/current.md. Do not edit prompts/.
---

# Pass 1 — ingest-service auth and schema

Parent: `prompt_2/internal_ingest_plan.md` (T1, T2). Next: `pass_2_file_ingest.md`.

This pass adds the Keycloak client and the Postgres tables. It does not add `/internal` routes, connector routes, or UI.

## Goal

A confidential client `ingest-client` can obtain an access token with `aud=api-client` and realm role `ingest-service`. Alembic revision after `c3d4e5f6a7b8` widens `files.ingestion_type` and creates `ingest_jobs`, `connectors`, and `connector_syncs`.

## Do not

- Mount `/internal` or `/admin/connectors` routes.
- Grant `ingest-service` the realm roles `admin` or `search-user`, or any `realm-management` client role.
- Map `ingest-service` onto OpenSearch `files_searcher` or `files_writer`. Leave `docker_service_configs/opensearch` role mappings alone.
- Auto-grant `file_acl` to the service account. Identity sync may insert a `users` row for `service-account-ingest-client`. That row gets no product roles and no file grants.
- Reuse `api-client` or `KEYCLOAK_API_SECRET` for ingest.
- Edit `prompts/`. Update `prompt_2/current.md` or root `README.md`.

## Why both realm.json and init

Keycloak imports `docker_service_configs/keycloak/realm.json` only into an empty realm database. A running stack will not pick up a JSON edit on restart. Fresh imports need the client in `realm.json`. Existing realms need the same client created idempotently in `backend/init_services/keycloak.py`.

## Auth

### Realm

Add realm role `ingest-service` next to `admin` and `search-user` in `docker_service_configs/keycloak/realm.json`. Description: machine ingest and connector status callbacks. Not a product user.

Add confidential client `ingest-client`:

| Setting | Value |
| --- | --- |
| `publicClient` | false |
| `secret` | `ingest-client-secret` (local demo; real value is `KEYCLOAK_INGEST_SECRET`) |
| `serviceAccountsEnabled` | true |
| `standardFlowEnabled` | false |
| `directAccessGrantsEnabled` | false |
| `authorizationServicesEnabled` | false |
| PKCE | off |

Protocol mappers, copied from `api-client` in the same file:

- `realm-roles-flat` → claim `roles`
- `groups` → claim `groups`, `full.path: false`
- `audience-api-client` → `included.client.audience: api-client`, access token only

`defaultClientScopes` includes `basic` so the token has `sub`. `decode_access_token` in `backend/app/core/security.py` already requires `aud=api-client` and the realm issuer. Do not change that verifier.

### Init (`backend/init_services/keycloak.py`)

`CLIENT_IDS` is `("api-client", "web-client")`. Extend it with `ingest-client`.

Add an idempotent ensure step, same style as `_ensure_api_client_service_account_roles`:

1. If `ingest-client` is missing, create it with the settings above and the three mappers. If it exists, do not rotate a secret the operator already set.
2. Ensure realm role `ingest-service` exists.
3. Load the service-account user. Assign realm role `ingest-service` only. Remove `admin` and `search-user` if they are present. Do not assign `realm-management` roles.
4. Ensure default client scope `basic` (the existing `_ensure_basic_scope` loop covers every id in `CLIENT_IDS`).
5. Confirm direct access grants stay off.

`_get_clients` currently raises if a `CLIENT_IDS` entry is missing. Creation must run before that lookup, or the lookup must create `ingest-client` first.

### Settings and env

In `backend/app/core/config.py`:

- `keycloak_ingest_client_id: str = "ingest-client"`
- `keycloak_ingest_secret: str = ""` from `KEYCLOAK_INGEST_SECRET`

Add `KEYCLOAK_INGEST_SECRET=ingest-client-secret` to `backend/.env.sample`. Add `KEYCLOAK_INGEST_SECRET` to `_ROOT_ENV_KEYS` in `setup/lib/env.sh`. An existing root `.env` will not be overwritten by setup; the human must add the key. The test gate checks the live `.env`.

### Dependency

Add `require_ingest_service` in `backend/app/api/deps.py`.

- Missing or invalid Bearer → 401 (same path as `get_current_user`).
- Token without realm role `ingest-service` → 403.
- Realm `admin` or `search-user` without `ingest-service` → 403. Do not treat `admin` as a bypass.
- Do not forward this token to OpenSearch. `user_bearer_header` stays the search path only.

Leave the function unused by routers until pass 2. That is expected.

## Schema

New Alembic revision. Suggested id `d4e5f6a7b8c9`. `down_revision = "c3d4e5f6a7b8"`. Hand-written, matching `backend/alembic/versions/c3d4e5f6a7b8_search_query_metrics.py`. Register models so `alembic/env.py` sees them via `import app.models`.

### `files`

Drop and recreate `ck_files_ingestion_type`. Allowed values:

`local`, `sharepoint`, `google_drive`, `s3`, `postgresql`, `oracle`, `sqlserver`, `salesforce`, `azure`, `gcs`, `email`, `box`, `sap`, `pipeline`.

Mirror the same CHECK on `File` in `backend/app/models/file.py`.

Partial unique index `uq_files_ingestion_source` on `(ingestion_type, original_source)` WHERE `original_source IS NOT NULL`. HTTP upload leaves `original_source` null, so those rows stay outside the index. The folder CLI sets `original_source` and `ingestion_type=local`; two CLI rows with the same relative path would then conflict. That is acceptable: internal re-sync reuses `file_id` on that pair. Do not change the folder CLI in this pass.

### `ingest_jobs`

No foreign key to `files`. Reserve must insert a job before any `files` row exists (`object_store_path` is `NOT NULL`).

| Column | Notes |
| --- | --- |
| `id` | UUID PK |
| `file_id` | UUID, not null, not an FK |
| `object_store_path` | not null |
| `ingestion_type` | not null, same CHECK values as `files` |
| `original_source` | not null |
| `filename` | not null |
| `size_bytes` | bigint, not null |
| `status` | `reserved`, `completed`, `failed`, `expired` |
| `error` | text, null |
| `created_at`, `updated_at` | timestamptz, server default now |
| `completed_at` | timestamptz, null |

Index `(file_id, created_at)`. Model module `backend/app/models/ingest_job.py`. Export from `backend/app/models/__init__.py`.

### `connectors`

Do not add a config or password column. Source secrets are forwarded once in pass 3 and never stored.

| Column | Notes |
| --- | --- |
| `id` | UUID PK |
| `type` | not null. UI catalog types plus `google_drive`. Not a Postgres ENUM. |
| `name` | not null |
| `enabled` | bool, not null, default false |
| `schedule` | text, null |
| `pipeline_connector_id` | text, null until the pipeline accepts the create |
| `status` | `pending`, `idle`, `syncing`, `success`, `failed` |
| `last_sync_at` | timestamptz, null |
| `last_error` | text, null |
| `created_at`, `updated_at` | timestamptz |

### `connector_syncs`

| Column | Notes |
| --- | --- |
| `id` | UUID PK |
| `connector_id` | UUID FK → `connectors.id` ON DELETE CASCADE |
| `status` | `syncing`, `success`, `failed` |
| `started_at` | timestamptz, not null |
| `finished_at` | timestamptz, null |
| `files_count` | int, null |
| `error` | text, null |

Model module `backend/app/models/connector.py` for both tables.

## Tasks

- [x] Add realm role `ingest-service` and client `ingest-client` to `docker_service_configs/keycloak/realm.json` (service account on, direct grants off, audience mapper `api-client`, `basic` scope).
- [x] Extend `backend/init_services/keycloak.py` so an existing realm gets the same client, mappers, and service-account role. Do not grant `realm-management`.
- [x] Add `KEYCLOAK_INGEST_SECRET` to `backend/app/core/config.py`, `backend/.env.sample`, and `setup/lib/env.sh`. Put the key in the live root `.env` (setup will not overwrite it).
- [x] Add `require_ingest_service` in `backend/app/api/deps.py`. Do not mount routes.
- [x] Alembic `d4e5f6a7b8c9`: widen `ck_files_ingestion_type`, partial unique `(ingestion_type, original_source)`, tables `ingest_jobs`, `connectors`, `connector_syncs`.
- [x] SQLAlchemy models and `__init__` exports. CHECK on `File` matches the migration.
- [x] Run the test gate below. Do not start pass 2 if any step fails.

## Shipped

Gate passed 28 Sep 2026 on the running Compose stack. No `/internal` routes. `prompt_2/current.md` and root `README.md` are unchanged until pass 4.

What changed:

- `docker_service_configs/keycloak/realm.json`: realm role `ingest-service`, confidential client `ingest-client` (service account on, direct grants and PKCE off, audience mapper `api-client`, `basic` scope). A restart does not import this into a realm that already exists.
- `backend/init_services/keycloak.py`: idempotent create of that client, the three mappers, and realm role `ingest-service` on the service account. Removes `admin` and `search-user` if present. Does not grant `realm-management`. Does not rotate a secret that is already set.
- `KEYCLOAK_INGEST_SECRET` in `backend/app/core/config.py`, `backend/.env.sample`, and `setup/lib/env.sh`. The live root `.env` has `KEYCLOAK_INGEST_SECRET=ingest-client-secret`. Setup will not add it to an existing `.env`.
- `require_ingest_service` in `backend/app/api/deps.py`. Missing bearer is 401. A token without `ingest-service` is 403, including `admin` and `search-user`. No router calls it yet.
- Alembic `d4e5f6a7b8c9` and models `IngestJob`, `Connector`, `ConnectorSync`. `files.ingestion_type` allows `local` plus the connector types through `pipeline`. Partial unique index `uq_files_ingestion_source` on `(ingestion_type, original_source)` where `original_source` is not null. `ingest_jobs.file_id` is not a foreign key.

Identity sync may insert `service-account-ingest-client`. That row gets `ingest-service` and Keycloak's default realm roles, not `admin` or `search-user`, and no `file_acl`. OpenSearch `files_searcher` stays mapped to `search-user` only.

The service-account token's `roles` also include `offline_access`, `uma_authorization`, and `default-roles-enterprise-search-realm`. Those are Keycloak defaults. The gate only requires `ingest-service` present and `admin` / `search-user` absent.

Local note: creating `uq_files_ingestion_source` fails if two `files` rows already share `(ingestion_type, original_source)`. On this machine, repeated folder-CLI runs of `notes.txt`, `nested/export.csv`, and `nested/q1.pdf` (no ACL) were collapsed to the earliest row of each path before the upgrade. The migration does not delete rows.

## Test gate

Stack up. `.env` is in the repo root, not in `backend/`. The script below upgrades the schema, ensures the Keycloak client, and checks the token. It prints `PASS`. Inserts are rolled back. A Postgres collation warning is harmless. `/internal` 403 is pass 2, after the routes exist.

```bash
set -euo pipefail
cd /home/aditya/repos/my_enterprise_search
set -a
source .env
set +a

echo "== upgrade =="
(cd backend && uv run alembic upgrade head)
rev=$(cd backend && uv run alembic current 2>/dev/null)
echo "$rev"
echo "$rev" | grep -q 'd4e5f6a7b8c9' || { echo "FAIL alembic not at d4e5f6a7b8c9"; exit 1; }

echo "== keycloak =="
(cd backend && uv run python -m init_services)

echo "== schema =="
docker compose exec -T postgres psql -U "$APP_USER" -d "$APP_DB" -v ON_ERROR_STOP=1 <<'SQL'
SELECT indexdef FROM pg_indexes WHERE indexname = 'uq_files_ingestion_source';
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_indexes
    WHERE indexname = 'uq_files_ingestion_source'
      AND indexdef ILIKE '%UNIQUE%'
      AND indexdef ILIKE '%original_source IS NOT NULL%'
  ) THEN
    RAISE EXCEPTION 'partial unique index missing';
  END IF;
  IF EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'ingest_jobs'::regclass AND contype = 'f'
  ) THEN
    RAISE EXCEPTION 'ingest_jobs must not have a foreign key';
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'ck_files_ingestion_type'
      AND pg_get_constraintdef(oid) LIKE '%pipeline%'
      AND pg_get_constraintdef(oid) LIKE '%local%'
  ) THEN
    RAISE EXCEPTION 'files ingestion_type check was not widened';
  END IF;
  IF to_regclass('public.ingest_jobs') IS NULL
     OR to_regclass('public.connectors') IS NULL
     OR to_regclass('public.connector_syncs') IS NULL THEN
    RAISE EXCEPTION 'ingest tables missing';
  END IF;
END $$;
BEGIN;
INSERT INTO files (id, object_store_path, file_type, size_bytes, ingestion_type)
VALUES (gen_random_uuid(), 'pass1-gate-' || gen_random_uuid()::text, 'txt', 1, 'local');
INSERT INTO files (id, object_store_path, file_type, size_bytes, ingestion_type, original_source)
VALUES (gen_random_uuid(), 'pass1-gate-sp-' || gen_random_uuid()::text, 'txt', 1, 'sharepoint', 'pass1-gate-src');
DO $$
BEGIN
  INSERT INTO files (id, object_store_path, file_type, size_bytes, ingestion_type, original_source)
  VALUES (gen_random_uuid(), 'pass1-gate-dup-' || gen_random_uuid()::text, 'txt', 1, 'sharepoint', 'pass1-gate-src');
  RAISE EXCEPTION 'duplicate original_source was inserted';
EXCEPTION WHEN unique_violation THEN
  NULL;
END $$;
ROLLBACK;
SQL

echo "== tokens =="
ingest_json=$(curl -fsS -X POST "${KEYCLOAK_URL:-http://localhost:8080}/realms/enterprise-search-realm/protocol/openid-connect/token" \
  -d grant_type=client_credentials \
  -d client_id=ingest-client \
  -d client_secret="$KEYCLOAK_INGEST_SECRET")
admin_json=$(curl -fsS -X POST "${KEYCLOAK_URL:-http://localhost:8080}/realms/enterprise-search-realm/protocol/openid-connect/token" \
  -d grant_type=password \
  -d client_id=api-client \
  -d client_secret="$KEYCLOAK_API_SECRET" \
  -d username=realm-admin \
  -d password=adminpass)
python3 - "$ingest_json" "$admin_json" <<'PY'
import base64, json, sys
def claims(body):
    token = json.loads(body).get("access_token")
    if not token:
        raise SystemExit("token response had no access_token")
    part = token.split(".")[1]
    part += "=" * ((4 - len(part) % 4) % 4)
    return json.loads(base64.urlsafe_b64decode(part))
ing = claims(sys.argv[1])
adm = claims(sys.argv[2])
aud = ing.get("aud")
aud = aud if isinstance(aud, list) else [aud]
roles = ing.get("roles") or []
admin_roles = adm.get("roles") or []
print("ingest aud", aud)
print("ingest roles", roles)
print("realm-admin roles", admin_roles)
assert "api-client" in aud, aud
assert "ingest-service" in roles, roles
assert "admin" not in roles and "search-user" not in roles, roles
assert "ingest-service" not in admin_roles, admin_roles
assert "admin" in admin_roles and "search-user" in admin_roles, admin_roles
print("PASS")
PY
```
