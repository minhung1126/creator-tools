"""
Shared FastAPI Dependencies

Centralizes common dependency injection functions used across API routes.
"""

import logging

from fastapi import HTTPException, Request
from google.oauth2.credentials import Credentials

from backend.app.core.config import settings
from backend.app.core.session_store import session_store
from backend.app.services.google_auth import get_login_credentials, get_youtube_credentials

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


def require_youtube_credentials(request: Request) -> Credentials:
    """Require both a valid page login and a separate YouTube authorization."""
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

    creds = get_youtube_credentials(session_id)
    if not creds or not creds.valid:
        logger.warning("YouTube API access attempted without channel authorization")
        raise HTTPException(
            status_code=403,
            detail={
                "code": "youtube_not_connected",
                "message": "尚未連結 YouTube 頻道 Google 帳號，請至「YouTube 設定」完成授權。",
            },
        )
    return creds


# Keep the original dependency name for routes and integrations that still
# import it; it now explicitly means the control-panel login connection.
require_credentials = require_login_credentials
