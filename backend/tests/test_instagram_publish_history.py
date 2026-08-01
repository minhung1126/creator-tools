import pytest
from fastapi import HTTPException

from backend.app.api import instagram as instagram_api
from backend.app.core.instagram_publish_store import InstagramPublishStore


def _published_job():
    return {
        "source_folder_id": "source-folder",
        "published_folder_id": "published-folder",
        "status": "completed",
        "items": [
            {
                "file_id": "file-1",
                "file_name": "reel.mp4",
                "status": "published",
                "media_id": "media-1",
                "drive_moved": True,
                "published_folder_id": "published-folder",
            }
        ],
    }


def test_publish_history_api_restores_drive_and_deletes_record(monkeypatch, tmp_path):
    store = InstagramPublishStore(tmp_path / "jobs.json")
    created = store.create(_published_job())
    moves = []
    monkeypatch.setattr(instagram_api, "instagram_publish_store", store)
    monkeypatch.setattr(instagram_api, "move_drive_file_to_folder", lambda *args: moves.append(args))

    result = instagram_api.delete_publish_history(created["id"], "file-1", object())

    assert result["drive_restored"] is True
    assert moves[0][1:] == ("file-1", "published-folder", "source-folder")
    assert store.list_history() == []


def test_publish_history_api_keeps_record_when_drive_restore_fails(monkeypatch, tmp_path):
    store = InstagramPublishStore(tmp_path / "jobs.json")
    created = store.create(_published_job())
    monkeypatch.setattr(instagram_api, "instagram_publish_store", store)
    monkeypatch.setattr(instagram_api, "move_drive_file_to_folder", lambda *args: (_ for _ in ()).throw(RuntimeError("denied")))

    with pytest.raises(HTTPException) as error:
        instagram_api.delete_publish_history(created["id"], "file-1", object())

    assert error.value.status_code == 502
    assert len(store.list_history()) == 1
