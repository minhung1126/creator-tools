from backend.app.core.database import Database
from backend.app.core.task_repository import TaskRepository
from backend.app.services import task_handlers
from backend.app.services.task_handlers import (
    process_instagram_reel_task,
    process_youtube_metadata_task,
    process_youtube_publish_cleanup_task,
)


def make_repo(tmp_path):
    return TaskRepository(Database(tmp_path / "creator_tools.db"))


def create_task(repo, *, platform, operation, payload=None, checkpoint=None):
    created = repo.create_batch_and_tasks(
        {"platform": platform, "operation": operation, "failure_policy": "continue"},
        [{
            "platform": platform,
            "operation": operation,
            "queue_lane": platform,
            "video_id": "video-1",
            "video_title": "測試影片",
            "payload": payload or {},
            "checkpoint": checkpoint or {},
        }],
    )
    task = repo.claim_next(platform)
    assert task["id"] == created["tasks"][0]["id"]
    return task["id"]


def test_instagram_media_checkpoint_never_calls_publish_again(monkeypatch, tmp_path):
    repo = make_repo(tmp_path)
    task_id = create_task(
        repo,
        platform="instagram",
        operation="instagram.reels_publish",
        payload={"file_id": "video-1", "source_folder_id": "source"},
        checkpoint={"media_id": "media-1", "object_key": "r2-key", "drive_moved": True},
    )
    deleted = []
    monkeypatch.setattr(task_handlers, "ensure_lifecycle", lambda *args, **kwargs: None, raising=False)
    monkeypatch.setattr("backend.app.services.r2_service.ensure_lifecycle", lambda *args, **kwargs: None)
    monkeypatch.setattr("backend.app.services.r2_service.delete_public_file", lambda *args: deleted.append(args))

    class NoPublishClient:
        def publish_container(self, *_args):
            raise AssertionError("published media must not be published again")

    result = process_instagram_reel_task(task_id, credentials=object(), client=NoPublishClient(), r2=object(), repository=repo)

    assert result["status"] == "succeeded"
    assert repo.get_task_internal(task_id)["checkpoint"]["media_id"] == "media-1"
    assert len(deleted) == 1


def test_youtube_metadata_cancel_before_update_stops_before_external_work(monkeypatch, tmp_path):
    repo = make_repo(tmp_path)
    task_id = create_task(
        repo,
        platform="youtube",
        operation="youtube.metadata_update",
        payload={"new_title": "新標題", "new_description": "新描述"},
    )
    repo.request_cancel(task_id)
    fetch_calls = []
    update_calls = []
    monkeypatch.setattr(task_handlers, "fetch_video_details", lambda *args: fetch_calls.append(args) or [])
    monkeypatch.setattr(task_handlers, "update_single_video_metadata", lambda *args, **kwargs: update_calls.append(args))

    result = process_youtube_metadata_task(task_id, credentials=object(), repository=repo)

    assert result["status"] == "canceled"
    assert fetch_calls == []
    assert update_calls == []


def test_youtube_public_checkpoint_retries_cleanup_without_republishing(monkeypatch, tmp_path):
    repo = make_repo(tmp_path)
    task_id = create_task(
        repo,
        platform="youtube",
        operation="youtube.publish_cleanup",
        payload={"playlist_item_id": "playlist-item"},
    )
    set_calls = []
    remove_calls = []
    monkeypatch.setattr(
        task_handlers,
        "fetch_video_details",
        lambda *_args: [{"id": "video-1", "snippet": {}, "status": {"privacyStatus": "private"}}],
    )
    monkeypatch.setattr(task_handlers, "set_video_public", lambda *args, **kwargs: set_calls.append(args) or {"id": "video-1"})

    def fail_cleanup(*args, **kwargs):
        remove_calls.append(args)
        raise RuntimeError("temporary playlist failure")

    monkeypatch.setattr(task_handlers, "remove_playlist_item", fail_cleanup)
    first = process_youtube_publish_cleanup_task(task_id, credentials=object(), repository=repo)
    assert first["status"] == "succeeded_with_warnings"
    assert repo.get_task_internal(task_id)["checkpoint"]["privacy_updated_at"]

    retried = repo.retry_task(task_id)
    assert retried["checkpoint"]["privacy_updated_at"]
    repo.claim_next("youtube")
    monkeypatch.setattr(task_handlers, "remove_playlist_item", lambda *args, **kwargs: remove_calls.append(args) or {})
    second = process_youtube_publish_cleanup_task(task_id, credentials=object(), repository=repo)

    assert second["status"] == "succeeded"
    assert len(set_calls) == 1
    assert len(remove_calls) == 2
