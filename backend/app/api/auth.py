import logging
import secrets
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse

from backend.app.core.account_state import get_account_active_slot, set_account_active_slot
from backend.app.core.config import normalize_youtube_slot, settings
from backend.app.core.credential_store import credential_store
from backend.app.core.runtime_config import runtime_config
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


def _check_oauth_configuration(purpose: str = LOGIN_FLOW, slot: str = "primary") -> None:
    if purpose == YOUTUBE_FLOW:
        youtube_slot = settings.youtube_oauth_slot(normalize_youtube_slot(slot))
        if not youtube_slot.configured:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "youtube_slot_not_configured",
                    "message": "此 YouTube OAuth slot 尚未完成伺服器設定。",
                    "slot": normalize_youtube_slot(slot),
                },
            )
        return
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
    slot: str = "primary",
) -> None:
    flow_payload = {
        "flow_type": flow_type,
        "state": state,
        "code_verifier": code_verifier,
    }
    if session_id:
        flow_payload["session_id"] = session_id
    if flow_type == YOUTUBE_FLOW:
        flow_payload["slot"] = normalize_youtube_slot(slot)
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
    youtube_slots = {
        slot: {
            "slot": slot,
            "label": slot_config.label,
            "configured": slot_config.configured,
            "enabled": slot_config.enabled,
            "client_fingerprint": slot_config.client_fingerprint,
            "uses_legacy_google_credentials": slot_config.uses_legacy_google_credentials,
            "quota_limit": slot_config.quota_limit,
            "safety_buffer_units": slot_config.safety_buffer_units,
        }
        for slot, slot_config in settings.youtube_oauth_slots.items()
    }
    return {
        "host": settings.base_url,
        "frontend_url": settings.frontend_url,
        "redirect_uri": settings.get_redirect_uri(),
        "has_client_id": bool(settings.GOOGLE_CLIENT_ID),
        "has_client_secret": bool(settings.GOOGLE_CLIENT_SECRET),
        "login_scopes": list(LOGIN_SCOPES),
        "youtube_scopes": list(YOUTUBE_SCOPES),
        "youtube_default_slot": settings.youtube_default_slot,
        "youtube_slots": youtube_slots,
    }


@router.get("/url")
def get_google_auth_url(response: Response):
    """Generate the control-panel login/Sheets OAuth URL."""
    _check_oauth_configuration(LOGIN_FLOW)
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
    """Legacy alias for the primary YouTube OAuth slot."""
    return get_youtube_slot_auth_url("primary", request, response)


@router.get("/youtube/{slot}/url")
def get_youtube_slot_auth_url(slot: str, request: Request, response: Response):
    """Generate a separate OAuth URL for one configured YouTube slot."""
    try:
        slot_name = normalize_youtube_slot(slot)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="不支援的 YouTube OAuth slot") from exc
    _check_oauth_configuration(YOUTUBE_FLOW, slot_name)
    session_id = _get_authenticated_session_id(request)
    try:
        url, state, code_verifier = build_google_auth_url(YOUTUBE_FLOW, slot=slot_name)
        _set_flow_cookie(
            response,
            flow_type=YOUTUBE_FLOW,
            state=state,
            code_verifier=code_verifier,
            session_id=session_id,
            slot=slot_name,
        )
        return {"auth_url": url}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to generate YouTube auth URL for slot %s: %s", slot_name, type(exc).__name__)
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
    flow_slot = "primary"
    if flow_type == YOUTUBE_FLOW:
        try:
            flow_slot = normalize_youtube_slot((flow_state or {}).get("slot", ""))
        except ValueError:
            return redirect_with_auth_error("YouTube OAuth slot verification failed.", YOUTUBE_FLOW)

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
            slot=flow_slot,
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
            channel_id = str(token_dict.get("channel_id") or "").strip()
            other_slot = "secondary" if flow_slot == "primary" else "primary"
            other_public = credential_store.get_youtube_public(owner_sub, slot=other_slot) or {}
            other_channel_id = str(other_public.get("channel_id") or "").strip()
            if other_channel_id and channel_id and other_channel_id != channel_id:
                raise RuntimeError("YouTube OAuth slots must manage the same channel")
            credential_store.save_youtube_connection(token_dict, owner_sub=owner_sub, slot=flow_slot)
            response = RedirectResponse(
                url=f"{settings.frontend_url}/#youtube_auth_success=1&youtube_slot={quote(flow_slot, safe='')}"
            )
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
        logger.error("OAuth callback error (%s/%s): %s", flow_type, flow_slot, type(exc).__name__)
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
            "youtube": {"authenticated": False, "user": None},
        }

    user_info = session_data.get("user") or {"email": "Authenticated User"}
    token_status = credential_store.get_google_public(session_sub) or {}

    youtube_slots = {}
    for slot, slot_config in settings.youtube_oauth_slots.items():
        youtube_public = credential_store.get_youtube_public(session_sub, slot=slot) or {}
        youtube_creds = get_youtube_credentials(session_id, slot=slot) if slot_config.configured else None
        quota_limit, quota_buffer = runtime_config.get_youtube_quota_settings(slot)
        authenticated = bool(
            slot_config.configured
            and youtube_creds
            and youtube_creds.valid
            and youtube_public.get("channel_id")
        )
        youtube_slots[slot] = {
            "slot": slot,
            "label": slot_config.label,
            "configured": slot_config.configured,
            "enabled": slot_config.enabled,
            "authenticated": authenticated,
            "user": youtube_public.get("user"),
            "channel_id": youtube_public.get("channel_id"),
            "channel_title": youtube_public.get("channel_title"),
            "token_expired": bool(youtube_creds and youtube_creds.expired),
            "token_expires_at": youtube_public.get("token_expires_at"),
            "token_status": youtube_public.get("status", "not_connected"),
            "last_refreshed_at": youtube_public.get("last_refreshed_at"),
            "last_refresh_error": youtube_public.get("last_refresh_error"),
            "client_fingerprint": youtube_public.get("client_fingerprint"),
            "can_be_active": authenticated,
            "uses_legacy_google_credentials": slot_config.uses_legacy_google_credentials,
            "quota_limit": quota_limit,
            "safety_buffer_units": quota_buffer,
        }
    primary_channel_id = str(youtube_slots["primary"].get("channel_id") or "").strip()
    secondary_channel_id = str(youtube_slots["secondary"].get("channel_id") or "").strip()
    channel_mismatch = bool(primary_channel_id and secondary_channel_id and primary_channel_id != secondary_channel_id)
    if channel_mismatch:
        for slot in youtube_slots.values():
            slot["channel_mismatch"] = True
            slot["can_be_active"] = False
    else:
        for slot in youtube_slots.values():
            slot["channel_mismatch"] = False
    active_slot = get_account_active_slot(session_sub)
    youtube_connection = {
        **youtube_slots.get(active_slot, {}),
        "active_slot": active_slot,
        "slots": youtube_slots,
        # Preserve the old top-level contract for existing frontend clients.
        "authenticated": bool(youtube_slots.get(active_slot, {}).get("authenticated")),
    }
    return {
        "authenticated": True,
        "user": user_info,
        "token_expired": creds.expired,
        "token_expires_at": token_status.get("token_expires_at"),
        "token_status": token_status.get("status", "active"),
        "last_refreshed_at": token_status.get("last_refreshed_at"),
        "last_refresh_error": token_status.get("last_refresh_error"),
        "youtube": youtube_connection,
    }


@router.post("/youtube/disconnect")
def disconnect_youtube(request: Request, confirm: bool = Query(False)):
    """Legacy primary disconnect endpoint."""
    return disconnect_youtube_slot("primary", request, confirm)


@router.post("/youtube/{slot}/disconnect")
def disconnect_youtube_slot(slot: str, request: Request, confirm: bool = Query(False)):
    """Remove only one persistent YouTube authorization."""
    try:
        slot_name = normalize_youtube_slot(slot)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="不支援的 YouTube OAuth slot") from exc
    session_id = _get_authenticated_session_id(request)
    session_data = session_store.get(session_id) or {}
    owner_sub = str(((session_data.get("user") or {}).get("sub") or "")).strip()
    if slot_name == get_account_active_slot(owner_sub) and not confirm:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "youtube_active_slot_disconnect_requires_confirmation",
                "message": "請先切換作用中的 YouTube slot，或以二次確認斷開目前 slot。",
                "slot": slot_name,
            },
        )
    credential_store.clear_youtube(owner_sub, slot=slot_name)
    logger.info("YouTube OAuth slot disconnected: %s", slot_name)
    return {"status": "youtube_disconnected", "slot": slot_name}


@router.post("/youtube/{slot}/activate")
def activate_youtube_slot(slot: str, request: Request):
    """Make a valid, channel-verified slot the default for new requests."""
    try:
        slot_name = normalize_youtube_slot(slot)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="不支援的 YouTube OAuth slot") from exc
    if not settings.youtube_oauth_slot(slot_name).configured:
        raise HTTPException(status_code=400, detail="此 YouTube OAuth slot 尚未完成伺服器設定。")
    session_id = _get_authenticated_session_id(request)
    session_data = session_store.get(session_id) or {}
    owner_sub = str(((session_data.get("user") or {}).get("sub") or "")).strip()
    public = credential_store.get_youtube_public(owner_sub, slot=slot_name) or {}
    credentials = get_youtube_credentials(session_id, slot=slot_name)
    other_slot = "secondary" if slot_name == "primary" else "primary"
    other_public = credential_store.get_youtube_public(owner_sub, slot=other_slot) or {}
    channel_id = str(public.get("channel_id") or "").strip()
    other_channel_id = str(other_public.get("channel_id") or "").strip()
    if channel_id and other_channel_id and channel_id != other_channel_id:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "youtube_channel_mismatch",
                "message": "Primary 與 secondary 必須管理同一個 YouTube Channel，不能啟用此 slot。",
                "slot": slot_name,
            },
        )
    if not credentials or not credentials.valid or not public.get("channel_id"):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "youtube_slot_not_ready",
                "message": "此 slot 尚未完成有效授權或頻道驗證。",
                "slot": slot_name,
            },
        )
    set_account_active_slot(owner_sub, slot_name)
    logger.info("YouTube active slot changed to %s", slot_name)
    return {"status": "youtube_slot_activated", "active_slot": slot_name}


@router.post("/logout")
def logout(request: Request):
    """Clear the control-panel login session without removing YouTube access."""
    res = Response(content='{"status":"logged_out"}', media_type="application/json")
    session_store.delete(request.cookies.get(SESSION_COOKIE, ""))
    res.delete_cookie(SESSION_COOKIE, path="/", secure=settings.cookie_secure, httponly=True, samesite="lax")
    res.delete_cookie(OAUTH_FLOW_COOKIE, path="/", secure=settings.cookie_secure, httponly=True, samesite="lax")
    return res
