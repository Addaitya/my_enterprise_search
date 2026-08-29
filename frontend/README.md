# Frontend

React SPA for Enterprise Search: Keycloak PKCE login, protected routes, and a Drive-style multi-file upload client against the FastAPI ingest API.

Stack: **React 19**, **Vite 8**, **TypeScript**, **Tailwind 4**, **Zustand**, **oidc-client-ts**, package manager **bun**.

## Setup

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
| `/` | signed-in | Search placeholder (Task 5) |
| `/upload` | signed-in (`search-user` \| `admin`) | Multi-file resumable upload |
| `/files` | signed-in | View files placeholder (Task 5) |
| `/admin` | realm role `admin` | Admin placeholder |

## Upload (`/upload`)

Uses the backend resumable API (`initiate` → sequential **256 KiB** `Content-Range` PUTs → `complete`).

- Accepts **PDF / TXT / CSV**, max **25 MiB** per file (client + server).
- Multi-select; files upload **one after another** with per-file progress.
- Cancel aborts the current session (`DELETE`) and stops the queue; retry starts a new session.
- Success shows `file_id` + `chunk_count`. Uploaded files have **no ACL** yet — not searchable until admin grants.

Client modules:

- `src/api/client.ts` — Bearer fetch, silent refresh on 401, `redirect: 'manual'` so Drive-style **308** is not followed
- `src/api/uploads.ts` — validation + `resumableUpload`
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
- See root [README.md](../README.md) for Compose, seed users (`realm-admin` / `searcher`), and backend bootstrap.
- Backend details: [backend/README.md](../backend/README.md).
