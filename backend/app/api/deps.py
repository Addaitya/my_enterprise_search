from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.security import CurrentUser, current_user_from_payload, decode_access_token

_bearer = HTTPBearer(auto_error=False)


def user_bearer_header(request: Request) -> dict[str, str]:
    """Forward the incoming user JWT to OpenSearch.

    Future POST /search must use this header. Do not switch search to
    internal basic `admin` — that bypasses DLS.
    """
    authorization = request.headers.get("Authorization")
    if not authorization:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return {"Authorization": authorization}


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> CurrentUser:
    """Return the caller from a verified Bearer JWT.

    Search-time OpenSearch calls must forward this user token so DLS can run.
    Ingest/admin writes keep using internal basic auth, not this helper.
    """
    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        payload = decode_access_token(credentials.credentials)
    except Exception:  # noqa: BLE001 — do not leak verify details to clients
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from None
    user = current_user_from_payload(payload)
    if not user.sub or not user.username:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    return user


def require_product_user(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if "search-user" not in user.roles and "admin" not in user.roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    return user


def require_admin(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if "admin" not in user.roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    return user
