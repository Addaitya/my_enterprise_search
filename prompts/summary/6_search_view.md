# Search view (product) — Task 5 Search half

Shipped **29 August 2026**. Product `POST /search` + React Search page on OpenSearch **3.8.0** via **client-side hybrid** (not native OS `hybrid`). View files / Open (list + MinIO stream) are **not** in this slice.

Plan SoT: `prompts/cursor_summary/8_search_view_api.md`  
Workaround SoT: `prompts/cursor_summary/hybrid_search_issue_sol.md`  
Change dump: `prompts/summary/hybrid_search_issue.md`

---

## What shipped

| Surface | Behavior |
| --- | --- |
| `POST /search` | Auth `require_product_user`; empty `q` → 400; missing `opensearch_model_id` → 503 |
| Client hybrid | Parallel **match** + **neural** with **user JWT**; min_max + weights **0.3 / 0.7**; union by `_id`; top `size` |
| Response | C3 DTO (`q`, `took_ms`, `total`, `hits[]`); **no** `embedding` |
| Errors | OS 401/403/5xx/timeout → **502** (fail closed; no keyword-only fallback) |
| React `/` | Enabled search input; results with snippet + score; 400/502/503 error UI |
| Open button | Deferred — `GET /files/{id}/content` not implemented yet |

`search_mode` default = `client_hybrid`. Optional `native_hybrid` exists but must not be default on 3.8.

---

## Why client hybrid

Native `hybrid` + DLS on 3.8 → `BooleanQuery cannot be cast to HybridQuery`. Match-only and neural-only DLS already PASS. Product still needs hybrid ranking + user JWT. Upstream fix expected on **3.9+** (security PR 6416).

---

## Proofs run

```bash
cd backend
uv run python -m scripts.search_unit_checks   # normalize/merge offline
uv run python -m scripts.search_view_proof    # S1–S6 product API
uv run python -m init_services.search_proof   # platform: hybrid=BLOCKED
```

| # | Test | Result |
| --- | --- | --- |
| Unit | settings defaults, min_max, merge, DTO strip | **PASS** |
| S1 | `POST /search` no token | **PASS** (401) |
| S2 | searcher + `alpha-proof-token` → `proof-role-search-user`, no embedding | **PASS** |
| S3 | searcher misses bravo/charlie proof docs | **PASS** |
| S4 | realm-admin + `bravo-proof-token` → `proof-group-engineering` | **PASS** |
| S5 | empty/whitespace `q` | **PASS** (400) |
| S6 | `/health` + `/auth/me` | **PASS** |
| Platform | native hybrid as JWT | **BLOCKED** (expected on 3.8) |

---

## Files

| Path | Role |
| --- | --- |
| `backend/app/core/config.py` | Search weight / fetch / mode knobs |
| `backend/app/services/opensearch_search.py` | match, neural, merge, client/native hybrid |
| `backend/app/schemas/search.py` | Request/response DTOs |
| `backend/app/api/routes/search.py` | `POST /search` |
| `backend/app/api/router.py` | Wire search router |
| `backend/scripts/search_unit_checks.py` | Offline merge tests |
| `backend/scripts/search_view_proof.py` | Live product proofs |
| `frontend/src/api/search.ts` | Authenticated `POST /search` |
| `frontend/src/pages/Search.tsx` | Results UI |

---

## Intentionally not done

- View files list / content stream / Search **Open** download → **done in** `prompts/summary/7_search_view_api.md`
- Native hybrid as product default
- Keyword-only or admin-bypass search
- Auto ACL on upload / Task 6 admin ACL UI
- Declaring `search_proof` native hybrid PASS

---

## Exit ramp (later)

When official 3.9+ is pinned and `search_proof` native hybrid **PASS**: set `search_mode=native_hybrid` (or make default), keep client path as fallback if desired, update this summary.

---

## Changelog

| Date | Change |
| --- | --- |
| 29 Aug 2026 | Client-hybrid `POST /search` + unit/product proofs + React Search; platform native hybrid remains BLOCKED. |
