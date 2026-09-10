# 13 — Access Control rename, Dashboard stats, Configuration page

**Implemented 10 September 2026.** Source of truth: `prompts/cursor_summary/13_changes.md`.

Builds on shipped search, local ingest, admin 6a/6b, and 12a/12b. Ingestion pipeline is **not** started — last three dashboard stats stay API constants until then.

---

## What “done” means (this slice)

A signed-in realm **`admin`** can:

1. Open navbar **Access Control(Admin)** (was **Admin**) and still manage users / roles / groups / file access. URL stays `/admin`.
2. Open navbar **Dashboard** and see six stats (three live from backend, three placeholders). Avg query time is labeled **last 24 hours**.
3. Open navbar **Configuration** and see the placeholder text `this is configuration.`

Non-admin: **403** on `GET /admin/stats`; no Dashboard / Access Control(Admin) / Configuration links; deep-link `/dashboard` / `/configuration` / `/admin` shows **Forbidden**. Unauthenticated `GET /admin/stats` → **401**.

---

## What shipped

### Backend

| Piece | Location |
| --- | --- |
| Migration | `backend/alembic/versions/c3d4e5f6a7b8_search_query_metrics.py` (revises `b2c3d4e5f6a7`) |
| Model | `backend/app/models/search_metrics.py` (`SearchQueryMetric`) — exported from `app/models/__init__.py` |
| Persist | `backend/app/services/search_metrics.py` — `record_search_metric(took_ms)` opens its own session |
| Search hook | `backend/app/api/routes/search.py` — `BackgroundTasks` after successful hybrid search only |
| MinIO | `MinioStore.sum_object_sizes()` — recursive list + sum; empty → `0`; errors → `MinioStatsError` (not 0) |
| Schema | `backend/app/schemas/admin_stats.py` (`AdminStatsOut`) |
| Service | `backend/app/services/admin_stats.py` |
| Route | `backend/app/api/routes/admin_stats.py` — `GET /admin/stats`, `require_admin`; MinIO fail → **502** |
| Mount | `backend/app/api/router.py` |

`search_query_metrics`: `id` UUID PK, `took_ms` INTEGER NOT NULL, `created_at` TIMESTAMPTZ DEFAULT now(), index on `created_at`. Unbounded (H9). No query text.

Live stats on read:

- `avg_query_time_ms` = `AVG(took_ms)` where `created_at >= now() - interval '24 hours'` (`null` if empty window)
- `total_data_ingested_bytes` = MinIO bucket `enterprise-search-files` object-size sum
- `total_docs_indexed` = `COUNT(*) FROM files`

Placeholders (backend constants, `placeholders.* = true`):

- `active_connectors` = `8`
- `ingestion_rate_docs_per_hour` = `12400`
- `last_sync` = `"2 min ago"` (static string; not a timestamp)

DTO example:

```json
{
  "avg_query_time_ms": 142.0,
  "total_data_ingested_bytes": 17739212,
  "total_docs_indexed": 16,
  "active_connectors": 8,
  "ingestion_rate_docs_per_hour": 12400,
  "last_sync": "2 min ago",
  "placeholders": {
    "active_connectors": true,
    "ingestion_rate_docs_per_hour": true,
    "last_sync": true
  }
}
```

OpenSearch is **not** queried for these stats. Postgres errors stay 500. Failed searches are not recorded (they never reach the insert).

### Frontend

| Piece | Location |
| --- | --- |
| API client | `frontend/src/api/stats.ts` — `getAdminStats()` |
| Dashboard | `frontend/src/pages/Dashboard.tsx` — six cards, `/dashboard` |
| Configuration | `frontend/src/pages/Configuration.tsx` — body `this is configuration.` |
| Routes | `frontend/src/App.tsx` — both wrapped in existing `AdminRoute` |
| Navbar | `frontend/src/components/layout/Navbar.tsx` |
| Admin h1 | `frontend/src/pages/Admin.tsx` — **Access Control(Admin)** only |

Navbar (admin): Search | Upload | View files | **Dashboard** | **Access Control(Admin)** | **Configuration**

UI formatting (from API values, not hardcoded 8 / 12400 / `"2 min ago"`):

- Avg card title: **Avg query time (last 24 hours)**; `null` → `—`
- Bytes → B / KB / MB / GB
- Rate → locale `12,400 docs/hr`
- Last sync rendered as the API string as-is

Unchanged on purpose: URL `/admin`, `Admin.tsx` filename, `AdminRoute`, backend `/admin/*` identity/ACL APIs, inner tab **Access**.

---

## Proofs run (10 Sep 2026)

`backend/scripts/admin_stats_proof.py`

```bash
cd backend
uv run alembic upgrade head
uv run python -m scripts.admin_stats_proof
```

| # | Result |
| --- | --- |
| 1 | no token `GET /admin/stats` → **401** |
| 2 | non-admin product user → **403** |
| 3 | `realm-admin` → **200**; docs=16, bytes=17739212, placeholders 8 / 12400 / `"2 min ago"`; avg was `null` before a persisted search |
| 4 | `POST /search` `took_ms=142` then BackgroundTasks insert; re-GET avg=`142.0` |

MinIO helper also checked off-API: `sum_object_sizes()` on `enterprise-search-files` → `17739212`; missing bucket raises `MinioStatsError` (not 0).

**Note on proof 2:** seed user `searcher` currently has realm role `admin` in this local Keycloak (likely from 12b experiments), so `/auth/admin-ping` as searcher is 200. The proof falls back to minting **`qa-stats-user`** / `qa-stats-pass` with only `search-user` and asserts 403 on that account.

Vite production bundle of the SPA succeeded (`vite build`). `tsc -b` still fails on a **pre-existing** error in `src/components/admin/MembersSection.tsx` (unrelated to this slice).

---

## Browser checks (10 Sep 2026)

Logged in as **`realm-admin`**:

- Navbar shows Dashboard, Access Control(Admin), Configuration
- `/dashboard` six cards: 142 ms (last 24 hours), 16.92 MB, 16 docs, 8 connectors, `12,400 docs/hr`, `2 min ago`
- `/configuration` body **this is configuration.**
- `/admin` h1 **Access Control(Admin)**; tabs Users / Roles / Groups / Access unchanged

Logged in as **`qa-stats-user`** (search-user only):

- Navbar: Search, Upload, View files only (no three admin links)
- `/dashboard` and `/configuration` → **Forbidden** / Admin role required

---

## Human test guide

Stack: Postgres, MinIO, OpenSearch, Keycloak, API `http://localhost:8000`, UI `http://localhost:5173` (`./start-dev.sh` or equivalent).

1. **Migrate**

   ```bash
   cd backend
   uv run alembic upgrade head
   ```

   Confirm `alembic_version` is `c3d4e5f6a7b8` and table `search_query_metrics` exists.

2. **Automated proofs** (API must be running **after** this code, reload is enough with `start-dev.sh`)

   ```bash
   cd backend
   uv run python -m scripts.admin_stats_proof
   ```

   Expect four `[ok]` lines then `=== all admin stats proofs passed ===`.

3. **Admin UI** — login as `realm-admin` / `adminpass`

   - Navbar order after View files: Dashboard, Access Control(Admin), Configuration.
   - **Dashboard:** six cards. The avg card must say **last 24 hours**. If nobody has searched since the migration, avg shows `—`. Run a Search, click Dashboard **Refresh** — avg becomes a number (ms). **Total no. of docs indexed** should match uploaded **files** (not OpenSearch chunks). **Total data ingested** is MinIO size, not Postgres `SUM(size_bytes)`.
   - **Active connectors** = 8, **Ingestion rate** = 12,400 docs/hr, **Last sync** stays **2 min ago** on every refresh (placeholders).
   - **Access Control(Admin):** still `/admin`; Users / Roles / Groups / Access still work.
   - **Configuration:** page contains exactly `this is configuration.`

4. **Non-admin UI**

   - If `searcher` still has `admin` in this realm, do **not** use searcher for this check. Use `qa-stats-user` / `qa-stats-pass` (created by the proof), or any user with only `search-user`.
   - Those three nav links must be absent. Visiting `/dashboard`, `/configuration`, or `/admin` shows Forbidden.

5. **Unauthenticated API**

   ```bash
   curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/admin/stats
   ```

   Expect `401`.

6. **Optional MinIO 502 (H10)** — only if you want to see the failure path: stop MinIO and reload Dashboard / `GET /admin/stats` as admin. Expect **502**, not `0` bytes.

---

## Locked decisions honored

| ID | Lock |
| --- | --- |
| H1–H3 | Frontend label only: `Access Control(Admin)`. Path `/admin`, files, `AdminRoute`, APIs, Access tab unchanged. |
| H4 | Avg over successful searches in last 24 hours; card copy says last 24 hours; failures not stored. |
| H5 | Docs indexed = `COUNT(*) FROM files`. |
| H6 | Data ingested = MinIO recursive object-size sum. |
| H7 | `last_sync` is the literal `"2 min ago"`. |
| H8 | Dashboard + Configuration admin-only. |
| H9 | No purge job; unbounded table. |
| H10 | MinIO list/sum failure → **502** for the whole endpoint, not a fake 0. |

---

## Explicitly out of scope (still)

- Ingestion pipeline, Airbyte, Kafka, Spark, Tika
- Real active-connector count, real ingest rate, real last-sync timestamp
- Configuration forms / settings persistence
- Renaming backend `/admin/users` etc. or Keycloak clients
- Renaming `Admin.tsx`, `AdminRoute`, URL `/admin`, or the Access tab
- Changing Search / Upload / View files behavior (except recording successful `took_ms`)
- OpenSearch `_count` / index store size on the dashboard
- Native hybrid on OpenSearch 3.8 (unchanged)

---

## Follow-on

| Next | Needs from 13 |
| --- | --- |
| Ingestion pipeline | Swap placeholder constants in `admin_stats.py` for live connector / rate / last-sync; keep DTO + `placeholders` flags |
| Configuration | Replace placeholder copy with real forms |
| Metrics retention | Optional delete job if `search_query_metrics` grows; avg still last 24 hours |
| Identity hygiene | `searcher` currently has `admin` in this local realm — restore seed roles if 12b experiments should not stick |
