from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException
from starlette.requests import Request

from backend.app.core import dependencies
from backend.app.core.credential_store import CredentialStore
from backend.app.core.security import (
    GOOGLE_OAUTH_STATE_SALT,
    sign_timed_data,
    verify_timed_data,
)
from backend.app.core.session_store import SessionStore
from backend.app.services import google_auth


def test_oauth_state_is_tamper_expiry_and_salt_bound():
    token = sign_timed_data({"state": "abc"}, GOOGLE_OAUTH_STATE_SALT)
    assert verify_timed_data(token, GOOGLE_OAUTH_STATE_SALT, 60)["state"] == "abc"
    assert verify_timed_data(token + "x", GOOGLE_OAUTH_STATE_SALT, 60) is None
    assert verify_timed_data(token, "different-oauth-flow", 60) is None
    expired = sign_timed_data({"state": "old"}, GOOGLE_OAUTH_STATE_SALT)
    assert verify_timed_data(expired, GOOGLE_OAUTH_STATE_SALT, -1) is None


def test_sessions_are_isolated_and_cookie_has_no_token(tmp_path: Path):
    store = SessionStore(tmp_path / "sessions.json")
    first = store.create({"token": "google-token-a", "client_secret": "secret-a"})
    second = store.create({"token": "google-token-b"})
    assert first != second
    assert store.get(first)["token"] == "google-token-a"
    store.delete(first)
    assert store.get(first) is None
    assert store.get(second)["token"] == "google-token-b"
    assert "google-token-a" not in first and "secret-a" not in first


def test_no_cookie_never_falls_back_to_global_credentials():
    request = Request(
        {"type": "http", "method": "GET", "path": "/", "headers": [], "query_string": b"", "server": ("testserver", 80)}
    )
    with pytest.raises(HTTPException) as error:
        dependencies.require_credentials(request)
    assert error.value.status_code == 401


def test_google_refresh_updates_only_the_current_server_session(monkeypatch, tmp_path: Path):
    store = SessionStore(tmp_path / "sessions.json")
    session_id = store.create(
        {
            "token": "old-token",
            "refresh_token": "refresh-token",
            "client_id": "client",
            "client_secret": "secret",
            "expiry": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
            "user": {"email": "admin@example.test"},
        }
    )
    monkeypatch.setattr(google_auth, "session_store", store)

    def refresh(self, request):
        self.token = "new-token"
        self.expiry = datetime.now(timezone.utc) + timedelta(hours=1)

    monkeypatch.setattr(google_auth.Credentials, "refresh", refresh)
    credentials = google_auth.get_current_credentials(session_id)
    assert credentials.token == "new-token"
    assert store.get(session_id)["token"] == "new-token"


def test_credential_store_encrypts_and_rejects_wrong_key(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("backend.app.core.credential_store.settings.CREDENTIAL_ENCRYPTION_KEY", "test-key")
    store = CredentialStore(tmp_path / "credentials.json")
    store.save_google_connection(
        {
            "token": "google-token",
            "refresh_token": "google-refresh-token",
            "expiry": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            "user": {"email": "admin@example.test"},
        }
    )
    raw = (tmp_path / "credentials.json").read_text(encoding="utf-8")
    assert "google-token" not in raw
    assert "google-refresh-token" not in raw
    store._fernet = Fernet(Fernet.generate_key())
    with pytest.raises(RuntimeError):
        store.get_google_credentials()
