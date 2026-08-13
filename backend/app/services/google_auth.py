import logging
import os
from datetime import datetime, timedelta, timezone
from threading import RLock
from typing import Optional

import googleapiclient.discovery
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow

from backend.app.core.config import normalize_youtube_slot, settings
from backend.app.core.credential_store import credential_store
from backend.app.core.session_store import session_store
from backend.app.services.youtube_quota_service import get_youtube_quota_tracker

logger = logging.getLogger(__name__)

LOGIN_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/spreadsheets.readonly",
]
YOUTUBE_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/youtube",
]
GOOGLE_TOKEN_REFRESH_WINDOW = timedelta(minutes=5)
_google_refresh_lock = RLock()


def get_client_config(purpose: str = "login", slot: str = "primary") -> dict:
    """Build the OAuth client config for login or one YouTube slot."""
    if purpose == "youtube":
        youtube_slot = settings.youtube_oauth_slot(normalize_youtube_slot(slot))
        client_id = youtube_slot.client_id
        client_secret = youtube_slot.client_secret
    elif purpose == "login":
        client_id = settings.GOOGLE_CLIENT_ID
        client_secret = settings.GOOGLE_CLIENT_SECRET
    else:
        raise ValueError(f"不支援的 Google OAuth 用途：{purpose}")
    return {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "redirect_uris": [settings.get_redirect_uri()],
        }
    }


def _scopes_for(purpose: str) -> list[str]:
    if purpose == "youtube":
        return YOUTUBE_SCOPES
    if purpose == "login":
        return LOGIN_SCOPES
    raise ValueError(f"不支援的 Google OAuth 用途：{purpose}")


def create_oauth_flow(
    code_verifier: Optional[str] = None,
    purpose: str = "login",
    slot: str = "primary",
) -> Flow:
    """Create a PKCE OAuth flow for either login/Sheets or one YouTube slot."""
    slot_name = normalize_youtube_slot(slot) if purpose == "youtube" else "primary"
    config = get_client_config(purpose=purpose, slot=slot_name)
    redirect_uri = settings.get_redirect_uri()

    # Only allow insecure transport (HTTP) in non-production environments
    if not settings.is_production:
        os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
    else:
        os.environ.pop("OAUTHLIB_INSECURE_TRANSPORT", None)

    flow = Flow.from_client_config(
        config,
        scopes=_scopes_for(purpose),
        redirect_uri=redirect_uri,
        code_verifier=code_verifier,
        autogenerate_code_verifier=code_verifier is None,
    )
    return flow


def get_auth_url(purpose: str = "login", slot: str = "primary") -> tuple[str, str, str]:
    """Generate a Google OAuth URL and return its PKCE state."""
    slot_name = normalize_youtube_slot(slot) if purpose == "youtube" else "primary"
    flow = create_oauth_flow(purpose=purpose, slot=slot_name)
    prompt = "consent select_account" if purpose == "youtube" else "consent"
    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt=prompt,
    )
    if not flow.code_verifier:
        raise RuntimeError("Google OAuth PKCE code verifier 未建立。")
    return auth_url, state, flow.code_verifier


def exchange_code_for_tokens(
    code: str,
    code_verifier: str,
    purpose: str = "login",
    slot: str = "primary",
) -> dict:
    """Exchange an authorization code with the matching flow and PKCE verifier."""
    slot_name = normalize_youtube_slot(slot) if purpose == "youtube" else "primary"
    flow = create_oauth_flow(code_verifier=code_verifier, purpose=purpose, slot=slot_name)
    flow.fetch_token(code=code)
    creds = flow.credentials

    token_dict = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes) if creds.scopes else [],
        "expiry": creds.expiry.isoformat() if creds.expiry else None,
    }

    # Fetch user profile using credentials
    user_info = get_user_profile(creds)
    token_dict["user"] = user_info

    if purpose == "youtube":
        channel = get_youtube_channel_info(creds, slot=slot_name)
        token_dict.update(
            {
                "channel_id": channel["channel_id"],
                "channel_title": channel.get("channel_title") or "",
            }
        )

    return token_dict


def get_youtube_channel_info(credentials: Credentials, *, slot: str = "primary") -> dict[str, str]:
    """Verify and return the channel represented by a YouTube OAuth token."""
    slot_name = normalize_youtube_slot(slot)
    service = googleapiclient.discovery.build("youtube", "v3", credentials=credentials)
    request = service.channels().list(part="id,snippet", mine=True, maxResults=1)
    response = get_youtube_quota_tracker(slot_name).execute(request, "channels.list")
    items = response.get("items") if isinstance(response, dict) else None
    channel = items[0] if isinstance(items, list) and items else None
    channel_id = str((channel or {}).get("id") or "").strip()
    if not channel_id:
        raise RuntimeError("授權的 Google 帳號沒有可存取的 YouTube 頻道。")
    snippet = (channel or {}).get("snippet") or {}
    return {
        "channel_id": channel_id,
        "channel_title": str(snippet.get("title") or "").strip(),
    }


def get_user_profile(credentials: Credentials) -> dict:
    """Fetch the authenticated user's profile information."""
    try:
        service = googleapiclient.discovery.build("oauth2", "v2", credentials=credentials)
        user_info = service.userinfo().get().execute()
        return {
            # The v2 userinfo endpoint exposes Google's stable OIDC subject as
            # ``id``. Keep both spellings accepted for test doubles/providers.
            "sub": user_info.get("sub") or user_info.get("id", ""),
            "email": user_info.get("email", ""),
            "name": user_info.get("name", ""),
            "picture": user_info.get("picture", ""),
        }
    except Exception as e:
        logger.error("Error fetching user profile: %s", type(e).__name__)
        return {"sub": "", "email": "Connected Account", "name": "", "picture": ""}


def _build_credentials(token_dict: dict, *, purpose: str = "login", slot: str = "primary") -> Credentials:
    expiry = token_dict.get("expiry")
    parsed_expiry = None
    if expiry:
        try:
            parsed_expiry = datetime.fromisoformat(expiry)
            if parsed_expiry.tzinfo:
                parsed_expiry = parsed_expiry.astimezone(timezone.utc).replace(tzinfo=None)
        except (TypeError, ValueError):
            parsed_expiry = None
    if purpose == "youtube":
        youtube_slot = settings.youtube_oauth_slot(normalize_youtube_slot(slot))
        client_id = youtube_slot.client_id
        client_secret = youtube_slot.client_secret
    else:
        client_id = token_dict.get("client_id") or settings.GOOGLE_CLIENT_ID
        client_secret = settings.GOOGLE_CLIENT_SECRET
    return Credentials(
        token=token_dict.get("token"),
        refresh_token=token_dict.get("refresh_token"),
        token_uri=token_dict.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=client_id,
        client_secret=client_secret,
        scopes=token_dict.get("scopes", LOGIN_SCOPES),
        expiry=parsed_expiry,
    )


def _needs_refresh(credentials: Credentials) -> bool:
    if not credentials.refresh_token:
        return False
    if credentials.expired:
        return True
    if not credentials.expiry:
        return False
    expiry = credentials.expiry
    if expiry.tzinfo:
        now = datetime.now(timezone.utc)
    else:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
    return expiry - now <= GOOGLE_TOKEN_REFRESH_WINDOW


def _refresh_credentials(
    token_dict: dict,
    *,
    owner_sub: str,
    credential_key: str = "google",
    slot: str = "primary",
) -> Credentials:
    """Refresh under one process-wide lock and persist the rotated token atomically."""
    with _google_refresh_lock:
        # Another request may have refreshed the persistent record while this
        # request was waiting for the lock. Always use the newest record.
        latest = (
            credential_store.get_youtube_credentials(owner_sub, slot=slot)
            if credential_key == "youtube"
            else credential_store.get_google_credentials(owner_sub)
        )
        active_dict = latest or token_dict
        purpose = "youtube" if credential_key == "youtube" else "login"
        credentials = _build_credentials(active_dict, purpose=purpose, slot=slot)
        if not _needs_refresh(credentials):
            return credentials

        try:
            credentials.refresh(Request())
            refreshed = dict(active_dict)
            refreshed["token"] = credentials.token
            refreshed["refresh_token"] = credentials.refresh_token or active_dict.get("refresh_token")
            refreshed["expiry"] = credentials.expiry.isoformat() if credentials.expiry else None
            if credential_key == "youtube":
                credential_store.save_youtube_connection(refreshed, owner_sub=owner_sub, slot=slot)
            else:
                credential_store.save_google_connection(refreshed, owner_sub=owner_sub)
            return credentials
        except Exception as exc:
            raw_message = str(exc).casefold()
            requires_reauthorization = any(
                marker in raw_message for marker in ("invalid_grant", "invalid client", "revoked")
            )
            # Never persist or expose the provider's raw response body. The
            # status is enough for the UI; diagnostics retain only the type.
            message = "Google OAuth 憑證需要重新授權。" if requires_reauthorization else "Google OAuth 憑證更新失敗。"
            if credential_key == "youtube":
                credential_store.mark_youtube_refresh_failed(
                    message,
                    owner_sub=owner_sub,
                    slot=slot,
                    requires_reauthorization=requires_reauthorization,
                )
            else:
                credential_store.mark_google_refresh_failed(
                    message, owner_sub=owner_sub, requires_reauthorization=requires_reauthorization
                )
            logger.error("Failed to refresh Google token: %s", type(exc).__name__)
            return credentials


def build_credentials_from_dict(
    token_dict: dict,
    *,
    credential_key: str = "google",
    owner_sub: str,
    slot: str = "primary",
) -> Credentials:
    """Reconstruct credentials and proactively refresh them before expiry."""
    purpose = "youtube" if credential_key == "youtube" else "login"
    credentials = _build_credentials(token_dict, purpose=purpose, slot=slot)
    if _needs_refresh(credentials):
        return _refresh_credentials(
            token_dict,
            owner_sub=owner_sub,
            credential_key=credential_key,
            slot=slot,
        )
    return credentials


def get_login_credentials(session_id: Optional[str] = None) -> Optional[Credentials]:
    """Load control-panel login/Sheets credentials for one server session."""
    if not session_id:
        return None
    session_data = session_store.get(session_id)
    if not session_data:
        return None

    session_user = session_data.get("user") if isinstance(session_data.get("user"), dict) else {}
    session_sub = str(session_user.get("sub") or "").strip() or None

    # New sessions contain only an account reference. OAuth credentials live in
    # the encrypted persistent credential store and survive session rotation or
    # a backend restart.
    if session_data.get("credential_provider") != "google_login" or not session_sub:
        return None
    token_dict = credential_store.get_google_credentials(session_sub)
    if not token_dict or not token_dict.get("token"):
        return None
    credential_user = token_dict.get("user") if isinstance(token_dict.get("user"), dict) else {}
    credential_sub = str(credential_user.get("sub") or credential_user.get("id") or "").strip()
    if credential_sub != session_sub:
        return None
    return build_credentials_from_dict(token_dict, credential_key="google", owner_sub=session_sub)


def get_youtube_credentials(session_id: Optional[str] = None, slot: str = "primary") -> Optional[Credentials]:
    """Load one separately authorized YouTube connection for a login session."""
    slot_name = normalize_youtube_slot(slot)
    session_data = session_store.get(session_id) if session_id else None
    session_user = session_data.get("user") if isinstance(session_data, dict) else None
    owner_sub = str((session_user or {}).get("sub") or "").strip() or None
    if not owner_sub:
        return None
    login_credentials = get_login_credentials(session_id)
    if not session_id or not login_credentials or not login_credentials.valid:
        return None
    token_dict = credential_store.get_youtube_credentials(owner_sub, slot=slot_name)
    if not token_dict or not token_dict.get("token"):
        return None
    return build_credentials_from_dict(
        token_dict,
        credential_key="youtube",
        owner_sub=owner_sub,
        slot=slot_name,
    )
