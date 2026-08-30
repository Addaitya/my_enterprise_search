from __future__ import annotations

from typing import Any

import httpx

from app.core.config import get_settings

REALM_ADMIN_USERNAME = "realm-admin"
REALM_ADMIN_PASSWORD = "adminpass"
SEARCHER_USERNAME = "searcher"
SEARCHER_PASSWORD = "searcherpass"
CLIENT_IDS = ("api-client", "web-client")
HARDCODED_GROUPS_MAPPERS = ("aaa-groups-always-present", "groups-always-present")
# Keycloak omits `groups` when membership is empty, which breaks OpenSearch DLS
# JSON. Dual mappers on the same claim overwrite each other, so searcher joins
# this sentinel group instead. FastAPI strips it from the groups list.
GROUPS_EMPTY_SENTINEL = "_empty"
BASIC_CLIENT_SCOPE = "basic"


def _admin_client() -> httpx.Client:
    settings = get_settings()
    token_response = httpx.post(
        f"{settings.keycloak_url}/realms/master/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": settings.keycloak_admin,
            "password": settings.keycloak_admin_password,
        },
        timeout=15,
    )
    token_response.raise_for_status()
    access_token = token_response.json()["access_token"]
    return httpx.Client(
        base_url=f"{settings.keycloak_url}/admin/realms/{settings.keycloak_realm}",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=15,
    )


def _json(response: httpx.Response) -> Any:
    if response.is_error:
        raise RuntimeError(
            f"keycloak {response.request.method} {response.request.url} "
            f"{response.status_code}: {response.text}"
        )
    if not response.content:
        return None
    return response.json()


def verify_realm() -> dict[str, Any]:
    settings = get_settings()
    url = f"{settings.keycloak_url}/realms/{settings.keycloak_realm}"
    response = httpx.get(url, timeout=10)
    response.raise_for_status()
    body = response.json()
    public_key = body.get("public_key") or ""
    print(f"[ok] keycloak realm {body.get('realm')} at {url}")
    if len(public_key) >= 16:
        print(f"[ok] realm public_key {public_key[:8]}...{public_key[-8:]}")
    else:
        print("[warn] realm public_key missing or short")
    return body


def _get_clients(admin: httpx.Client) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for client_id in CLIENT_IDS:
        matches = _json(admin.get("/clients", params={"clientId": client_id})) or []
        if not matches:
            raise RuntimeError(f"keycloak client {client_id} not found")
        client = matches[0]
        found[client_id] = client
        print(f"[ok] keycloak client {client_id} id={client.get('id')}")
        if client_id == "web-client" and client.get("directAccessGrantsEnabled"):
            raise RuntimeError("web-client must not have direct access grants enabled")
    _ensure_web_client_browser_settings(admin, found)
    return found


def _ensure_web_client_browser_settings(
    admin: httpx.Client, clients: dict[str, dict[str, Any]]
) -> None:
    client = clients["web-client"]
    client_uuid = client["id"]
    full = _json(admin.get(f"/clients/{client_uuid}"))
    attributes = dict(full.get("attributes") or {})
    redirect_uris = list(full.get("redirectUris") or [])
    changed = False
    if "http://localhost:5173/*" not in redirect_uris:
        redirect_uris.append("http://localhost:5173/*")
        full["redirectUris"] = redirect_uris
        changed = True
    if not attributes.get("post.logout.redirect.uris"):
        attributes["post.logout.redirect.uris"] = "http://localhost:5173/*"
        full["attributes"] = attributes
        changed = True
    if changed:
        response = admin.put(f"/clients/{client_uuid}", json=full)
        if response.is_error:
            raise RuntimeError(f"update web-client {response.status_code}: {response.text}")
        print("[ok] web-client redirect and post-logout URIs set")
    else:
        print("[ok] web-client browser URIs already set")


def _ensure_basic_scope(admin: httpx.Client, clients: dict[str, dict[str, Any]]) -> None:
    """Keycloak 26 puts `sub` on the `basic` client scope. realm.json omitted it,
    so access tokens otherwise have no `sub`.
    """
    scopes = _json(admin.get("/client-scopes")) or []
    basic = next((scope for scope in scopes if scope.get("name") == BASIC_CLIENT_SCOPE), None)
    if basic is None:
        print("[warn] client scope 'basic' missing; adding sub mapper on each client")
        for client_id, client in clients.items():
            _ensure_sub_mapper(admin, client_id, client["id"])
        return
    for client_id, client in clients.items():
        client_uuid = client["id"]
        assigned = _json(admin.get(f"/clients/{client_uuid}/default-client-scopes")) or []
        if any(scope.get("id") == basic["id"] or scope.get("name") == BASIC_CLIENT_SCOPE for scope in assigned):
            print(f"[ok] {client_id} already has default scope {BASIC_CLIENT_SCOPE}")
            continue
        response = admin.put(f"/clients/{client_uuid}/default-client-scopes/{basic['id']}")
        if response.is_error:
            raise RuntimeError(
                f"assign basic scope {client_id} {response.status_code}: {response.text}"
            )
        print(f"[ok] assigned default scope {BASIC_CLIENT_SCOPE} to {client_id}")


def _ensure_sub_mapper(admin: httpx.Client, client_id: str, client_uuid: str) -> None:
    mappers = _json(admin.get(f"/clients/{client_uuid}/protocol-mappers/models")) or []
    if any(
        mapper.get("name") == "subject" or mapper.get("protocolMapper") == "oidc-sub-mapper"
        for mapper in mappers
    ):
        print(f"[ok] sub mapper present on {client_id}")
        return
    _json(
        admin.post(
            f"/clients/{client_uuid}/protocol-mappers/models",
            json={
                "name": "subject",
                "protocol": "openid-connect",
                "protocolMapper": "oidc-usermodel-property-mapper",
                "consentRequired": False,
                "config": {
                    "user.attribute": "id",
                    "claim.name": "sub",
                    "jsonType.label": "String",
                    "id.token.claim": "true",
                    "access.token.claim": "true",
                    "userinfo.token.claim": "true",
                },
            },
        )
    )
    print(f"[ok] added sub mapper on {client_id}")


def _ensure_groups_claim(admin: httpx.Client, clients: dict[str, dict[str, Any]]) -> None:
    """Keep the native groups mapper only. Remove hardcoded mappers that fight it."""
    for client_id, client in clients.items():
        client_uuid = client["id"]
        mappers = _json(admin.get(f"/clients/{client_uuid}/protocol-mappers/models")) or []
        by_name = {mapper.get("name"): mapper for mapper in mappers}
        if by_name.get("groups") is None:
            raise RuntimeError(f"{client_id} is missing the groups protocol mapper")
        for name in HARDCODED_GROUPS_MAPPERS:
            leftover = by_name.get(name)
            if leftover and leftover.get("id"):
                admin.delete(
                    f"/clients/{client_uuid}/protocol-mappers/models/{leftover['id']}"
                ).raise_for_status()
                print(f"[ok] removed conflicting mapper {name} on {client_id}")
        print(f"[ok] groups mapper present on {client_id}")
    _ensure_group(admin, GROUPS_EMPTY_SENTINEL)


def _ensure_group(admin: httpx.Client, name: str) -> dict[str, Any]:
    try:
        return _group_by_name(admin, name)
    except RuntimeError:
        response = admin.post("/groups", json={"name": name})
        if response.status_code not in (201, 204):
            raise RuntimeError(f"create group {name} {response.status_code}: {response.text}")
        group = _group_by_name(admin, name)
        print(f"[ok] created keycloak group {name}")
        return group


def _realm_role(admin: httpx.Client, name: str) -> dict[str, Any]:
    return _json(admin.get(f"/roles/{name}"))


def _find_user(admin: httpx.Client, username: str) -> dict[str, Any] | None:
    users = _json(admin.get("/users", params={"username": username, "exact": "true"})) or []
    return users[0] if users else None


def _set_password(admin: httpx.Client, user_id: str, password: str) -> None:
    response = admin.put(
        f"/users/{user_id}/reset-password",
        json={"type": "password", "value": password, "temporary": False},
    )
    if response.is_error:
        raise RuntimeError(f"reset-password {user_id} {response.status_code}: {response.text}")


def _ensure_realm_roles(admin: httpx.Client, user_id: str, required: set[str], *, only: bool) -> None:
    current = _json(admin.get(f"/users/{user_id}/role-mappings/realm")) or []
    current_names = {role["name"] for role in current}
    missing = required - current_names
    if missing:
        representations = [_realm_role(admin, name) for name in sorted(missing)]
        response = admin.post(f"/users/{user_id}/role-mappings/realm", json=representations)
        if response.is_error:
            raise RuntimeError(f"assign roles {response.status_code}: {response.text}")
    if only:
        extra = [role for role in current if role["name"] not in required]
        if extra:
            response = admin.request(
                "DELETE",
                f"/users/{user_id}/role-mappings/realm",
                json=extra,
            )
            if response.is_error:
                raise RuntimeError(f"remove roles {response.status_code}: {response.text}")


def _group_by_name(admin: httpx.Client, name: str) -> dict[str, Any]:
    groups = _json(admin.get("/groups", params={"search": name})) or []
    for group in groups:
        if group.get("name") == name:
            return group
    raise RuntimeError(f"keycloak group {name} not found")


def _ensure_group_membership(admin: httpx.Client, user_id: str, group_name: str | None) -> None:
    current = _json(admin.get(f"/users/{user_id}/groups")) or []
    if group_name is None:
        for group in current:
            response = admin.delete(f"/users/{user_id}/groups/{group['id']}")
            if response.is_error:
                raise RuntimeError(f"leave group {response.status_code}: {response.text}")
        return
    wanted = _group_by_name(admin, group_name)
    if any(group.get("id") == wanted["id"] for group in current):
        return
    response = admin.put(f"/users/{user_id}/groups/{wanted['id']}")
    if response.is_error:
        raise RuntimeError(f"join group {response.status_code}: {response.text}")


def _ensure_user(
    admin: httpx.Client,
    *,
    username: str,
    password: str,
    email: str,
    first_name: str,
    last_name: str,
    roles: set[str],
    group: str | None,
    only_listed_roles: bool,
) -> None:
    user = _find_user(admin, username)
    if user is None:
        response = admin.post(
            "/users",
            json={
                "username": username,
                "enabled": True,
                "email": email,
                "emailVerified": True,
                "firstName": first_name,
                "lastName": last_name,
            },
        )
        if response.status_code not in (201, 204):
            raise RuntimeError(f"create user {username} {response.status_code}: {response.text}")
        user = _find_user(admin, username)
        if user is None:
            raise RuntimeError(f"created user {username} but could not reload it")
        print(f"[ok] created keycloak user {username} id={user['id']}")
    else:
        if not user.get("enabled", True):
            response = admin.put(
                f"/users/{user['id']}",
                json={**user, "enabled": True},
            )
            if response.is_error:
                raise RuntimeError(f"enable user {username} {response.status_code}: {response.text}")
        print(f"[ok] keycloak user {username} id={user['id']}")

    _set_password(admin, user["id"], password)
    _ensure_realm_roles(admin, user["id"], roles, only=only_listed_roles)
    _ensure_group_membership(admin, user["id"], group)
    print(f"[ok] user {username} roles={sorted(roles)} group={group or '(none)'}")


PAGE_SIZE = 100
PAGINATION_SAFETY_LIMIT = 10_000


def _paginate(
    admin: httpx.Client, path: str, extra_params: dict[str, Any] | None = None
) -> list[Any]:
    first = 0
    items: list[Any] = []
    while first <= PAGINATION_SAFETY_LIMIT:
        params: dict[str, Any] = dict(extra_params or {})
        params["first"] = first
        params["max"] = PAGE_SIZE
        batch = _json(admin.get(path, params=params)) or []
        if not isinstance(batch, list):
            raise RuntimeError(f"expected list from {path}, got {type(batch).__name__}")
        items.extend(batch)
        if len(batch) < PAGE_SIZE:
            return items
        first += PAGE_SIZE
    raise RuntimeError(f"pagination safety stop on {path} after {first} rows")


def list_all_realm_roles(admin: httpx.Client) -> list[dict[str, Any]]:
    return _paginate(admin, "/roles", {"briefRepresentation": "false"})


def list_all_groups(admin: httpx.Client) -> list[dict[str, Any]]:
    """Flatten the realm group tree, including subgroups (C6)."""
    seen: dict[str, dict[str, Any]] = {}

    def walk(groups: list[dict[str, Any]]) -> None:
        for group in groups:
            group_id = group.get("id")
            if not group_id or group_id in seen:
                continue
            seen[group_id] = group
            children = _paginate(
                admin,
                f"/groups/{group_id}/children",
                {"briefRepresentation": "false"},
            )
            walk(children)

    walk(_paginate(admin, "/groups", {"briefRepresentation": "false"}))
    return list(seen.values())


def list_service_account_users(admin: httpx.Client) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for client in _paginate(admin, "/clients"):
        if not client.get("serviceAccountsEnabled"):
            continue
        client_uuid = client.get("id")
        if not client_uuid:
            continue
        response = admin.get(f"/clients/{client_uuid}/service-account-user")
        if response.status_code == 404:
            continue
        user = _json(response)
        if user:
            found.append(user)
    return found


def list_all_users(admin: httpx.Client) -> list[dict[str, Any]]:
    """All realm users, including disabled and service accounts (G6)."""
    by_id: dict[str, dict[str, Any]] = {}
    for user in _paginate(admin, "/users", {"briefRepresentation": "false"}):
        user_id = user.get("id")
        if user_id:
            by_id[user_id] = user
    for user in list_service_account_users(admin):
        user_id = user.get("id")
        if user_id and user_id not in by_id:
            by_id[user_id] = user
    return list(by_id.values())


def list_user_realm_roles(admin: httpx.Client, user_id: str) -> list[dict[str, Any]]:
    return _json(admin.get(f"/users/{user_id}/role-mappings/realm")) or []


def list_user_groups(admin: httpx.Client, user_id: str) -> list[dict[str, Any]]:
    return _paginate(
        admin,
        f"/users/{user_id}/groups",
        {"briefRepresentation": "false"},
    )


# Client roles on realm-management required for product Admin API (api-client
# service account via client_credentials). manage-realm covers realm role CRUD.
_API_CLIENT_ADMIN_ROLES = (
    "manage-users",
    "view-users",
    "query-users",
    "query-groups",
    "manage-realm",
    "view-realm",
)


def _ensure_api_client_service_account_roles(
    admin: httpx.Client, clients: dict[str, dict[str, Any]]
) -> None:
    """Grant realm-management roles so api-client can dual-write identity."""
    settings = get_settings()
    api_client = clients["api-client"]
    client_uuid = api_client["id"]
    sa = _json(admin.get(f"/clients/{client_uuid}/service-account-user"))
    if not sa or not sa.get("id"):
        raise RuntimeError("api-client service-account user missing")
    sa_id = sa["id"]

    rm_clients = _json(admin.get("/clients", params={"clientId": "realm-management"})) or []
    if not rm_clients:
        raise RuntimeError("realm-management client not found")
    rm_id = rm_clients[0]["id"]

    available = {
        role["name"]: role
        for role in (_json(admin.get(f"/users/{sa_id}/role-mappings/clients/{rm_id}/available")) or [])
    }
    # Also pull already-assigned so we can skip quietly.
    assigned = {
        role["name"]: role
        for role in (_json(admin.get(f"/users/{sa_id}/role-mappings/clients/{rm_id}")) or [])
    }
    to_add: list[dict[str, Any]] = []
    for name in _API_CLIENT_ADMIN_ROLES:
        if name in assigned:
            continue
        role = available.get(name)
        if role is None:
            # Fall back to full client role list
            all_roles = _json(admin.get(f"/clients/{rm_id}/roles")) or []
            role = next((r for r in all_roles if r.get("name") == name), None)
        if role is None:
            raise RuntimeError(f"realm-management role {name} not found")
        to_add.append(role)
    if to_add:
        response = admin.post(
            f"/users/{sa_id}/role-mappings/clients/{rm_id}",
            json=to_add,
        )
        if response.is_error:
            raise RuntimeError(
                f"assign api-client service-account roles {response.status_code}: {response.text}"
            )
        print(
            f"[ok] api-client service account granted realm-management roles: "
            f"{sorted(r['name'] for r in to_add)}"
        )
    else:
        print(
            f"[ok] api-client service account already has Admin API roles "
            f"({settings.keycloak_client_id})"
        )


def configure() -> None:
    """Verify realm/clients and ensure seed users. Does not re-import realm.json."""
    verify_realm()
    admin = _admin_client()
    with admin:
        clients = _get_clients(admin)
        _ensure_basic_scope(admin, clients)
        _ensure_groups_claim(admin, clients)
        _ensure_api_client_service_account_roles(admin, clients)
        _ensure_user(
            admin,
            username=REALM_ADMIN_USERNAME,
            password=REALM_ADMIN_PASSWORD,
            email="admin@example.com",
            first_name="Realm",
            last_name="Admin",
            roles={"admin", "search-user"},
            group="engineering",
            only_listed_roles=False,
        )
        _ensure_user(
            admin,
            username=SEARCHER_USERNAME,
            password=SEARCHER_PASSWORD,
            email="searcher@example.com",
            first_name="Search",
            last_name="User",
            roles={"search-user"},
            group=GROUPS_EMPTY_SENTINEL,
            only_listed_roles=True,
        )
