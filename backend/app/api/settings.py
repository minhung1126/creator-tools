import json
import logging
from typing import Annotated, Dict, List, Literal

from fastapi import APIRouter, Depends, HTTPException
from google.oauth2.credentials import Credentials
from pydantic import BaseModel, Field, model_validator

from backend.app.core.config import settings
from backend.app.core.dependencies import require_login_credentials
from backend.app.core.runtime_config import runtime_config

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/settings", tags=["System & Resource Settings"])


class SharedResourceSettingsModel(BaseModel):
    """Settings shared by Sheet and platform workflows unless overridden."""

    default_spreadsheet_id: str = Field(default="", max_length=512)


class YouTubeResourceSettingsModel(BaseModel):
    """YouTube-only fallback resources."""

    default_playlist_id: str = Field(default="", max_length=256)
    youtube_general_quota_limit: int | None = None
    youtube_quota_safety_buffer_units: int | None = None

    @model_validator(mode="after")
    def validate_quota_policy(self):
        if self.youtube_general_quota_limit is not None and self.youtube_general_quota_limit <= 0:
            raise ValueError("youtube_general_quota_limit 必須大於 0")
        if self.youtube_quota_safety_buffer_units is not None and self.youtube_quota_safety_buffer_units < 0:
            raise ValueError("youtube_quota_safety_buffer_units 必須大於等於 0")
        if (
            self.youtube_general_quota_limit is not None
            and self.youtube_quota_safety_buffer_units is not None
            and self.youtube_quota_safety_buffer_units >= self.youtube_general_quota_limit
        ):
            raise ValueError("youtube_quota_safety_buffer_units 必須小於 youtube_general_quota_limit")
        return self


class YouTubeDraftConfigModel(BaseModel):
    spreadsheet_id: str = Field(default="", max_length=512)
    playlist_id: str = Field(default="", max_length=256)
    worksheet_name: str = Field(default="", max_length=200)
    title_column: str = Field(default="", max_length=200)
    description_column: str = Field(default="", max_length=200)


class TeamPersonFilterModel(BaseModel):
    team: str = Field(default="", max_length=200)
    selected_people: List[Annotated[str, Field(max_length=200)]] = Field(default_factory=list, max_length=200)

    @model_validator(mode="after")
    def normalize_values(self):
        self.team = self.team.strip()
        self.selected_people = list(dict.fromkeys(person.strip() for person in self.selected_people if person.strip()))
        return self


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


def _clean_draft_config(config: Dict) -> Dict:
    cleaned = dict(config)
    cleaned.pop("team", None)
    cleaned.pop("enabled_people", None)
    return cleaned


def _read_legacy_team_person_filter() -> tuple[Dict, bool]:
    for video_type in ("Video", "Shorts"):
        config = _read_draft_config(video_type)
        team = config.get("team")
        people = config.get("enabled_people")
        if team or people:
            value = TeamPersonFilterModel(team=team or "", selected_people=people or [])
            return value.model_dump(), True
    return TeamPersonFilterModel().model_dump(), False


def _read_team_person_filter() -> tuple[Dict, bool]:
    raw = runtime_config.get("shared_team_person_filter", None)
    if isinstance(raw, dict):
        try:
            return TeamPersonFilterModel.model_validate(raw).model_dump(), True
        except ValueError:
            logger.warning("Ignoring invalid persisted shared team/person filter")
    return _read_legacy_team_person_filter()


@router.get("/shared")
def get_shared_settings(creds: Credentials = Depends(require_login_credentials)):
    del creds
    return {
        "default_spreadsheet_id": runtime_config.get("default_spreadsheet_id", ""),
    }


@router.get("/system")
def get_system_info(creds: Credentials = Depends(require_login_credentials)):
    del creds
    return {
        "host": settings.base_url,
        "public_base_url": settings.base_url,
        "bind_host": settings.BIND_HOST,
        "frontend_url": settings.frontend_url,
        "redirect_uri": settings.get_redirect_uri(),
        "google_client_configured": bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET),
    }


@router.put("/shared")
def update_shared_settings(
    payload: SharedResourceSettingsModel, creds: Credentials = Depends(require_login_credentials)
):
    runtime_config.update({"default_spreadsheet_id": payload.default_spreadsheet_id.strip()})
    logger.info("Shared resource settings updated: default_spreadsheet_id")
    return {"status": "success", "settings": get_shared_settings(creds)}


@router.get("/youtube")
def get_youtube_settings(creds: Credentials = Depends(require_login_credentials)):
    del creds
    return {
        "default_playlist_id": runtime_config.get("default_playlist_id", ""),
        "youtube_general_quota_limit": runtime_config.get("youtube_general_quota_limit", 10_000),
        "youtube_quota_safety_buffer_units": runtime_config.get("youtube_quota_safety_buffer_units", 1_000),
    }


@router.put("/youtube")
def update_youtube_settings(
    payload: YouTubeResourceSettingsModel, creds: Credentials = Depends(require_login_credentials)
):
    current_limit = int(runtime_config.get("youtube_general_quota_limit", 10_000))
    current_buffer = int(runtime_config.get("youtube_quota_safety_buffer_units", 1_000))
    limit = payload.youtube_general_quota_limit if payload.youtube_general_quota_limit is not None else current_limit
    buffer = (
        payload.youtube_quota_safety_buffer_units
        if payload.youtube_quota_safety_buffer_units is not None
        else current_buffer
    )
    if limit <= 0:
        raise HTTPException(status_code=422, detail="youtube_general_quota_limit 必須大於 0")
    if buffer < 0 or buffer >= limit:
        raise HTTPException(status_code=422, detail="youtube_quota_safety_buffer_units 必須大於等於 0 且小於 limit")
    runtime_config.update(
        {
            "default_playlist_id": payload.default_playlist_id.strip(),
            "youtube_general_quota_limit": limit,
            "youtube_quota_safety_buffer_units": buffer,
        }
    )
    logger.info("YouTube resource settings updated: playlist and quota policy")
    return {"status": "success", "settings": get_youtube_settings(creds)}


@router.get("/youtube-drafts")
def get_youtube_draft_settings(creds: Credentials = Depends(require_login_credentials)):
    del creds
    return {
        "video": _clean_draft_config(_read_draft_config("Video")),
        "shorts": _clean_draft_config(_read_draft_config("Shorts")),
    }


@router.put("/youtube-drafts")
def update_youtube_draft_settings(
    payload: YouTubeDraftConfigUpdateModel, creds: Credentials = Depends(require_login_credentials)
):
    del creds
    key = _draft_config_key(payload.video_type)
    value = payload.config.model_dump()
    runtime_config.set(key, value)
    logger.info("YouTube %s draft settings updated", payload.video_type)
    return {"status": "success", "video_type": payload.video_type, "config": value}


@router.get("/team-person-filter")
def get_team_person_filter(creds: Credentials = Depends(require_login_credentials)):
    del creds
    value, configured = _read_team_person_filter()
    return {"configured": configured, **value}


@router.put("/team-person-filter")
def update_team_person_filter(payload: TeamPersonFilterModel, creds: Credentials = Depends(require_login_credentials)):
    del creds
    value = payload.model_dump()
    runtime_config.set("shared_team_person_filter", value)
    logger.info("Shared team/person filter updated")
    return {"configured": True, **value}
