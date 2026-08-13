from backend.app.core.account_state_store import MISSING, AccountStateStore


def test_account_state_isolated_by_google_subject(tmp_path):
    store = AccountStateStore(tmp_path / "account-state.json")
    store.ensure_account("google-user-a", {})
    store.ensure_account("google-user-b", {})

    store.set_setting("google-user-a", "default_spreadsheet_id", "sheet-a")
    store.set_work_state("google-user-a", "navigation", {"activeTab": "sheet_copy"})

    assert store.get_setting("google-user-a", "default_spreadsheet_id") == "sheet-a"
    assert store.get_setting("google-user-b", "default_spreadsheet_id") is MISSING
    assert store.get_work_state("google-user-a") == {"navigation": {"activeTab": "sheet_copy"}}
    assert store.get_work_state("google-user-b") == {}


def test_legacy_runtime_settings_are_migrated_once(tmp_path):
    store = AccountStateStore(tmp_path / "account-state.json")
    store.ensure_account("first-user", {"default_playlist_id": "legacy-playlist"})
    store.ensure_account("second-user", {"default_playlist_id": "should-not-leak"})

    assert store.get_setting("first-user", "default_playlist_id") == "legacy-playlist"
    assert store.get_setting("second-user", "default_playlist_id") is MISSING
