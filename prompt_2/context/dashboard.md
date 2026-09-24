# Admin dashboard

Shipped. Source: `prompts/summary/13_changes.md`.

`GET /admin/stats` requires `admin`. MinIO failure is 502.

Live values:

- `avg_query_time_ms` — average of `search_query_metrics.took_ms` over the last 24 hours. `null` if the window is empty. `took_ms` is the OpenSearch `took` recorded in a background task after a successful `POST /search` only. No query text is stored. The table is unbounded.
- `total_data_ingested_bytes` — sum of object sizes in bucket `enterprise-search-files`. Empty bucket is 0. A MinIO error is not reported as 0.
- `total_docs_indexed` — `COUNT(*)` from `files`.

Placeholders (constants, `placeholders.* = true`): `active_connectors = 8`, `ingestion_rate_docs_per_hour = 12400`, `last_sync = "2 min ago"`. OpenSearch is not queried when stats are read.

Alembic `c3d4e5f6a7b8` revises the ACL jobs revision.
