import logging
import secrets
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Request, Response, HTTPException, Query, Depends
from fastapi.responses import RedirectResponse
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

OAUTH_FLOW_COOKIE = "creator_tools_oauth_flow"
OAUTH_FLOW_MAX_AGE = 10 * 60


def redirect_with_auth_error(message: str) -> RedirectResponse:
    """Redirect to the frontend with a safely encoded OAuth error."""
    response = RedirectResponse(
        url=f"{settings.frontend_url}/#auth_error={quote(message, safe='')}"
    )
    response.delete_cookie(OAUTH_FLOW_COOKIE)
    return response


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
def get_google_auth_url(response: Response):
    """Generate the Google OAuth URL and store its short-lived PKCE state."""
    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
        raise HTTPException(
            status_code=400,
            detail="Google Client ID and Client Secret are not configured. "
                   "Please set them in .env file."
        )
    try:
        url, state, code_verifier = get_auth_url()
        flow_cookie = encrypt_session_data({
            "state": state,
            "code_verifier": code_verifier,
        })
        response.set_cookie(
            key=OAUTH_FLOW_COOKIE,
            value=flow_cookie,
            httponly=True,
            secure=settings.is_production,
            samesite="lax",
            max_age=OAUTH_FLOW_MAX_AGE,
        )
        return {"auth_url": url}
    except Exception as e:
        logger.error("Failed to generate auth URL: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/callback")
def google_oauth_callback(
    request: Request,
    code: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    error: Optional[str] = Query(None),
    error_description: Optional[str] = Query(None),
):
    """Handle the OAuth2 callback from Google and verify PKCE state."""
    if error:
        return redirect_with_auth_error(error_description or error)

    if not code or not state:
        return redirect_with_auth_error("Google OAuth callback is missing code or state.")

    flow_cookie = request.cookies.get(OAUTH_FLOW_COOKIE)
    flow_state = decrypt_session_data(flow_cookie, max_age=OAUTH_FLOW_MAX_AGE) if flow_cookie else None
    if not flow_state:
        return redirect_with_auth_error("Google OAuth session expired. Please try signing in again.")

    expected_state = flow_state.get("state")
    code_verifier = flow_state.get("code_verifier")
    if not expected_state or not code_verifier:
        return redirect_with_auth_error("Google OAuth session data is incomplete.")

    if not secrets.compare_digest(state, expected_state):
        return redirect_with_auth_error("Google OAuth state verification failed.")

    try:
        token_dict = exchange_code_for_tokens(
            code=code,
            code_verifier=code_verifier,
        )
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
        response.delete_cookie(OAUTH_FLOW_COOKIE)
        return response
    except Exception as e:
        logger.error("OAuth callback error: %s", e, exc_info=True)
        return redirect_with_auth_error(str(e))


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
    res.delete_cookie(OAUTH_FLOW_COOKIE)
    return res
