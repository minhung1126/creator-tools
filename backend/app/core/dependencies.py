"""
Shared FastAPI Dependencies

Centralizes common dependency injection functions used across API routes.
"""

import logging

from fastapi import Depends, HTTPException, Request
from google.oauth2.credentials import Credentials

from backend.app.core.account_state import get_account_active_slot
from backend.app.core.config import settings
from backend.app.core.credential_store import credential_store
from backend.app.core.session_store import session_store
from backend.app.core.youtube_context import YouTubeRequestContext
from backend.app.services.google_auth import get_login_credentials, get_youtube_credentials
from backend.app.services.youtube_quota_service import get_youtube_quota_tracker

logger = logging.getLogger(__name__)


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
        raise HTTPException(
            status_code=401,
            detail={
                "code": "login_required",
                "message": "登入資料缺少 Google OIDC subject，請重新登入。",
            },
        )
    creds = get_login_credentials(session_id)

    if not creds or not creds.valid:
        logger.warning("Unauthorized control-panel API access attempt")
        raise HTTPException(
            status_code=401,
            detail={
                "code": "login_required",
                "message": "控制台登入已失效，請重新登入 Google 帳號。",
            },
        )
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
        raise HTTPException(
            status_code=401,
            detail={
                "code": "login_required",
                "message": "登入資料缺少 Google OIDC subject，請重新登入。",
            },
        )
    return subject


def require_youtube_context(request: Request) -> YouTubeRequestContext:
    """Resolve the active slot once at request start."""
    session_id = request.cookies.get(settings.session_cookie_name)
    login_creds = get_login_credentials(session_id)
    if not login_creds or not login_creds.valid:
        logger.warning("Unauthorized YouTube API access attempt without page login")
        raise HTTPException(
            status_code=401,
            detail={
                "code": "login_required",
                "message": "控制台登入已失效，請重新登入 Google 帳號。",
            },
        )

    session_data = session_store.get(session_id) or {}
    owner_sub = str(((session_data.get("user") or {}).get("sub") or "")).strip() or None
    slot = get_account_active_slot(owner_sub)
    slot_config = settings.youtube_oauth_slot(slot)
    if not slot_config.configured:
        logger.warning("YouTube API access attempted with an unconfigured active slot: %s", slot)
        raise HTTPException(
            status_code=503,
            detail={
                "code": "youtube_slot_not_configured",
                "message": "目前作用中的 YouTube OAuth slot 尚未完成伺服器設定。",
                "slot": slot,
            },
        )

    creds = get_youtube_credentials(session_id, slot=slot)
    if not creds or not creds.valid:
        logger.warning("YouTube API access attempted without channel authorization")
        raise HTTPException(
            status_code=403,
            detail={
                "code": "youtube_not_connected",
                "message": "尚未連結 YouTube 頻道 Google 帳號，請至「YouTube 設定」完成授權。",
                "slot": slot,
            },
        )
    public = credential_store.get_youtube_public(owner_sub, slot=slot) if owner_sub else None
    other_slot = "secondary" if slot == "primary" else "primary"
    other_public = credential_store.get_youtube_public(owner_sub, slot=other_slot) if owner_sub else None
    channel_id = str((public or {}).get("channel_id") or "").strip()
    other_channel_id = str((other_public or {}).get("channel_id") or "").strip()
    if channel_id and other_channel_id and channel_id != other_channel_id:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "youtube_channel_mismatch",
                "message": "Primary 與 secondary 必須管理同一個 YouTube Channel，請重新授權其中一個 slot。",
                "slot": slot,
            },
        )
    return YouTubeRequestContext(
        slot=slot,
        credentials=creds,
        quota_limiter=get_youtube_quota_tracker(slot),
        channel_id=(public or {}).get("channel_id"),
        owner_sub=owner_sub,
    )


def require_youtube_credentials(request: Request) -> YouTubeRequestContext:
    """Compatibility alias for routes and integrations using the old name."""
    return require_youtube_context(request)
