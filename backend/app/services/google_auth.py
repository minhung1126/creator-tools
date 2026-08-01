import logging
import os
from datetime import datetime, timedelta, timezone
from threading import RLock
from typing import Optional

import googleapiclient.discovery
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow

from backend.app.core.config import settings
from backend.app.core.credential_store import credential_store
from backend.app.core.session_store import session_store

logger = logging.getLogger(__name__)

SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/drive",
]
GOOGLE_TOKEN_REFRESH_WINDOW = timedelta(minutes=5)
_google_refresh_lock = RLock()


def get_client_config() -> dict:
    """Build OAuth client config from .env settings."""
    return {
        "web": {
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "redirect_uris": [settings.get_redirect_uri()],
        }
    }


def create_oauth_flow(code_verifier: Optional[str] = None) -> Flow:
    """Create an OAuth2 flow, generating PKCE only for a new authorization request."""
    config = get_client_config()
    redirect_uri = settings.get_redirect_uri()

    # Only allow insecure transport (HTTP) in non-production environments
    if not settings.is_production:
        os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
    else:
        os.environ.pop("OAUTHLIB_INSECURE_TRANSPORT", None)

    flow = Flow.from_client_config(
        config,
        scopes=SCOPES,
        redirect_uri=redirect_uri,
        code_verifier=code_verifier,
        autogenerate_code_verifier=code_verifier is None,
    )
    return flow


def get_auth_url() -> tuple[str, str, str]:
    """Generate the Google OAuth consent URL and return its PKCE state."""
    flow = create_oauth_flow()
    auth_url, state = flow.authorization_url(access_type="offline", include_granted_scopes="true", prompt="consent")
    if not flow.code_verifier:
        raise RuntimeError("Google OAuth PKCE code verifier was not generated.")
    return auth_url, state, flow.code_verifier


def exchange_code_for_tokens(code: str, code_verifier: str) -> dict:
    """Exchange an authorization code with its original PKCE verifier."""
    flow = create_oauth_flow(code_verifier=code_verifier)
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

    return token_dict


def get_user_profile(credentials: Credentials) -> dict:
    """Fetch the authenticated user's profile information."""
    try:
        service = googleapiclient.discovery.build("oauth2", "v2", credentials=credentials)
        user_info = service.userinfo().get().execute()
        return {
            "email": user_info.get("email", ""),
            "name": user_info.get("name", ""),
            "picture": user_info.get("picture", ""),
        }
    except Exception as e:
        logger.error("Error fetching user profile: %s", e, exc_info=True)
        return {"email": "Connected Account", "name": "", "picture": ""}


def _build_credentials(token_dict: dict) -> Credentials:
    expiry = token_dict.get("expiry")
    parsed_expiry = None
    if expiry:
        try:
            parsed_expiry = datetime.fromisoformat(expiry)
            if parsed_expiry.tzinfo:
                parsed_expiry = parsed_expiry.astimezone(timezone.utc).replace(tzinfo=None)
        except (TypeError, ValueError):
            parsed_expiry = None
    return Credentials(
        token=token_dict.get("token"),
        refresh_token=token_dict.get("refresh_token"),
        token_uri=token_dict.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=token_dict.get("client_id") or settings.GOOGLE_CLIENT_ID,
        client_secret=token_dict.get("client_secret") or settings.GOOGLE_CLIENT_SECRET,
        scopes=token_dict.get("scopes", SCOPES),
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
    session_id: Optional[str],
    persistent: bool,
) -> Credentials:
    """Refresh under one process-wide lock and persist the rotated token atomically."""
    with _google_refresh_lock:
        # Another request may have refreshed the persistent record while this
        # request was waiting for the lock. Always use the newest record.
        latest = credential_store.get_google_credentials() if persistent else None
        active_dict = latest or token_dict
        credentials = _build_credentials(active_dict)
        if not _needs_refresh(credentials):
            return credentials

        try:
            credentials.refresh(Request())
            refreshed = dict(active_dict)
            refreshed["token"] = credentials.token
            refreshed["refresh_token"] = credentials.refresh_token or active_dict.get("refresh_token")
            refreshed["expiry"] = credentials.expiry.isoformat() if credentials.expiry else None
            if persistent:
                credential_store.save_google_connection(refreshed)
            elif session_id:
                # Backward compatibility for sessions created before the
                # persistent credential store was introduced.
                session_store.update(session_id, refreshed)
            return credentials
        except Exception as exc:
            message = str(exc) or type(exc).__name__
            requires_reauthorization = any(
                marker in message.lower() for marker in ("invalid_grant", "invalid client", "revoked")
            )
            if persistent:
                credential_store.mark_google_refresh_failed(message, requires_reauthorization)
            logger.error("Failed to refresh Google token: %s", type(exc).__name__)
            return credentials


def build_credentials_from_dict(
    token_dict: dict,
    session_id: Optional[str] = None,
    *,
    persistent: bool = False,
) -> Credentials:
    """Reconstruct credentials and proactively refresh them before expiry."""
    credentials = _build_credentials(token_dict)
    if _needs_refresh(credentials):
        return _refresh_credentials(token_dict, session_id=session_id, persistent=persistent)
    return credentials


def get_current_credentials(session_id: Optional[str] = None) -> Optional[Credentials]:
    """Load the persistent Google credentials for exactly one server session."""
    if not session_id:
        return None
    session_data = session_store.get(session_id)
    if not session_data:
        return None

    # New sessions contain only an account reference. OAuth credentials live in
    # the encrypted persistent credential store and survive session rotation or
    # a backend restart.
    if session_data.get("credential_provider") == "google":
        token_dict = credential_store.get_google_credentials()
        if not token_dict or not token_dict.get("token"):
            return None
        session_email = str((session_data.get("user") or {}).get("email") or "").casefold()
        credential_email = str((token_dict.get("user") or {}).get("email") or "").casefold()
        if session_email and credential_email and session_email != credential_email:
            return None
        return build_credentials_from_dict(token_dict, persistent=True)

    # Read old sessions during migration. They are refreshed in place and will
    # continue to work until the user signs in again.
    if not session_data.get("token"):
        return None
    return build_credentials_from_dict(session_data, session_id=session_id)
