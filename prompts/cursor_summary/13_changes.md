# 13 — Access Control rename, Dashboard stats, Configuration page

Working notes to implement **admin nav + ops dashboard + configuration placeholder**. Product brief: `prompts/cursor_summary/2_project_overview_tasks.md`. Current status: `prompts/summary/` (search, ingest, admin 6a/6b, 12a/12b all shipped). Ingestion pipeline is **later** (`prompts/cursor_summary/12_ingestion_pipeline_proposal.md`) — last three dashboard stats stay hardcoded until then.

This file is the source of truth for this slice. Do **not** start the connector/ingestion pipeline, rename backend `/admin` identity/ACL APIs, or fill Configuration with real forms.

**Agent rules while implementing**

- Run and execute code to confirm it works before moving on.
- Do not proceed past a broken step; fix it first.
- Where something cannot be verified in this environment, leave a clear human check and wait for feedback.
- Treat **Locked decisions** in this file as law.

**Human locks (10 Sep 2026):** H1–H10 **LOCKED** as written below.

---

## What “done” means

A signed-in realm **`admin`** can:

1. Open navbar **Access Control(Admin)** (was **Admin**) and still manage users / roles / groups / file access. URL stays `/admin`.
2. Open navbar **Dashboard** and see six stats (three live from backend, three placeholders). Avg query time is labeled as **last 24 hours**.
3. Open navbar **Configuration** and see the placeholder text `this is configuration.`

| Actor | What they may do in this slice |
| --- | --- |
| FastAPI | `GET /admin/stats` (`require_admin`); persist successful search `took_ms` |
| React | `/dashboard`, `/configuration`; label Admin → **Access Control(Admin)** only |
| Postgres | new `search_query_metrics`; `COUNT(*)` on `files` |
| MinIO | sum object sizes in bucket `enterprise-search-files` |
| OpenSearch | **Not queried** for dashboard stats in this slice |
| Keycloak | **Unchanged** |

Non-admin → **403** on `/admin/stats` and no Dashboard / Access Control(Admin) / Configuration links. Unauthenticated → **401**. Search / Upload / View files stay as they are for all product users.

---

## Current state (do not re-scaffold)

| Layer | Today |
| --- | --- |
| React routes | `/` Search, `/upload`, `/files`, `/admin` |
| Navbar | Search, Upload, View files, **Admin** (admin only) — [`frontend/src/components/layout/Navbar.tsx`](../../frontend/src/components/layout/Navbar.tsx) |
| Admin page | h1 **Admin**; tabs Users \| Roles \| Groups \| Access — [`frontend/src/pages/Admin.tsx`](../../frontend/src/pages/Admin.tsx) |
| Admin gate | [`AdminRoute`](../../frontend/src/auth/AdminRoute.tsx) + `require_admin` |
| Search latency | `took_ms` computed in [`opensearch_search.py`](../../backend/app/services/opensearch_search.py), returned on `POST /search` — **not stored** |
| File rows | Postgres `files` (one row per successfully completed ingest) |
| Object bytes | MinIO bucket `enterprise-search-files` via [`MinioStore`](../../backend/app/services/minio_store.py) — list/sum **not** implemented yet |
| Connectors / last sync / ingest rate | **Do not exist** (pipeline later) |

Existing admin APIs (`/admin/users*`, `/admin/roles*`, `/admin/groups*`, `/admin/files*`, acl jobs) stay. This slice only **adds** stats + two pages + frontend label changes.

---

## Target surfaces

```
Navbar (admin)
  Search | Upload | View files | Dashboard | Access Control(Admin) | Configuration
                                              │                    │
                                              │                    └─ /configuration  (placeholder copy)
                                              └─ /admin           (identity + ACL; label only)

Dashboard /dashboard
        │
        ▼
GET /admin/stats  (require_admin)
        ├── AVG(search_query_metrics.took_ms) last 24 hours
        ├── MinIO bucket total object size
        ├── COUNT(*) FROM files
        └── hardcoded: active_connectors=8, rate=12400, last_sync="2 min ago"
```

---

## Requirements

Each requirement has a **solution** and **reason**. Locked human decisions are law.

### R1. Rename Admin page to Access Control(Admin)

**Solution (LOCKED H1–H3)**

- Navbar link text: **Admin → `Access Control(Admin)`** ([`Navbar.tsx`](../../frontend/src/components/layout/Navbar.tsx) `Link to="/admin"`).
- Page h1: **Admin → `Access Control(Admin)`** ([`Admin.tsx`](../../frontend/src/pages/Admin.tsx)).
- **No other changes:** URL stays `/admin`. Component stays `Admin.tsx`. `AdminRoute` name stays. Backend `/admin/*` prefixes stay. Inner tab **Access** stays **Access**. Subtitle unchanged unless it still says only “Admin” as a title (it does not).

**Reason**

Human: change the **frontend display name only** to `Access Control(Admin)`. Path, files, route guard, APIs, and the Access tab are out of scope.

---

### R2. Dashboard page with six stats (backend + frontend)

**Solution (page + API)**

- New React page [`frontend/src/pages/Dashboard.tsx`](../../frontend/src/pages/Dashboard.tsx): six stat cards, `AppShell`, same dark Tailwind as Admin.
- Route `/dashboard` wrapped in `AdminRoute` ([`App.tsx`](../../frontend/src/App.tsx)).
- Navbar **Dashboard** (admin only), placed **before** Access Control(Admin).
- New client [`frontend/src/api/stats.ts`](../../frontend/src/api/stats.ts): `getAdminStats()`.
- New backend `GET /admin/stats`, `require_admin`, mounted in [`backend/app/api/router.py`](../../backend/app/api/router.py).
- One DTO for all six fields. Live values computed on read. Last three are backend constants until the ingestion pipeline exists. Include `placeholders: true` (or per-field `is_placeholder`) so the UI does not hardcode those three.

**Reason**

User asked for both backend and frontend. A single stats endpoint keeps the SPA ready when the pipeline later fills real connector / rate / last-sync values. Cards match six KPIs.

**Who can see it (LOCKED H8):** realm role **`admin` only**. Same for Configuration.

---

#### R2.1 Avg query time (live) — last 24 hours

**Solution (LOCKED H4, H9)**

- `POST /search` already measures wall-clock `took_ms` around hybrid search.
- After a **successful** search, persist that `took_ms` into a new Postgres table via FastAPI `BackgroundTasks` so the insert does not change `took_ms` or block the response.

```
search_query_metrics
  id          UUID PK
  took_ms     INTEGER NOT NULL
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
```

- Index `created_at`. Alembic revision **after** `b2c3d4e5f6a7`. Export model from [`backend/app/models/__init__.py`](../../backend/app/models/__init__.py).
- Stats query: `AVG(took_ms)` where `created_at >= now() - interval '24 hours'`.
- Empty window → JSON `null`; UI shows `—` (or `n/a`).
- Do **not** record failed searches (4xx/5xx never produced a completed hybrid `took_ms`).
- **UI must say the window clearly**, e.g. card title **Avg query time (last 24 hours)** — not a bare “Avg query time”.
- Retention (H9): table is **unbounded** in this slice. The average is still only over the last 24 hours. No delete job.

**Reason**

Human locked the window to last 24 hours of queries. `took_ms` is the real product search latency. In-memory averages die on restart and disagree across workers. Unbounded insert + 24h `WHERE` avoids a cleanup job for v1.

---

#### R2.2 Total data ingested (live) — MinIO bucket size

**Solution (LOCKED H6)**

- Sum **object sizes present in MinIO**, bucket `enterprise-search-files` (settings `minio_bucket`).
- Use the existing MinIO Python client ([`MinioStore`](../../backend/app/services/minio_store.py)): `list_objects(bucket, recursive=True)` and sum each object’s `size`.
- Empty bucket → `0`.
- API returns **bytes** (`total_data_ingested_bytes`). UI formats for humans (KB / MB / GB).
- If MinIO is unreachable / list fails → **502** for the whole `/admin/stats` (H10). Do not silently show 0.

**Reason**

Human: KPI is data **in MinIO**, not Postgres `SUM(size_bytes)` and not OpenSearch store size. Listing the product bucket matches “what is actually stored” (including any object not mirrored in `files`, if that ever happens). Staging uploads live on local disk, not MinIO, so they are not counted.

---

#### R2.3 Total no. of docs indexed (live) — files, not chunks

**Solution (LOCKED H5)**

- `SELECT COUNT(*) FROM files` (Postgres). That is the number of **files** that completed ingest (a `files` row is written only after MinIO put + OpenSearch bulk in the current upload path).
- This is **not** OpenSearch chunk `_count`. One PDF still counts as **1**.
- Postgres down → normal 500 (DB dependency). No OpenSearch call for this field.

**Reason**

Human: “docs indexed” means **number of files indexed**, not chunk documents.

---

#### R2.4 Active connectors (placeholder)

**Solution**

- Backend constant `active_connectors = 8`.
- Mark as placeholder in the DTO.

**Reason**

No connector registry exists until the ingestion pipeline. Hardcoding in the **API** (not the React page) means one swap later.

---

#### R2.5 Ingestion rate (placeholder)

**Solution**

- Backend constant `ingestion_rate_docs_per_hour = 12400`.
- UI label: `12,400 docs/hr` (locale format ok).

**Reason**

Same as R2.4 — pipeline later. Do not invent a live rate now.

---

#### R2.6 Last sync (placeholder)

**Solution (LOCKED H7)**

- Backend returns a **static string** `last_sync: "2 min ago"`.
- Do **not** compute `now() - 2 minutes`, do not return an ISO timestamp, do not let the client format relative time.
- UI renders the API string as-is. It stays **2 min ago** on every refresh until the ingestion pipeline exists.

**Reason**

Human: keep the `2 min ago` value static. A timestamp would drift (“3 min ago”, …) and is not the requested placeholder.

---

#### Suggested stats DTO

```json
{
  "avg_query_time_ms": 142.5,
  "total_data_ingested_bytes": 10485760,
  "total_docs_indexed": 42,
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

`avg_query_time_ms` may be `null` (no successful searches in the last 24 hours). Round for display (integer ms or one decimal).

---

### R3. Configuration page (empty)

**Solution (LOCKED H8)**

- New [`frontend/src/pages/Configuration.tsx`](../../frontend/src/pages/Configuration.tsx).
- Body text **exactly**: `this is configuration.`
- Route `/configuration`, wrapped in `AdminRoute`.
- Navbar link **Configuration** (admin only), after Access Control(Admin).
- **No** backend route for this page.

**Reason**

User asked for an empty placeholder. Admin-only (H8). Exact copy avoids inventing extra placeholder prose. Path `/configuration` matches the label.

---

## Human decisions

| ID | Question | Status | Lock (10 Sep 2026) |
| --- | --- | --- | --- |
| **H1** | Access Control URL | **LOCKED** | Keep `/admin`. Frontend label only. |
| **H2** | Rename `Admin.tsx` / `AdminRoute` | **LOCKED** | No. Labels only. |
| **H3** | Inner ACL tab name | **LOCKED** | Keep **Access**. No other Admin-page changes. Visible name is **`Access Control(Admin)`**. |
| **H4** | Avg query window | **LOCKED** | Average of successful queries in the **last 24 hours**. UI must say **last 24 hours** on the card. Do not record failed searches. |
| **H5** | “Docs indexed” | **LOCKED** | **Number of files indexed** = `COUNT(*) FROM files`. Not OpenSearch chunks. |
| **H6** | “Total data ingested” | **LOCKED** | **MinIO** bucket object-size sum (`enterprise-search-files`). Not PG `size_bytes`, not OS store size. |
| **H7** | Last sync display | **LOCKED** | Static string `"2 min ago"`. No timestamp, no client relative time. |
| **H8** | Who sees Dashboard + Configuration | **LOCKED** | **Admin only.** |
| **H9** | Metrics retention | **LOCKED** | Unbounded table this slice; average still last 24 hours only. No delete job. |
| **H10** | Backing-store failure | **LOCKED** | **502** the whole `/admin/stats` rather than a fake 0. Originally written for OS `_count`; that call is gone after H5. Apply the same rule to **MinIO list/sum** (H6). Postgres errors stay 500. |

---

## Locked decisions (this slice)

### H1–H3. Frontend label only

| | |
| --- | --- |
| Status | **LOCKED** 10 Sep 2026 |
| Decision | Navbar + Admin h1 text = **`Access Control(Admin)`**. Do not change URL, filenames, `AdminRoute`, backend `/admin/*`, or the inner **Access** tab. |

### H4. Avg query time window

| | |
| --- | --- |
| Status | **LOCKED** 10 Sep 2026 |
| Decision | Mean `took_ms` over successful `POST /search` in the **last 24 hours**. Dashboard copy must state **last 24 hours**. Failed searches are not stored. |

### H5. Docs indexed = files

| | |
| --- | --- |
| Status | **LOCKED** 10 Sep 2026 |
| Decision | `COUNT(*) FROM files`. One ingested file = 1, regardless of chunk count. |

### H6. Data ingested = MinIO size

| | |
| --- | --- |
| Status | **LOCKED** 10 Sep 2026 |
| Decision | Sum sizes of objects in MinIO bucket `enterprise-search-files` (recursive list). |

### H7. Last sync is a static string

| | |
| --- | --- |
| Status | **LOCKED** 10 Sep 2026 |
| Decision | `last_sync` is always the literal `"2 min ago"` from the API. Do not compute or format a relative time. |

### H8. Admin-only ops pages

| | |
| --- | --- |
| Status | **LOCKED** 10 Sep 2026 |
| Decision | Dashboard and Configuration are visible and callable only with realm role `admin`. |

### H9. Metrics table retention

| | |
| --- | --- |
| Status | **LOCKED** 10 Sep 2026 |
| Decision | No purge in this slice. Keep inserting; filter last 24 hours at read time. |

### H10. Fail the stats endpoint, do not fake zero

| | |
| --- | --- |
| Status | **LOCKED** 10 Sep 2026 |
| Decision | If MinIO usage listing fails, `GET /admin/stats` returns **502**. Do not return `total_data_ingested_bytes: 0` as a stand-in for “MinIO down”. |

Shared invariants that already apply (do not reopen):

- Admin capability = Keycloak realm role `admin` (`require_admin` / `AdminRoute`).
- Search writes to OpenSearch still use internal basic admin, never user JWT.
- No Celery/Redis (G2 from admin plans). `BackgroundTasks` for metrics insert is enough.
- Do not invent connectors or last-sync from Airbyte in this slice.

---

## Implementation tasks

Order is dependency order. Check a box only after the step has been run.

### Backend

- [ ] Alembic: `search_query_metrics` (revises `b2c3d4e5f6a7`); `alembic upgrade head`
- [ ] Model + export in `app/models`
- [ ] Record `took_ms` from successful `post_search` via `BackgroundTasks` ([`search.py`](../../backend/app/api/routes/search.py))
- [ ] Schema `AdminStatsOut` (or similar) in `app/schemas/`
- [ ] `MinioStore` helper (or stats service): recursive list + sum object sizes; empty → 0; errors raise for 502
- [ ] Service: PG `AVG` last 24h, PG `COUNT(files)`, MinIO sum, hardcoded 8 / 12400 / `"2 min ago"`
- [ ] Route `GET /admin/stats` + include router
- [ ] Proof: unauth 401; searcher 403; admin 200; after one successful `POST /search`, avg is non-null (or document empty-window `null` then search then re-GET)

### Frontend

- [ ] `frontend/src/api/stats.ts`
- [ ] `Dashboard.tsx` — six cards; **Avg query time (last 24 hours)** labeled clearly; format bytes and `docs/hr`; `—` when avg is null
- [ ] `Configuration.tsx` — text `this is configuration.`
- [ ] Routes in `App.tsx`: `/dashboard`, `/configuration` + `AdminRoute`
- [ ] Navbar: Dashboard, **Access Control(Admin)**, Configuration — admin only
- [ ] Admin page h1 **Access Control(Admin)** only (no tab/URL/file rename)

### Docs / proofs

- [ ] `backend/scripts/` proof driver for stats auth + smoke (follow existing `admin_*_proof.py` style)
- [ ] After **code** ships: dump status under `prompts/summary/` (not required for this plan-only write)

---

## File map (expected)

| Path | Role |
| --- | --- |
| `backend/alembic/versions/<new>_search_query_metrics.py` | table |
| `backend/app/models/search_metrics.py` (or similar) | SQLAlchemy |
| `backend/app/schemas/admin_stats.py` | DTO |
| `backend/app/services/admin_stats.py` | assemble stats |
| `backend/app/services/minio_store.py` | add list/sum sizes (keep put/get as they are) |
| `backend/app/api/routes/admin_stats.py` | `GET /admin/stats` |
| `backend/app/api/routes/search.py` | enqueue metrics insert |
| `backend/app/api/router.py` | mount |
| `frontend/src/api/stats.ts` | client |
| `frontend/src/pages/Dashboard.tsx` | UI |
| `frontend/src/pages/Configuration.tsx` | placeholder |
| `frontend/src/App.tsx` | routes |
| `frontend/src/components/layout/Navbar.tsx` | links + **Access Control(Admin)** |
| `frontend/src/pages/Admin.tsx` | h1 **Access Control(Admin)** only |

---

## Out of scope

- Ingestion pipeline, Airbyte, Kafka, Spark, Tika
- Real active-connector count, real ingest rate, real last-sync timestamp
- Configuration form fields / settings persistence
- Renaming backend `/admin/users` etc. or Keycloak clients
- Renaming `Admin.tsx`, `AdminRoute`, URL `/admin`, or the Access tab
- Changing Search / Upload / View files behavior
- Native hybrid on OpenSearch 3.8 (unchanged)
- OpenSearch `_count` / index store size on the dashboard

---

## Notes for the coding agent

- Do **not** call OpenSearch for these stats. Files = Postgres count. Bytes = MinIO list/sum.
- Do not log query text in `search_query_metrics` (latency only).
- Keep Configuration copy **exact**: `this is configuration.`
- Visible Admin name is exactly **`Access Control(Admin)`** (no extra spaces unless human asks).
- Avg query card copy must include **last 24 hours**.
- Do not hardcode 8 / 12400 / “2 min ago” in React if the API already returns them. Last sync stays the static API string; do not convert it to a timestamp.
- MinIO 502: wrap list errors; do not catch and return 0.
