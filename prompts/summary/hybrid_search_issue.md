# Hybrid search issue — changes dump (29 Aug 2026)

Implements `prompts/cursor_summary/hybrid_search_issue_sol.md`: product hybrid on OpenSearch **3.8** via **client-side merge** (match ∥ neural + user JWT). Native OS `hybrid` stays platform-BLOCKED.

Related summaries: `prompts/summary/6_search_view.md`, `prompts/summary/4_search_layer.md`, `prompts/summary/5_local_ingestion_setup.md`.

---

## Verdict

| Layer | Status |
| --- | --- |
| Product `POST /search` (client hybrid) | **Shipped + proved (S1–S6)** |
| React Search UI | **Shipped** (Open deferred — no content route yet) |
| Platform `search_proof` native hybrid | **Still BLOCKED** (expected) |
| View files / MinIO download | **Not in this slice** |

---

## Phase 0 — Doc alignment

| File | Change |
| --- | --- |
| `prompts/cursor_summary/8_search_view_api.md` | G1 → client hybrid override; C2 two-query + merge; C9 → 502/503; architecture diagram; landmine 12; proofs 9–12 unblocked; §D/§E checked; changelog |
| `prompts/cursor_summary/2_project_overview_tasks.md` | Task 5 wording → client-side hybrid; Search half checkboxes flipped |
| `prompts/summary/4_search_layer.md` | WAIT → pointer to client hybrid; follow-on row updated |
| `prompts/summary/5_local_ingestion_setup.md` | Removed Task 5 WAIT; link workaround |
| `prompts/summary/6_search_view.md` | **NEW** — shipped behavior + proofs |

Left alone (per plan): `6_search_setup.md`, `search_proof.py` BLOCKED narrative, `search-pipeline.json`, no OS version bump.

---

## Phase 1–2 — Backend

### Settings (`backend/app/core/config.py`)

Added defaults matching search pipeline:

- `search_keyword_weight=0.3`, `search_neural_weight=0.7`
- `search_fetch_multiplier=5`, `search_max_fetch=100`
- `search_default_size=10`, `search_max_size=50`, `search_snippet_chars=400`
- `search_mode=client_hybrid`, `search_neural_k=50`

### Service (`backend/app/services/opensearch_search.py`) — **NEW**

- `min_max_normalize`, `merge_hybrid_scores`, `hit_to_dto`
- `search_match` / `search_neural` (user Bearer headers only)
- `client_hybrid_search` — `asyncio.gather` + merge
- `native_hybrid_search` — optional; not default on 3.8
- `OpenSearchSearchError` → route maps to 502 (model missing → 503)

### API

- `backend/app/schemas/search.py` — `SearchRequest` / `SearchHit` / `SearchResponse`
- `backend/app/api/routes/search.py` — `POST /search` + `require_product_user` + `user_bearer_header`
- `backend/app/api/router.py` — include search router

### Offline tests

- `backend/scripts/search_unit_checks.py` — **PASS**

```text
[ok] settings defaults
[ok] min_max_normalize
[ok] merge_hybrid_scores
[ok] hit_to_dto
all search unit checks passed
```

---

## Phase 3 — Product proofs

- `backend/scripts/search_view_proof.py` — **NEW**; upserts `proof-*`, runs S1–S6
- **PASS:**

```text
[ok] S1 POST /search no token → 401
[ok] S2 searcher alpha → proof-role-search-user
[ok] S3 searcher misses bravo/charlie proof docs
[ok] S4 realm-admin bravo → proof-group-engineering
[ok] S5 empty/whitespace q → 400
[ok] S6 /health + /auth/me → 200
```

- Platform re-check: `uv run python -m init_services.search_proof` → `hybrid=BLOCKED`

---

## Phase 4 — Frontend

| Path | Change |
| --- | --- |
| `frontend/src/api/search.ts` | **NEW** — `searchFiles` via authenticated `apiPostJson` |
| `frontend/src/pages/Search.tsx` | Enabled input/submit; hit list (snippet, score); 400/502/503 errors; no “unavailable on 3.8” banner; Open omitted until content API |

---

## Explicitly unchanged

- Ingest / chunker / MinIO upload
- Auto-ACL on upload
- Searching with basic `admin`
- Dropping neural or keyword from merge
- Deleting `proof-*`
- OpenSearch image / DLS YAML / filter-level DLS
- Declaring platform native hybrid PASS via app merge

---

## Human test guide

### Prerequisites

- Docker stack up (`postgres`, `keycloak`, `opensearch`, `minio`)
- Backend on `:8000` (`./start-dev.sh` or `cd backend && uv run enterprise-search-api`)
- Frontend on Vite (often `:5173` / `:5174`)
- `opensearch_model_id` present in `backend/runtime_config.json` (from `init_services`)

### Automated (preferred)

```bash
cd backend
uv run python -m scripts.search_unit_checks
uv run python -m scripts.search_view_proof
# optional platform truth — expect hybrid=BLOCKED:
uv run python -m init_services.search_proof
```

### Manual API

```bash
# Get searcher token (password grant; use your .env client secret)
TOKEN=$(curl -sS -X POST 'http://localhost:8080/realms/enterprise-search-realm/protocol/openid-connect/token' \
  -d 'grant_type=password' -d 'client_id=api-client' -d "client_secret=$KEYCLOAK_API_SECRET" \
  -d 'username=searcher' -d 'password=searcherpass' | jq -r .access_token)

# Expect 200, hit proof-role-search-user, no embedding key
curl -sS -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"q":"alpha-proof-token","size":10}' http://localhost:8000/search | jq .

# Expect 400
curl -sS -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"q":"  "}' http://localhost:8000/search

# Expect 401
curl -sS -H 'Content-Type: application/json' -d '{"q":"alpha"}' http://localhost:8000/search
```

As **realm-admin**, query `bravo-proof-token` → expect `proof-group-engineering`.

### Manual UI

1. Open the SPA → log in as **searcher**.
2. On Search (`/`), type `alpha-proof-token` → Search.
3. Expect one hit for the role proof chunk; snippet visible; no crash/banner about 3.8.
4. Empty query → client or API validation error message.
5. Log in as **realm-admin** → search `bravo-proof-token` → group proof hit.

### What you should *not* see

- Keyword-only results when neural fails (should be **502**, not partial 200)
- `embedding` in JSON
- Native hybrid ClassCast on the default product path
- Platform `search_proof` reporting hybrid=PASS on 3.8

---

## Follow-ups

1. Task 5 A–C: `GET /files` + content stream → wire Search **Open**.
2. After OS 3.9 + native hybrid PASS: set `search_mode=native_hybrid`.
3. G3 seed for real-file search hits (uploaded files currently have empty `allowed_*`).

---

## Changelog

| Date | Change |
| --- | --- |
| 29 Aug 2026 | Full dump of client-hybrid implementation, proofs, UI, and human test guide. |
