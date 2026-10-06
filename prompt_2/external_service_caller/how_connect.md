# Connect an external service to this API

How a service outside this repo calls search. Product behavior is `prompt_2/current.md`. This note is the caller handoff.

You talk only to Keycloak (for a token) and to this API (for search). You do not get OpenSearch, Postgres, or MinIO credentials. Do not send the token to OpenSearch yourself. This API forwards it.

## What you receive

| Name | Local demo |
| --- | --- |
| Keycloak base URL | `http://localhost:8080` |
| Realm | `enterprise-search-realm` |
| API base URL | `http://localhost:8000` (no `/api` prefix) |
| Client id | `external-api-client` |
| Client secret | `external-api-client-secret` (`KEYCLOAK_EXTERNAL_SECRET` on our side) |

The secret is confidential. Keep it in your environment. The demo value is for this local stack only. A deployed stack will give you a different secret and different hostnames. Do not use `web-client`, `api-client`, or `ingest-client`.

## 1. Get a token

`POST {KEYCLOAK_URL}/realms/enterprise-search-realm/protocol/openid-connect/token`

`Content-Type: application/x-www-form-urlencoded`

| Field | Value |
| --- | --- |
| `grant_type` | `client_credentials` |
| `client_id` | `external-api-client` |
| `client_secret` | the secret we gave you |

200 body includes `access_token` and `expires_in` (seconds). Request a new token before that window ends. An expired or bad token is 401 on the API. A wrong secret is 401 from Keycloak and there is no `access_token`.

The access token is a JWT. Before you call search, confirm:

| Claim | Required |
| --- | --- |
| `sub` | present |
| `aud` | includes `api-client` (`account` may also be present) |
| `roles` | includes `admin` and `search-user` |
| `groups` | includes `_empty` |

`_empty` is a sentinel so the groups claim is always present. It does not grant access to files. There is no `ingest-service` role on this token, so `/internal/*` returns 403.

```bash
export KEYCLOAK_EXTERNAL_SECRET=external-api-client-secret
export TOKEN=$(curl -sS -X POST \
  "http://localhost:8080/realms/enterprise-search-realm/protocol/openid-connect/token" \
  -d grant_type=client_credentials \
  -d client_id=external-api-client \
  -d client_secret="$KEYCLOAK_EXTERNAL_SECRET" \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')
```

## 2. Call search

```http
POST {API_BASE}/search
Authorization: Bearer {access_token}
Content-Type: application/json

{"q":"alpha-proof-token","size":10}
```

| Field | Rule |
| --- | --- |
| `q` | Required non-empty string. |
| `size` | Optional. Integer 1–50. Default is 10. |

200 body:

| Field | Meaning |
| --- | --- |
| `q` | The query you sent, after trim |
| `took_ms` | Wall-clock time on this API |
| `total` | Number of hits in this response |
| `hits` | List of chunks you are allowed to see |

Each hit has `chunk_id`, `score`, `snippet`, and may include `file_id`, `chunk_seq`, `display_name`, `meta_file_type`, `object_store_path`, and `uploaded_at`.

```bash
curl -sS -X POST http://localhost:8000/search \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"q":"alpha-proof-token","size":10}'
```

Search returns only chunks granted to role `search-user` (or to a real group on the token). Realm role `admin` does not show every file. A 200 with `"hits": []` means the call worked and nothing visible matched. That is success, not an auth failure.

On this local stack, if proof documents are indexed, `chunk_id` `proof-role-search-user` is in the hits for `q=alpha-proof-token`.

## 3. Errors

| Status | When |
| --- | --- |
| 401 | Missing Bearer, expired token, or a token this API cannot verify. Also the Keycloak response for a bad secret. |
| 403 | Token is valid but missing `search-user` and `admin`. `/internal/*` is 403 for this client. |
| 400 | `q` is missing or blank. |
| 422 | `size` is outside 1–50, or the body is not the JSON object above. |
| 502 | Search backend failed. |
| 503 | Search is not configured yet. Retry after this stack finishes setup. |

## Checks

`GET {API_BASE}/health` has no token and returns 200 when the process is up.

`GET {API_BASE}/auth/me` with the Bearer returns `{ sub, username, roles, groups }`. `username` is `service-account-external-api-client`. `groups` in this response omits `_empty`.

`GET {API_BASE}/auth/admin-ping` with the Bearer returns `{"ok": true}` when `admin` is on the token.

```bash
curl -sS -H "Authorization: Bearer $TOKEN" http://localhost:8000/auth/admin-ping
curl -sS -o /dev/null -w "%{http_code}\n" \
  -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"q":"alpha-proof-token","size":10}'
```

The second call has no Bearer and must be 401.

## Python

```python
import json
import os
import urllib.parse
import urllib.request

KEYCLOAK = os.environ.get("KEYCLOAK_URL", "http://localhost:8080")
API = os.environ.get("API_BASE_URL", "http://localhost:8000")
SECRET = os.environ["KEYCLOAK_EXTERNAL_SECRET"]

token_body = urllib.parse.urlencode(
    {
        "grant_type": "client_credentials",
        "client_id": "external-api-client",
        "client_secret": SECRET,
    }
).encode()
with urllib.request.urlopen(
    urllib.request.Request(
        f"{KEYCLOAK}/realms/enterprise-search-realm/protocol/openid-connect/token",
        data=token_body,
        method="POST",
    )
) as response:
    token = json.load(response)["access_token"]

search = json.dumps({"q": "alpha-proof-token", "size": 10}).encode()
request = urllib.request.Request(
    f"{API}/search",
    data=search,
    method="POST",
    headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    },
)
with urllib.request.urlopen(request) as response:
    print(response.status, response.read().decode())
```

## Pass

- Token request is 200 and `access_token` is present.
- JWT `aud` includes `api-client`. `roles` includes `admin` and `search-user`.
- `GET /auth/admin-ping` is 200.
- `POST /search` is 200. Empty `hits` is fine when nothing is visible. 401 or 403 is a failure.
- The same search with no Bearer, or a token request with a bad secret, is 401.
