from types import SimpleNamespace

from backend.app.api import settings as settings_api


def test_legacy_settings_update_can_update_only_one_scope(monkeypatch):
    updates = []
    monkeypatch.setattr(settings_api.runtime_config, "update", lambda data: updates.append(data))
    monkeypatch.setattr(
        settings_api,
        "get_system_settings",
        lambda creds: {"default_playlist_id": "youtube-playlist"},
    )

    result = settings_api.update_system_settings(
        settings_api.ResourceSettingsModel(default_playlist_id="youtube-playlist"),
        SimpleNamespace(),
    )

    assert updates == [{"default_playlist_id": "youtube-playlist"}]
    assert result["settings"]["default_playlist_id"] == "youtube-playlist"


def test_scoped_settings_update_does_not_touch_other_resource(monkeypatch):
    updates = []
    monkeypatch.setattr(settings_api.runtime_config, "update", lambda data: updates.append(data))
    monkeypatch.setattr(
        settings_api.runtime_config,
        "get",
        lambda key, default="": {"default_spreadsheet_id": "shared-sheet"}.get(key, default),
    )

    result = settings_api.update_shared_settings(
        settings_api.SharedResourceSettingsModel(default_spreadsheet_id="  shared-sheet  "),
        SimpleNamespace(),
    )

    assert updates == [{"default_spreadsheet_id": "shared-sheet"}]
    assert result["settings"] == {"default_spreadsheet_id": "shared-sheet"}


def test_youtube_settings_returns_only_youtube_resource(monkeypatch):
    monkeypatch.setattr(
        settings_api.runtime_config,
        "get",
        lambda key, default="": {"default_playlist_id": "youtube-playlist"}.get(key, default),
    )

    result = settings_api.get_youtube_settings(SimpleNamespace())

    assert result == {"default_playlist_id": "youtube-playlist"}
