import logging
from typing import Annotated, Any, Dict, List, Literal

from fastapi import APIRouter, Depends, HTTPException
from google.oauth2.credentials import Credentials
from pydantic import BaseModel, Field, model_validator

from backend.app.core.account_state import (
    get_account_active_slot,
    get_account_setting,
    get_account_work_state,
    set_account_setting,
    update_account_work_state,
)
from backend.app.core.config import settings
from backend.app.core.dependencies import require_account_subject, require_login_credentials
from backend.app.core.runtime_config import runtime_config

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/settings", tags=["System & Resource Settings"])


class SharedResourceSettingsModel(BaseModel):
    """Settings shared by Sheet and platform workflows unless overridden."""

    default_spreadsheet_id: str = Field(default="", max_length=512)


class YouTubeResourceSettingsModel(BaseModel):
    """YouTube-only resource settings."""

    default_playlist_id: str = Field(default="", max_length=256)
    slot: Literal["primary", "secondary"]
    quota_limit: int
    safety_buffer_units: int

    @model_validator(mode="after")
    def validate_quota_policy(self):
        if self.quota_limit <= 0:
            raise ValueError("quota_limit 必須大於 0")
        if self.safety_buffer_units < 0:
            raise ValueError("safety_buffer_units 必須大於等於 0")
        if self.safety_buffer_units >= self.quota_limit:
            raise ValueError("safety_buffer_units 必須小於 quota_limit")
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


class WorkStateUpdateModel(BaseModel):
    key: Literal[
        "navigation",
        "sheet_copy",
        "youtube_publish_cleaner",
        "youtube_draft_video",
        "youtube_draft_shorts",
    ]
    value: Dict[str, Any] = Field(default_factory=dict)


def _draft_config_key(video_type: str) -> str:
    return f"youtube_draft_{video_type.lower()}_config"


def _read_draft_config(video_type: str, owner_sub: str) -> Dict:
    raw = get_account_setting(owner_sub, _draft_config_key(video_type), "")
    if not isinstance(raw, dict) or not raw:
        return {}
    try:
        return YouTubeDraftConfigModel.model_validate(raw).model_dump()
    except ValueError:
        logger.warning("Ignoring invalid persisted %s draft config", video_type)
        return {}


def _read_team_person_filter(owner_sub: str) -> tuple[Dict, bool]:
    raw = get_account_setting(owner_sub, "shared_team_person_filter", None)
    if isinstance(raw, dict):
        try:
            return TeamPersonFilterModel.model_validate(raw).model_dump(), True
        except ValueError:
            logger.warning("Ignoring invalid persisted shared team/person filter")
    return TeamPersonFilterModel().model_dump(), False


@router.get("/shared")
def get_shared_settings(
    creds: Credentials = Depends(require_login_credentials),
    owner_sub: str = Depends(require_account_subject),
):
    del creds
    return {
        "default_spreadsheet_id": get_account_setting(owner_sub, "default_spreadsheet_id", ""),
    }


@router.get("/system")
def get_system_info(creds: Credentials = Depends(require_login_credentials)):
    del creds
    return {
        "public_base_url": settings.base_url,
        "bind_host": settings.BIND_HOST,
        "frontend_url": settings.frontend_url,
        "redirect_uri": settings.get_redirect_uri(),
        "google_client_configured": bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET),
    }


@router.put("/shared")
def update_shared_settings(
    payload: SharedResourceSettingsModel,
    creds: Credentials = Depends(require_login_credentials),
    owner_sub: str = Depends(require_account_subject),
):
    value = payload.default_spreadsheet_id.strip()
    set_account_setting(owner_sub, "default_spreadsheet_id", value)
    logger.info("Account-scoped resource settings updated: default_spreadsheet_id")
    return {"status": "success", "settings": get_shared_settings(creds, owner_sub)}


@router.get("/youtube")
def get_youtube_settings(
    creds: Credentials = Depends(require_login_credentials),
    owner_sub: str = Depends(require_account_subject),
):
    del creds
    primary_limit, primary_buffer = runtime_config.get_youtube_quota_settings("primary")
    return {
        "default_playlist_id": get_account_setting(owner_sub, "default_playlist_id", ""),
        "slot": "primary",
        "quota_limit": primary_limit,
        "safety_buffer_units": primary_buffer,
    }


@router.get("/youtube-slots")
def get_youtube_slot_settings(
    creds: Credentials = Depends(require_login_credentials),
    owner_sub: str = Depends(require_account_subject),
):
    """Return non-secret configuration defaults for both YouTube slots."""
    del creds
    slots = {}
    for slot, slot_config in settings.youtube_oauth_slots.items():
        limit, buffer = runtime_config.get_youtube_quota_settings(slot)
        slots[slot] = {
            "slot": slot,
            "label": slot_config.label,
            "configured": slot_config.configured,
            "enabled": slot_config.enabled,
            "client_fingerprint": slot_config.client_fingerprint,
            "quota_limit": limit,
            "safety_buffer_units": buffer,
        }
    return {"active_slot": get_account_active_slot(owner_sub), "slots": slots}


@router.put("/youtube")
def update_youtube_settings(
    payload: YouTubeResourceSettingsModel,
    creds: Credentials = Depends(require_login_credentials),
    owner_sub: str = Depends(require_account_subject),
):
    slot = payload.slot
    limit = payload.quota_limit
    buffer = payload.safety_buffer_units
    if limit <= 0:
        raise HTTPException(status_code=422, detail="quota_limit 必須大於 0")
    if buffer < 0 or buffer >= limit:
        raise HTTPException(status_code=422, detail="safety_buffer_units 必須大於等於 0 且小於 limit")
    set_account_setting(owner_sub, "default_playlist_id", payload.default_playlist_id.strip())
    runtime_config.update(
        {
            f"youtube_{slot}_general_quota_limit": limit,
            f"youtube_{slot}_quota_safety_buffer_units": buffer,
        }
    )
    logger.info("YouTube resource settings updated: account playlist, slot=%s quota policy", slot)
    return {
        "status": "success",
        "settings": {
            "default_playlist_id": payload.default_playlist_id.strip(),
            "slot": slot,
            "quota_limit": limit,
            "safety_buffer_units": buffer,
        },
    }


@router.get("/youtube-drafts")
def get_youtube_draft_settings(
    creds: Credentials = Depends(require_login_credentials),
    owner_sub: str = Depends(require_account_subject),
):
    del creds
    return {
        "video": _read_draft_config("Video", owner_sub),
        "shorts": _read_draft_config("Shorts", owner_sub),
    }


@router.put("/youtube-drafts")
def update_youtube_draft_settings(
    payload: YouTubeDraftConfigUpdateModel,
    creds: Credentials = Depends(require_login_credentials),
    owner_sub: str = Depends(require_account_subject),
):
    del creds
    key = _draft_config_key(payload.video_type)
    value = payload.config.model_dump()
    set_account_setting(owner_sub, key, value)
    logger.info("Account-scoped YouTube %s draft settings updated", payload.video_type)
    return {"status": "success", "video_type": payload.video_type, "config": value}


@router.get("/team-person-filter")
def get_team_person_filter(
    creds: Credentials = Depends(require_login_credentials),
    owner_sub: str = Depends(require_account_subject),
):
    del creds
    value, configured = _read_team_person_filter(owner_sub)
    return {"configured": configured, **value}


@router.put("/team-person-filter")
def update_team_person_filter(
    payload: TeamPersonFilterModel,
    creds: Credentials = Depends(require_login_credentials),
    owner_sub: str = Depends(require_account_subject),
):
    del creds
    value = payload.model_dump()
    set_account_setting(owner_sub, "shared_team_person_filter", value)
    logger.info("Account-scoped team/person filter updated")
    return {"configured": True, **value}


@router.get("/work-state")
def get_work_state(
    creds: Credentials = Depends(require_login_credentials),
    owner_sub: str = Depends(require_account_subject),
):
    del creds
    return {"version": 1, "state": get_account_work_state(owner_sub)}


@router.put("/work-state")
def update_work_state(
    payload: WorkStateUpdateModel,
    creds: Credentials = Depends(require_login_credentials),
    owner_sub: str = Depends(require_account_subject),
):
    del creds
    try:
        state = update_account_work_state(owner_sub, payload.key, payload.value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"version": 1, "state": state}
