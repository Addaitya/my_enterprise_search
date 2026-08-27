# Auth layer — implemented 26 August 2026

This slice is **implemented as of 26 August 2026**. It is Task 1 (Auth) only: a signed-in user can use the product APIs, an anonymous user cannot, an admin can open `/admin`, a non-admin cannot. Search-time OpenSearch calls will use the **user JWT**. Ingest/admin writes keep **internal basic auth**.

No Postgres identity tables, no ingest, no search UI, no admin CRUD.

---

## Request path

```
React (web-client, authorization code + PKCE)
  → Keycloak
  → /auth/callback
  → access_token (aud includes api-client, roles[], groups[])
  → Zustand cache + Authorization: Bearer
        │
        ├─ FastAPI: PyJWKClient, RS256, iss / aud=api-client / exp
        │     GET /auth/me, GET /auth/admin-ping
        │     future POST /search forwards the same Bearer to OpenSearch
        │
        └─ OpenSearch jwt domain (signing_key PEM, type jwt)
              mapped to files_searcher only (DLS). Never all_access.
```

Ingest later: OpenSearch HTTP basic `admin` / `OPENSEARCH_INITIAL_ADMIN_PASSWORD`. Helper `user_bearer_header()` exists so search does not “helpfully” switch to basic admin.

---

## What shipped

### A. Compose
- `plugins.security.unsupported.restapi.allow_securityconfig_modification: "true"` on the OpenSearch service in `docker-compose.yml`.
- Proven: `GET /_plugins/_security/api/securityconfig` returns 200 as `admin`.

### B. Keycloak init (`init_services/keycloak.py`)
Idempotent Admin API (does **not** re-import `realm.json`):
- Verifies realm `enterprise-search-realm` and clients `api-client`, `web-client` (direct access grants stay **off** on `web-client`).
- Assigns Keycloak 26 `basic` client scope so access tokens include `sub` (realm.json originally omitted it).
- Ensures `realm-admin` / `adminpass` with roles `admin` + `search-user`, group `engineering`.
- Ensures `searcher` / `searcherpass` with role `search-user` only.
- Prints realm `public_key` prefix/suffix for correlation with OpenSearch `signing_key`.

### C. OpenSearch security (`init_services/opensearch_security.py`)
Called from `opensearch.configure()` **before** ML/index work:
- Merges `jwt_auth_domain` (`type: jwt`, PEM `signing_key` from Keycloak `public_key`, `roles_key: roles`, `required_audience: api-client`, `required_issuer: http://localhost:8080/realms/enterprise-search-realm`). **Not** `jwks_uri` (OpenSearch 2.19).
- Keeps `basic_internal_auth_domain` enabled (order 4).
- PUTs role `files_searcher` (DLS from `roles.yml`) and `files_writer` (unmapped to JWT users).
- Maps `files_searcher` ← backend role `search-user`.
- Patches `all_access` so `users` includes `admin` and `backend_roles` does **not** include `admin`.
- Reference file rewritten: `docker_service_configs/opensearch/security/jwt-auth-domain.yml.example`.

### D. FastAPI
- `PyJWT[crypto]`, `app/core/security.py`, `app/api/deps.py`.
- `GET /auth/me` (`search-user` or `admin`) → `{ sub, username, roles, groups }`.
- `GET /auth/admin-ping` (`admin` only) → `{ "ok": true }`.
- `GET /health` stays public.
- 401 `Not authenticated` / `Invalid token`; 403 `Forbidden`.

### E. React
- `oidc-client-ts` + `react-router-dom` (not `keycloak-js`).
- `UserManager` in sessionStorage; Zustand is an in-memory cache of token / username / roles / groups.
- Routes: `/login`, `/auth/callback` (singleton `signinRedirectCallback` for StrictMode), `/auth/silent-callback`, `/` and `/files` (ProtectedRoute), `/admin` (AdminRoute → Forbidden, no redirect loop).
- Navbar: Login / username+Logout; Admin link only if `admin`.
- API client attaches Bearer, silent-renews once on 401, then clears session and goes to `/login`.
- `bun run build` succeeds.

---

## Intentional deviations from the plan (needed to make it work)

1. **`files_searcher` is mapped to `search-user` only, not also `admin`.**  
   OpenSearch’s internal user `admin` already has backend role `admin`. Mapping JWT realm role `admin` → `files_searcher` attached the DLS role to basic `admin`, which mixed DLS + `all_access` and made `GET /_cluster/health` return 500. Seed `realm-admin` still gets `files_searcher` because that user also has `search-user`. Init keeps both Keycloak roles on `realm-admin`.

2. **`groups` is always present via sentinel group `_empty`, not a hardcoded mapper.**  
   Keycloak omits empty `groups` arrays/strings. Two mappers on claim `groups` overwrite each other (`engineering` disappeared). `searcher` is in group `_empty` so DLS JSON `${attr.jwt.groups}` stays valid. FastAPI and the SPA strip `_empty` from product-facing `groups`.

3. **`basic` client scope** is assigned so access tokens include `sub` (Keycloak 26).

Re-run `cd backend && uv run python -m init_services` after Keycloak realm **key rotation** (OpenSearch `signing_key` is a static PEM).

---

## Automated proofs already run (26 August 2026)

| # | Test | Result |
| --- | --- | --- |
| 1 | `GET /health` no token | 200 |
| 2 | `GET /auth/me` no token | 401 |
| 3 | Password-grant `realm-admin` via `api-client` → `/auth/me` | 200, roles `admin` + `search-user`, groups include `engineering` |
| 4 | Same token → OpenSearch `authinfo` | `user_name=realm-admin`, `files_searcher`, **not** `all_access` |
| 5 | Password-grant `searcher` → `/auth/me` | 200, no `admin` |
| 6 | `searcher` → `/auth/admin-ping` | 403 |
| 7 | `realm-admin` → `/auth/admin-ping` | 200 `{ok: true}` |
| 8 | `searcher` → OpenSearch `authinfo` | `files_searcher`, not `all_access` |
| 9 | Basic `admin` → `/_cluster/health` | 200 |
| — | Garbage Bearer → OpenSearch | 401 |
| — | Tampered JWT → `/auth/me` | 401 |
| — | Frontend production build | success |
| — | SPA routes `/`, `/login`, `/admin`, callbacks | 200 (HTML shell) |
| — | Vite `/api/health` proxy | 200 |

DLS hit/miss with real chunks is **not** this slice (Tasks 3/5).

---

## Seed users (local only)

| User | Password | Keycloak roles | Groups (in token) | Product |
| --- | --- | --- | --- | --- |
| `realm-admin` | `adminpass` | `admin`, `search-user` | `engineering` | Search + Admin |
| `searcher` | `searcherpass` | `search-user` | `_empty` (stripped in API/UI) | Search only |

SPA client: `web-client` (public, PKCE). API/OpenSearch audience: `api-client`.
