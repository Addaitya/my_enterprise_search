# Auth setup — full implementation plan

**Superseded for JWT keys:** OpenSearch is now **3.8.0**. Live `jwt_auth_domain` uses `type: jwt` + `jwks_uri` (Docker DNS). PEM `signing_key` and “2.19 cannot jwks_uri” below are historical. See `prompts/cursor_summary/update_opensearch_version.md` and `6_search_setup.md`.

Working notes to implement **Task 1 (Auth)** from `prompts/cursor_summary/2_project_overview_tasks.md`. Scaffold already exists under `backend/`, `frontend/`, `docker-compose.yml`, and `docker_service_configs/`. This file is the source of truth for the auth slice. Do not invent a second identity model.

**Agent rules while implementing**
- Run and execute code to confirm it works before moving on.
- Do not proceed past a broken step; fix it first.
- Where something cannot be verified in this environment, leave a clear human check and wait for feedback.
- Do not start ingest, search UI, Postgres identity tables, or admin CRUD. Auth only. Admin UI is a stub behind a guard.
- After each layer (OpenSearch JWT, FastAPI JWT, React PKCE), prove it independently before wiring the next.

---

## What “done” means

A signed-in user can use the product; an anonymous user cannot; an admin can open `/admin`; a non-admin cannot. Search-time OpenSearch calls use the **user** JWT (so DLS can run later). Ingest/admin writes to OpenSearch keep using **internal basic auth** (`admin` / `OPENSEARCH_INITIAL_ADMIN_PASSWORD`).

| Actor | How they authenticate | What they may do in this slice |
| --- | --- | --- |
| Browser user | Keycloak `web-client` authorization code + PKCE | Login, logout, refresh, hit FastAPI with Bearer, see Admin nav iff realm role `admin` |
| FastAPI | Verify Bearer JWT (JWKS, `iss`, `aud=api-client`) | `/health` public; `/auth/me` and future APIs protected; `/admin/*` requires `admin` |
| OpenSearch (user search) | Same access token, `http_authenticator.type: jwt` | Mapped to `files_searcher` only (DLS). **Never** `all_access` |
| OpenSearch (ingest / security bootstrap) | HTTP basic `admin` | Unchanged. Writes have no DLS |

---

## Current state (do not re-scaffold)

Already in place:

- Realm `enterprise-search-realm` imported on **first empty Keycloak DB only** (`start-dev --import-realm`). File: `docker_service_configs/keycloak/realm.json`.
- Confidential client `api-client` (secret `KEYCLOAK_API_SECRET` / realm.json `api-client-secret`), service account on, audience mapper adds `api-client`.
- Public client `web-client`, PKCE S256, standard flow, **direct access grants off**, redirect `http://localhost:5173/*`.
- Flattened protocol mappers on **both** clients: top-level `roles` (realm roles), top-level `groups` (`full.path: false`), audience `api-client`.
- Seed user `realm-admin` / `adminpass` with realm roles `admin` + `search-user`, group `/engineering`.
- Frontend: Zustand `authStore` (in-memory, never hydrated), `config/env.ts` already points at `web-client`, Navbar already hides Admin unless `roles.includes('admin')`, API client has **no** Authorization header, no router, no OIDC library.
- Backend: CORS for `http://localhost:5173`, `/health` public, **no** JWT code, `pyjwt` not in `pyproject.toml`.
- OpenSearch: `roles.yml` defines `files_searcher` (DLS) and `files_writer`. **Neither is applied.** `jwt-auth-domain.yml.example` is a comment-only fragment and is **not merged**. Compose does **not** mount `opensearch.yml`. Init only uses basic `admin`.
- `init_services/keycloak.py` only GETs the realm; it does not create extra users or patch clients.

Keycloak import **will not re-apply** `realm.json` if the realm already exists. Client/mapper/user changes after first boot must go through Admin API in `init_services` (idempotent) or a documented realm reset.

---

## Locked decisions

| Topic | Decision |
| --- | --- |
| IdP | Keycloak 26.2, realm `enterprise-search-realm` |
| SPA client | `web-client`, public, authorization code + PKCE. No secret in the frontend. No resource-owner password on this client. |
| API audience | Every access token used by FastAPI and OpenSearch must include `aud` **`api-client`** (already mapped). Validate audience as `api-client`, not `web-client`. |
| FastAPI JWT | `PyJWT[crypto]` + `PyJWKClient` against Keycloak JWKS. Algorithms `RS256` only. Check `iss`, `aud`, `exp`. |
| SPA library | `oidc-client-ts` + `react-router-dom`. Do **not** use `keycloak-js` (Vite / React 19 StrictMode double-init is a common failure). |
| Token in UI | `UserManager` is source of truth. Zustand is a reactive cache of `access_token`, `preferred_username`, `roles`, `groups`. Persist OIDC user in **sessionStorage** (survive refresh). Do not use `localStorage`. |
| Admin capability | Keycloak realm role **`admin`**. FastAPI enforces it. Frontend route guard is UX only. Do **not** add `admin_grants` (that is Task 2). |
| Product access | Protected APIs require realm role `search-user` **or** `admin`. |
| OpenSearch authenticator | **`jwt`**, never `openid`. `${attr.jwt.*}` DLS is empty with `openid` even when login works. |
| OpenSearch JWT keys (2.19) | **Static `signing_key` PEM**, not `jwks_uri`. Native `jwks_uri` on the jwt authenticator is OpenSearch **3.3+**. This cluster is **2.19.1**. Fetch Keycloak `public_key` in `init_services` and write it as PEM. |
| OpenSearch search role | `files_searcher` from `roles.yml`. Map backend roles `search-user` **and** `admin`. |
| OpenSearch writes | Internal basic `admin` only. Do not map JWT roles to `files_writer` or `all_access`. |
| `/health` | Stays unauthenticated. |
| New API | `GET /auth/me` — returns claims FastAPI accepted. Use it as the backend proof and as the SPA session check. |

---

## Landmines (read before coding)

These are the ways this stack silently ships a broken or wide-open system.

### 1. Keycloak role `admin` vs OpenSearch `all_access`

Demo OpenSearch maps backend role `admin` → security role `all_access`. Keycloak seed user has realm role `admin`. That claim is copied into JWT `roles`. If left as-is, an admin search request is **not** DLS-filtered and sees every chunk.

**Required fix (do this in the same OpenSearch security step as JWT):**

- PATCH `all_access` role mapping: keep the **internal user** named `admin` via `users: ["admin"]`.
- Remove backend role `"admin"` from `all_access` (and do not add it back).
- Map JWT `admin` / `search-user` **only** to `files_searcher`.

Prove with `GET /_plugins/_security/authinfo` using a Bearer token from `realm-admin`: `roles` must include `files_searcher` and must **not** include `all_access`.

### 2. `jwks_uri` on jwt domain will not work on 2.19

Ignore `jwks_uri` in `jwt-auth-domain.yml.example`. For 2.19:

1. `GET http://localhost:8080/realms/enterprise-search-realm` → `public_key` (raw base64, no PEM header).
2. Wrap as:

```
-----BEGIN PUBLIC KEY-----
<public_key>
-----END PUBLIC KEY-----
```

3. Put that string in jwt domain `signing_key`. `authentication_backend: noop`. `challenge: false`.

Re-run `init_services` after Keycloak realm key rotation. Document that. FastAPI **does** use JWKS (`PyJWKClient`); only OpenSearch 2.19 cannot.

### 3. Issuer vs JWKS/signing fetch URL

| Who | Verify `iss` as | Fetch keys from |
| --- | --- | --- |
| Browser / FastAPI on host | `http://localhost:8080/realms/enterprise-search-realm` | `http://localhost:8080/realms/.../protocol/openid-connect/certs` |
| OpenSearch in Docker | **same public `iss`** (`required_issuer`) | Keycloak **Docker DNS**: `GET http://keycloak:8080/realms/enterprise-search-realm` for `public_key` (init_services runs on the host, so init fetches via localhost, which is the same key material) |

`required_issuer` must be the value **inside the token**, which is the public URL. Do not set it to `http://keycloak:8080/...`.

### 4. PUT securityconfig is disabled until a compose flag is set

Roles and role mappings APIs work with demo `admin`. Replacing `config.yml` (authc domains) requires:

```yaml
plugins.security.unsupported.restapi.allow_securityconfig_modification: "true"
```

Add this to the **opensearch service environment** in `docker-compose.yml` (the YAML file under `docker_service_configs/opensearch/` is not mounted today). Restart OpenSearch. Then:

- `GET /_plugins/_security/api/securityconfig`
- Merge `jwt_auth_domain` into existing `dynamic.authc`
- **Keep** `basic_internal_auth_domain` (ingest will die without it)
- `PUT /_plugins/_security/api/securityconfig/config` with the full `dynamic` object

JWT domain: `order: 0`, `challenge: false`. Basic domain: keep enabled, `order` higher than JWT (e.g. 1 or 4).

If PUT returns 403, the flag was not picked up — do not workaround by disabling security.

### 5. DLS does not apply if the user also has a non-DLS role

Do not map JWT users to `all_access`, `security_rest_api_access`, or `files_writer`. Do not set `plugins.security.dfm_empty_overrides_all: true` unless you have a dedicated break-glass role (you do not, for v1).

### 6. Missing `groups` claim breaks DLS JSON

If a user has no groups, Keycloak may omit `groups`. Then `${attr.jwt.groups}` can produce invalid DLS JSON and every search 500s.

**Required:** idempotent init creates a second user `searcher` with **no groups**, and you prove search still returns 200 (zero hits is OK). If it 500s, add a Keycloak mapper/default so `groups` is always present (empty array or empty string) **or** split DLS into a roles-only should-clause that does not reference groups when the claim is missing. Prefer always-emitting `groups`.

Seed `searcher` also exists so Admin route guard can be proved (no `admin` role).

### 7. `roles_key` format

Docs say comma-separated string. Keycloak `multivalued` mapper emits a JSON array. OpenSearch 2.x jwt authenticator usually accepts a Collection. If `authinfo` shows empty `backend_roles`, add a protocol mapper that joins realm roles with commas. Do not guess — read `authinfo`.

### 8. React 19 StrictMode + PKCE

`signinRedirectCallback` must run **once**. A module-level in-flight Promise (singleton) is mandatory. Double consume of the auth code → Keycloak `invalid_grant` and a stuck loop.

### 9. Do not trust the SPA for authorization

Hide Admin in the Navbar (already done) **and** add a route guard **and** `require_admin` on FastAPI. The backend check is the real one.

### 10. Token lifetime is 5 minutes

`api-client` attribute `access.token.lifespan` is `300`. Enable `automaticSilentRenew` in `oidc-client-ts`. Add `/auth/silent-callback` route that calls `signinSilentCallback()`. Without this, the app dies after five minutes.

---

## Target filesystem (create / change)

```
backend/
  pyproject.toml                          # add PyJWT[crypto]
  app/core/security.py                    # JWKS client, decode, CurrentUser
  app/api/deps.py                         # get_current_user, require_product_user, require_admin
  app/api/routes/auth.py                  # GET /auth/me
  app/api/router.py                       # include auth router
  app/schemas/auth.py                     # MeResponse
  init_services/opensearch_security.py    # jwt domain, roles, mappings, all_access fix
  init_services/keycloak.py               # verify clients; ensure users realm-admin + searcher
  init_services/opensearch.py             # call opensearch_security.configure()
  init_services/run.py                    # already calls keycloak + opensearch

frontend/
  package.json                            # oidc-client-ts, react-router-dom
  src/auth/userManager.ts                 # UserManager singleton
  src/auth/AuthProvider.tsx               # hydrate Zustand, silent renew events
  src/auth/callback.tsx                   # /auth/callback
  src/auth/silentCallback.tsx             # /auth/silent-callback
  src/auth/ProtectedRoute.tsx
  src/auth/AdminRoute.tsx
  src/pages/Login.tsx
  src/pages/Search.tsx                    # move current App body here
  src/pages/Admin.tsx                     # stub
  src/App.tsx                             # BrowserRouter + routes
  src/api/client.ts                       # Bearer + 401 → renew → retry once
  src/store/authStore.ts                  # keep shape; hydrate from UserManager
  src/components/layout/Navbar.tsx        # Login / Logout buttons

docker-compose.yml                        # allow_securityconfig_modification on opensearch
docker_service_configs/opensearch/security/jwt-auth-domain.yml.example
                                          # rewrite to 2.19 signing_key; keep as reference
```

Do not add Postgres models. Do not add Keycloak admin-client wrappers beyond what init_services needs.

---

## Architecture (request path)

```
React (web-client, PKCE)
  → Keycloak /protocol/openid-connect/auth
  → redirect /auth/callback?code=
  → token endpoint (PKCE verifier)
  → access_token (aud includes api-client, roles[], groups[])
  → Zustand + Authorization: Bearer
        │
        ├─ FastAPI: PyJWKClient + iss/aud/exp
        │     GET /auth/me
        │     future: POST /search  ──Bearer──► OpenSearch jwt domain
        │                              DLS files_searcher
        │
        └─ FastAPI ingest (later): OpenSearch basic admin (no user JWT)
```

Expected access-token claims (decode one during verification; do not ship if any are missing):

| Claim | Expected |
| --- | --- |
| `iss` | `http://localhost:8080/realms/enterprise-search-realm` |
| `aud` | `api-client` or array containing `api-client` |
| `azp` | `web-client` (SPA) or `api-client` (password-grant tests) |
| `preferred_username` | `realm-admin` / `searcher` |
| `roles` | array including `search-user`; `admin` only for realm-admin |
| `groups` | `["engineering"]` for realm-admin; always present for searcher (possibly `[]`) |
| `alg` / `kid` | RS256, kid matching Keycloak JWKS |

---

## Implementation steps

Check a box only after that step has been **run** (not only written).

### A. Compose + OpenSearch security flag

- [ ] Add to `opensearch` environment:

```yaml
plugins.security.unsupported.restapi.allow_securityconfig_modification: "true"
```

- [ ] `docker compose up -d opensearch` (or recreate) so the flag is live.
- [ ] **Human / local:** `curl -k -u admin:$OPENSEARCH_INITIAL_ADMIN_PASSWORD http://localhost:9200/_plugins/_security/api/securityconfig` returns JSON (not 401).

### B. Keycloak init: clients + two users (idempotent)

Extend `init_services/keycloak.py`. Use master realm `admin-cli` password grant with `KEYCLOAK_ADMIN` / `KEYCLOAK_ADMIN_PASSWORD` (bootstrap admin), then Admin API.

- [ ] Verify realm exists (already).
- [ ] Verify clients `api-client` and `web-client` exist; print client ids.
- [ ] Ensure user `realm-admin` exists, enabled, roles `admin` + `search-user`, group `engineering`, password `adminpass` (do not rotate here).
- [ ] Ensure user `searcher` exists, enabled, **only** role `search-user`, **no groups** (or empty groups claim — see landmine 6), password `searcherpass`.
- [ ] Print realm `public_key` (first/last 8 chars) so OpenSearch signing_key can be correlated.
- [ ] Run `cd backend && uv run python -m init_services` and confirm the new prints.

Do not re-import `realm.json`. Do not enable direct access grants on `web-client`.

### C. OpenSearch: jwt domain + roles + mappings

New module `init_services/opensearch_security.py`, called from `opensearch.configure()` **before** index/model work is fine (order vs model does not matter; order vs “can we still basic-auth” does).

**C1. JWT auth domain**

- [ ] GET securityconfig; deep-copy `config.dynamic`.
- [ ] Set `authc.jwt_auth_domain`:

```yaml
http_enabled: true
transport_enabled: true
order: 0
http_authenticator:
  type: jwt          # NOT openid
  challenge: false
  config:
    signing_key: <PEM from Keycloak public_key>
    jwt_header: Authorization
    subject_key: preferred_username
    roles_key: roles
    required_audience: api-client
    required_issuer: http://localhost:8080/realms/enterprise-search-realm
    jwt_clock_skew_tolerance_seconds: 30
authentication_backend:
  type: noop
```

- [ ] Leave `basic_internal_auth_domain` intact and enabled.
- [ ] PUT `/_plugins/_security/api/securityconfig/config`.
- [ ] Prove basic auth still works: `GET /_cluster/health` as `admin`.

**C2. Role `files_searcher`**

- [ ] PUT `/_plugins/_security/api/roles/files_searcher` using the DLS body in `docker_service_configs/opensearch/security/roles.yml` (JSON equivalent of the `dls` string). Cluster: `cluster_composite_ops_ro`. Index: `enterprise-search-chunks`, actions `read` + `search` only.
- [ ] Do **not** apply `files_writer` to any JWT mapping. Optional: PUT the role for later ingest; map it to nobody (or only internal users later).

**C3. Role mappings**

- [ ] PUT `/_plugins/_security/api/rolesmapping/files_searcher`:

```json
{
  "backend_roles": ["search-user", "admin"],
  "hosts": [],
  "users": []
}
```

- [ ] GET `/_plugins/_security/api/rolesmapping/all_access`. PATCH so `users` includes `"admin"` and `backend_roles` does **not** include `"admin"`. Preserve other demo users if present (`kibanaserver` must keep its own mapping; do not wipe unrelated mappings).
- [ ] Confirm `all_access` is **not** granted via backend role `search-user`.

**C4. JWT proof against OpenSearch (no FastAPI yet)**

Password-grant a token with **api-client** (confidential; allowed). SPA PKCE is proved later.

```bash
# host
curl -s -X POST 'http://localhost:8080/realms/enterprise-search-realm/protocol/openid-connect/token' \
  -d grant_type=password \
  -d client_id=api-client \
  -d client_secret="$KEYCLOAK_API_SECRET" \
  -d username=realm-admin \
  -d password=adminpass
```

Decode payload (python/jwt.io). Confirm `roles`, `groups`, `aud`, `iss`.

```bash
curl -s http://localhost:9200/_plugins/_security/authinfo \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

- [ ] `user_name` is `realm-admin` (because `subject_key: preferred_username`).
- [ ] `backend_roles` contains `admin` and `search-user`.
- [ ] `roles` contains `files_searcher` and does **not** contain `all_access`.
- [ ] Repeat with `searcher` / `searcherpass`: `files_searcher` only, no `all_access`.
- [ ] Repeat with a garbage Bearer: 401.
- [ ] Repeat with basic `admin`: still 200 on `/_cluster/health`.

If `backend_roles` is empty, fix `roles_key` / mapper before touching FastAPI.

Rewrite `jwt-auth-domain.yml.example` so it documents **signing_key + type jwt** for 2.19, and that `jwks_uri` is 3.3+ only. Keep it as comments/reference, not as something compose mounts.

### D. FastAPI JWT

Dependencies: `PyJWT[crypto]` via uv (`cd backend && uv add 'pyjwt[crypto]'`).

`app/core/security.py`:

- Cached `PyJWKClient(settings.keycloak_jwks_url)` (public URL; backend runs on the host today).
- `decode_access_token(token: str) -> dict` with `algorithms=["RS256"]`, `audience=settings.keycloak_client_id` (`api-client`), `issuer=settings.keycloak_issuer`.
- `CurrentUser` dataclass/pydantic: `sub`, `username` (`preferred_username`), `roles: list[str]`, `groups: list[str]`, `raw`.
- Normalize claims: if `roles`/`groups` is a string, split on comma; if missing, `[]`.

`app/api/deps.py`:

- `HTTPBearer` for protected routes.
- `get_current_user` → 401 on missing/invalid/expired token. Do not leak key material in the error body.
- `require_product_user` → 403 unless `search-user` in roles or `admin` in roles.
- `require_admin` → 403 unless `admin` in roles.

`GET /auth/me` (`require_product_user`): return username, roles, groups, sub.

`GET /auth/admin-ping` (`require_admin`): `{ "ok": true }` — exists only so the admin guard is provable without building Task 6. Can stay.

Keep `/health` public.

- [ ] `GET /auth/me` no header → 401/403 (Bearer missing).
- [ ] `GET /auth/me` with realm-admin token → 200, roles include `admin`.
- [ ] `GET /auth/me` with searcher token → 200, roles are `search-user` only.
- [ ] `GET /auth/admin-ping` as searcher → 403.
- [ ] `GET /auth/admin-ping` as realm-admin → 200.
- [ ] `GET /health` still 200 without token.
- [ ] Tampered token (last segment flipped) → 401.
- [ ] Token with wrong `aud` (if you can mint one) → 401. At minimum, code must pass `audience="api-client"` into `jwt.decode`.

CORS: already allows `Authorization`. If the browser later shows a CORS error on `/auth/me`, add `Authorization` explicitly; do not disable CORS.

### E. React PKCE + guards

```bash
cd frontend && bun add oidc-client-ts react-router-dom
```

**UserManager** (`src/auth/userManager.ts`) — exact settings:

| Setting | Value |
| --- | --- |
| `authority` | `{VITE_KEYCLOAK_URL}/realms/{VITE_KEYCLOAK_REALM}` |
| `client_id` | `web-client` |
| `redirect_uri` | `{origin}/auth/callback` |
| `silent_redirect_uri` | `{origin}/auth/silent-callback` |
| `post_logout_redirect_uri` | `{origin}/` |
| `response_type` | `code` |
| `scope` | `openid profile email` |
| `automaticSilentRenew` | `true` |
| `loadUserInfo` | `false` (roles are on the access token; skip extra round trip) |
| user store | sessionStorage |

Do not request `offline_access`. PKCE is default in oidc-client-ts; do not disable it.

**AuthProvider:** on mount, `getUser()`; subscribe to `UserManagerEvents` (`userLoaded`, `userUnloaded`, `silentRenewError`) and write Zustand. Parse `roles` / `groups` from the access-token payload (base64url JSON). Username from `profile.preferred_username`.

**Routes:**

| Path | Gate | Page |
| --- | --- | --- |
| `/login` | public | Login button → `signinRedirect()` |
| `/auth/callback` | public | `signinRedirectCallback()` once, then navigate `/` |
| `/auth/silent-callback` | public | `signinSilentCallback()` only (blank page) |
| `/` | `ProtectedRoute` | current search shell |
| `/admin` | `AdminRoute` (`admin` role) | stub “Admin” heading |
| `/files` | `ProtectedRoute` | stub “View files” (Navbar already links; hash `#files` should become `/files`) |

`ProtectedRoute`: if no user, redirect `/login` (save `location` as `from`). `AdminRoute`: if user but not admin, render a simple “Forbidden” on the same shell — **do not** redirect to `/` in a loop.

Navbar: Login when signed out; username + Logout (`signoutRedirect`) when signed in. Admin link stays role-gated; point it at `/admin`.

API client: read token from `useAuthStore.getState().accessToken` (or pass from UserManager). Attach `Authorization: Bearer`. On 401: `signinSilent()`, retry **once**, then `clearSession` + redirect `/login`. Never attach a token to `/health` if you like; harmless either way.

**StrictMode:** callback module:

```ts
let callbackPromise: Promise<User> | null = null
export function handleRedirectCallback() {
  if (!callbackPromise) callbackPromise = userManager.signinRedirectCallback()
  return callbackPromise
}
```

- [ ] `bun run build` succeeds.
- [ ] Dev: open `/`, redirected to `/login`, Login → Keycloak → back on `/` with username `realm-admin`.
- [ ] Navbar shows Admin. `/admin` renders stub. `/auth/me` from the browser network tab is 200 with Bearer.
- [ ] Logout returns to signed-out Login.
- [ ] Log in as `searcher`: no Admin link; visiting `/admin` shows Forbidden; `/auth/admin-ping` is 403.
- [ ] Reload on `/` stays signed in (sessionStorage + `getUser()`).
- [ ] **Human:** wait for access token expiry (~5 min) or temporarily set lifespan to 60s in Keycloak and confirm silent renew (no full redirect). If renew fails, fix before claiming done.

### F. Wire search-proxy contract (no search feature)

Future `POST /search` will forward the **incoming** `Authorization` header to OpenSearch. In this slice, add a short comment on `get_current_user` and/or a helper `user_bearer_header(request)` so the next task does not “helpfully” switch search to basic admin.

Do **not** implement `/search` here. Optional: `GET /auth/opensearch-authinfo` as admin-only debug that forwards the user JWT to OpenSearch `authinfo` — useful, delete or gate it if it feels noisy. Prefer proving C4 from the shell instead of exposing it.

---

## FastAPI shapes (implement exactly)

```python
# schemas/auth.py
class MeResponse(BaseModel):
    sub: str
    username: str
    roles: list[str]
    groups: list[str]
```

Errors: 401 `{"detail": "Not authenticated"}` / `"Invalid token"`; 403 `{"detail": "Forbidden"}`. Do not distinguish “expired” vs “bad signature” in the body (avoid helping attackers); logs may.

Settings: existing `keycloak_issuer` and `keycloak_jwks_url` are correct for host-run FastAPI. Do not point FastAPI JWKS at `http://keycloak:8080` unless the API itself runs on the compose network.

---

## Verification matrix

Run these after E. All must pass.

| # | Test | Expected |
| --- | --- | --- |
| 1 | `GET /health` no token | 200 |
| 2 | `GET /auth/me` no token | 401 |
| 3 | Password-grant `realm-admin` via `api-client` → `/auth/me` | 200, roles include `admin` and `search-user`, groups include `engineering` |
| 4 | Same token → OpenSearch `authinfo` | `files_searcher`, not `all_access` |
| 5 | Password-grant `searcher` → `/auth/me` | 200, no `admin` |
| 6 | `searcher` → `/auth/admin-ping` | 403 |
| 7 | `realm-admin` → `/auth/admin-ping` | 200 |
| 8 | `searcher` → OpenSearch `authinfo` | `files_searcher`, not `all_access` |
| 9 | Basic `admin` → OpenSearch `_cluster/health` | 200 |
| 10 | Browser PKCE as `realm-admin` | Navbar Admin, `/admin` stub, `/auth/me` 200 |
| 11 | Browser PKCE as `searcher` | No Admin, `/admin` Forbidden |
| 12 | Logout | signed out; `/auth/me` 401 |
| 13 | Reload after login | still signed in |
| 14 | Silent renew | token changes, no Keycloak login page |

DLS hit/miss with real chunks is **Task 3/5**, not this file. This slice only proves the JWT principal is `files_searcher`.

---

## Human checks (cannot be faked in code)

- [ ] `docker compose ps` — Keycloak 8080, OpenSearch 9200 healthy after the securityconfig flag restart.
- [ ] Keycloak account login UI loads at `http://localhost:8080/realms/enterprise-search-realm/account` (or the OpenID auth page from the SPA).
- [ ] First-time realm import already happened. If clients/mappers are missing, **do not** assume editing `realm.json` and restarting Keycloak will fix it — use Admin API or wipe the Keycloak DB volume (destructive; ask before).
- [ ] Browser login as both seed users.
- [ ] Silent renew after token TTL.
- [ ] Confirm OpenSearch heap still ≥2g; this step does not change RAM needs.

---

## Out of scope (do not do in this pass)

- Postgres `users` / `roles` / `groups` / `admin_grants` (Task 2).
- MiniLM, ingest pipeline proof, DLS document tests (Task 3).
- Upload, chunking, search UI, file open (Tasks 4–5).
- Admin CRUD for users/roles/groups/file ACL (Task 6).
- Mapping JWT users to OpenSearch Dashboards (plugin is disabled).
- Putting the backend in Docker (JWKS URL would then use `keycloak_internal_url` for **fetch** only; `iss` stays public).

---

## If something fails (quick isolator)

| Symptom | Likely cause |
| --- | --- |
| Keycloak login works, FastAPI 401 | `aud` missing `api-client`; JWKS URL wrong; `iss` mismatch (`https` vs `http`) |
| FastAPI 200, OpenSearch 401 on Bearer | jwt domain not merged; `signing_key` stale/wrong; `required_issuer`/`required_audience` mismatch; still using `type: openid` |
| OpenSearch 200 but `all_access` in authinfo | `admin` backend role still mapped to `all_access` |
| authinfo `backend_roles` empty | `roles_key` not reading JSON array; mapper not on the client that issued the token |
| Search 500 mentioning DLS / query parse | `${attr.jwt.groups}` missing; fix groups claim |
| PKCE `invalid_grant` | StrictMode double callback; code reused |
| Infinite redirect to Keycloak | `ProtectedRoute` wrapping `/login` or `/auth/callback` |
| Works until 5 minutes then 401s | silent renew / missing `/auth/silent-callback` |
| PUT securityconfig 403 | flag not in running container |
| Basic auth to OpenSearch starts failing | jwt `challenge: true` or basic domain removed |
| SPA token has no `roles` | mappers only on `api-client`; browser uses `web-client` — both already have mappers; if missing, patch `web-client` via Admin API |

---

## Checklist copied from Task 1 (map to this file)

- [ ] Merge JWT auth domain into OpenSearch security config (`type: jwt`, PEM `signing_key`, `roles_key: roles`) — steps A, C
- [ ] Create OS role `files_searcher` with DLS from `roles.yml`; map `search-user` and `admin`; strip `admin` from `all_access` backend_roles — step C
- [ ] FastAPI: validate Bearer JWT (issuer, audience `api-client`, JWKS) — step D
- [ ] React: PKCE login via `web-client`; store access token in Zustand — step E
- [ ] Admin route guard: realm role `admin` only (UI + `require_admin`) — steps D, E
