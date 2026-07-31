from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from backend.app.core.config import settings

router = APIRouter(prefix="/settings", tags=["System & Resource Settings"])

class SystemSettingsModel(BaseModel):
    host: Optional[str] = "http://localhost:8000"
    frontend_url: Optional[str] = "http://localhost:3000"
    google_client_id: Optional[str] = ""
    google_client_secret: Optional[str] = ""
    default_spreadsheet_id: Optional[str] = ""
    default_playlist_id: Optional[str] = ""
    default_drive_folder_id: Optional[str] = ""
    
    # Meta API Extensibility Fields
    meta_app_id: Optional[str] = ""
    meta_app_secret: Optional[str] = ""
    meta_access_token: Optional[str] = ""

@router.get("")
def get_system_settings():
    return {
        "host": settings.HOST,
        "frontend_url": settings.FRONTEND_URL,
        "redirect_uri": settings.get_redirect_uri(),
        "google_client_id": settings.GOOGLE_CLIENT_ID,
        "google_client_secret_set": bool(settings.GOOGLE_CLIENT_SECRET),
        "default_spreadsheet_id": settings.DEFAULT_SPREADSHEET_ID,
        "default_playlist_id": settings.DEFAULT_PLAYLIST_ID,
        "default_drive_folder_id": settings.DEFAULT_DRIVE_FOLDER_ID,
        
        # Meta API Integration Status
        "meta_app_id": settings.META_APP_ID,
        "meta_configured": bool(settings.META_APP_ID and settings.META_ACCESS_TOKEN)
    }

@router.post("")
def update_system_settings(payload: SystemSettingsModel):
    if payload.host is not None:
        settings.HOST = payload.host
    if payload.frontend_url is not None:
        settings.FRONTEND_URL = payload.frontend_url
    if payload.google_client_id is not None:
        settings.GOOGLE_CLIENT_ID = payload.google_client_id
    if payload.google_client_secret:
        settings.GOOGLE_CLIENT_SECRET = payload.google_client_secret
    if payload.default_spreadsheet_id is not None:
        settings.DEFAULT_SPREADSHEET_ID = payload.default_spreadsheet_id
    if payload.default_playlist_id is not None:
        settings.DEFAULT_PLAYLIST_ID = payload.default_playlist_id
    if payload.default_drive_folder_id is not None:
        settings.DEFAULT_DRIVE_FOLDER_ID = payload.default_drive_folder_id
        
    if payload.meta_app_id is not None:
        settings.META_APP_ID = payload.meta_app_id
    if payload.meta_app_secret is not None:
        settings.META_APP_SECRET = payload.meta_app_secret
    if payload.meta_access_token is not None:
        settings.META_ACCESS_TOKEN = payload.meta_access_token

    return {
        "status": "success",
        "message": "Settings updated successfully",
        "settings": get_system_settings()
    }
