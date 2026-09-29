from fastapi import APIRouter

from app.api.routes import (
    admin_acl,
    admin_connectors,
    admin_identity,
    admin_stats,
    auth,
    files,
    health,
    internal_ingest,
    search,
)

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(auth.router)
api_router.include_router(files.router)
api_router.include_router(search.router)
api_router.include_router(admin_identity.router)
api_router.include_router(admin_acl.router)
api_router.include_router(admin_stats.router)
api_router.include_router(admin_connectors.router)
api_router.include_router(internal_ingest.router)
