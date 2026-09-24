# Frontend UI log

Not product truth. Step notes only.

## Decisions from §8

- Mood board: colors and type, not a pixel rebuild. Routes and APIs stay.
- Light theme for the whole signed-in app, applied step by step.
- Search modes: Hybrid selected; Keyword and Semantic disabled. Request stays `{ q, size }`.
- Facets: placeholder or disabled. Search itself stays as it is today.
- Pager: disabled Prev/Next, size stays 10, “showing N of total”.
- Ask AI: “Answer generation is not connected.” No sample answer, no fetch.
- Result details: real hit fields plus Open. Open still downloads the file. No Copy Link unless the current page already has one.
- Dashboard: six API fields, plus p99, searches today, and total sources as Placeholder cards.
- Ingestion fixtures: the reference connector rows, all placeholders.
- Configuration: Ingestion plus a sidebar. The other eleven sections are a “not built” card.
- `/upload` stays its own nav item. Ingestion does not call the upload API.
- Inter from Google Fonts.
- Facet column stacks above results below the `sm` breakpoint.
- `prompt_2/current.md` stays unchanged until T8.

## T1 — Shell and tokens

`frontend` build passed (`bun run build`).

What changed:

- Inter (300–700) is loaded from Google Fonts. Page background is gray-50, text is gray-900.
- Shared CSS: fade-in, search focus ring, spinner, thin scrollbar.
- Header is sticky and light: ES mark, title, route pills, initials, username, Logout. Admin links stay hidden unless the realm role is `admin`.
- Content width is `max-w-7xl`. Footer names the product and the stack. No Grafana link.
- Login is a card with one button that calls `userManager.signinRedirect()`. No username or password fields.
- Sign-in callback uses the light page and spinner. Logout still calls `userManager.signoutRedirect()`.
- Primary buttons are indigo. `Button` children can be any React node so existing labels still compile.
- Forbidden (non-admin on an admin route) uses dark text on the light shell.

Search, Upload, View files, Dashboard, Access Control, and Configuration bodies are still the old dark markup. They will look wrong on the light page until their own steps.

### Human test

1. Open `/login`. You should see a white card, an ES mark, short copy, and one Login button. There is no username or password field.
2. Sign in with PKCE. The header should be white and sticky, with Search, Upload, and View files. Logout should still send you through Keycloak sign-out.
3. As `searcher`, Dashboard, Access Control(Admin), and Configuration should be absent. Opening `/dashboard` should say Forbidden in dark text.
4. As `realm-admin`, those three links should appear. The active route pill should be indigo.
5. Inner pages (search form, file list, admin tables) still use the old dark styles. That is expected for this step.

## T2 — Search

`frontend` build passed (`bun run build`). `frontend/src/api/search.ts` is unchanged. The request is still `POST /search` with `{ q, size: 10 }`.

What changed:

- Empty state before the first query: icon, heading, short description, five chips that run the existing search, and a source row. PDF, TXT, and CSV are labeled as real types. Databases, Emails, and S3 / Blob say not available and do nothing.
- Light search bar, indigo Search button, loading spinner, “N hits · took ms”, and an empty-results line.
- Result cards use the real hit only: emoji from `meta_file_type`, `display_name` or `chunk_id`, a score pill (green ≥ 0.9, amber ≥ 0.7, otherwise gray), and plain snippet text.
- Clicking a card opens a details modal with score, uploaded time, type, chunk id, file id, snippet, and Open. Open still downloads through `downloadFileContent`. Proof hits, 403, and 404 keep the previous error text. There is no Copy Link.
- Hybrid looks selected. Keyword and Semantic are disabled. They do not change the request.
- After a search, Domain, File Type, Source, and Language each say “Not available”. They do not filter or refetch. Below the `sm` breakpoint that column sits above the results.
- Pager reads “showing N of total”. Prev and Next are disabled. `size` stays 10.
- Ask AI opens a panel that says “Answer generation is not connected.” No request.
- No autocomplete call.

### Human test

1. Open `/` before searching. You should see the empty state. Click a chip. The network call should be `POST /search` with only `q` and `size`.
2. Confirm Hybrid is the only mode that looks selected. Keyword, Semantic, Prev, and Next should not be clickable.
3. Open a result. The modal should show only the real fields and Open. Open should download an allowed file. A proof hit should show the existing proof error.
4. Ask AI should show the not-connected line and should not add a network call.
5. Filters should say not available and should not change the result list.

## T3 — Upload and View files

`frontend` build passed (`bun run build`). Upload and file APIs are unchanged. Both routes stay in the nav.

What changed:

- `/upload` uses light cards. Type and size checks, multi-file progress, cancel, remove, and the “No ACL assigned” warning are the same.
- `/files` uses a light table. Loading, empty, and error states are restyled. Refresh and Open still use the authenticated list and download.

### Human test

1. On `/upload`, pick a PDF, TXT, or CSV under 25 MiB. Upload should show progress, then the file id and the ACL warning. Cancel during an upload should still stop the batch. A wrong type or an oversized file should still fail before upload.
2. On `/files`, the list should load in the light table. Refresh should reload it. Open should download a file you can access. A file you cannot access should still say you do not have access.
3. Search, Upload, and View files should all still be in the header.

## T4 — Dashboard

`frontend` build passed (`bun run build`). `getAdminStats()` is unchanged.

What changed:

- Light card grid. Query time, ingested bytes, and doc count stay live from `GET /admin/stats`.
- Active connectors, ingestion rate, and last sync still show the API values, with a Placeholder badge when `stats.placeholders.*` is true.
- p99 latency (187 ms), searches today (3,841), and total sources (12) are static cards with a Placeholder badge. They are not from the API.
- Connector status is a static table. Sync Now sets a local notice only and does not send a request.
- Index distribution is three static bars, labeled Placeholder.
- Refresh and the previous error strings stay.

### Human test

1. As `realm-admin`, open `/dashboard`. The first three cards should match `GET /admin/stats`. The next three should match the API and show Placeholder while `placeholders.*` is true.
2. p99, searches today, and total sources should show Placeholder and should not change on Refresh.
3. Sync Now should show a local notice and should not add a network call.
4. Refresh should reload the live cards. A failed load should still show the previous error text.

## T5 — Access Control

`frontend` build passed (`bun run build`). `frontend/src/api/admin.ts` is unchanged.

What changed:

- Users, Roles, Groups, and Access, including tables, modals, and the sync job tray, use the light theme.
- Tabs, inputs, and selected rows use indigo. Errors and job failures use rose. The ACL warning in the grant modal uses amber.
- The same admin API calls remain. There is no local role list, document-tag scope, or DLS JSON preview.

### Human test

1. As `realm-admin`, open `/admin`. Users, Roles, Groups, and Access should be readable on the light page.
2. Create or edit one user, one role, and one group. Members and file grants should still save through the existing APIs.
3. On Access, change one file’s grants. The job tray should still poll, and a finished job should show succeeded or failed in readable text.
4. A non-admin should still not see the Access Control link.

## T6 — Configuration, including ingestion

`frontend` build passed (`bun run build`). No new API client.

What changed:

- `/configuration` is a sidebar with twelve sections. Ingestion is a local placeholder. The other eleven sections are a single “not built” card.
- Search’s card says hybrid weights stay 0.3 and 0.7. IAM’s card says it does not change Keycloak or the PKCE client. Neither section has fields.
- Ingestion lists the reference connectors (PostgreSQL, SharePoint, Email, S3, Salesforce, Oracle, Box, SAP), each marked placeholder and “Not connected.”
- Configure, Add connector, the enable toggle, and Sync Now change only component state. Save shows “Saved locally” for about two seconds and writes nothing. Password fields stay in component state and are not logged.
- Ingestion does not call the upload API.

### Human test

1. As `realm-admin`, open `/configuration`. Ingestion should be selected. Walking the other eleven sections should show “not built” and should not add a network call.
2. Toggle a connector, open Configure, type in a password field, and click Save locally. Sync Now should show a local notice. Add connector should only add a row on this page.
3. Reload the page. Those edits should be gone.
4. `/upload` should still be its own nav item.

## T8 — Docs

Human confirmed T1–T6. `frontend` build had already passed on each step.

What changed:

- `prompt_2/current.md`: Configuration is a local placeholder shell. The long visual reference was removed. Now / Not yet / Invariants stay the short source of truth.
- Root `README.md`: same Configuration wording. Dashboard text notes the extra static placeholder cards. Connector count, rate, and last sync stay API placeholders. Ingestion is still not built.
- `prompt_2/frontend_ui_plan.md` status is `implemented`. The checklist is a record.
- `prompt_2/index.md` points at that file as an implemented record, not an open plan.
