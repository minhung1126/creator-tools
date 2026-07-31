import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional
from google.oauth2.credentials import Credentials

from backend.app.core.config import settings
from backend.app.core.dependencies import require_credentials
from backend.app.core.runtime_config import runtime_config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/settings", tags=["System & Resource Settings"])


class ResourceSettingsModel(BaseModel):
    """Settings that can be modified via the UI and persisted."""
    default_spreadsheet_id: Optional[str] = ""
    default_playlist_id: Optional[str] = ""
    default_drive_folder_id: Optional[str] = ""

    # Meta API Extensibility Fields
    meta_app_id: Optional[str] = ""
    meta_app_secret: Optional[str] = ""
    meta_access_token: Optional[str] = ""


@router.get("")
def get_system_settings(creds: Credentials = Depends(require_credentials)):
    """Get current system settings (requires authentication)."""
    rc = runtime_config.get_all()
    return {
        "host": settings.base_url,
        "frontend_url": settings.frontend_url,
        "redirect_uri": settings.get_redirect_uri(),
        "google_client_configured": bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET),
        "default_spreadsheet_id": rc.get("default_spreadsheet_id", ""),
        "default_playlist_id": rc.get("default_playlist_id", ""),
        "default_drive_folder_id": rc.get("default_drive_folder_id", ""),

        # Meta API Integration Status
        "meta_app_id": rc.get("meta_app_id", ""),
        "meta_configured": bool(rc.get("meta_app_id") and rc.get("meta_access_token"))
    }


@router.post("")
def update_system_settings(
    payload: ResourceSettingsModel,
    creds: Credentials = Depends(require_credentials)
):
    """Update and persist resource settings (requires authentication)."""
    update_data = {}
    if payload.default_spreadsheet_id is not None:
        update_data["default_spreadsheet_id"] = payload.default_spreadsheet_id
    if payload.default_playlist_id is not None:
        update_data["default_playlist_id"] = payload.default_playlist_id
    if payload.default_drive_folder_id is not None:
        update_data["default_drive_folder_id"] = payload.default_drive_folder_id
    if payload.meta_app_id is not None:
        update_data["meta_app_id"] = payload.meta_app_id
    if payload.meta_app_secret is not None:
        update_data["meta_app_secret"] = payload.meta_app_secret
    if payload.meta_access_token is not None:
        update_data["meta_access_token"] = payload.meta_access_token

    runtime_config.update(update_data)
    logger.info("System settings updated: %s", list(update_data.keys()))

    return {
        "status": "success",
        "message": "Settings updated and saved successfully",
        "settings": get_system_settings(creds)
    }
