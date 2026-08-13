from backend.app import main


def test_health_reports_configuration_readiness_without_secrets(monkeypatch):
    monkeypatch.setattr(main.settings, "PUBLIC_BASE_URL", "http://localhost:8000")
    monkeypatch.setattr(main.settings, "GOOGLE_CLIENT_ID", "configured-client")
    monkeypatch.setattr(main.settings, "GOOGLE_CLIENT_SECRET", "configured-secret")
    monkeypatch.setattr(main.settings, "YOUTUBE_OAUTH_PRIMARY_CLIENT_ID", "configured-youtube-client")
    monkeypatch.setattr(main.settings, "YOUTUBE_OAUTH_PRIMARY_CLIENT_SECRET", "configured-youtube-secret")
    result = main.health_check()

    assert result["status"] == "healthy"
    assert result["ready"] is True
    assert result["configuration"] == {
        "google_oauth_ready": True,
        "access_allowlist_ready": True,
    }
    assert "configured-client" not in str(result)
    assert "configured-secret" not in str(result)


def test_health_explains_why_login_is_not_ready(monkeypatch):
    monkeypatch.setattr(main.settings, "PUBLIC_BASE_URL", "https://creator-tools.example.com")
    monkeypatch.setattr(main.settings, "GOOGLE_CLIENT_ID", "")
    monkeypatch.setattr(main.settings, "GOOGLE_CLIENT_SECRET", "")
    monkeypatch.setattr(main.settings, "YOUTUBE_OAUTH_PRIMARY_CLIENT_ID", "")
    monkeypatch.setattr(main.settings, "YOUTUBE_OAUTH_PRIMARY_CLIENT_SECRET", "")
    monkeypatch.setattr(main.settings, "ALLOWED_GOOGLE_EMAILS", "")

    result = main.health_check()

    assert result["ready"] is False
    assert result["configuration"]["google_oauth_ready"] is False
    assert result["configuration"]["access_allowlist_ready"] is False
    assert len(result["warnings"]) == 2
