import logging
import secrets
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Request, Response, HTTPException, Query, Depends
from fastapi.responses import RedirectResponse
from google.oauth2.credentials import Credentials

from backend.app.core.config import settings
from backend.app.core.security import (
    GOOGLE_OAUTH_STATE_SALT,
    sign_timed_data,
    verify_timed_data,
)
from backend.app.core.dependencies import require_credentials
from backend.app.core.session_store import SESSION_MAX_AGE, session_store
from backend.app.services.google_auth import (
    get_auth_url,
    exchange_code_for_tokens,
    get_current_credentials,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Google OAuth"])

OAUTH_FLOW_COOKIE = "creator_tools_oauth_flow"
OAUTH_FLOW_MAX_AGE = 10 * 60
SESSION_COOKIE = "creator_tools_session"


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
    if settings.is_production and not settings.allowed_google_emails:
        raise HTTPException(status_code=503, detail="正式環境必須設定 ALLOWED_GOOGLE_EMAILS")
    try:
        url, state, code_verifier = get_auth_url()
        flow_cookie = sign_timed_data({
            "state": state,
            "code_verifier": code_verifier,
        }, salt=GOOGLE_OAUTH_STATE_SALT)
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
        logger.info("Google OAuth provider returned an error: %s", error)
        return redirect_with_auth_error("Google OAuth 授權遭拒，請重新嘗試。")

    if not code or not state:
        return redirect_with_auth_error("Google OAuth callback is missing code or state.")

    flow_cookie = request.cookies.get(OAUTH_FLOW_COOKIE)
    flow_state = verify_timed_data(
        flow_cookie, salt=GOOGLE_OAUTH_STATE_SALT, max_age=OAUTH_FLOW_MAX_AGE
    ) if flow_cookie else None
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
        user_info = token_dict.get("user") or {}
        email = str(user_info.get("email") or "").strip()
        if not settings.is_google_email_allowed(email):
            raise RuntimeError("此 Google 帳號不在 ALLOWED_GOOGLE_EMAILS")
        session_id = session_store.create(token_dict, max_age=SESSION_MAX_AGE)

        response = RedirectResponse(url=f"{settings.frontend_url}/#auth_success=1")
        response.set_cookie(
            key=SESSION_COOKIE,
            value=session_id,
            httponly=True,
            secure=settings.is_production,
            samesite="lax",
            max_age=SESSION_MAX_AGE
        )
        response.delete_cookie(OAUTH_FLOW_COOKIE)
        return response
    except Exception as e:
        logger.error("OAuth callback error: %s", type(e).__name__, exc_info=True)
        return redirect_with_auth_error("Google OAuth 登入失敗，請重新嘗試。")


@router.get("/user")
def get_user_status(request: Request):
    """Check current authentication status."""
    session_id = request.cookies.get(SESSION_COOKIE)
    stored_tokens = session_store.get(session_id) if session_id else None
    creds = get_current_credentials(session_id)
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
def logout(request: Request):
    """Clear authentication session."""
    res = Response(content='{"status":"logged_out"}', media_type="application/json")
    session_store.delete(request.cookies.get(SESSION_COOKIE, ""))
    res.delete_cookie(SESSION_COOKIE)
    res.delete_cookie(OAUTH_FLOW_COOKIE)
    return res
