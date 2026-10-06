# Auth

Shipped Task 1. Later superseded for JWT keys by the OpenSearch 3.8 upgrade: product path is `jwks_uri`, not a static PEM. Source dumps: `prompts/summary/2_auth_layer.md`, `prompts/summary/4_search_layer.md`. The auth plan still describes PEM and is stale.

## Request path

React `web-client` uses authorization code + PKCE (`oidc-client-ts`, not `keycloak-js`). The access token audience includes `api-client` and carries `roles` and `groups`. Zustand caches the token in memory; `UserManager` uses sessionStorage.

FastAPI verifies RS256 with `PyJWKClient` (`iss`, `aud=api-client`, `exp`). `GET /auth/me` returns `{ sub, username, roles, groups }` for `search-user` or `admin`. `GET /auth/admin-ping` is `admin` only. `GET /health` is public. Missing or bad tokens are 401; a non-admin on an admin route is 403.

Search forwards the same user Bearer to OpenSearch. Ingest and admin OpenSearch writes use internal basic `admin`. `user_bearer_header()` exists so search does not switch to basic admin.

## Keycloak

Realm `enterprise-search-realm`. Clients `api-client`, `web-client`, `ingest-client`, and `external-api-client`. Direct access grants stay off on `web-client`. Keycloak 26 `basic` client scope is assigned so tokens include `sub`.

`ingest-client` is confidential, service accounts on, direct access grants off, no PKCE. Its only realm role is `ingest-service`. The audience mapper sets `aud=api-client`. It has no product roles (`admin`, `search-user`) and no OpenSearch role mapping. `/internal/*` requires `ingest-service`. The secret is `KEYCLOAK_INGEST_SECRET`.

`external-api-client` is the same kind of confidential client (service accounts on, standard flow off, direct access grants off, no PKCE, `basic` scope, same roles and groups mappers, audience `aud=api-client`). Its service account `service-account-external-api-client` has product roles `admin` and `search-user` and group `_empty` so the `groups` claim is present. It does not get `ingest-service` or `realm-management`. The secret is `KEYCLOAK_EXTERNAL_SECRET` (demo `external-api-client-secret`). Init creates or fixes the client on an existing realm and does not rotate a secret that is already set. Identity sync may insert that service-account user; that row is expected and gets no automatic `file_acl`. Do not map JWT `admin` onto OpenSearch `files_searcher` or `all_access`. Search with this token still goes through FastAPI, which forwards the Bearer.

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
