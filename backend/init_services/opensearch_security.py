from __future__ import annotations

import copy
from typing import Any

import httpx

from app.core.config import get_settings

INDEX_NAME = "enterprise-search-chunks"
# 3.8 jwt+JWKS expands attr.jwt.groups as a JSON array already. Extra []
# becomes [["engineering"]] and DLS evaluation 500s. ${user.roles} still
# expands as quoted scalars, so it keeps the wrapper brackets.
FILES_SEARCHER_DLS = (
    '{"bool":{"should":[{"terms":{"allowed_roles":[${user.roles}]}},'
    '{"terms":{"allowed_groups":${attr.jwt.groups}}}],"minimum_should_match":1}}'
)


def _client() -> httpx.Client:
    settings = get_settings()
    return httpx.Client(
        base_url=settings.opensearch_url,
        verify=settings.opensearch_verify_certs,
        auth=("admin", settings.opensearch_initial_admin_password),
        timeout=30,
    )


def _json(response: httpx.Response) -> Any:
    if response.is_error:
        raise RuntimeError(
            f"opensearch {response.request.method} {response.request.url.path} "
            f"{response.status_code}: {response.text}"
        )
    if not response.content:
        return {}
    return response.json()


def _jwks_uri() -> str:
    """OpenSearch fetches JWKS from inside the compose network (not localhost)."""
    settings = get_settings()
    return (
        f"{settings.keycloak_internal_url}/realms/{settings.keycloak_realm}"
        "/protocol/openid-connect/certs"
    )


def _put_jwt_auth_domain(client: httpx.Client) -> None:
    settings = get_settings()
    jwks_uri = _jwks_uri()
    current = _json(client.get("/_plugins/_security/api/securityconfig"))
    dynamic = copy.deepcopy(current["config"]["dynamic"])
    authc = dynamic.setdefault("authc", {})
    authc["jwt_auth_domain"] = {
        "http_enabled": True,
        "transport_enabled": True,
        "order": 0,
        "http_authenticator": {
            "type": "jwt",
            "challenge": False,
            "config": {
                "jwks_uri": jwks_uri,
                "jwt_header": "Authorization",
                "subject_key": "preferred_username",
                "roles_key": "roles",
                "required_audience": "api-client",
                "required_issuer": settings.keycloak_issuer,
                "jwt_clock_skew_tolerance_seconds": 30,
            },
        },
        "authentication_backend": {"type": "noop"},
        "description": "Authenticate via Json Web Token from Keycloak",
    }
    basic = authc.get("basic_internal_auth_domain")
    if not basic or not basic.get("http_enabled", True):
        raise RuntimeError("refusing to PUT securityconfig: basic_internal_auth_domain missing or disabled")
    basic["http_enabled"] = True
    if int(basic.get("order", 4)) <= 0:
        basic["order"] = 4
    response = client.put(
        "/_plugins/_security/api/securityconfig/config",
        json={"dynamic": dynamic},
    )
    body = _json(response)
    print(f"[ok] merged jwt_auth_domain ({body.get('status') or response.status_code})")


def _put_roles(client: httpx.Client) -> None:
    searcher = {
        "description": "Read chunks allowed by role or group RACL",
        "cluster_permissions": [
            "cluster_composite_ops_ro",
            "cluster:admin/opensearch/ml/predict",
            "cluster:admin/opensearch/ml/models/get",
        ],
        "index_permissions": [
            {
                "index_patterns": [INDEX_NAME],
                "allowed_actions": ["read", "search"],
                "dls": FILES_SEARCHER_DLS,
            }
        ],
    }
    _json(client.put("/_plugins/_security/api/roles/files_searcher", json=searcher))
    print("[ok] role files_searcher")
    writer = {
        "description": "Backend service ingest and ACL updates; no DLS",
        "cluster_permissions": ["cluster_composite_ops"],
        "index_permissions": [
            {
                "index_patterns": [INDEX_NAME],
                "allowed_actions": ["crud", "create_index", "manage"],
            }
        ],
    }
    _json(client.put("/_plugins/_security/api/roles/files_writer", json=writer))
    print("[ok] role files_writer (not mapped to JWT users)")


def _put_role_mappings(client: httpx.Client) -> None:
    _json(
        client.put(
            "/_plugins/_security/api/rolesmapping/files_searcher",
            json={
                "backend_roles": ["search-user"],
                "hosts": [],
                "users": [],
            },
        )
    )
    print("[ok] rolesmapping files_searcher backend_roles=search-user")
    print(
        "[ok] Keycloak role 'admin' is not mapped here: it collides with the "
        "internal OpenSearch user backend role and would attach DLS to basic admin"
    )

    current = _json(client.get("/_plugins/_security/api/rolesmapping/all_access"))
    mapping = current.get("all_access") or current
    users = [user for user in mapping.get("users") or [] if user != "*"]
    if "admin" not in users:
        users.append("admin")
    backend_roles = [
        role for role in mapping.get("backend_roles") or [] if role != "admin"
    ]
    payload = {
        "hosts": mapping.get("hosts") or [],
        "users": users,
        "backend_roles": backend_roles,
        "and_backend_roles": mapping.get("and_backend_roles") or [],
    }
    if mapping.get("description"):
        payload["description"] = mapping["description"]
    _json(client.put("/_plugins/_security/api/rolesmapping/all_access", json=payload))
    print(f"[ok] all_access users={users} backend_roles={backend_roles} (admin role unmapped)")


def configure() -> None:
    """JWT auth domain, files_searcher DLS role, and all_access fix. Idempotent."""
    with _client() as client:
        _put_jwt_auth_domain(client)
        print(f"[ok] jwt jwks_uri={_jwks_uri()} issuer={get_settings().keycloak_issuer}")
        _put_roles(client)
        _put_role_mappings(client)
        health = _json(client.get("/_cluster/health"))
        print(f"[ok] basic admin still works; cluster {health.get('status')}")
