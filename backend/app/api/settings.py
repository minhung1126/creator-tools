import json
import logging
from typing import Dict, List, Literal, Optional

from fastapi import APIRouter, Depends
from google.oauth2.credentials import Credentials
from pydantic import BaseModel, Field

from backend.app.core.config import settings
from backend.app.core.dependencies import require_credentials
from backend.app.core.runtime_config import runtime_config

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/settings", tags=["System & Resource Settings"])


class ResourceSettingsModel(BaseModel):
    default_spreadsheet_id: Optional[str] = ""
    default_playlist_id: Optional[str] = ""


class YouTubeDraftConfigModel(BaseModel):
    spreadsheet_id: str = ""
    playlist_id: str = ""
    worksheet_name: str = ""
    title_column: str = ""
    description_column: str = ""
    team: str = ""
    enabled_people: List[str] = Field(default_factory=list)


class YouTubeDraftConfigUpdateModel(BaseModel):
    video_type: Literal["Video", "Shorts"]
    config: YouTubeDraftConfigModel


def _draft_config_key(video_type: str) -> str:
    return f"youtube_draft_{video_type.lower()}_config"


def _read_draft_config(video_type: str) -> Dict:
    raw = runtime_config.get(_draft_config_key(video_type), "")
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, json.JSONDecodeError):
        logger.warning("Ignoring invalid persisted %s draft config", video_type)
        return {}


@router.get("")
def get_system_settings(creds: Credentials = Depends(require_credentials)):
    del creds
    rc = runtime_config.get_all()
    return {
        "host": settings.base_url,
        "frontend_url": settings.frontend_url,
        "redirect_uri": settings.get_redirect_uri(),
        "google_client_configured": bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET),
        "default_spreadsheet_id": rc.get("default_spreadsheet_id", ""),
        "default_playlist_id": rc.get("default_playlist_id", ""),
    }


@router.post("")
def update_system_settings(payload: ResourceSettingsModel, creds: Credentials = Depends(require_credentials)):
    update_data = {}
    if payload.default_spreadsheet_id is not None:
        update_data["default_spreadsheet_id"] = payload.default_spreadsheet_id
    if payload.default_playlist_id is not None:
        update_data["default_playlist_id"] = payload.default_playlist_id
    runtime_config.update(update_data)
    logger.info("System settings updated: %s", list(update_data.keys()))
    return {"status": "success", "message": "Settings updated and saved successfully", "settings": get_system_settings(creds)}


@router.get("/youtube-drafts")
def get_youtube_draft_settings(creds: Credentials = Depends(require_credentials)):
    del creds
    return {"video": _read_draft_config("Video"), "shorts": _read_draft_config("Shorts")}


@router.put("/youtube-drafts")
def update_youtube_draft_settings(payload: YouTubeDraftConfigUpdateModel, creds: Credentials = Depends(require_credentials)):
    del creds
    key = _draft_config_key(payload.video_type)
    value = payload.config.model_dump()
    runtime_config.set(key, value)
    logger.info("YouTube %s draft settings updated", payload.video_type)
    return {"status": "success", "video_type": payload.video_type, "config": value}
