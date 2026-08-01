import json

import pytest
from fastapi import HTTPException

from backend.app.api import instagram as instagram_api
from backend.app.core.database import Database
from backend.app.core.instagram_publish_store import InstagramPublishStore
from backend.app.core.task_repository import TaskRepository, migrate_legacy_instagram_jobs


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


def test_migrated_history_is_not_duplicated_and_delete_releases_sqlite_reservation(monkeypatch, tmp_path):
    store = InstagramPublishStore(tmp_path / "jobs.json")
    created = store.create(_published_job())
    legacy_path = tmp_path / "instagram_publish_jobs.json"
    legacy_path.write_text(
        json.dumps({"version": 1, "jobs": {created["id"]: store.get(created["id"])}}),
        encoding="utf-8",
    )
    repo = TaskRepository(Database(tmp_path / "creator_tools.db"))
    assert migrate_legacy_instagram_jobs(repository=repo, legacy_path=legacy_path) == 1
    monkeypatch.setattr(instagram_api, "instagram_publish_store", store)
    monkeypatch.setattr(instagram_api, "task_repository", repo)
    monkeypatch.setattr(instagram_api, "move_drive_file_to_folder", lambda *args: None)

    history = instagram_api.get_publish_history(object())
    assert history["total"] == 1

    deleted = instagram_api.delete_publish_history(created["id"], "file-1", object())

    assert deleted["drive_restored"] is True
    assert repo.list_instagram_history() == []
    assert repo.find_instagram_record("source-folder", "file-1") is None
