from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import Request

from backend.app import main
from backend.app.api import auth
from backend.app.core.config import Settings
from backend.app.core.credential_store import CredentialStore
from backend.app.core.security import GOOGLE_OAUTH_STATE_SALT, sign_timed_data
from backend.app.core.youtube_context import YouTubeRequestContext
from backend.app.core.youtube_quota_limiter import YouTubeQuotaLimiter
from backend.app.services.youtube_errors import YouTubeQuotaUnavailable


def test_youtube_settings_require_secondary_pair_and_validate_default_slot():
    common = {
        "ENVIRONMENT": "production",
        "PUBLIC_BASE_URL": "https://creator.example.com",
        "FRONTEND_URL": "https://creator.example.com",
        "SECRET_KEY": "s" * 64,
        "CREDENTIAL_ENCRYPTION_KEY": "c" * 64,
        "ALLOWED_GOOGLE_EMAILS": "admin@example.com",
        "GOOGLE_CLIENT_ID": "login-client",
        "GOOGLE_CLIENT_SECRET": "login-secret",
    }

    with pytest.raises(ValueError, match="SECONDARY_ENABLED"):
        Settings(**{**common, "YOUTUBE_OAUTH_SECONDARY_ENABLED": True})

    configured = Settings(
        **{
            **common,
            "YOUTUBE_OAUTH_PRIMARY_CLIENT_ID": "youtube-primary",
            "YOUTUBE_OAUTH_PRIMARY_CLIENT_SECRET": "youtube-primary-secret",
            "YOUTUBE_OAUTH_SECONDARY_ENABLED": True,
            "YOUTUBE_OAUTH_SECONDARY_CLIENT_ID": "youtube-secondary",
            "YOUTUBE_OAUTH_SECONDARY_CLIENT_SECRET": "youtube-secondary-secret",
            "YOUTUBE_OAUTH_DEFAULT_SLOT": "secondary",
        }
    )
    assert configured.youtube_oauth_slot("primary").configured is True
    assert configured.youtube_oauth_slot("secondary").configured is True
    assert configured.youtube_oauth_slot("primary").client_fingerprint != "youtube-primary"


def test_primary_requires_explicit_credentials_even_when_login_is_configured():
    configured = Settings(
        ENVIRONMENT="development",
        PUBLIC_BASE_URL="http://localhost:8000",
        GOOGLE_CLIENT_ID="login-client",
        GOOGLE_CLIENT_SECRET="login-secret",
    )
    primary = configured.youtube_oauth_slot("primary")
    assert primary.configured is False
    assert configured.youtube_oauth_warnings() == ["尚未設定 YouTube primary OAuth 憑證"]


def test_youtube_slot_credentials_and_ledgers_are_isolated(tmp_path: Path):
    store = CredentialStore(tmp_path / "credentials.json")
    for slot in ("primary", "secondary"):
        store.save_youtube_connection(
            {
                "token": f"{slot}-access",
                "refresh_token": f"{slot}-refresh",
                "client_id": f"{slot}-client",
                "user": {"sub": "subject", "email": "creator@example.com"},
                "channel_id": "channel-1",
            },
            owner_sub="subject",
            slot=slot,
        )
    assert store.get_youtube_credentials("subject", "primary")["token"] == "primary-access"
    assert store.get_youtube_credentials("subject", "secondary")["token"] == "secondary-access"

    primary = YouTubeQuotaLimiter(
        tmp_path / "primary.json", slot="primary", configured_limit=100, safety_buffer_units=1
    )
    secondary = YouTubeQuotaLimiter(
        tmp_path / "secondary.json", slot="secondary", configured_limit=100, safety_buffer_units=1
    )
    primary.record("videos.update")
    assert primary.get_usage()["estimated_used_units"] == 50
    assert secondary.get_usage()["estimated_used_units"] == 0


def test_quota_ledger_rejects_a_file_from_another_slot(tmp_path: Path):
    primary = YouTubeQuotaLimiter(tmp_path / "quota.json", slot="primary", configured_limit=100, safety_buffer_units=1)
    primary.get_usage()
    secondary = YouTubeQuotaLimiter(
        tmp_path / "quota.json", slot="secondary", configured_limit=100, safety_buffer_units=1
    )
    with pytest.raises(YouTubeQuotaUnavailable) as caught:
        secondary.get_usage()
    assert caught.value.code == "youtube_quota_storage_unavailable"


def test_callback_rejects_a_signed_cookie_with_an_invalid_slot():
    payload = sign_timed_data(
        {"flow_type": auth.YOUTUBE_FLOW, "state": "state", "code_verifier": "verifier", "slot": "forged"},
        salt=GOOGLE_OAUTH_STATE_SALT,
    )
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/auth/callback",
            "headers": [(b"cookie", f"{auth.OAUTH_FLOW_COOKIE}={payload}".encode())],
            "query_string": b"code=code&state=state",
            "server": ("testserver", 80),
        }
    )
    response = auth.google_oauth_callback(request, code="code", state="state")
    assert "youtube_auth_error=" in response.headers["location"]


def test_request_context_keeps_the_selected_slot():
    context = YouTubeRequestContext(
        slot="secondary",
        credentials=SimpleNamespace(token="secondary-token"),
        quota_limiter=SimpleNamespace(),
        channel_id="channel-1",
        owner_sub="subject",
    )
    assert context.slot == "secondary"
    assert context.channel_id == "channel-1"


def test_slot_api_routes_are_exposed_without_single_slot_aliases():
    paths = main.app.openapi()["paths"]
    assert "/api/v1/auth/youtube/{slot}/url" in paths
    assert "/api/v1/auth/youtube/{slot}/disconnect" in paths
    assert "/api/v1/auth/youtube/{slot}/activate" in paths
    assert "/api/v1/settings/youtube-slots" in paths
    assert "/api/v1/auth/youtube/url" not in paths
    assert "/api/v1/auth/youtube/disconnect" not in paths
