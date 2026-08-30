# Frontend

React SPA for Enterprise Search: Keycloak PKCE login, protected routes, hybrid search, ACL-filtered file list/download, and a Drive-style multi-file upload client against the FastAPI API.

Stack: **React 19**, **Vite 8**, **TypeScript**, **Tailwind 4**, **Zustand**, **oidc-client-ts**, package manager **bun**.

## Setup

Preferred: from the **repo root**, run `./setup/setup.sh` (installs frontend deps too). See [setup/README.md](../setup/README.md).

Manual:

```bash
cp .env.sample .env
bun install
bun run dev
```

Dev server: http://localhost:5173. Vite proxies `/api` → `http://localhost:8000`.

From the repo root you can also run API + UI together:

```bash
./start-dev.sh
```

### Env

| Variable | Purpose |
| --- | --- |
| `VITE_API_BASE_URL` | API prefix (default `/api`) |
| `VITE_KEYCLOAK_URL` | Keycloak base (default `http://localhost:8080`) |
| `VITE_KEYCLOAK_REALM` | Realm id |
| `VITE_KEYCLOAK_CLIENT_ID` | Public SPA client (`web-client`) |

## Routes

| Path | Access | Status |
| --- | --- | --- |
| `/login` | public | Keycloak PKCE sign-in |
| `/` | signed-in | Hybrid search + results + Open download |
| `/upload` | signed-in (`search-user` \| `admin`) | Multi-file resumable upload |
| `/files` | signed-in | ACL-filtered file list + Open |
| `/admin` | realm role `admin` | Admin placeholder (Task 6) |

## Search (`/`)

Calls `POST /search` (client-hybrid on the backend). Shows chunk hits with snippet, score, and **Open**.

- Empty query surfaces the API **400**.
- Open uses an authenticated blob download (`GET /files/{id}/content`) so the Bearer header is sent (plain `<a href>` will not).
- Synthetic `proof-*` OpenSearch fixtures have no MinIO object — Open shows a clear error.

Client: `src/api/search.ts`, `src/pages/Search.tsx`.

## View files (`/files`)

Fetches `GET /files` (Postgres ACL). Rows show basename `display_name`, short `file_id`, size; **Open** uses the same blob download helper as Search.

Client: `src/api/files.ts`, `src/pages/Files.tsx`.

Uploaded files have **no ACL** until an admin grant or the backend seed script — the list can be empty after a fresh upload.

## Upload (`/upload`)

Uses the backend resumable API (`initiate` → sequential **256 KiB** `Content-Range` PUTs → `complete`).

- Accepts **PDF / TXT / CSV**, max **25 MiB** per file (client + server).
- Multi-select; files upload **one after another** with per-file progress.
- Cancel aborts the current session (`DELETE`) and stops the queue; retry starts a new session.
- Success shows `file_id` + `chunk_count`. Uploaded files have **no ACL** yet — not searchable/listable until grants.
- Range PUTs use **XHR** (not `fetch`) so Drive-style HTTP **308** Resume Incomplete is readable (fetch `redirect: 'manual'` becomes an opaque redirect).

Client modules:

- `src/api/client.ts` — Bearer fetch, silent refresh on 401
- `src/api/uploads.ts` — validation + `resumableUpload` (XHR for parts)
- `src/pages/Upload.tsx` — UI

## Scripts

```bash
bun run dev       # Vite HMR
bun run build     # tsc + production build
bun run preview   # serve build
bun run lint      # oxlint
```

## Notes

- Auth state: Zustand + `oidc-client-ts` (`web-client` PKCE).
- See root [README.md](../README.md) for Compose, seed users (`realm-admin` / `searcher`), ACL seed, and backend bootstrap.
- Backend details: [backend/README.md](../backend/README.md).
