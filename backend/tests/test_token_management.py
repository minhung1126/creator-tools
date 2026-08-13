from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.app.core.credential_store import CredentialStore
from backend.app.core.session_store import SessionStore
from backend.app.services import google_auth


def google_token_payload(expiry: datetime, token: str = "access-token"):
    return {
        "token": token,
        "refresh_token": "refresh-token",
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": "client-id",
        "client_secret": "client-secret",
        "scopes": ["scope-a"],
        "expiry": expiry.isoformat(),
        "user": {"sub": "subject-a", "email": "admin@example.test"},
    }


def test_google_credentials_are_persistent_and_proactively_refreshed(monkeypatch, tmp_path: Path):
    credentials_store = CredentialStore(tmp_path / "credentials.json")
    sessions = SessionStore(tmp_path / "sessions.json")
    credentials_store.save_google_connection(
        google_token_payload(datetime.now(timezone.utc) + timedelta(minutes=1)), owner_sub="subject-a"
    )
    session_id = sessions.create(
        {"credential_provider": "google_login", "user": {"sub": "subject-a", "email": "admin@example.test"}}
    )
    monkeypatch.setattr(google_auth, "credential_store", credentials_store)
    monkeypatch.setattr(google_auth, "session_store", sessions)

    def refresh(self, request):
        self.token = "refreshed-access-token"
        self.expiry = datetime.now(timezone.utc) + timedelta(hours=1)

    monkeypatch.setattr(google_auth.Credentials, "refresh", refresh)
    credentials = google_auth.get_login_credentials(session_id)

    assert credentials.token == "refreshed-access-token"
    assert sessions.get(session_id)["credential_provider"] == "google_login"
    assert "token" not in sessions.get(session_id)
    assert credentials_store.get_google_credentials("subject-a")["token"] == "refreshed-access-token"
    assert "refreshed-access-token" not in (tmp_path / "credentials.json").read_text(encoding="utf-8")


def test_google_reconnect_without_refresh_token_preserves_previous_refresh_token(tmp_path: Path):
    store = CredentialStore(tmp_path / "credentials.json")
    store.save_google_connection(
        google_token_payload(datetime.now(timezone.utc) + timedelta(hours=1)), owner_sub="subject-a"
    )
    replacement = google_token_payload(datetime.now(timezone.utc) + timedelta(hours=1), token="replacement-token")
    replacement["refresh_token"] = None
    store.save_google_connection(replacement, owner_sub="subject-a")

    assert store.get_google_credentials("subject-a")["refresh_token"] == "refresh-token"
