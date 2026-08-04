from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Response
from fastapi.testclient import TestClient
from pydantic import ValidationError
from starlette.requests import Request

from backend.app import main
from backend.app.api import auth
from backend.app.api import sheets as sheets_api
from backend.app.api.sheets import SpreadsheetInput
from backend.app.api.youtube import BatchUpdateInput, VideoAssignment
from backend.app.core.config import Settings, settings
from backend.app.core.credential_store import CredentialStore
from backend.app.core.request_protection import require_same_origin


def test_frontend_path_traversal_cannot_escape_dist():
    with pytest.raises(HTTPException) as error:
        main.resolve_frontend_path("../../backend/app/main.py")

    assert error.value.status_code == 404
    assert "main.py" not in str(error.value.detail)


def test_production_settings_fail_closed_and_use_host_only_cookies():
    common = {
        "ENVIRONMENT": "production",
        "PUBLIC_BASE_URL": "https://creator.example.com",
        "FRONTEND_URL": "https://creator.example.com",
        "SECRET_KEY": "s" * 64,
        "CREDENTIAL_ENCRYPTION_KEY": "c" * 64,
        "ALLOWED_GOOGLE_EMAILS": "admin@example.com",
    }

    with pytest.raises(ValueError, match="SECRET_KEY"):
        Settings(**{**common, "SECRET_KEY": ""})
    with pytest.raises(ValueError, match="CREDENTIAL_ENCRYPTION_KEY"):
        Settings(**{**common, "CREDENTIAL_ENCRYPTION_KEY": ""})
    with pytest.raises(ValueError, match="HTTPS"):
        Settings(**{**common, "PUBLIC_BASE_URL": "http://creator.example.com"})
    with pytest.raises(ValueError, match="different"):
        Settings(**{**common, "CREDENTIAL_ENCRYPTION_KEY": common["SECRET_KEY"]})

    production = Settings(**common)
    assert production.is_production is True
    assert production.cookie_secure is True
    assert production.session_cookie_name.startswith("__Host-")
    assert production.oauth_flow_cookie_name.startswith("__Host-")

    https_development = Settings(**{**common, "ENVIRONMENT": "development", "ALLOWED_GOOGLE_EMAILS": ""})
    assert https_development.allowlist_required is True
    assert https_development.is_google_email_allowed("anyone@example.com") is False


def test_production_oauth_flow_cookie_has_secure_host_only_attributes(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(auth, "OAUTH_FLOW_COOKIE", "__Host-test_oauth_flow")
    response = Response()

    auth._set_flow_cookie(response, flow_type="login", state="state", code_verifier="verifier")
    set_cookie = response.headers["set-cookie"]

    assert set_cookie.startswith("__Host-test_oauth_flow=")
    assert "Secure" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "Path=/" in set_cookie
    assert "SameSite=lax" in set_cookie

    deleted = auth.redirect_with_auth_error("test")
    delete_cookie = deleted.headers["set-cookie"]
    assert "__Host-test_oauth_flow=" in delete_cookie
    assert "Secure" in delete_cookie
    assert "Path=/" in delete_cookie


def test_credentials_are_isolated_by_oidc_subject(tmp_path: Path):
    store = CredentialStore(tmp_path / "credentials.json")
    store.save_google_connection(
        {"token": "google-a", "refresh_token": "refresh-a", "user": {"sub": "sub-a", "email": "a@example.com"}},
        owner_sub="sub-a",
    )
    store.save_youtube_connection(
        {"token": "youtube-a", "refresh_token": "youtube-refresh-a", "user": {"sub": "sub-a"}},
        owner_sub="sub-a",
    )
    store.save_google_connection(
        {"token": "google-b", "refresh_token": "refresh-b", "user": {"sub": "sub-b", "email": "b@example.com"}},
        owner_sub="sub-b",
    )

    assert store.get_google_credentials("sub-a")["token"] == "google-a"
    assert store.get_google_credentials("sub-b")["token"] == "google-b"
    assert store.get_youtube_credentials("sub-a")["token"] == "youtube-a"
    assert store.get_youtube_credentials("sub-b") is None
    assert "owner_sub" not in store.get_google_public("sub-a")


def test_foreign_origin_is_rejected_for_mutations():
    request = Request(
        {
            "type": "http",
            "method": "PUT",
            "path": "/api/v1/settings/shared",
            "headers": [(b"origin", b"https://evil.example")],
            "query_string": b"",
            "server": ("testserver", 80),
        }
    )

    with pytest.raises(HTTPException) as error:
        require_same_origin(request)

    assert error.value.status_code == 403
    assert error.value.detail["code"] == "csrf_origin_denied"


def test_production_requires_origin_or_referer(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/settings/shared",
            "headers": [],
            "query_string": b"",
            "server": ("testserver", 80),
        }
    )

    with pytest.raises(HTTPException) as error:
        require_same_origin(request)

    assert error.value.status_code == 403


def test_quota_usage_requires_login():
    response = TestClient(main.app).get("/api/v1/youtube/quota-usage")
    assert response.status_code == 401


def test_provider_exception_is_not_returned_to_the_client(monkeypatch):
    secret_detail = "https://sheets.googleapis.com/v4/spreadsheets/private-id"

    def raise_provider_error(*args, **kwargs):
        raise RuntimeError(secret_detail)

    monkeypatch.setattr(sheets_api, "get_spreadsheet_metadata", raise_provider_error)
    with pytest.raises(HTTPException) as error:
        sheets_api.spreadsheet_metadata(SpreadsheetInput(spreadsheet_url_or_id="sheet-id"), SimpleNamespace())

    assert error.value.status_code == 500
    assert secret_detail not in str(error.value.detail)


def test_security_headers_are_present():
    response = TestClient(main.app).get("/api/v1/health")
    assert response.status_code == 200
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Content-Security-Policy"].startswith("default-src 'self'")


def test_batch_input_has_a_bounded_assignment_count():
    with pytest.raises(ValidationError):
        BatchUpdateInput(
            worksheet_name="工作表",
            title_column="標題",
            description_column="描述",
            team="團體",
            assignments=[VideoAssignment(video_id=str(index), person="人物") for index in range(501)],
        )
