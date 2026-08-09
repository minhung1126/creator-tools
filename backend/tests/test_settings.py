from types import SimpleNamespace

from backend.app.api import settings as settings_api


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

    assert result == {
        "default_playlist_id": "youtube-playlist",
        "youtube_general_quota_limit": 10000,
        "youtube_quota_safety_buffer_units": 1000,
    }


def test_team_person_filter_normalizes_and_persists_as_one_shared_record(monkeypatch):
    updates = []
    monkeypatch.setattr(settings_api.runtime_config, "set", lambda key, value: updates.append((key, value)))

    result = settings_api.update_team_person_filter(
        settings_api.TeamPersonFilterModel(team=" 團體 ", selected_people=[" 甲 ", "甲", ""]),
        SimpleNamespace(),
    )

    assert updates == [("shared_team_person_filter", {"team": "團體", "selected_people": ["甲"]})]
    assert result == {"configured": True, "team": "團體", "selected_people": ["甲"]}


def test_team_person_filter_requires_the_shared_record(monkeypatch):
    def read_config(key, default=""):
        return {}.get(key, default)

    monkeypatch.setattr(settings_api.runtime_config, "get", read_config)

    assert settings_api.get_team_person_filter(SimpleNamespace()) == {
        "configured": False,
        "team": "",
        "selected_people": [],
    }


def test_youtube_draft_response_uses_the_current_config_shape(monkeypatch):
    monkeypatch.setattr(
        settings_api.runtime_config,
        "get",
        lambda key, default="": {
            "youtube_draft_video_config": {
                "spreadsheet_id": "sheet",
                "playlist_id": "playlist",
                "worksheet_name": "工作表",
                "title_column": "標題",
                "description_column": "描述",
            }
        }.get(key, default),
    )

    result = settings_api.get_youtube_draft_settings(SimpleNamespace())

    assert result == {
        "video": {
            "spreadsheet_id": "sheet",
            "playlist_id": "playlist",
            "worksheet_name": "工作表",
            "title_column": "標題",
            "description_column": "描述",
        },
        "shorts": {},
    }
