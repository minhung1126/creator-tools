import logging
import secrets
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse

from backend.app.core.config import settings
from backend.app.core.credential_store import credential_store
from backend.app.core.security import (
    GOOGLE_OAUTH_STATE_SALT,
    sign_timed_data,
    verify_timed_data,
)
from backend.app.core.session_store import SESSION_MAX_AGE, session_store
from backend.app.services.google_auth import (
    LOGIN_SCOPES,
    YOUTUBE_SCOPES,
    exchange_code_for_tokens,
    get_login_credentials,
    get_youtube_credentials,
)
from backend.app.services.google_auth import (
    get_auth_url as build_google_auth_url,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Google OAuth"])

OAUTH_FLOW_COOKIE = settings.oauth_flow_cookie_name
OAUTH_FLOW_MAX_AGE = 10 * 60
SESSION_COOKIE = settings.session_cookie_name
LOGIN_FLOW = "login"
YOUTUBE_FLOW = "youtube"


def redirect_with_auth_error(message: str, flow_type: str = LOGIN_FLOW) -> RedirectResponse:
    """Redirect to the frontend with a safely encoded OAuth error."""
    hash_key = "youtube_auth_error" if flow_type == YOUTUBE_FLOW else "auth_error"
    response = RedirectResponse(url=f"{settings.frontend_url}/#{hash_key}={quote(message, safe='')}")
    _delete_flow_cookie(response)
    return response


def _delete_flow_cookie(response: Response) -> None:
    response.delete_cookie(
        OAUTH_FLOW_COOKIE,
        path="/",
        secure=settings.cookie_secure,
        httponly=True,
        samesite="lax",
    )


def _check_oauth_configuration() -> None:
    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
        raise HTTPException(
            status_code=400,
            detail="Google Client ID and Client Secret are not configured. Please set them in .env file.",
        )


def _set_flow_cookie(
    response: Response,
    *,
    flow_type: str,
    state: str,
    code_verifier: str,
    session_id: Optional[str] = None,
) -> None:
    flow_payload = {
        "flow_type": flow_type,
        "state": state,
        "code_verifier": code_verifier,
    }
    if session_id:
        flow_payload["session_id"] = session_id
    response.set_cookie(
        key=OAUTH_FLOW_COOKIE,
        value=sign_timed_data(flow_payload, salt=GOOGLE_OAUTH_STATE_SALT),
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=OAUTH_FLOW_MAX_AGE,
        path="/",
    )


def _get_authenticated_session_id(request: Request) -> str:
    session_id = request.cookies.get(SESSION_COOKIE)
    session_data = session_store.get(session_id) if session_id else None
    user = session_data.get("user") if isinstance(session_data, dict) else None
    if not str((user or {}).get("sub") or "").strip():
        raise HTTPException(
            status_code=401,
            detail={
                "code": "login_required",
                "message": "登入資料缺少 Google OIDC subject，請重新登入。",
            },
        )
    creds = get_login_credentials(session_id)
    if not session_id or not creds or not creds.valid:
        raise HTTPException(
            status_code=401,
            detail={
                "code": "login_required",
                "message": "請先登入控制台，再連結 YouTube 頻道 Google 帳號。",
            },
        )
    return session_id


@router.get("/config")
def get_auth_config():
    """Return OAuth configuration status without exposing credentials."""
    return {
        "host": settings.base_url,
        "frontend_url": settings.frontend_url,
        "redirect_uri": settings.get_redirect_uri(),
        "has_client_id": bool(settings.GOOGLE_CLIENT_ID),
        "has_client_secret": bool(settings.GOOGLE_CLIENT_SECRET),
        "login_scopes": list(LOGIN_SCOPES),
        "youtube_scopes": list(YOUTUBE_SCOPES),
        # ``scopes`` remains as a compatibility field for older clients.
        "scopes": list(LOGIN_SCOPES),
    }


@router.get("/url")
def get_google_auth_url(response: Response):
    """Generate the control-panel login/Sheets OAuth URL."""
    _check_oauth_configuration()
    if settings.allowlist_required and not settings.allowed_google_emails:
        raise HTTPException(status_code=503, detail="HTTPS/正式環境必須設定 ALLOWED_GOOGLE_EMAILS")
    try:
        url, state, code_verifier = build_google_auth_url(LOGIN_FLOW)
        _set_flow_cookie(
            response,
            flow_type=LOGIN_FLOW,
            state=state,
            code_verifier=code_verifier,
        )
        return {"auth_url": url}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to generate login auth URL: %s", type(exc).__name__)
        raise HTTPException(status_code=500, detail="無法建立 Google 登入授權網址，請稍後再試。") from exc


@router.get("/youtube/url")
def get_youtube_auth_url(request: Request, response: Response):
    """Generate a separate OAuth URL for the Google account managing YouTube."""
    _check_oauth_configuration()
    session_id = _get_authenticated_session_id(request)
    try:
        url, state, code_verifier = build_google_auth_url(YOUTUBE_FLOW)
        _set_flow_cookie(
            response,
            flow_type=YOUTUBE_FLOW,
            state=state,
            code_verifier=code_verifier,
            session_id=session_id,
        )
        return {"auth_url": url}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to generate YouTube auth URL: %s", type(exc).__name__)
        raise HTTPException(status_code=500, detail="無法建立 YouTube 頻道授權網址，請稍後再試。") from exc


@router.get("/callback")
def google_oauth_callback(
    request: Request,
    code: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    error: Optional[str] = Query(None),
    error_description: Optional[str] = Query(None),
):
    """Handle either the login or the separately initiated YouTube callback."""
    flow_cookie = request.cookies.get(OAUTH_FLOW_COOKIE)
    flow_state = (
        verify_timed_data(flow_cookie, salt=GOOGLE_OAUTH_STATE_SALT, max_age=OAUTH_FLOW_MAX_AGE)
        if flow_cookie
        else None
    )
    flow_type = (flow_state or {}).get("flow_type", LOGIN_FLOW)
    if flow_type not in {LOGIN_FLOW, YOUTUBE_FLOW}:
        flow_type = LOGIN_FLOW

    if error:
        logger.info("Google OAuth provider returned an error: %s", error)
        message = (
            "YouTube 頻道 Google 授權遭拒，請重新嘗試。"
            if flow_type == YOUTUBE_FLOW
            else "Google 登入授權遭拒，請重新嘗試。"
        )
        if error_description:
            logger.debug("Google OAuth error description: %s", error_description)
        return redirect_with_auth_error(message, flow_type)

    if not code or not state:
        return redirect_with_auth_error("Google OAuth callback is missing code or state.", flow_type)

    if not flow_state:
        message = (
            "YouTube Google OAuth session expired. Please try again."
            if flow_type == YOUTUBE_FLOW
            else "Google OAuth session expired. Please try signing in again."
        )
        return redirect_with_auth_error(message, flow_type)

    expected_state = flow_state.get("state")
    code_verifier = flow_state.get("code_verifier")
    if not expected_state or not code_verifier:
        return redirect_with_auth_error("Google OAuth session data is incomplete.", flow_type)

    if not secrets.compare_digest(state, expected_state):
        return redirect_with_auth_error("Google OAuth state verification failed.", flow_type)

    try:
        token_dict = exchange_code_for_tokens(
            code=code,
            code_verifier=code_verifier,
            purpose=flow_type,
        )
        user_info = token_dict.get("user") or {}

        if flow_type == YOUTUBE_FLOW:
            session_id = request.cookies.get(SESSION_COOKIE)
            expected_session_id = flow_state.get("session_id")
            session_data = session_store.get(session_id) if session_id else None
            owner_sub = str(((session_data or {}).get("user") or {}).get("sub") or "").strip()
            login_credentials = get_login_credentials(session_id)
            if (
                not session_id
                or not expected_session_id
                or not secrets.compare_digest(session_id, str(expected_session_id))
                or not owner_sub
                or not login_credentials
                or not login_credentials.valid
            ):
                return redirect_with_auth_error("控制台登入已失效，請重新登入後再連結 YouTube。", YOUTUBE_FLOW)
            credential_store.save_youtube_connection(token_dict, owner_sub=owner_sub)
            response = RedirectResponse(url=f"{settings.frontend_url}/#youtube_auth_success=1")
            _delete_flow_cookie(response)
            return response

        email = str(user_info.get("email") or "").strip()
        if not settings.is_google_email_allowed(email):
            raise RuntimeError("此 Google 帳號不在 ALLOWED_GOOGLE_EMAILS")
        subject = str(user_info.get("sub") or user_info.get("id") or "").strip()
        if not subject:
            raise RuntimeError("Google OAuth profile did not contain an OIDC subject")
        # Keep login/Sheets OAuth secrets in the encrypted persistent store. The
        # browser session only carries the account identity and a random id.
        credential_store.save_google_connection(token_dict, owner_sub=subject)
        session_id = session_store.create(
            {
                "credential_provider": "google_login",
                "user": {**user_info, "sub": subject},
            },
            max_age=SESSION_MAX_AGE,
        )

        response = RedirectResponse(url=f"{settings.frontend_url}/#auth_success=1")
        response.set_cookie(
            key=SESSION_COOKIE,
            value=session_id,
            httponly=True,
            secure=settings.cookie_secure,
            samesite="lax",
            max_age=SESSION_MAX_AGE,
            path="/",
        )
        _delete_flow_cookie(response)
        return response
    except Exception as exc:
        logger.error("OAuth callback error (%s): %s", flow_type, type(exc).__name__)
        message = (
            "YouTube 頻道 Google 授權失敗，請重新嘗試。"
            if flow_type == YOUTUBE_FLOW
            else "Google OAuth 登入失敗，請重新嘗試。"
        )
        return redirect_with_auth_error(message, flow_type)


@router.get("/user")
def get_user_status(request: Request):
    """Check control-panel login and independent YouTube authorization status."""
    session_id = request.cookies.get(SESSION_COOKIE)
    session_data = session_store.get(session_id) or {}
    session_sub = str(((session_data.get("user") or {}).get("sub") or "")).strip() or None
    creds = get_login_credentials(session_id) if session_sub else None
    if not session_sub or not creds or not creds.valid:
        return {
            "authenticated": False,
            "user": None,
            "youtube_authenticated": False,
            "youtube": {"authenticated": False, "user": None},
        }

    user_info = session_data.get("user") or {"email": "Authenticated User"}
    token_status = credential_store.get_google_public(session_sub) or {}

    youtube_public = credential_store.get_youtube_public(session_sub) or {}
    youtube_creds = get_youtube_credentials(session_id)
    youtube_authenticated = bool(youtube_creds and youtube_creds.valid)
    youtube_connection = {
        "authenticated": youtube_authenticated,
        "user": youtube_public.get("user"),
        "token_expired": bool(youtube_creds and youtube_creds.expired),
        "token_expires_at": youtube_public.get("token_expires_at"),
        "token_status": youtube_public.get("status", "not_connected"),
        "last_refreshed_at": youtube_public.get("last_refreshed_at"),
        "last_refresh_error": youtube_public.get("last_refresh_error"),
    }
    return {
        "authenticated": True,
        "user": user_info,
        "token_expired": creds.expired,
        "token_expires_at": token_status.get("token_expires_at"),
        "token_status": token_status.get("status", "active"),
        "last_refreshed_at": token_status.get("last_refreshed_at"),
        "last_refresh_error": token_status.get("last_refresh_error"),
        "youtube_authenticated": youtube_authenticated,
        "youtube": youtube_connection,
    }


@router.post("/youtube/disconnect")
def disconnect_youtube(request: Request):
    """Remove only the persistent YouTube authorization, keeping page login."""
    session_id = _get_authenticated_session_id(request)
    session_data = session_store.get(session_id) or {}
    owner_sub = str(((session_data.get("user") or {}).get("sub") or "")).strip()
    credential_store.clear_youtube(owner_sub)
    return {"status": "youtube_disconnected"}


@router.post("/logout")
def logout(request: Request):
    """Clear the control-panel login session without removing YouTube access."""
    res = Response(content='{"status":"logged_out"}', media_type="application/json")
    session_store.delete(request.cookies.get(SESSION_COOKIE, ""))
    res.delete_cookie(SESSION_COOKIE, path="/", secure=settings.cookie_secure, httponly=True, samesite="lax")
    res.delete_cookie(OAUTH_FLOW_COOKIE, path="/", secure=settings.cookie_secure, httponly=True, samesite="lax")
    return res
