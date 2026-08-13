"""
Shared FastAPI Dependencies

Centralizes common dependency injection functions used across API routes.
"""

import logging

from fastapi import Depends, Request
from google.oauth2.credentials import Credentials

from backend.app.core.account_state import get_account_setting
from backend.app.core.config import settings
from backend.app.core.error_contract import http_error
from backend.app.core.session_store import session_store
from backend.app.core.youtube_context import YouTubeRequestContext
from backend.app.core.youtube_routing import choose_youtube_slot, estimate_youtube_request_units
from backend.app.services.google_auth import get_login_credentials
from backend.app.services.youtube_quota_service import get_youtube_quota_tracker

logger = logging.getLogger(__name__)


def _get_preview_slot_hint(path: str, body: object) -> str | None:
    """Only pin a slot for a write request carrying a complete preview."""
    normalized_path = path.rstrip("/")
    if not isinstance(body, dict) or not (
        normalized_path.endswith("/batch-update") or normalized_path.endswith("/publish-and-cleanup")
    ):
        return None
    if not str(body.get("preview_token") or "").strip() or not isinstance(body.get("preview_snapshot"), dict):
        return None
    hint = body.get("youtube_slot")
    return hint if isinstance(hint, str) else None


def require_login_credentials(request: Request) -> Credentials:
    """
    Extract and validate the control-panel login/Sheets credentials from the
    session cookie. Raises 401 if the page login is not authenticated.
    """
    session_id = request.cookies.get(settings.session_cookie_name)
    session_data = session_store.get(session_id) if session_id else None
    user = session_data.get("user") if isinstance(session_data, dict) else None
    if not str((user or {}).get("sub") or "").strip():
        logger.warning("API access attempted with a session missing an OIDC subject")
        raise http_error(401, "login_required", "登入資料缺少 Google OIDC subject，請重新登入。")
    creds = get_login_credentials(session_id)

    if not creds or not creds.valid:
        logger.warning("Unauthorized control-panel API access attempt")
        raise http_error(401, "login_required", "控制台登入已失效，請重新登入 Google 帳號。")
    return creds


def require_account_subject(
    request: Request,
    creds: Credentials = Depends(require_login_credentials),
) -> str:
    """Resolve the authenticated Google account used to scope saved state."""
    del creds
    session_id = request.cookies.get(settings.session_cookie_name)
    session_data = session_store.get(session_id) if session_id else None
    subject = str(((session_data or {}).get("user") or {}).get("sub") or "").strip()
    if not subject:
        raise http_error(401, "login_required", "登入資料缺少 Google OIDC subject，請重新登入。")
    return subject


async def require_youtube_context(request: Request) -> YouTubeRequestContext:
    """Resolve one quota-aware YouTube slot once at request start."""
    session_id = request.cookies.get(settings.session_cookie_name)
    login_creds = get_login_credentials(session_id)
    if not login_creds or not login_creds.valid:
        logger.warning("Unauthorized YouTube API access attempt without page login")
        raise http_error(401, "login_required", "控制台登入已失效，請重新登入 Google 帳號。")

    session_data = session_store.get(session_id) or {}
    owner_sub = str(((session_data.get("user") or {}).get("sub") or "")).strip()
    if not owner_sub:
        raise http_error(401, "login_required", "登入資料缺少 Google OIDC subject，請重新登入。")
    try:
        body = await request.json()
    except Exception:
        body = {}
    default_playlist_id = get_account_setting(owner_sub, "default_playlist_id", "")
    slot_hint = _get_preview_slot_hint(request.url.path, body)
    estimated_units = estimate_youtube_request_units(
        request.url.path,
        body if isinstance(body, dict) else {},
        default_playlist_id=str(default_playlist_id or ""),
    )
    decision = choose_youtube_slot(
        session_id,
        owner_sub,
        estimated_units=estimated_units,
        slot_hint=slot_hint if isinstance(slot_hint, str) else None,
    )
    logger.info(
        "YouTube request routed to slot=%s mode=%s reason=%s estimated_units=%s",
        decision.slot,
        decision.routing_mode,
        decision.reason,
        decision.estimated_units,
    )
    return YouTubeRequestContext(
        slot=decision.slot,
        credentials=decision.credentials,
        quota_limiter=get_youtube_quota_tracker(decision.slot),
        channel_id=decision.channel_id,
        owner_sub=owner_sub,
        routing_mode=decision.routing_mode,
        selection_reason=decision.reason,
        estimated_units=decision.estimated_units,
        preferred_slot=decision.preferred_slot,
    )
