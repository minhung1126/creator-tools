import os
from typing import Dict, Any, Optional
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
import googleapiclient.discovery
from backend.app.core.config import settings

SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/drive.readonly",
]

# Memory/File token store fallback for local development
_token_cache: Dict[str, Any] = {}

def get_client_config(client_id: str = "", client_secret: str = "") -> dict:
    cid = client_id or settings.GOOGLE_CLIENT_ID
    csecret = client_secret or settings.GOOGLE_CLIENT_SECRET
    return {
        "web": {
            "client_id": cid,
            "client_secret": csecret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "redirect_uris": [settings.get_redirect_uri()]
        }
    }

def create_oauth_flow(client_id: str = "", client_secret: str = "") -> Flow:
    config = get_client_config(client_id, client_secret)
    redirect_uri = settings.get_redirect_uri()
    
    # Allow insecure transport for local dev if needed
    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
    
    flow = Flow.from_client_config(
        config,
        scopes=SCOPES,
        redirect_uri=redirect_uri
    )
    return flow

def get_auth_url(client_id: str = "", client_secret: str = "") -> str:
    flow = create_oauth_flow(client_id, client_secret)
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent"
    )
    return auth_url

def exchange_code_for_tokens(code: str, client_id: str = "", client_secret: str = "") -> dict:
    flow = create_oauth_flow(client_id, client_secret)
    flow.fetch_token(code=code)
    creds = flow.credentials
    
    token_dict = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": creds.scopes
    }
    
    # Fetch user profile using credentials
    user_info = get_user_profile(creds)
    token_dict["user"] = user_info
    
    # Cache locally
    _token_cache["current"] = token_dict
    return token_dict

def get_user_profile(credentials: Credentials) -> dict:
    try:
        service = googleapiclient.discovery.build("oauth2", "v2", credentials=credentials)
        user_info = service.userinfo().get().execute()
        return {
            "email": user_info.get("email", ""),
            "name": user_info.get("name", ""),
            "picture": user_info.get("picture", "")
        }
    except Exception as e:
        print(f"Error fetching user profile: {e}")
        return {"email": "Connected Account", "name": "", "picture": ""}

def build_credentials_from_dict(token_dict: dict) -> Credentials:
    creds = Credentials(
        token=token_dict.get("token"),
        refresh_token=token_dict.get("refresh_token"),
        token_uri=token_dict.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=token_dict.get("client_id") or settings.GOOGLE_CLIENT_ID,
        client_secret=token_dict.get("client_secret") or settings.GOOGLE_CLIENT_SECRET,
        scopes=token_dict.get("scopes", SCOPES)
    )
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            # Update cache
            if "current" in _token_cache:
                _token_cache["current"]["token"] = creds.token
        except Exception as e:
            print(f"Failed to refresh token: {e}")
    return creds

def get_current_credentials(stored_tokens: Optional[dict] = None) -> Optional[Credentials]:
    if stored_tokens and stored_tokens.get("token"):
        return build_credentials_from_dict(stored_tokens)
    if "current" in _token_cache and _token_cache["current"].get("token"):
        return build_credentials_from_dict(_token_cache["current"])
    return None

def clear_current_credentials():
    _token_cache.pop("current", None)
