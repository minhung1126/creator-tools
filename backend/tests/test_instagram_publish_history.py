import pytest
from fastapi import HTTPException

from backend.app.api import instagram as instagram_api
from backend.app.core.database import Database
from backend.app.core.task_repository import TaskRepository


def _repository_with_published_reel(tmp_path):
    repository = TaskRepository(Database(tmp_path / "creator_tools.db"))
    created = repository.create_batch_and_tasks(
        {
            "platform": "instagram",
            "operation": "instagram.reels_publish",
            "failure_policy": "pause_remaining_in_batch",
        },
        [
            {
                "platform": "instagram",
                "operation": "instagram.reels_publish",
                "sequence_in_batch": 1,
                "video_id": "file-1",
                "video_title": "reel.mp4",
                "status": "succeeded",
                "stage": "completed",
                "progress_percent": 100,
                "payload": {
                    "source_folder_id": "source-folder",
                    "published_folder_id": "published-folder",
                    "person": "A",
                    "share_to_feed": True,
                },
                "checkpoint": {
                    "media_id": "media-1",
                    "drive_moved": True,
                    "published_folder_id": "published-folder",
                },
            }
        ],
    )
    return repository, created["batch"]["id"]


def test_publish_history_api_restores_drive_and_deletes_record(monkeypatch, tmp_path):
    repository, batch_id = _repository_with_published_reel(tmp_path)
    moves = []
    monkeypatch.setattr(instagram_api, "task_repository", repository)
    monkeypatch.setattr(instagram_api, "move_drive_file_to_folder", lambda *args: moves.append(args))

    result = instagram_api.delete_publish_history(batch_id, "file-1", object())

    assert result["drive_restored"] is True
    assert moves[0][1:] == ("file-1", "published-folder", "source-folder")
    assert repository.list_instagram_history() == []


def test_publish_history_api_keeps_record_when_drive_restore_fails(monkeypatch, tmp_path):
    repository, batch_id = _repository_with_published_reel(tmp_path)
    monkeypatch.setattr(instagram_api, "task_repository", repository)
    monkeypatch.setattr(
        instagram_api,
        "move_drive_file_to_folder",
        lambda *args: (_ for _ in ()).throw(RuntimeError("denied")),
    )

    with pytest.raises(HTTPException) as error:
        instagram_api.delete_publish_history(batch_id, "file-1", object())

    assert error.value.status_code == 502
    assert len(repository.list_instagram_history()) == 1


def test_publish_history_uses_only_sqlite_and_release_removes_reservation(monkeypatch, tmp_path):
    repository, batch_id = _repository_with_published_reel(tmp_path)
    monkeypatch.setattr(instagram_api, "task_repository", repository)
    monkeypatch.setattr(instagram_api, "move_drive_file_to_folder", lambda *args: None)

    history = instagram_api.get_publish_history(object())
    assert history["total"] == 1

    deleted = instagram_api.delete_publish_history(batch_id, "file-1", object())

    assert deleted["drive_restored"] is True
    assert repository.list_instagram_history() == []
    assert repository.find_instagram_record("source-folder", "file-1") is None


def test_clear_publish_history_restores_drive_and_releases_all_records(monkeypatch, tmp_path):
    repository, _ = _repository_with_published_reel(tmp_path)
    moves = []
    monkeypatch.setattr(instagram_api, "task_repository", repository)
    monkeypatch.setattr(instagram_api, "move_drive_file_to_folder", lambda *args: moves.append(args))

    result = instagram_api.clear_publish_history(object())

    assert result["total_count"] == 1
    assert result["deleted_count"] == 1
    assert result["failed_count"] == 0
    assert result["drive_restored_count"] == 1
    assert moves[0][1:] == ("file-1", "published-folder", "source-folder")
    assert repository.list_instagram_history() == []
