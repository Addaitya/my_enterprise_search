---
status: implemented
title: Frontend UI update
date: 2026-09-24
notes: Implemented record. Not product truth. Do not edit prompts/. Core APIs stayed. Ingestion stayed a placeholder.
---

# Frontend UI plan

**Implemented record.** The checklist below is the spec that was executed. Do not treat it as open work. `prompts/` was not modified.

**Where this file lives.** `prompt_2/` is agent memory. `prompts/` is frozen. `prompt_2/current.md` is product truth and must not become a task list. `prompt_2/context/` is shipped behavior. This plan is a sibling of `current.md`.

**Authority when documents disagree.**

1. `prompt_2/current.md` sections Now, Not yet, and Invariants.
2. This plan.
3. The visual reference that was pasted under “Updates to be added” in `prompt_2/current.md`. That block was removed in T8 so Now / Not yet / Invariants stay the short source of truth.

That reference was a layout and styling target from a different app. It was not permission to replace this frontend or its APIs.

---

## 1. Goal

Restyle the existing Vite React app toward the light Inter / indigo reference, and add placeholder screens that can later take real APIs.

Shipped behavior stays on the same calls:

- Keycloak PKCE (`oidc-client-ts`), URL routes, admin route guard
- `POST /search` body `{ q, size }` with the user JWT
- Authenticated file list and download
- Resumable upload of PDF, TXT, and CSV, with no auto `file_acl`
- Admin Users, Roles, Groups, and Access, including ACL job polling
- `GET /admin/stats` for live dashboard numbers

Connector ingestion, RAG, autocomplete, server facets, search-mode switching, and configuration save stay unwired.

---

## 2. Out of scope

- Any edit under `prompts/`.
- Backend, OpenSearch, Keycloak realm, or ingest pipeline work.
- Replacing the Vite + React 19 + TypeScript app with the reference’s single `index.html`, Babel standalone, or CDN React 18.
- Password-grant login, or a client secret in the browser.
- A local-only Access Control table that pretends to write Keycloak or OpenSearch DLS.
- Native hybrid search, Task 7, content-hash dedup, auto-ACL.
- Sending new search fields (`page`, `facets`, `semantic_weight`, `highlight`, mode).

---

## 3. What exists today

| Route | Guard | Behavior to keep |
| --- | --- | --- |
| `/login`, `/auth/callback`, `/auth/silent-callback` | public | PKCE redirect. Login page is a button, not a password form. |
| `/` | signed in | `searchFiles(q, size)`. Open calls `downloadFileContent`. Proof hits (`file-proof-` / `proof-`) error instead of downloading. |
| `/upload` | signed in | Resumable multi-file upload. Type and size checks stay. |
| `/files` | signed in | `GET /files`, then authenticated download. |
| `/dashboard` | admin | `GET /admin/stats`. |
| `/admin` | admin | Live users, roles, groups, file ACL. |
| `/configuration` | admin | One line of placeholder copy. |

Search hit fields today: `file_id`, `chunk_id`, `chunk_seq`, `score`, `snippet`, `meta_file_type`, `object_store_path`, `display_name`, `uploaded_at`. Response also has `q`, `took_ms`, `total`. No facets, highlights HTML, domain, author, ML classes, or page token.

Dashboard live fields: `avg_query_time_ms`, `total_data_ingested_bytes`, `total_docs_indexed`. Placeholder fields already returned by the API, with `placeholders.* = true`: `active_connectors`, `ingestion_rate_docs_per_hour`, `last_sync`.

Theme today: dark slate, `max-w-5xl`, no Inter.

Nav today: Search, Upload, View files, and for admins Dashboard, Access Control(Admin), Configuration, plus username and Logout.

---

## 4. Reference UI, and what not to copy

Source: the “Enterprise Data Search Platform — Frontend Implementation Summary” block in `prompt_2/current.md`. Use it for layout, color, type, and the shape of new placeholder panels.

Do not copy:

| Reference | This app |
| --- | --- |
| One HTML file, Babel, CDN React 18 | Existing Vite app |
| `activeTab` and a URL that never changes | React Router paths in §3 |
| Password form, `client_secret=changeme` | PKCE button |
| `POST /api/v1/search` with filters, page, semantic weight | `POST /search` `{ q, size }` |
| Autocomplete `GET /api/v1/autocomplete` | No such route. Do not add a client for it. |
| RAG `POST /api/v1/rag/answer` SSE | No such route. Do not add a client for it. |
| `MOCK_METRICS` for every dashboard card | Live `GET /admin/stats` |
| Local role CRUD, tag scope, DLS JSON editor | Live admin API |
| `dangerouslySetInnerHTML` highlights | Plain `snippet` text |
| No logout | Keep Logout |
| Grafana link to `http://localhost:3000` | This stack has no Grafana service. Do not add that link. |

Naming collision: in the reference, tab `admin` is the metrics dashboard and tab `acl` is access control. Here `/admin` is Access Control and `/dashboard` is metrics. Keep these URLs.

---

## 5. Design system

Apply inside the existing Tailwind 4 setup. Do not load Tailwind from a CDN.

- Font: Inter 300–700.
- Page `bg-gray-50`, cards white, borders `gray-200`, primary text `gray-900`, muted `gray-400`.
- Primary indigo-600 / indigo-700. Status emerald, amber, rose. Placeholder ML chrome violet.
- Cards `rounded-xl`, modals `rounded-2xl`, inputs `rounded-lg`, pills `rounded-full`.
- CSS: fade-in, search focus ring, spinner, thin scrollbar. Match the reference `<style>` block.
- Icons: emoji, using the reference file-type and domain map.
- Shared primitives, new or restyled: `Badge`, `Spinner`, `Toggle`, `Field`, `Input`, `Select`, `SectionCard`, `SaveBar`.
- `SaveBar` copy is “Saved locally” and never implies the server changed.
- Shell: sticky header, ES mark, title, nav pills, initials plus username, Logout. Content `max-w-7xl`. Short footer with product name and stack. No Grafana link.
- Admin links stay hidden unless the JWT realm role is `admin`.

Domain color map from the reference may be used on placeholder chips. Do not invent domain values on real search hits.

---

## 6. Tasks

Checkboxes are this plan’s only. Do not copy them into `current.md`.

### T1 — Shell and tokens

- [x] Add Inter and the reference CSS utilities in `frontend/src/index.css`.
- [x] Restyle `AppShell`, `Navbar`, `Button`, `Login`, and the auth callback pages onto the light shell.
- [x] Login card: logo, title, short copy, one button that calls `userManager.signinRedirect()`. No username or password inputs.
- [x] Keep Logout on `userManager.signoutRedirect()`.

### T2 — Search

Files: `frontend/src/pages/Search.tsx` and small presentational components under `frontend/src/components/search/`. Keep `frontend/src/api/search.ts` request shape.

- [x] Empty state before the first query: icon, heading, short description, five chips that set the query and call the existing search, and a source-type icon row. PDF, TXT, and CSV are the real types. Other icons are inert labels.
- [x] Search bar, Search button, loading line, “N hits · took ms”, empty-results line.
- [x] Result cards from real hit fields only: emoji from `meta_file_type` (pdf, txt, csv, else generic), `display_name` or `chunk_id`, score pill at the reference thresholds (0.9 / 0.7), plain snippet.
- [x] Open stays `downloadFileContent`. Proof hits keep the current error. 403 and 404 copy stays.
- [x] Details modal shows real fields: score, uploaded time, type, chunk id, file id, snippet, and Open. See §8 before adding empty domain, ML, metadata, or ACL blocks.
- [x] Mode pills Hybrid / Keyword / Semantic. Assumed behavior until §8: Hybrid is selected and is the only control that looks active. Keyword and Semantic are disabled. The request stays `{ q, size }`.
- [x] Facet column chrome (Domain, File Type, Source, Language). Assumed until §8: all four sections render and say not available. No client-side filter. No refetch.
- [x] Pager chrome shows “showing N of total”. Prev and Next stay disabled. Do not add `page` to the body. Do not raise `size` to fake pages.
- [x] Ask AI opens a panel whose body is the fixed line “Answer generation is not connected.” No fetch, no stream, no canned answer.
- [x] No autocomplete request. Empty-state chips are the only suggestions.

### T3 — Upload and View files

- [x] Restyle `Upload.tsx` and `Files.tsx` with the light cards, tables, and empty / loading / error states.
- [x] Keep validation, progress, cancel, ACL warning on upload, list, refresh, and authenticated open.
- [x] Both routes stay in the nav. The reference omits them; this product does not.

### T4 — Dashboard

File: `frontend/src/pages/Dashboard.tsx`. Keep `getAdminStats()`.

- [x] Card grid in the reference style for the six API fields.
- [x] Query time, bytes, and doc count render as live values.
- [x] Active connectors, ingestion rate, and last sync render the API strings and show a Placeholder badge when `stats.placeholders.*` is true.
- [x] Connector status table: static rows. Sync Now sets a local notice only. No request.
- [x] Index distribution: three static bars, labeled placeholder.
- [x] Do not replace live numbers with `MOCK_METRICS`. Do not add p99, searches today, or total sources unless §8 says to add them as labeled placeholders.
- [x] Keep refresh and the current error text.

### T5 — Access Control

- [x] Restyle `Admin.tsx` and the existing admin components (tables, modals, job tray) to the light theme.
- [x] Users, Roles, Groups, and Access keep calling `frontend/src/api/admin.ts`.
- [x] Do not add the reference role list, document-tag scope, or DLS JSON preview.

### T6 — Configuration, including ingestion

Replace `frontend/src/pages/Configuration.tsx`. Fixture constants in something like `frontend/src/config/placeholders.ts`.

- [x] Sidebar plus twelve sections: Ingestion, Messaging, ETL, Parsing, Enrichment, Metadata, ML Classify, Search, IAM, API, Observability, Orchestration.
- [x] Each section is `useState` only. `SaveBar` shows “Saved locally” for about two seconds and writes nothing.
- [x] Ingestion: connector table, configure modal, add-connector picker, enable toggle, Sync Now. All mutate the local list only. No Airbyte, Kafka, Spark, Tika, or MinIO calls. Password fields stay in component state and are not logged.
- [x] Search-section hybrid weights are display-only. They must not change server weights `[0.3, 0.7]`.
- [x] IAM fields must not change the Keycloak realm or the PKCE client.
- [x] Fixture connector list: see §8. Assumption until answered: use the reference’s sample rows, each marked placeholder, and do not describe them as connected.

### T7 — Verify

- [x] `npm run build` in `frontend` passes.
- [x] Non-admin: PKCE sign-in, search, open an allowed file, upload a PDF or TXT or CSV, View files. Request bodies unchanged.
- [x] Admin: one real user, role, group, and file-ACL change still works, and the job tray still polls.
- [x] Dashboard live cards match `GET /admin/stats`. Placeholder stats are badged.
- [x] Walking Configuration, including Ingestion, produces no network call other than the ones the page already made to load the app.
- [x] Keyword, Semantic, Ask AI, facets, and pager send no new fields.

### T8 — Docs after the UI ships

Only after implementation, and only if product-facing copy changed:

- [x] Update `prompt_2/current.md` and root `README.md` together: Configuration is a local placeholder shell; connector count, rate, and last sync remain API placeholders; ingestion is still not built.
- [x] Remove the long visual reference from the product-truth body of `current.md`, or move it so Now / Not yet / Invariants stay the short source of truth. Do not edit `prompts/`.
- [x] Set this file’s `status` to `implemented` and turn the checklist into a record, the same way `prompt_2/context_migration.md` closed its plan.

---

## 7. Done when

T1–T7 are checked and §8 questions are either answered or explicitly accepted as the assumptions in §6.

---

## 8. Human review

Answered before implementation. The choices below are what shipped. The old assumptions are kept so the record shows the alternatives that were not taken.

1. **Is the pasted spec a pixel target or a loose mood board?** Shipped: loose mood board (colors and type). Routes and APIs stayed. Not rebuilt as one HTML file.

2. **Light theme for the whole app, or only the new Configuration page?** Assumption: the whole signed-in shell, including Search, Upload, Files, Dashboard, and Access Control, moves off the dark slate theme.

3. **Search mode pills.** Assumption: Hybrid looks selected; Keyword and Semantic are disabled and do not change the request. Alternative: all three are selectable local state and still do not change the request, so a later API can read that state.

4. **Facets.** Shipped: the column is visible and every section says not available. No filtering of the current hits. Main search stays the original request.

5. **Pager.** Assumption: disabled Prev/Next, no `page` field, `size` stays 10. Alternative: one response with a larger `size`, sliced in the browser. That still is not server paging.

6. **Ask AI.** Assumption: the panel opens and says it is not connected. No sample answer. Alternative: a clearly labeled fake answer with no network call. A fake answer is easier to mistake for search.

7. **Result details modal.** Assumption: only real hit fields, plus Open. Alternative: also render empty domain, ML, metadata, and ACL blocks with a Placeholder label. Empty ACL chips are risky because file ACL is Postgres, not the search hit.

8. **Extra dashboard cards from the reference** (p99 latency, searches today, total sources). Shipped: static numbers with a Placeholder badge, in addition to the six API fields.

9. **Connector fixture list.** The reference uses PostgreSQL, SharePoint, Email, S3, Salesforce, Oracle, Box, SAP. The unfinished ingestion brief is SharePoint, Google Drive, and S3/MinIO. Assumption: show the reference’s rows, all marked placeholder, so the modal catalog matches the spec. Alternative: only the three sources named in the brief.

10. **How much of Configuration to build now?** Shipped: Ingestion plus a sidebar. The other eleven sections are a single “not built” card. Search and IAM have no fields.

11. **Where local upload sits.** Assumption: `/upload` stays its own nav item. It is not moved under Configuration → Ingestion. The ingestion section does not call the resumable upload API.

12. **Copy Link on a document.** Shipped: omitted. Open still downloads the file with the Bearer token, as the previous page did.

13. **Inter from Google Fonts.** Assumption: link Inter from Google Fonts in `frontend/index.html`. Alternative: a system font stack if the environment should not call Google.

14. **Facet sidebar on a narrow screen.** The reference stays side by side and can overflow. Assumption: stack the facet column above results below the `sm` breakpoint so the page is usable. This is a small departure from the reference.

15. **The spec currently sits inside `prompt_2/current.md`.** It conflicts with the invariants above it (PKCE, search body, live ACL, live stats). Assumption: leave `current.md` unchanged until T8, and implementers follow this plan when the two disagree. Say if that spec should be moved out before implementation so the next agent does not treat password login and mock ACL as product truth.
