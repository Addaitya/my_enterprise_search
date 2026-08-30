from fastapi import APIRouter

from app.api.routes import admin_acl, admin_identity, auth, files, health, search

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(auth.router)
api_router.include_router(files.router)
api_router.include_router(search.router)
api_router.include_router(admin_identity.router)
api_router.include_router(admin_acl.router)
