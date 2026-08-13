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
    slot: Literal["primary", "secondary"] | None = None
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


def _resolve_owner(owner_sub: Any) -> str | None:
    if not isinstance(owner_sub, str):
        return None
    value = owner_sub.strip()
    return value or None


def _read_draft_config(video_type: str, owner_sub: str | None = None) -> Dict:
    raw = get_account_setting(owner_sub, _draft_config_key(video_type), "")
    if not isinstance(raw, dict) or not raw:
        return {}
    try:
        return YouTubeDraftConfigModel.model_validate(raw).model_dump()
    except ValueError:
        logger.warning("Ignoring invalid persisted %s draft config", video_type)
        return {}


def _read_team_person_filter(owner_sub: str | None = None) -> tuple[Dict, bool]:
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
    owner = _resolve_owner(owner_sub)
    return {
        "default_spreadsheet_id": get_account_setting(owner, "default_spreadsheet_id", ""),
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
    owner = _resolve_owner(owner_sub)
    value = payload.default_spreadsheet_id.strip()
    if owner:
        set_account_setting(owner, "default_spreadsheet_id", value)
    else:
        # Keep direct/unit-test callers and legacy integrations functional.
        runtime_config.update({"default_spreadsheet_id": value})
    logger.info("Account-scoped resource settings updated: default_spreadsheet_id")
    return {"status": "success", "settings": get_shared_settings(creds, owner)}


@router.get("/youtube")
def get_youtube_settings(
    creds: Credentials = Depends(require_login_credentials),
    owner_sub: str = Depends(require_account_subject),
):
    del creds
    owner = _resolve_owner(owner_sub)
    primary_limit, primary_buffer = runtime_config.get_youtube_quota_settings("primary")
    return {
        "default_playlist_id": get_account_setting(owner, "default_playlist_id", ""),
        "youtube_general_quota_limit": primary_limit,
        "youtube_quota_safety_buffer_units": primary_buffer,
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
            "uses_legacy_google_credentials": slot_config.uses_legacy_google_credentials,
            "quota_limit": limit,
            "safety_buffer_units": buffer,
        }
    return {"active_slot": get_account_active_slot(_resolve_owner(owner_sub)), "slots": slots}


@router.put("/youtube")
def update_youtube_settings(
    payload: YouTubeResourceSettingsModel,
    creds: Credentials = Depends(require_login_credentials),
    owner_sub: str = Depends(require_account_subject),
):
    owner = _resolve_owner(owner_sub)
    slot = payload.slot or "primary"
    current_limit, current_buffer = runtime_config.get_youtube_quota_settings(slot)
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
    updates = {"default_playlist_id": payload.default_playlist_id.strip()}
    if payload.slot is None:
        # Preserve the old API's primary keys for clients that have not yet
        # learned the slot-specific settings contract.
        updates.update(
            {
                "youtube_general_quota_limit": limit,
                "youtube_quota_safety_buffer_units": buffer,
            }
        )
    else:
        updates.update(
            {
                f"youtube_{slot}_general_quota_limit": limit,
                f"youtube_{slot}_quota_safety_buffer_units": buffer,
            }
        )
    if owner:
        set_account_setting(owner, "default_playlist_id", updates["default_playlist_id"])
        quota_updates = {key: value for key, value in updates.items() if key != "default_playlist_id"}
        if quota_updates:
            # Quota is tied to the deployed OAuth project and shared ledger;
            # keep its policy server-global while scoping the working playlist.
            runtime_config.update(quota_updates)
    else:
        runtime_config.update(updates)
    logger.info("YouTube resource settings updated: account playlist, slot=%s quota policy", slot)
    return {"status": "success", "settings": get_youtube_settings(creds, owner)}


@router.get("/youtube-drafts")
def get_youtube_draft_settings(
    creds: Credentials = Depends(require_login_credentials),
    owner_sub: str = Depends(require_account_subject),
):
    del creds
    owner = _resolve_owner(owner_sub)
    return {
        "video": _read_draft_config("Video", owner),
        "shorts": _read_draft_config("Shorts", owner),
    }


@router.put("/youtube-drafts")
def update_youtube_draft_settings(
    payload: YouTubeDraftConfigUpdateModel,
    creds: Credentials = Depends(require_login_credentials),
    owner_sub: str = Depends(require_account_subject),
):
    del creds
    owner = _resolve_owner(owner_sub)
    key = _draft_config_key(payload.video_type)
    value = payload.config.model_dump()
    if owner:
        set_account_setting(owner, key, value)
    else:
        runtime_config.set(key, value)
    logger.info("Account-scoped YouTube %s draft settings updated", payload.video_type)
    return {"status": "success", "video_type": payload.video_type, "config": value}


@router.get("/team-person-filter")
def get_team_person_filter(
    creds: Credentials = Depends(require_login_credentials),
    owner_sub: str = Depends(require_account_subject),
):
    del creds
    value, configured = _read_team_person_filter(_resolve_owner(owner_sub))
    return {"configured": configured, **value}


@router.put("/team-person-filter")
def update_team_person_filter(
    payload: TeamPersonFilterModel,
    creds: Credentials = Depends(require_login_credentials),
    owner_sub: str = Depends(require_account_subject),
):
    del creds
    value = payload.model_dump()
    owner = _resolve_owner(owner_sub)
    if owner:
        set_account_setting(owner, "shared_team_person_filter", value)
    else:
        runtime_config.set("shared_team_person_filter", value)
    logger.info("Account-scoped team/person filter updated")
    return {"configured": True, **value}


@router.get("/work-state")
def get_work_state(
    creds: Credentials = Depends(require_login_credentials),
    owner_sub: str = Depends(require_account_subject),
):
    del creds
    return {"version": 1, "state": get_account_work_state(_resolve_owner(owner_sub))}


@router.put("/work-state")
def update_work_state(
    payload: WorkStateUpdateModel,
    creds: Credentials = Depends(require_login_credentials),
    owner_sub: str = Depends(require_account_subject),
):
    del creds
    owner = _resolve_owner(owner_sub)
    try:
        state = update_account_work_state(owner, payload.key, payload.value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"version": 1, "state": state}
