import logging

from fastapi import APIRouter, Request, Response, HTTPException, Query, Depends
from fastapi.responses import RedirectResponse
from typing import Optional
from google.oauth2.credentials import Credentials

from backend.app.core.config import settings
from backend.app.core.security import encrypt_session_data, decrypt_session_data
from backend.app.core.dependencies import require_credentials
from backend.app.services.google_auth import (
    get_auth_url,
    exchange_code_for_tokens,
    get_current_credentials,
    clear_current_credentials
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Google OAuth"])


@router.get("/config")
def get_auth_config():
    """Return OAuth configuration status (without exposing any credentials)."""
    return {
        "host": settings.base_url,
        "frontend_url": settings.frontend_url,
        "redirect_uri": settings.get_redirect_uri(),
        "has_client_id": bool(settings.GOOGLE_CLIENT_ID),
        "has_client_secret": bool(settings.GOOGLE_CLIENT_SECRET),
        "scopes": [
            "Google Sheets API",
            "YouTube Data API v3",
            "Google Drive API"
        ]
    }


@router.get("/url")
def get_google_auth_url():
    """Generate the Google OAuth consent URL using .env credentials."""
    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
        raise HTTPException(
            status_code=400,
            detail="Google Client ID and Client Secret are not configured. "
                   "Please set them in .env file."
        )
    try:
        url = get_auth_url()
        return {"auth_url": url}
    except Exception as e:
        logger.error("Failed to generate auth URL: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/callback")
def google_oauth_callback(code: str = Query(...), error: Optional[str] = None):
    """Handle the OAuth2 callback from Google."""
    if error:
        return RedirectResponse(url=f"{settings.frontend_url}/#auth_error={error}")
    try:
        token_dict = exchange_code_for_tokens(code=code)
        encrypted_cookie = encrypt_session_data(token_dict)

        response = RedirectResponse(url=f"{settings.frontend_url}/#auth_success=1")
        response.set_cookie(
            key="creator_tools_session",
            value=encrypted_cookie,
            httponly=True,
            secure=settings.is_production,
            samesite="lax",
            max_age=60 * 60 * 24 * 7
        )
        return response
    except Exception as e:
        logger.error("OAuth callback error: %s", e, exc_info=True)
        return RedirectResponse(url=f"{settings.frontend_url}/#auth_error={str(e)}")


@router.get("/user")
def get_user_status(request: Request):
    """Check current authentication status."""
    cookie = request.cookies.get("creator_tools_session")
    stored_tokens = decrypt_session_data(cookie) if cookie else None

    creds = get_current_credentials(stored_tokens)
    if not creds or not creds.valid:
        return {
            "authenticated": False,
            "user": None
        }

    user_info = stored_tokens.get("user", {}) if stored_tokens else {"email": "Authenticated User"}
    return {
        "authenticated": True,
        "user": user_info,
        "token_expired": creds.expired
    }


@router.post("/logout")
def logout(response: Response):
    """Clear authentication session."""
    clear_current_credentials()
    res = Response(content='{"status":"logged_out"}', media_type="application/json")
    res.delete_cookie("creator_tools_session")
    return res
