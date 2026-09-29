---
status: implemented
title: Pass 3 reference — connector control plane and live stats
date: 2026-09-28
notes: Implementation record and retest guide. Not product truth. Product truth is prompt_2/current.md. Ship dump is prompt_2/internal_ingest_log.md.
---

# Pass 3 reference — connector control plane and live stats

Parent plan: `prompt_2/internal_ingest_plan.md` (T5, T6, T8). Spec: `prompt_2/internal_ingest/pass_3_connectors_stats.md`.

Gate passed 28 Sep 2026 on the running Compose stack. From `backend/`:

- `uv run python -m scripts.admin_stats_proof` printed `=== all admin stats proofs passed ===`
- `uv run python -m scripts.internal_ingest_proof` printed `PASS file ingest` and then `PASS connectors`

This pass adds the admin connector routes, the pipeline status callback, and live values for three dashboard stats. It does not add a pipeline service. Configuration UI and the product-truth edits landed in pass 4.

## What the routes do

Admins create, update, list, and sync connectors through FastAPI. FastAPI calls `INGESTION_PIPELINE_URL`. The pipeline reports status to `/internal`. The SPA does not call the pipeline.

`config` is a string-keyed object of catalog field values. It is forwarded on create and update and is not a Postgres column. GET responses never include `config`, and the client does not send the admin JWT or the ingest JWT.

Create inserts a `connectors` row only after the pipeline returns a string `id`. If that insert then fails, the response is 502 and the detail says the pipeline may keep an orphan connector. There is no delete call on the contract.

Sync inserts a `connector_syncs` row, sets the connector to `syncing`, commits, then calls the pipeline. A 502/503 marks that sync row `failed` and leaves it as history. A 2xx leaves the row `syncing` until the status callback closes it.

`GET /admin/stats` reads Postgres for connector count, completed `ingest_jobs` in the last hour, and the latest `connectors.last_sync_at`. It does not query OpenSearch. MinIO failure is still 502 for the whole stats response.

## Settings

In `backend/app/core/config.py`:

| Setting | Env | Default |
| --- | --- | --- |
| `ingestion_pipeline_url` | `INGESTION_PIPELINE_URL` | empty |
| `ingestion_pipeline_timeout_seconds` | `INGESTION_PIPELINE_TIMEOUT_SECONDS` | `10` |

Both keys are comments in `backend/.env.sample`. They are not required keys in `setup/lib/env.sh`. The live root `.env` was not changed. Leave the URL empty on the API at `:8000`. The proof's 502 case starts its own API.

Empty or whitespace URL → 503 `ingestion pipeline URL is not configured`. One httpx attempt. No retries.

| Condition | FastAPI |
| --- | --- |
| DNS, connect, timeout | 502 `ingestion pipeline unreachable` or `ingestion pipeline request timed out` |
| Pipeline status not 2xx | 502 `ingestion pipeline returned HTTP <code>`. The pipeline body is not copied. |
| Create 2xx body has no string `id` | 502 `ingestion pipeline create response missing string id`, and no local row |

## Pipeline contract

Documented on `backend/app/services/ingestion_pipeline.py`. The other side is not in this repo.

| Call | Request | Success |
| --- | --- | --- |
| `POST {base}/connectors` | `type`, `name`, `enabled`, `schedule`, `config` | JSON object with string `id` |
| `PATCH {base}/connectors/{pipeline_id}` | same fields, all optional | 2xx, body ignored |
| `POST {base}/connectors/{pipeline_id}/sync` | `{}` | 2xx, body ignored |

## Admin routes

Router `backend/app/api/routes/admin_connectors.py`, prefix `/admin`, tag `admin-connectors`, `require_admin` on every route. Schemas in `backend/app/schemas/admin_connectors.py`. Orchestration in `backend/app/services/admin_connectors.py`.

GET list and GET one return `id`, `type`, `name`, `enabled`, `schedule`, `pipeline_connector_id`, `status`, `last_sync_at`, `last_error`, `created_at`, `updated_at`. No `config`.

`POST /admin/connectors` body: `type` and `name` are required non-empty strings (whitespace is 422). `enabled` defaults false. `schedule` is optional. `config` defaults `{}`. Unknown types are accepted; the React catalog is not an allowlist. After the pipeline returns an id, the row is `idle` when `enabled` else `pending`, with `last_sync_at` and `last_error` null. Response 201 uses the GET shape.

`PATCH /admin/connectors/{id}` needs at least one of `name`, `enabled`, `schedule`, `config`. 404 when missing. 409 `connector has no pipeline id` when `pipeline_connector_id` is null. The pipeline is called first. On 502/503 the local row is unchanged. `config` is not written locally.

`POST /admin/connectors/{id}/sync` is 404 or 409 on the same conditions. Success is 202 `{ "sync_id", "status": "syncing" }`.

`GET /admin/connectors/{id}/syncs` is newest first: `id`, `connector_id`, `status`, `started_at`, `finished_at`, `files_count`, `error`.

## Status callback

`POST /internal/connectors/{id}/status` on the internal router. `require_ingest_service`. `id` is our connector UUID, not `pipeline_connector_id`.

Body (`extra` forbidden): `status` (`success` or `failed`), optional `files_count`, `error`, `started_at`, `finished_at`.

404 when the connector is missing. Updates `connectors.status`, sets `last_error` null on success (otherwise the body's `error`), and sets `last_sync_at` from `finished_at` or now. Closes the newest `connector_syncs` row with `status=syncing` by setting `status`, `finished_at`, `files_count`, and `error`. `started_at` is accepted and not written. If no row is `syncing`, the connector still updates and the response is 200. The callback does not insert a sync row.

Response 200 is the connector GET shape.

## Live stats

`placeholders.active_connectors`, `placeholders.ingestion_rate_docs_per_hour`, and `placeholders.last_sync` are false. The three old constants (`8`, `12400`, `"2 min ago"`) are gone.

| Field | Value |
| --- | --- |
| `active_connectors` | `COUNT(*)` from `connectors` where `enabled` is true. `0` when none are enabled. |
| `ingestion_rate_docs_per_hour` | `COUNT(*)` from `ingest_jobs` where `status=completed` and `completed_at` is in the last hour. `files.updated_at` is not counted. |
| `last_sync` | Latest `connectors.last_sync_at` as ISO-8601 UTC, or the string `—` (U+2014) when none. The field stays a string. |

`avg_query_time_ms`, `total_data_ingested_bytes`, and `total_docs_indexed` are unchanged.

`frontend/src/pages/Dashboard.tsx` already sets the Placeholder badge from `stats.placeholders.*`. Those three cards lose the badge. p99, searches today, and total sources stay hardcoded placeholders. The connector-status table and the index-distribution bars stay placeholders too. Configuration is still the local shell.

## Files touched

| Path | Change |
| --- | --- |
| `backend/app/core/config.py` | Pipeline URL and timeout. |
| `backend/.env.sample` | Commented defaults. Not required by setup. |
| `backend/app/services/ingestion_pipeline.py` | httpx client and the contract docstring. |
| `backend/app/schemas/admin_connectors.py` | Create, update, GET, sync, and status models. `extra=forbid` on writes. |
| `backend/app/services/admin_connectors.py` | Mirror, sync history, status callback. |
| `backend/app/api/routes/admin_connectors.py` | Admin routes. |
| `backend/app/api/router.py` | Registers that router. |
| `backend/app/api/routes/internal_ingest.py` | `POST /internal/connectors/{id}/status`. |
| `backend/app/services/admin_stats.py` | Live connector, rate, and last-sync values. |
| `backend/app/schemas/admin_stats.py` | Placeholder flags default false. |
| `backend/scripts/admin_stats_proof.py` | Proof 3 matches SQL. A temporary completed job must raise the rate by 1. |
| `backend/scripts/internal_ingest_proof.py` | Connector cases after the file half. |

Not changed: React, `prompt_2/current.md`, root `README.md`, `prompt_2/context/`, `prompts/`.

## Proof result

Commands, from `backend/`, with the stack and `./start-dev.sh` already up. `INGESTION_PIPELINE_URL` unset. Port `8013` free. The stats proof ran first.

```text
[ok] 1: unauth GET /admin/stats → 401
[ok] 2: searcher GET /admin/stats → 403
[ok] 3: admin GET /admin/stats → 200 docs=39 bytes=32232621 connectors=0 rate=6 last_sync='—' avg=None
[ok] 4: POST /search wall-clock took_ms=986 then avg_query_time_ms=368.0 (OpenSearch took; may differ from API took_ms)
=== all admin stats proofs passed ===
```

`rate=6` was the SQL count of `ingest_jobs` completed in the last hour on this machine (earlier pass 2 completes). The proof asserts equality with that query, then inserts one completed job, asserts the rate increases by 1, and deletes the job. `connectors=0` and `last_sync='—'` because no connector rows were left.

```text
PASS file ingest
[ok] connectors 1 empty pipeline URL is 503 and connectors count is unchanged
[ok] connectors 2 unreachable pipeline is 502 and inserts nothing
[ok] connectors 3 status callback closes the open sync; realm-admin is 403
PASS connectors
```

The file half is unchanged. Connector step 3 inserts a row in SQL, checks GET list and GET one for the keys `config`, `password`, `secret`, and `token`, then deletes the row. A Postgres collation warning is harmless.

Before those scripts, a throwaway stub on `127.0.0.1:8765` plus an API on `:8013` also checked the happy path: 201 create (unknown type allowed, `pending` when disabled, `idle` when enabled), PATCH 500 leaves the name unchanged, sync 502 marks the sync row `failed`, sync 202 leaves it `syncing`, and the status callback closes it. A create body without string `id` is 502 and inserts nothing. The stub saw no `Authorization` header. A local `POST /files/uploads` of `pass3-local.txt` did not insert `ingest_jobs` and did not change the rate. That file is a normal local upload and is still in the bucket.

# Test guide

Use this when you need to re-check pass 3 later. Do not start pass 4 if either script fails.

## What must already be running

- Compose: Postgres, Keycloak, MinIO, OpenSearch (`docker compose up -d`).
- API on `http://localhost:8000` (`./start-dev.sh`). Code changes reload under `start-dev.sh`.
- Root `.env` with `KEYCLOAK_INGEST_SECRET` (pass 1). Demo value `ingest-client-secret`.
- Pass 1 migration `d4e5f6a7b8c9` applied (`cd backend && uv run alembic upgrade head`).
- `INGESTION_PIPELINE_URL` unset in the environment of the API on `:8000`. An empty default is what the 503 step needs. Do not put the URL in the root `.env` for this gate.
- Port `8013` free. The connector proof binds a second API there and then stops it.

## Automated gate

```bash
cd /home/aditya/repos/my_enterprise_search/backend
uv run python -m scripts.admin_stats_proof
uv run python -m scripts.internal_ingest_proof
```

Expect exit code 0, `=== all admin stats proofs passed ===`, `PASS file ingest`, and `PASS connectors`.

What the stats proof checks:

1. No bearer on `GET /admin/stats` → 401.
2. `searcher` (or a stand-in product user) → 403.
3. `realm-admin` → 200. `active_connectors` equals `SELECT count(*) FROM connectors WHERE enabled`. `ingestion_rate_docs_per_hour` equals completed `ingest_jobs` in the last hour. `last_sync` is `—` or a string that parses as ISO-8601. All three `placeholders` flags are false. One inserted completed job raises the rate by 1; the proof deletes that row.
4. A successful `POST /search` makes `avg_query_time_ms` non-null.

What the connector steps check, after the file half:

1. `POST /admin/connectors` on `:8000` → 503, and `connectors` count is unchanged.
2. The same POST against the short-lived API on `:8013` with `INGESTION_PIPELINE_URL=http://127.0.0.1:9` → 502, no new row, and the response does not echo the config value.
3. A SQL-inserted connector with an open sync row. `realm-admin` on `POST /internal/connectors/{id}/status` → 403. The ingest token sets `status=success`, `last_sync_at`, and `last_error` null, and closes that sync row (`files_count` included). GET list and GET one contain none of `config`, `password`, `secret`, `token`. The row is deleted afterward.

## Manual walkthrough

From the repo root, with `.env` loaded:

```bash
set -a
source .env
set +a
KC="${KEYCLOAK_URL:-http://localhost:8080}/realms/enterprise-search-realm/protocol/openid-connect/token"

admin=$(curl -fsS -X POST "$KC" \
  -d grant_type=password \
  -d client_id=api-client \
  -d client_secret="$KEYCLOAK_API_SECRET" \
  -d username=realm-admin \
  -d password=adminpass | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')

ingest=$(curl -fsS -X POST "$KC" \
  -d grant_type=client_credentials \
  -d client_id=ingest-client \
  -d client_secret="$KEYCLOAK_INGEST_SECRET" | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')
```

Empty URL on the API you started with `./start-dev.sh`:

```bash
curl -sS -D - -o /tmp/pass3-create.json -X POST http://localhost:8000/admin/connectors \
  -H "Authorization: Bearer $admin" -H 'Content-Type: application/json' \
  -d '{"type":"s3","name":"manual-empty","config":{"password":"do-not-store"}}'
python3 -m json.tool /tmp/pass3-create.json
```

Expect HTTP 503 and a detail that the pipeline URL is not configured. `SELECT count(*) FROM connectors` stays the same. The body must not contain `do-not-store`.

Stats, still with no connector rows:

```bash
curl -fsS http://localhost:8000/admin/stats -H "Authorization: Bearer $admin" | python3 -m json.tool
```

Expect `active_connectors` 0, `last_sync` equal to `—`, and all three `placeholders` values false. `ingestion_rate_docs_per_hour` matches completed `ingest_jobs` in the last hour. It is not required to be 0 if earlier file completes are still inside that window.

To see the rate move, insert one completed job and read stats again, then delete it. `APP_USER` and `APP_DB` come from `.env`.

```bash
docker compose exec -T postgres psql -U "$APP_USER" -d "$APP_DB" -c \
  "INSERT INTO ingest_jobs (id, file_id, object_store_path, ingestion_type, original_source, filename, size_bytes, status, completed_at)
   VALUES (gen_random_uuid(), gen_random_uuid(), 'files/pipeline/manual/rate.txt', 'pipeline', 'manual://rate', 'rate.txt', 4, 'completed', now());"

curl -fsS http://localhost:8000/admin/stats -H "Authorization: Bearer $admin" \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["ingestion_rate_docs_per_hour"])'

docker compose exec -T postgres psql -U "$APP_USER" -d "$APP_DB" -c \
  "DELETE FROM ingest_jobs WHERE original_source = 'manual://rate';"
```

The printed rate is one higher than the previous read. A small txt through `POST /files/uploads` (initiate, PUT, complete) must not change the rate and must not add an `ingest_jobs` row.

Status callback without a pipeline. Pick a new UUID:

```bash
CID=$(uuidgen)
SID=$(uuidgen)
docker compose exec -T postgres psql -U "$APP_USER" -d "$APP_DB" -c \
  "INSERT INTO connectors (id, type, name, enabled, pipeline_connector_id, status)
   VALUES ('$CID', 's3', 'manual-status', true, 'pipe-manual', 'idle');
   INSERT INTO connector_syncs (id, connector_id, status, started_at)
   VALUES ('$SID', '$CID', 'syncing', now());"

curl -sS -o /dev/null -w "%{http_code}\n" -X POST "http://localhost:8000/internal/connectors/$CID/status" \
  -H "Authorization: Bearer $admin" -H 'Content-Type: application/json' \
  -d '{"status":"success","files_count":1}'

curl -fsS -X POST "http://localhost:8000/internal/connectors/$CID/status" \
  -H "Authorization: Bearer $ingest" -H 'Content-Type: application/json' \
  -d '{"status":"success","files_count":2,"finished_at":"2026-09-28T12:00:00Z"}' | python3 -m json.tool
```

The admin call prints `403`. The ingest call returns 200, `status` `success`, `last_error` null, and `last_sync_at` at that timestamp. The sync row is `success` with `files_count` 2. Then delete the connector (`connector_syncs` cascades):

```bash
docker compose exec -T postgres psql -U "$APP_USER" -d "$APP_DB" -c \
  "DELETE FROM connectors WHERE id = '$CID';"
```

Happy path against a stub. This is not part of the automated gate. In one terminal:

```bash
python3 - <<'PY'
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
class H(BaseHTTPRequestHandler):
    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""
    def do_POST(self):
        self._body()
        body = b'{"id":"pipe-manual"}' if self.path == "/connectors" else b"{}"
        self.send_response(200 if self.path == "/connectors" else 202)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)
    def do_PATCH(self):
        self._body()
        self.send_response(204)
        self.end_headers()
    def log_message(self, *args):
        return
ThreadingHTTPServer(("127.0.0.1", 8765), H).serve_forever()
PY
```

In another terminal, from `backend/`, start an API that is not the one on `:8000`:

```bash
INGESTION_PIPELINE_URL=http://127.0.0.1:8765 uv run uvicorn app.main:app --host 127.0.0.1 --port 8013
```

Then:

```bash
curl -fsS -X POST http://127.0.0.1:8013/admin/connectors \
  -H "Authorization: Bearer $admin" -H 'Content-Type: application/json' \
  -d '{"type":"custom_widget","name":"manual-stub","enabled":false,"config":{"password":"secret"}}' \
  | python3 -m json.tool
```

Expect 201, `status` `pending`, `pipeline_connector_id` `pipe-manual`, and no `config` or `password` field. `enabled: true` on a second create returns `status` `idle`. PATCH `name`, then `POST /admin/connectors/{id}/sync`, and expect 202 with `status` `syncing`. Close it with the ingest token on `POST /internal/connectors/{id}/status`. Stop both extra processes when finished, and delete the `manual-stub` rows so later stats reads stay easy to interpret.

Stop the stub and point the same extra API at a closed port to see 502:

```bash
INGESTION_PIPELINE_URL=http://127.0.0.1:9 uv run uvicorn app.main:app --host 127.0.0.1 --port 8013
```

`POST /admin/connectors` returns 502 and does not insert a row.

Dashboard, in a browser, as `realm-admin` at `http://localhost:5173/dashboard`:

- Active connectors, Ingestion rate, and Last sync have no Placeholder badge. With no connectors those values are `0`, the current hourly rate, and `—`.
- p99 latency, Searches today, and Total sources still show Placeholder.
- The Connector status table and Index distribution still show Placeholder. Sync Now on that table is not wired.
- Configuration still says it is a local placeholder shell.

## Not covered here

- A real pipeline. Create, PATCH, and sync 2xx were checked against a local stub during implementation. The committed proof does not start that stub.
- Forced database failure after the pipeline accepts a create. The 502 orphan detail is implemented. The proof does not force the insert to fail.
- Configuration UI, and edits to `prompt_2/current.md`, the root README, and `prompt_2/context/`. Those are pass 4.
