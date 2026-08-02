from fastapi import APIRouter

from backend.app.api.auth import router as auth_router
from backend.app.api.settings import router as settings_router
from backend.app.api.sheets import router as sheets_router
from backend.app.api.youtube import router as youtube_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth_router)
api_router.include_router(settings_router)
api_router.include_router(sheets_router)
api_router.include_router(youtube_router)
