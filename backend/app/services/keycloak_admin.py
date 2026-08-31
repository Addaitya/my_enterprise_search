"""Keycloak Admin API client for product identity dual-write.

Uses ``api-client`` client_credentials — never the end-user Bearer.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import httpx

from app.core.config import get_settings

GROUPS_EMPTY_SENTINEL = "_empty"
SYSTEM_ROLE_NAMES = frozenset({"offline_access", "uma_authorization"})
SYSTEM_ROLE_PREFIX = "default-roles-"
RESERVED_NAMES = frozenset({"_empty", "offline_access", "uma_authorization"})


def is_system_role_name(name: str) -> bool:
    return name in SYSTEM_ROLE_NAMES or name.startswith(SYSTEM_ROLE_PREFIX)


def is_reserved_name(name: str) -> bool:
    return name in RESERVED_NAMES or name.startswith(SYSTEM_ROLE_PREFIX)


class KeycloakAdminError(Exception):
    def __init__(self, message: str, *, status_code: int = 502) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class KeycloakAdmin:
    """Thin wrappers over Keycloak Admin REST for users / realm roles / groups."""

    def __init__(self) -> None:
        self._settings = get_settings()

    def fetch_token(self) -> str:
        response = httpx.post(
            f"{self._settings.keycloak_url}/realms/{self._settings.keycloak_realm}"
            "/protocol/openid-connect/token",
            data={
                "grant_type": "client_credentials",
                "client_id": self._settings.keycloak_client_id,
                "client_secret": self._settings.keycloak_api_secret,
            },
            timeout=15,
        )
        if response.is_error:
            raise KeycloakAdminError(
                f"client_credentials failed: {response.status_code} {response.text}",
                status_code=503,
            )
        token = response.json().get("access_token")
        if not token:
            raise KeycloakAdminError("client_credentials response missing access_token", status_code=503)
        return token

    def _client(self) -> httpx.Client:
        token = self.fetch_token()
        return httpx.Client(
            base_url=(
                f"{self._settings.keycloak_url}/admin/realms/{self._settings.keycloak_realm}"
            ),
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )

    def _json(self, response: httpx.Response) -> Any:
        if response.status_code == 409:
            raise KeycloakAdminError(self._conflict_message(response), status_code=409)
        if response.status_code == 404:
            raise KeycloakAdminError("Not found", status_code=404)
        if response.is_error:
            raise KeycloakAdminError(
                f"keycloak {response.request.method} {response.request.url.path} "
                f"{response.status_code}: {response.text}",
                status_code=502,
            )
        if not response.content:
            return None
        return response.json()

    @staticmethod
    def _conflict_message(response: httpx.Response) -> str:
        text = (response.text or "").lower()
        if "user exists" in text or "username" in text:
            return "Username already exists"
        if "role" in text:
            return "Role name already exists"
        if "group" in text:
            return "Group name already exists"
        return "Conflict"

    @staticmethod
    def _id_from_location(response: httpx.Response) -> str:
        location = response.headers.get("Location") or response.headers.get("location")
        if not location:
            raise KeycloakAdminError("Keycloak create response missing Location header")
        path = urlparse(location).path.rstrip("/")
        entity_id = path.rsplit("/", 1)[-1]
        if not entity_id:
            raise KeycloakAdminError(f"Could not parse id from Location: {location}")
        return entity_id

    # --- Users ---

    def find_user_by_username(self, username: str) -> dict[str, Any] | None:
        with self._client() as client:
            users = self._json(
                client.get("/users", params={"username": username, "exact": "true"})
            ) or []
            return users[0] if users else None

    def get_user(self, user_id: str) -> dict[str, Any]:
        with self._client() as client:
            return self._json(client.get(f"/users/{user_id}"))

    def create_user(
        self,
        *,
        username: str,
        email: str | None,
        enabled: bool,
        first_name: str | None = None,
        last_name: str | None = None,
    ) -> str:
        payload: dict[str, Any] = {
            "username": username,
            "enabled": enabled,
            "emailVerified": True,
            # Keycloak 26 VERIFY_PROFILE blocks password-grant until names exist.
            "firstName": first_name or username,
            "lastName": last_name or "User",
            "requiredActions": [],
        }
        if email:
            payload["email"] = email
        with self._client() as client:
            response = client.post("/users", json=payload)
            if response.status_code == 409:
                raise KeycloakAdminError("Username already exists", status_code=409)
            if response.status_code not in (201, 204):
                self._json(response)
            if response.headers.get("Location") or response.headers.get("location"):
                user_id = self._id_from_location(response)
            else:
                found = self.find_user_by_username(username)
                if not found:
                    raise KeycloakAdminError(f"Created user {username} but could not reload it")
                user_id = found["id"]
            # Keycloak 26 user profile requires first/last name; clear VERIFY_PROFILE etc.
            current = self._json(client.get(f"/users/{user_id}"))
            current["firstName"] = current.get("firstName") or first_name or username
            current["lastName"] = current.get("lastName") or last_name or "User"
            current["emailVerified"] = True
            current["requiredActions"] = []
            self._json(client.put(f"/users/{user_id}", json=current))
            return user_id

    def update_user(
        self,
        user_id: str,
        *,
        email: str | None = None,
        enabled: bool | None = None,
    ) -> None:
        with self._client() as client:
            current = self._json(client.get(f"/users/{user_id}"))
            if email is not None:
                current["email"] = email
            if enabled is not None:
                current["enabled"] = enabled
            self._json(client.put(f"/users/{user_id}", json=current))

    def set_password(self, user_id: str, password: str) -> None:
        with self._client() as client:
            response = client.put(
                f"/users/{user_id}/reset-password",
                json={"type": "password", "value": password, "temporary": False},
            )
            if response.is_error:
                raise KeycloakAdminError(
                    f"reset-password failed: {response.status_code} {response.text}",
                    status_code=502,
                )

    def delete_user(self, user_id: str) -> None:
        """Compensate helper after a failed Postgres mirror upsert."""
        with self._client() as client:
            response = client.delete(f"/users/{user_id}")
            if response.status_code in (204, 404):
                return
            self._json(response)

    def list_user_realm_roles(self, user_id: str) -> list[dict[str, Any]]:
        with self._client() as client:
            return self._json(client.get(f"/users/{user_id}/role-mappings/realm")) or []

    def list_user_groups(self, user_id: str) -> list[dict[str, Any]]:
        with self._client() as client:
            return self._json(client.get(f"/users/{user_id}/groups")) or []

    def get_realm_role(self, name: str) -> dict[str, Any]:
        with self._client() as client:
            return self._json(client.get(f"/roles/{name}"))

    def replace_user_realm_roles(self, user_id: str, role_names: list[str]) -> None:
        """Set product realm roles; leave system/built-in roles untouched."""
        desired = set(role_names)
        with self._client() as client:
            current = self._json(client.get(f"/users/{user_id}/role-mappings/realm")) or []
            current_by_name = {role["name"]: role for role in current}
            system_keep = {
                name: role
                for name, role in current_by_name.items()
                if is_system_role_name(name)
            }
            product_current = {
                name: role
                for name, role in current_by_name.items()
                if not is_system_role_name(name)
            }
            to_remove = [role for name, role in product_current.items() if name not in desired]
            to_add_names = desired - set(product_current) - set(system_keep)
            if to_remove:
                response = client.request(
                    "DELETE",
                    f"/users/{user_id}/role-mappings/realm",
                    json=to_remove,
                )
                if response.is_error:
                    raise KeycloakAdminError(
                        f"remove roles failed: {response.status_code} {response.text}"
                    )
            if to_add_names:
                representations = [
                    self._json(client.get(f"/roles/{name}")) for name in sorted(to_add_names)
                ]
                response = client.post(
                    f"/users/{user_id}/role-mappings/realm",
                    json=representations,
                )
                if response.is_error:
                    raise KeycloakAdminError(
                        f"assign roles failed: {response.status_code} {response.text}"
                    )

    def add_user_realm_role(self, user_id: str, role_name: str) -> None:
        """Add one product realm role (no-op if already present). Does not touch other roles."""
        if is_system_role_name(role_name):
            raise KeycloakAdminError(f"Cannot assign system role {role_name}", status_code=400)
        with self._client() as client:
            current = self._json(client.get(f"/users/{user_id}/role-mappings/realm")) or []
            if any(role.get("name") == role_name for role in current):
                return
            representation = self._json(client.get(f"/roles/{role_name}"))
            response = client.post(
                f"/users/{user_id}/role-mappings/realm",
                json=[representation],
            )
            if response.is_error:
                raise KeycloakAdminError(
                    f"assign role failed: {response.status_code} {response.text}"
                )

    def remove_user_realm_role(self, user_id: str, role_name: str) -> None:
        """Remove one product realm role (no-op if absent). Does not touch other roles."""
        if is_system_role_name(role_name):
            raise KeycloakAdminError(f"Cannot remove system role {role_name}", status_code=400)
        with self._client() as client:
            current = self._json(client.get(f"/users/{user_id}/role-mappings/realm")) or []
            match = next((role for role in current if role.get("name") == role_name), None)
            if match is None:
                return
            response = client.request(
                "DELETE",
                f"/users/{user_id}/role-mappings/realm",
                json=[match],
            )
            if response.is_error:
                raise KeycloakAdminError(
                    f"remove role failed: {response.status_code} {response.text}"
                )

    def replace_user_groups(self, user_id: str, group_names: list[str]) -> None:
        """Set product groups. Empty product list → join ``_empty`` sentinel only."""
        product = [name for name in group_names if name != GROUPS_EMPTY_SENTINEL]
        wanted_names = set(product) if product else {GROUPS_EMPTY_SENTINEL}
        with self._client() as client:
            current = self._json(client.get(f"/users/{user_id}/groups")) or []
            current_by_name = {group["name"]: group for group in current}
            for name, group in list(current_by_name.items()):
                if name not in wanted_names:
                    response = client.delete(f"/users/{user_id}/groups/{group['id']}")
                    if response.is_error:
                        raise KeycloakAdminError(
                            f"leave group failed: {response.status_code} {response.text}"
                        )
            for name in wanted_names:
                if name in current_by_name:
                    continue
                group = self._group_by_name(client, name)
                response = client.put(f"/users/{user_id}/groups/{group['id']}")
                if response.is_error:
                    raise KeycloakAdminError(
                        f"join group failed: {response.status_code} {response.text}"
                    )

    def join_user_group(self, user_id: str, group_name: str) -> None:
        """Join one group by name (no-op if already a member). Leaves other groups alone."""
        with self._client() as client:
            current = self._json(client.get(f"/users/{user_id}/groups")) or []
            if any(group.get("name") == group_name for group in current):
                return
            group = self._group_by_name(client, group_name)
            response = client.put(f"/users/{user_id}/groups/{group['id']}")
            if response.is_error:
                raise KeycloakAdminError(
                    f"join group failed: {response.status_code} {response.text}"
                )
            # Leaving _empty when joining a product group keeps KC consistent with replace path.
            if group_name != GROUPS_EMPTY_SENTINEL:
                empty = next(
                    (g for g in current if g.get("name") == GROUPS_EMPTY_SENTINEL),
                    None,
                )
                if empty is not None:
                    leave = client.delete(f"/users/{user_id}/groups/{empty['id']}")
                    if leave.is_error:
                        raise KeycloakAdminError(
                            f"leave _empty failed: {leave.status_code} {leave.text}"
                        )

    def leave_user_group(self, user_id: str, group_name: str) -> None:
        """Leave one group by name. If no product groups remain, join ``_empty``."""
        with self._client() as client:
            current = self._json(client.get(f"/users/{user_id}/groups")) or []
            match = next((group for group in current if group.get("name") == group_name), None)
            if match is None:
                # Still ensure _empty if no product groups left.
                product_left = [
                    g for g in current if g.get("name") != GROUPS_EMPTY_SENTINEL
                ]
                if not product_left and group_name != GROUPS_EMPTY_SENTINEL:
                    if not any(g.get("name") == GROUPS_EMPTY_SENTINEL for g in current):
                        empty = self._group_by_name(client, GROUPS_EMPTY_SENTINEL)
                        response = client.put(f"/users/{user_id}/groups/{empty['id']}")
                        if response.is_error:
                            raise KeycloakAdminError(
                                f"join _empty failed: {response.status_code} {response.text}"
                            )
                return
            response = client.delete(f"/users/{user_id}/groups/{match['id']}")
            if response.is_error:
                raise KeycloakAdminError(
                    f"leave group failed: {response.status_code} {response.text}"
                )
            remaining = [
                g
                for g in current
                if g.get("name") != group_name and g.get("name") != GROUPS_EMPTY_SENTINEL
            ]
            if not remaining and group_name != GROUPS_EMPTY_SENTINEL:
                if not any(g.get("name") == GROUPS_EMPTY_SENTINEL for g in current):
                    empty = self._group_by_name(client, GROUPS_EMPTY_SENTINEL)
                    join = client.put(f"/users/{user_id}/groups/{empty['id']}")
                    if join.is_error:
                        raise KeycloakAdminError(
                            f"join _empty failed: {join.status_code} {join.text}"
                        )

    def _group_by_name(self, client: httpx.Client, name: str) -> dict[str, Any]:
        groups = self._json(client.get("/groups", params={"search": name})) or []
        for group in groups:
            if group.get("name") == name:
                return group
        raise KeycloakAdminError(f"Group {name!r} not found", status_code=404)

    # --- Roles ---

    def create_realm_role(self, *, name: str, description: str | None) -> dict[str, Any]:
        payload: dict[str, Any] = {"name": name}
        if description is not None:
            payload["description"] = description
        with self._client() as client:
            response = client.post("/roles", json=payload)
            if response.status_code == 409:
                raise KeycloakAdminError("Role name already exists", status_code=409)
            if response.status_code not in (201, 204):
                self._json(response)
            return self._json(client.get(f"/roles/{name}"))

    def get_realm_role_by_id(self, role_id: str) -> dict[str, Any]:
        with self._client() as client:
            return self._json(client.get(f"/roles-by-id/{role_id}"))

    def update_realm_role_description(self, name: str, description: str | None) -> dict[str, Any]:
        with self._client() as client:
            current = self._json(client.get(f"/roles/{name}"))
            current["description"] = description
            # Name must stay identical (G7).
            response = client.put(f"/roles/{name}", json=current)
            if response.is_error:
                self._json(response)
            return self._json(client.get(f"/roles/{name}"))

    def delete_realm_role(self, name: str) -> None:
        with self._client() as client:
            response = client.delete(f"/roles/{name}")
            if response.status_code in (204, 404):
                return
            self._json(response)

    # --- Groups ---

    def create_group(self, *, name: str) -> dict[str, Any]:
        with self._client() as client:
            response = client.post("/groups", json={"name": name})
            if response.status_code == 409:
                raise KeycloakAdminError("Group name already exists", status_code=409)
            if response.status_code not in (201, 204):
                self._json(response)
            if response.headers.get("Location") or response.headers.get("location"):
                group_id = self._id_from_location(response)
                return self._json(client.get(f"/groups/{group_id}"))
            return self._group_by_name(client, name)

    def get_group(self, group_id: str) -> dict[str, Any]:
        with self._client() as client:
            return self._json(client.get(f"/groups/{group_id}"))

    def find_group_by_name(self, name: str) -> dict[str, Any] | None:
        with self._client() as client:
            try:
                return self._group_by_name(client, name)
            except KeycloakAdminError as exc:
                if exc.status_code == 404:
                    return None
                raise

    def delete_group(self, group_id: str) -> None:
        with self._client() as client:
            response = client.delete(f"/groups/{group_id}")
            if response.status_code in (204, 404):
                return
            self._json(response)
