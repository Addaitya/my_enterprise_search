# Hybrid search + DLS on OpenSearch 3.8 — issue, solution, and update plan

Working note for **staying on OpenSearch 3.8.0** while still shipping product search (Task 5). This file is the **source of truth for the G1 override**: client-side hybrid on 3.8. Updates Task 5 plan G1 in `prompts/cursor_summary/8_search_view_api.md` and corrects WAIT language in `prompts/summary/*`.

Do **not** search as basic `admin`. Do **not** ship keyword-only as the only product path.

**Status:** Solution chosen for local/v1 on 3.8 — **client-side hybrid** (two user-JWT queries + merge in FastAPI). Native OS `hybrid` query remains the long-term target after 3.9+.

**Human override (29 Aug 2026):** G1 WAIT is lifted for product `POST /search` **via this workaround**, not via OpenSearch upgrade. Platform native-hybrid proofs in `init_services/search_proof.py` stay **BLOCKED** on 3.8 (truth of the cluster). Product search ships on the FastAPI merge path.

---

## Problem (simple)

Product needs **both**:

1. **ACL** — search as the user’s JWT so OpenSearch DLS hides chunks they cannot see.
2. **Hybrid** — keyword (BM25) **and** semantic (neural), then blend scores.

On **3.8**, DLS wraps the query. Native `hybrid` **must** stay top-level. The wrap turns it into a boolean/constant-score query → crash:

`BooleanQuery cannot be cast to HybridQuery`

| Mode | User JWT + DLS on 3.8 |
| --- | --- |
| `match` only | Works (proved) |
| `neural` only | Works (proved) |
| Native `hybrid` + `search_pipeline=enterprise-search-hybrid` | **Broken** |

Upstream fix: OpenSearch Security [PR #6416](https://github.com/opensearch-project/security/pull/6416) / neural-search hybrid+DLS work → expected in **3.9+**. Official `opensearchproject/opensearch:3.9.0` not on Docker Hub yet (as of 29 Aug 2026).

Forum / issues: [forum thread](https://forum.opensearch.org/t/hybrid-search-not-working-with-document-level-security/24239), [neural-search #1303](https://github.com/opensearch-project/neural-search/issues/1303).

**Contradiction this plan resolves**

| Doc | Current statement | After this plan |
| --- | --- | --- |
| `prompts/summary/4_search_layer.md` | Task 5 `POST /search` **WAIT** until 3.9+ | Product search unblocked via client hybrid; native still BLOCKED |
| `prompts/summary/5_local_ingestion_setup.md` | Task 5 still WAIT on hybrid+DLS | Point to this workaround |
| `prompts/cursor_summary/8_search_view_api.md` | G1 WAIT; Search API blocked; C2 = native hybrid body; C9 = 503 | G1 = client hybrid; C2 = two queries + merge; C9 fail OS errors as 502 |
| Task 3 human lock | Do not ship workaround | **Overridden** for product path only; still no keyword-only / admin search |

---

## Chosen solution: two searches + merge (client-side hybrid)

Stay on **3.8**. Keep **user JWT** on every OpenSearch call (DLS still applies). **Do not** send a native `hybrid` query for product `POST /search`.

```
Client                    FastAPI                         OpenSearch (user JWT)
  │                          │
  │  POST /search {q}        │
  │─────────────────────────►│
  │                          ├── match query  ──────────► DLS OK
  │                          ├── neural query ──────────► DLS OK  (parallel)
  │                          │
  │                          ├── min_max normalize each hit list
  │                          ├── arithmetic_mean weights [0.3, 0.7]
  │                          ├── union by chunk _id, sort, top N
  │                          ├── strip embedding
  │◄─────────────────────────┤ SearchResponse DTO
```

This matches the pattern OpenSearch maintainers suggest when hybrid cannot run as one request (e.g. [neural-search #914](https://github.com/opensearch-project/neural-search/issues/914) — run subqueries separately, normalize/combine outside OpenSearch).

### Why this is acceptable

- Still **hybrid product behavior** (keyword + neural + same weights as the search pipeline).
- Still **user JWT** → DLS unchanged (no admin bypass).
- No OpenSearch version bump required for Task 5.
- Swap later to native `hybrid` behind the same API when 3.9 works.

### What this is not

- Not keyword-only product search.
- Not “search as admin then filter in Postgres.”
- Not changing ingest, index mapping, or DLS role YAML for this workaround.
- Not declaring `init_services.search_proof` native hybrid **PASS** (platform truth stays BLOCKED).

---

## Algorithm (implement exactly)

### Constants (match existing search pipeline)

From `docker_service_configs/opensearch/search-pipeline.json`:

| Setting | Value |
| --- | --- |
| Normalization | `min_max` |
| Combination | `arithmetic_mean` |
| Weights | keyword **0.3**, neural **0.7** |
| Neural `k` | **50** (same as Task 3 hybrid body) |

Settings knobs (add to `backend/app/core/config.py`):

| Setting | Default | Purpose |
| --- | --- | --- |
| `search_keyword_weight` | `0.3` | Match pipeline weight |
| `search_neural_weight` | `0.7` | Match pipeline weight |
| `search_fetch_multiplier` | `5` | `fetch_size = min(cap, size * multiplier)` so merge has enough candidates |
| `search_max_fetch` | `100` | Cap over-fetch (protect OS + latency) |
| `search_default_size` | `10` | API default |
| `search_max_size` | `50` | API clamp |
| `search_snippet_chars` | `400` | DTO snippet truncation |
| `search_mode` | `client_hybrid` | Flip to `native_hybrid` after 3.9 proofs |
| `opensearch_model_id` | from runtime JSON | Already exists — required for neural |

Do **not** require `opensearch_search_pipeline` for the `client_hybrid` path (pipeline unused until `native_hybrid`).

### Query A — keyword (user JWT)

```http
POST /enterprise-search-chunks/_search
Authorization: Bearer <user access token>

{
  "size": <fetch_size>,
  "query": { "match": { "content": "<q>" } },
  "_source": { "excludes": ["embedding"] }
}
```

No `search_pipeline` (not hybrid).

### Query B — neural (user JWT)

```http
POST /enterprise-search-chunks/_search
Authorization: Bearer <user access token>

{
  "size": <fetch_size>,
  "query": {
    "neural": {
      "embedding": {
        "query_text": "<q>",
        "model_id": "<opensearch_model_id>",
        "k": 50
      }
    }
  },
  "_source": { "excludes": ["embedding"] }
}
```

### Merge

1. Run A and B **in parallel** (same Bearer via `user_bearer_header`).
2. For each list, `min_max` normalize `_score` → `[0, 1]`.
   - If one hit or all scores equal: normalized score = `1.0` for those hits (empty list → nothing to merge).
3. Build map `_id` → `{ source fields, score_kw?, score_nn? }`.
4. Combined score = `0.3 * score_kw + 0.7 * score_nn` (missing side = `0`).
5. Sort by combined score desc; take top `size` (API request size).
6. Map to Task 5 search DTO (C3 in `8_search_view_api.md`); never include `embedding`.

### Pseudocode

```python
async def client_hybrid_search(q: str, size: int, headers: dict) -> list[Hit]:
    fetch = min(SEARCH_MAX_FETCH, size * SEARCH_FETCH_MULTIPLIER)
    kw_resp, nn_resp = await asyncio.gather(
        os_search(match_body(q, fetch), headers),
        os_search(neural_body(q, fetch, model_id), headers),
    )
    kw = min_max_normalize(hits(kw_resp))
    nn = min_max_normalize(hits(nn_resp))
    merged = {}
    for h in kw:
        merged[h.id] = {**h, "s_kw": h.norm, "s_nn": 0.0}
    for h in nn:
        row = merged.setdefault(h.id, {**h, "s_kw": 0.0, "s_nn": 0.0})
        row["s_nn"] = h.norm
        # prefer richer _source if needed
    scored = [
        (0.3 * r["s_kw"] + 0.7 * r["s_nn"], r)
        for r in merged.values()
    ]
    scored.sort(key=lambda t: t[0], reverse=True)
    return [to_dto(score, r) for score, r in scored[:size]]
```

### Error handling

| Case | Behavior |
| --- | --- |
| Either OS call 401/403 | API **502** (token rejected by OS — rare after FastAPI verify) |
| Either OS call 5xx / timeout | API **502** with clear detail; do **not** return partial ranked list as if complete |
| Empty / whitespace `q` | **400** |
| `model_id` missing | **503** config error |
| Native ClassCast on 3.8 | Must **not** happen on default path (`client_hybrid` never sends `hybrid`) |

Do **not** fall back to keyword-only on neural failure without a logged/explicit flag — v1 fail the request.

### Product API contract (unchanged shape)

- `POST /search` body: `{ "q": "<string>", "size": 10 }` (size clamped 1..50).
- Response: Task 5 C3 DTO (`q`, `took_ms`, `total`, `hits[]` with snippet, no `embedding`).
- Auth: `require_product_user` + forward same Bearer to both OS calls.

---

## Example

Index (DLS):

| `_id` | Content | `allowed_roles` / `allowed_groups` |
| --- | --- | --- |
| `proof-role-search-user` | `alpha-proof-token` | roles: `search-user` |
| `proof-group-engineering` | `bravo-proof-token` | groups: `engineering` |
| `proof-nobody` | `charlie-proof-token` | empty |

User **searcher** (`search-user`, group `_empty`) calls `POST /search` with `q=alpha-proof-token`:

1. Match as searcher → can only see role doc → hit A.
2. Neural as searcher → same DLS → hit A (and not B/C).
3. Merge → return A only; no `embedding` in JSON.

Native hybrid as searcher on 3.8 would **error** instead of returning A.

---

# Detailed update plan

Goal: make every doc and code path agree that **product hybrid on 3.8 = client-side merge**, then implement Task 5 Search without waiting for OpenSearch 3.9.

## Phase 0 — Doc alignment (do first; no code yet)

Update plans/summaries so the next implementer does not re-block on G1 WAIT.

### Task D0.1 — This file is SoT

- [x] Keep problem + algorithm + landmines here.
- [ ] Treat checkboxes below as the execution backlog for the Search half of Task 5.

### Task D0.2 — `prompts/cursor_summary/8_search_view_api.md` (Task 5 plan)

Edit in place (do not fork a second plan):

| Section | Change |
| --- | --- |
| Agent rules / Hard gate G1 | Replace “do not ship until hybrid+DLS” with: ship `POST /search` via **client-side hybrid** per this file; native hybrid remains post-3.9. |
| G1 table | Lock option: **client hybrid on 3.8** (this doc). Drop “WAIT for official 3.9 before Search”. Keep “no keyword-only / no admin search”. |
| Dependency map | Search unblocked without OS upgrade. Diagram: parallel match + neural → merge, not `search_pipeline` on the hot path. |
| C2 | Product default = two queries + merge. Native hybrid body = `search_mode=native_hybrid` only after proofs. |
| C9 | Remove “503 `hybrid_dls_unavailable` / keep route unimplemented”. OS failures → **502**. Config missing model → **503**. |
| Architecture diagram | FastAPI runs match ∥ neural with `user_bearer_header`; merge; strip embedding. |
| Module notes | `opensearch_search.py` implements `client_hybrid_search`; optional `native_hybrid_search`. |
| API `POST /search` | Unblock (“Blocked until G1 clear” → “ships with client hybrid”). |
| Landmine 12 | Rephrase: do not call native hybrid on 3.8 hot path; client hybrid is OK. |
| Proofs 9–13 | No longer skip for G1 wait; prove **client** hybrid DLS hit/miss. Skip/print only if API not implemented yet. |
| Checklist §D / §E | Unblock. Replace “confirm native hybrid PASS” with “confirm client hybrid PASS; keep `search_proof` native as BLOCKED until 3.9”. |
| Changelog | Note G1 override → client hybrid. |

### Task D0.3 — `prompts/cursor_summary/2_project_overview_tasks.md`

- [ ] Task 5 bullet: change “proxies hybrid query” → “proxies **client-side hybrid** (match + neural + merge) with user JWT on 3.8; native hybrid after 3.9”.
- [ ] Do **not** mark Task 5 checkboxes done until code + proofs land.

### Task D0.4 — `prompts/summary/4_search_layer.md`

- [ ] Keep Task 3 facts (native hybrid BLOCKED, match/neural DLS PASS).
- [ ] Replace human-lock “Task 5 WAIT” with pointer: product path = `hybrid_search_issue_sol.md` (client hybrid); this summary still describes **platform** proofs only.
- [ ] Follow-on row for Task 5: remove WAIT; link this file.
- [ ] Do **not** rewrite proof table rows 8–11 to PASS for native hybrid.

### Task D0.5 — `prompts/summary/5_local_ingestion_setup.md`

- [ ] Drop “Task 5 still WAIT on hybrid+DLS (OS 3.9+)”.
- [ ] Say: ingest does not wait on Search; Search unblocked via client hybrid (link this file).

### Task D0.6 — Later summary (when Search ships)

- [ ] Write `prompts/summary/6_search_view.md` documenting client hybrid as shipped behavior (after Phase 2–3 code).
- [ ] Optional stub note in `4_search_layer.md` / `5_local_ingestion_setup.md` “see summary 6”.

### Task D0.7 — Explicitly leave alone (docs)

| File | Why |
| --- | --- |
| `prompts/cursor_summary/6_search_setup.md` | Task 3 platform plan; native hybrid still the cluster contract for proofs |
| `init_services/search_proof.py` narrative as BLOCKED | Platform truth |
| `docker_service_configs/opensearch/search-pipeline.json` | Keep for future `native_hybrid` |
| `opesearch_version_update.md` (empty) | Out of scope; no version bump |

**Phase 0 exit:** A reader of `8_search_view_api.md` + this file knows Search is implementable now; `4_search_layer.md` no longer contradicts.

---

## Phase 1 — Backend settings + pure merge helpers

No OpenSearch HTTP yet beyond what unit tests mock.

### Task B1.1 — Settings

- [ ] Add to `backend/app/core/config.py`:
  - `search_keyword_weight: float = 0.3`
  - `search_neural_weight: float = 0.7`
  - `search_fetch_multiplier: int = 5`
  - `search_max_fetch: int = 100`
  - `search_default_size: int = 10`
  - `search_max_size: int = 50`
  - `search_snippet_chars: int = 400`
  - `search_mode: Literal["client_hybrid", "native_hybrid"] = "client_hybrid"` (or plain `str` with validation)
- [ ] Reuse existing `opensearch_index`, `opensearch_model_id`, `opensearch_url`.
- [ ] Do **not** require pipeline name for client path.

**Accept:** Settings load; defaults match pipeline weights.

### Task B1.2 — Normalize + merge unit tests

- [ ] Implement pure functions (same module or `opensearch_search.py`):
  - `min_max_normalize(scores) -> norms`
  - `merge_hybrid_scores(kw_hits, nn_hits, w_kw, w_nn) -> ranked list`
- [ ] Unit tests (no OS):
  - equal scores → all 1.0
  - single hit → 1.0
  - missing side contributes 0
  - weights 0.3/0.7 applied
  - sort order + top-N trim
  - union by `_id`

**Accept:** Tests green without Docker.

---

## Phase 2 — OpenSearch search service + `POST /search`

### Task B2.1 — `app/services/opensearch_search.py`

- [ ] `search_match(q, size, headers)` — match on `content`; `_source.excludes: ["embedding"]`.
- [ ] `search_neural(q, size, headers, model_id)` — neural on `embedding`; `k=50`.
- [ ] `client_hybrid_search(q, size, headers)` — parallel gather, normalize, merge, map fields.
- [ ] Optional stub/`native_hybrid_search` behind `search_mode` (must not be default on 3.8).
- [ ] Always use caller-supplied headers from `user_bearer_header` — never basic admin.
- [ ] Map OS hit → C3 fields: `file_id`, `chunk_id`, `chunk_seq`, `score`, `snippet`, `meta_file_type`, `object_store_path`, `display_name` (basename), `uploaded_at`.
- [ ] Double-strip `embedding` if present.

**Accept:** Callable from a script/REPL with a real searcher token returns DLS-correct hits for `alpha-proof-token`.

### Task B2.2 — Schemas + route

- [ ] `app/schemas/search.py` — `SearchRequest`, `SearchHit`, `SearchResponse`.
- [ ] `app/api/routes/search.py` — `POST /search`:
  - Auth: `require_product_user`
  - Validate empty `q` → 400
  - Clamp `size`
  - If `opensearch_model_id` missing → 503
  - Dispatch on `search_mode` (default client hybrid)
  - Measure `took_ms`
- [ ] Wire into `app/api/router.py`.

**Accept:** `curl` with searcher Bearer:

```bash
# expect 200, hits include proof-role-search-user, no embedding key
curl -sS -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"q":"alpha-proof-token","size":10}' http://localhost:8000/search
```

### Task B2.3 — Fail-closed errors

- [ ] Map OS 401/403/5xx/timeout → API 502 (no silent keyword-only).
- [ ] Never catch ClassCast by falling back on the default path (default path must not send hybrid).

**Accept:** Kill neural path (bad model id) → 502/503, not a keyword-only 200.

---

## Phase 3 — Proofs (product layer)

### Task P3.1 — `scripts/search_view_proof.py` (or search-only module)

Extend Task 5 proof driver; search cases no longer `[skip] hybrid_dls_wait`:

| # | Test | Expect |
| --- | --- | --- |
| S1 | `POST /search` no token | 401 |
| S2 | searcher + `q=alpha-proof-token` | hit `proof-role-search-user`; no `embedding` |
| S3 | searcher does not see `bravo-proof-token` / `charlie-proof-token` docs | miss group-only + empty ACL |
| S4 | realm-admin + group proof token / content | hit `proof-group-engineering` |
| S5 | empty `q` | 400 |
| S6 | `/health` + `/auth/me` regression | 200 |

- [ ] Run after API is up: `uv run python -m scripts.search_view_proof` (or agreed module path).
- [ ] Optional debug: log that both subqueries ran — not required if DLS hit/miss holds.

### Task P3.2 — Keep platform proof separate

- [ ] `init_services/search_proof.py` native hybrid attempt remains **BLOCKED** on 3.8.
- [ ] Do **not** “fix” platform hybrid by calling client merge inside `init_services`.
- [ ] Interim match/neural DLS proofs in `search_proof` stay as-is.

**Phase 3 exit:** Product proofs S1–S6 PASS; `search_proof` still reports native hybrid BLOCKED.

---

## Phase 4 — Frontend Search (Task 5 E)

Contract unchanged; only unblock UI.

### Task F4.1

- [ ] `frontend/src/api/search.ts` — `POST /search` via existing authenticated client.
- [ ] `Search.tsx` — enable input; show hits (snippet, score, Open using file content helper when View/Open exists).
- [ ] No “search unavailable on 3.8” banner for this workaround.
- [ ] Error UI for 400/502/503.

**Accept:** Manual smoke as searcher: query `alpha-proof-token` → see role proof hit.

**Note:** View files / Open (Task 5 A–C) remain independent; Search Open button needs content route if that half is not done yet — either implement Open later or show results without Open until G2 path lands.

---

## Phase 5 — Close the loop (docs after code)

### Task D5.1

- [ ] Write `prompts/summary/6_search_view.md` (what shipped, client hybrid, proofs).
- [ ] Flip Task 5 search-related boxes in `2_project_overview_tasks.md` only when Search API + UI + proofs done.
- [ ] Check off items in `8_search_view_api.md` §D/§E.
- [ ] Changelog rows in this file + `8_search_view_api.md`.

---

## Recommended execution order (summary)

```
1. Phase 0  — Doc alignment (8_search_view_api, summaries 4+5, overview Task 5 wording)
2. Phase 1  — Settings + unit-tested merge math
3. Phase 2  — opensearch_search.py + POST /search
4. Phase 3  — Product proofs on proof-* fixtures
5. Phase 4  — React Search page
6. Phase 5  — summary/6_search_view.md + checkbox flips
```

View/Open (Task 5 A–C in `8_search_view_api.md`) can run **in parallel** with Phases 1–4; they do not depend on hybrid. Prefer finishing ACL list/open if Search Open is required for UI smoke.

---

## Master checklist (copy status here)

### Docs

- [x] D0.2 `8_search_view_api.md` G1/C2/C9/diagram/proofs/§D unblocked
- [x] D0.3 `2_project_overview_tasks.md` Task 5 wording
- [x] D0.4 `summary/4_search_layer.md` WAIT → client-hybrid pointer
- [x] D0.5 `summary/5_local_ingestion_setup.md` WAIT removed
- [x] D5.1 `summary/6_search_view.md` after ship

### Backend

- [x] B1.1 Settings knobs
- [x] B1.2 Normalize/merge unit tests
- [x] B2.1 `opensearch_search.py` client hybrid
- [x] B2.2 Schemas + `POST /search` + router
- [x] B2.3 Fail-closed errors

### Proofs / UI

- [x] P3.1 Product search proofs (no G1 skip)
- [x] P3.2 Platform native hybrid still BLOCKED
- [x] F4.1 React Search wired

### Explicitly do not change

- [x] Ingest / chunker / MinIO upload
- [x] Auto-ACL on upload
- [x] Searching with basic `admin`
- [x] Dropping neural or keyword from the product merge
- [x] Deleting `proof-*` docs
- [x] OpenSearch image bump / DLS YAML / `filter-level` DLS mode
- [x] Declaring `search_proof` native hybrid PASS via app merge

---

## Comparison of options (decision record)

| Option | Stay 3.8? | User JWT + DLS? | Hybrid behavior? | Notes |
| --- | --- | --- | --- | --- |
| **Client-side two-query merge (CHOSEN)** | Yes | Yes | Yes (app-normalized) | Extra latency; parallel helps |
| Wait for official 3.9 | Yes until then | Yes | Native | Blocks Task 5 search — **rejected for product** |
| Staging 3.9 image | Maybe | Yes | Native | Non-GA risk — not required |
| Keyword- or neural-only product | Yes | Yes | No | Rejected (Task 3 C4) |
| Admin search + app ACL filter | Yes | No (bypass DLS) | Native hybrid possible | Rejected |

---

## Landmines specific to this workaround

1. **Forgetting parallel fetch size** — merge with `size=10` only from each side under-recalls vs real hybrid; use multiplier + max fetch cap.
2. **Partial failure** — if neural fails and you silently return keyword-only, you violated the product contract; fail closed.
3. **Admin token for either subquery** — forbidden; both must use `user_bearer_header`.
4. **Calling native hybrid “just to try” on the hot path** — will 500 every searcher request on 3.8; only use behind `search_mode=native_hybrid` after proofs.
5. **Double-counting / wrong weights** — must match pipeline `[0.3, 0.7]` and min_max, not raw score sum.
6. **Assuming search pipeline runs on match/neural** — it does not; pipeline is for native hybrid only. Client owns normalization.
7. **Doc drift** — leaving “WAIT until 3.9” in summaries after shipping client hybrid will re-block the next agent; Phase 0 is mandatory.
8. **Conflating platform vs product proofs** — green `POST /search` does not mean `search_proof` native hybrid PASS.

---

## Exit ramp (later, not this slice)

When official 3.9+ is pinned and `search_proof` native hybrid **PASS**:

1. Set `search_mode=native_hybrid` (or make it default).
2. Single OS request with `hybrid` + `search_pipeline=enterprise-search-hybrid`.
3. Keep client-hybrid code path as fallback for one release if desired.
4. Update this file + Task 5 / summary 6: “workaround retired.”

---

## Changelog

| Date | Change |
| --- | --- |
| 29 Aug 2026 | Document issue + choose client-side hybrid for 3.8; list required plan/code/proof updates for Task 5. |
| 29 Aug 2026 | Expand into detailed phased update plan + task backlog (doc alignment, settings, service, API, proofs, UI, exit criteria); record G1 override vs summary WAIT language. |
| 29 Aug 2026 | **Implemented:** settings, `opensearch_search.py`, `POST /search`, unit + product proofs S1–S6, React Search; summary `6_search_view.md` + dump `summary/hybrid_search_issue.md`. Platform native hybrid still BLOCKED. |
