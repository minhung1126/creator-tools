"""Instagram API with Instagram Login OAuth helpers."""

from typing import Any, Dict, Iterable
from urllib.parse import urlencode

import httpx

AUTHORIZATION_URL = "https://www.instagram.com/oauth/authorize"
TOKEN_URL = "https://api.instagram.com/oauth/access_token"
GRAPH_BASE_URL = "https://graph.instagram.com"
REQUIRED_SCOPES = (
    "instagram_business_basic",
    "instagram_business_content_publish",
)


def _error_message(response: httpx.Response, fallback: str) -> str:
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        return error.get("message") or error.get("error_user_msg") or fallback
    if isinstance(error, str):
        return error
    return payload.get("error_message") or fallback if isinstance(payload, dict) else fallback


def build_authorization_url(app_id: str, redirect_uri: str, state: str) -> str:
    query = urlencode(
        {
            "client_id": app_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": ",".join(REQUIRED_SCOPES),
            "state": state,
            "enable_fb_login": "0",
            "force_authentication": "1",
        }
    )
    return f"{AUTHORIZATION_URL}?{query}"


def exchange_authorization_code(
    *,
    app_id: str,
    app_secret: str,
    redirect_uri: str,
    code: str,
) -> Dict[str, Any]:
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        response = client.post(
            TOKEN_URL,
            data={
                "client_id": app_id,
                "client_secret": app_secret,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
                "code": code,
            },
        )
    if response.is_error:
        raise RuntimeError(_error_message(response, f"Instagram token exchange failed: HTTP {response.status_code}"))
    payload = response.json()
    # Some Business Login responses wrap the token data in a one-item data array.
    if isinstance(payload, dict) and isinstance(payload.get("data"), list) and payload["data"]:
        payload = payload["data"][0]
    if not isinstance(payload, dict) or not payload.get("access_token"):
        raise RuntimeError("Instagram token exchange did not return an access token")
    return payload


def exchange_long_lived_token(short_lived_token: str, app_secret: str) -> Dict[str, Any]:
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        response = client.get(
            f"{GRAPH_BASE_URL}/access_token",
            params={
                "grant_type": "ig_exchange_token",
                "client_secret": app_secret,
                "access_token": short_lived_token,
            },
        )
    if response.is_error:
        raise RuntimeError(_error_message(response, f"Instagram long-lived token exchange failed: HTTP {response.status_code}"))
    payload = response.json()
    if not isinstance(payload, dict) or not payload.get("access_token"):
        raise RuntimeError("Instagram long-lived token exchange did not return an access token")
    return payload


def refresh_long_lived_token(access_token: str) -> Dict[str, Any]:
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        response = client.get(
            f"{GRAPH_BASE_URL}/refresh_access_token",
            params={
                "grant_type": "ig_refresh_token",
                "access_token": access_token,
            },
        )
    if response.is_error:
        raise RuntimeError(_error_message(response, f"Instagram token refresh failed: HTTP {response.status_code}"))
    payload = response.json()
    if not isinstance(payload, dict) or not payload.get("access_token"):
        raise RuntimeError("Instagram token refresh did not return an access token")
    return payload


def normalize_permissions(value: Any) -> list[str]:
    if isinstance(value, str):
        raw: Iterable[str] = value.replace(" ", ",").split(",")
    elif isinstance(value, list):
        raw = value
    else:
        return []
    return sorted({str(item).strip() for item in raw if str(item).strip()})
