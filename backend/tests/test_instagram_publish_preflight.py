from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.app.api import instagram


def test_publish_preflight_checks_instagram_before_r2(monkeypatch):
    calls = []
    client = SimpleNamespace(profile=lambda: calls.append("instagram"))
    monkeypatch.setattr(instagram, "get_connected_client", lambda refresh_if_needed=True: client)
    monkeypatch.setattr(instagram, "get_r2", lambda: object())
    monkeypatch.setattr(instagram, "test_r2_connection", lambda config: calls.append("r2"))

    instagram.validate_publish_connections()

    assert calls == ["instagram", "r2"]


def test_publish_preflight_returns_actionable_instagram_error(monkeypatch):
    def fail_instagram(refresh_if_needed=True):
        raise RuntimeError("secret provider detail")

    monkeypatch.setattr(instagram, "get_connected_client", fail_instagram)

    with pytest.raises(HTTPException) as caught:
        instagram.validate_publish_connections()

    assert caught.value.status_code == 409
    assert "Instagram / R2 設定" in caught.value.detail
    assert "secret provider detail" not in caught.value.detail


def test_publish_preflight_returns_actionable_r2_error(monkeypatch):
    monkeypatch.setattr(
        instagram,
        "get_connected_client",
        lambda refresh_if_needed=True: SimpleNamespace(profile=lambda: {}),
    )
    monkeypatch.setattr(instagram, "get_r2", lambda: object())
    monkeypatch.setattr(
        instagram,
        "test_r2_connection",
        lambda config: (_ for _ in ()).throw(RuntimeError("secret storage detail")),
    )

    with pytest.raises(HTTPException) as caught:
        instagram.validate_publish_connections()

    assert caught.value.status_code == 409
    assert "測試 R2" in caught.value.detail
    assert "secret storage detail" not in caught.value.detail


def test_publish_job_is_not_prepared_when_preflight_fails(monkeypatch):
    prepared = []
    monkeypatch.setattr(instagram, "cfg", lambda key: "configured-resource")
    monkeypatch.setattr(
        instagram,
        "validate_publish_connections",
        lambda: (_ for _ in ()).throw(HTTPException(status_code=409, detail="not ready")),
    )
    monkeypatch.setattr(instagram, "prepare_job", lambda **kwargs: prepared.append(kwargs))
    payload = instagram.PublishInput(
        worksheet_name="Insta Reels",
        caption_column="Reels Content",
        team="Team A",
        assignments=[instagram.Assignment(file_id="drive-1", person="Alice")],
    )

    with pytest.raises(HTTPException) as caught:
        instagram.create_publish_job(payload, creds=object())

    assert caught.value.status_code == 409
    assert prepared == []
