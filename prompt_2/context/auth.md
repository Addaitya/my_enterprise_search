# Auth

Shipped Task 1. Later superseded for JWT keys by the OpenSearch 3.8 upgrade: product path is `jwks_uri`, not a static PEM. Source dumps: `prompts/summary/2_auth_layer.md`, `prompts/summary/4_search_layer.md`. The auth plan still describes PEM and is stale.

## Request path

React `web-client` uses authorization code + PKCE (`oidc-client-ts`, not `keycloak-js`). The access token audience includes `api-client` and carries `roles` and `groups`. Zustand caches the token in memory; `UserManager` uses sessionStorage.

FastAPI verifies RS256 with `PyJWKClient` (`iss`, `aud=api-client`, `exp`). `GET /auth/me` returns `{ sub, username, roles, groups }` for `search-user` or `admin`. `GET /auth/admin-ping` is `admin` only. `GET /health` is public. Missing or bad tokens are 401; a non-admin on an admin route is 403.

Search forwards the same user Bearer to OpenSearch. Ingest and admin OpenSearch writes use internal basic `admin`. `user_bearer_header()` exists so search does not switch to basic admin.

## Keycloak

Realm `enterprise-search-realm`. Clients `api-client` and `web-client`. Direct access grants stay off on `web-client`. Keycloak 26 `basic` client scope is assigned so tokens include `sub`.

Seed users (local):

| User | Password | Roles | Groups | Product |
| --- | --- | --- | --- | --- |
| `realm-admin` | `adminpass` | `admin`, `search-user` | `engineering` | Search + Admin |
| `searcher` | `searcherpass` | `search-user` | `_empty` (stripped in API and UI) | Search only |

## OpenSearch JWT

`jwt_auth_domain` stays `type: jwt` (not `openid`, which breaks `${attr.jwt.*}`).

- `jwks_uri` from the OpenSearch container: `http://keycloak:8080/realms/enterprise-search-realm/protocol/openid-connect/certs`
- `required_issuer`: `http://localhost:8080/realms/enterprise-search-realm` (must match the token `iss`)
- `roles_key: roles`, `required_audience: api-client`
- PEM `signing_key` is emergency fallback only

`files_searcher` maps from backend role `search-user` only. Do not map Keycloak `admin` onto `files_searcher`: that attached DLS to the internal basic `admin` and made cluster health 500. Internal user `admin` stays on `all_access`. `files_writer` is unmapped to JWT users.

`groups` is always present because `searcher` is in sentinel group `_empty`. Two mappers on the `groups` claim overwrite each other. FastAPI and the SPA strip `_empty`. Never write `_empty` into `allowed_groups`.

SPA routes: `/login`, `/auth/callback` (singleton callback for StrictMode), `/auth/silent-callback`, `/` and `/files` (protected), `/admin` (admin route shows Forbidden, no redirect loop). The API client attaches Bearer, silent-renews once on 401, then clears the session.
