from fastapi import APIRouter, Depends

from app.api.deps import require_admin, require_product_user
from app.core.security import CurrentUser
from app.schemas.auth import MeResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/me", response_model=MeResponse)
def me(user: CurrentUser = Depends(require_product_user)) -> MeResponse:
    return MeResponse(sub=user.sub, username=user.username, roles=user.roles, groups=user.groups)


@router.get("/admin-ping")
def admin_ping(_user: CurrentUser = Depends(require_admin)) -> dict[str, bool]:
    return {"ok": True}
