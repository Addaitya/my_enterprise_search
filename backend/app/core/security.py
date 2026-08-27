from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

import jwt
from jwt import PyJWKClient

from app.core.config import get_settings

# Keycloak omits empty group membership; searcher is in this sentinel group so
# DLS JSON stays valid. Strip it from product-facing claims.
GROUPS_EMPTY_SENTINEL = "_empty"


@dataclass
class CurrentUser:
    sub: str
    username: str
    roles: list[str] = field(default_factory=list)
    groups: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


@lru_cache
def _jwk_client() -> PyJWKClient:
    settings = get_settings()
    return PyJWKClient(settings.keycloak_jwks_url)


def decode_access_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    signing_key = _jwk_client().get_signing_key_from_jwt(token)
    return jwt.decode(
        token,
        signing_key.key,
        algorithms=["RS256"],
        audience=settings.keycloak_client_id,
        issuer=settings.keycloak_issuer,
    )


def _as_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        parts = [part.strip() for part in value.split(",") if part.strip()]
    elif isinstance(value, list):
        parts = [str(item).strip() for item in value if str(item).strip()]
    else:
        parts = [str(value).strip()] if str(value).strip() else []
    return [part for part in parts if part != GROUPS_EMPTY_SENTINEL]


def current_user_from_payload(payload: dict[str, Any]) -> CurrentUser:
    username = str(payload.get("preferred_username") or payload.get("azp") or "")
    sub = str(payload.get("sub") or username)
    return CurrentUser(
        sub=sub,
        username=username,
        roles=_as_str_list(payload.get("roles")),
        groups=_as_str_list(payload.get("groups")),
        raw=payload,
    )
