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
        [
            {
                "platform": platform,
                "operation": operation,
                "queue_lane": platform,
                "video_id": "video-1",
                "video_title": "測試影片",
                "payload": payload or {},
                "checkpoint": checkpoint or {},
            }
        ],
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

    result = process_instagram_reel_task(
        task_id, credentials=object(), client=NoPublishClient(), r2=object(), repository=repo
    )

    assert result["status"] == "succeeded"
    assert repo.get_task_internal(task_id)["checkpoint"]["media_id"] == "media-1"
    assert len(deleted) == 1


def test_instagram_batch_handler_batches_meta_phases_in_sequence(monkeypatch, tmp_path):
    repo = TaskRepository(Database(tmp_path / "creator_tools.db"))
    created = repo.create_batch_and_tasks(
        {"platform": "instagram", "operation": "instagram.reels_publish", "failure_policy": "pause_remaining_in_batch"},
        [
            {
                "platform": "instagram",
                "operation": "instagram.reels_publish",
                "queue_lane": "instagram",
                "sequence_in_batch": 1,
                "video_id": "file-1",
                "video_title": "one.mp4",
                "payload": {"file_id": "file-1", "caption": "caption A", "source_folder_id": "source"},
            },
            {
                "platform": "instagram",
                "operation": "instagram.reels_publish",
                "queue_lane": "instagram",
                "sequence_in_batch": 2,
                "video_id": "file-2",
                "video_title": "two.mp4",
                "payload": {"file_id": "file-2", "caption": "caption B", "source_folder_id": "source"},
            },
        ],
    )
    claimed = repo.claim_batch("instagram")
    assert [task["id"] for task in claimed] == [task["id"] for task in created["tasks"]]

    monkeypatch.setattr("backend.app.services.r2_service.ensure_lifecycle", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "backend.app.services.drive_service.download_drive_file",
        lambda credentials, file_id, destination: destination.write_bytes(file_id.encode()),
    )
    monkeypatch.setattr("backend.app.services.instagram_publish_service.validate_reel_file", lambda path: {"size_bytes": path.stat().st_size})
    monkeypatch.setattr("backend.app.services.r2_service.upload_public_file", lambda *args, **kwargs: f"https://cdn.example/{args[2]}")
    monkeypatch.setattr(task_handlers, "_instagram_cleanup", lambda *args, **kwargs: [])

    class BatchClient:
        def __init__(self):
            self.created = []
            self.waited = []
            self.published = []

        def create_reel_containers(self, reels):
            self.created.append(reels)
            return [f"container-{index}" for index, _ in enumerate(reels, start=1)]

        def wait_for_containers(self, creation_ids):
            self.waited.append(list(creation_ids))

        def publish_containers(self, creation_ids):
            self.published.append(list(creation_ids))
            return [f"media-{creation_id}" for creation_id in creation_ids]

    client = BatchClient()
    results = task_handlers.process_instagram_reel_tasks(
        claimed,
        credentials=object(),
        client=client,
        r2=object(),
        repository=repo,
    )

    assert [result["status"] for result in results] == ["succeeded", "succeeded"]
    assert [[reel["caption"] for reel in call] for call in client.created] == [["caption A", "caption B"]]
    assert client.waited == [["container-1", "container-2"]]
    assert client.published == [["container-1", "container-2"]]


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
    monkeypatch.setattr(
        task_handlers, "update_single_video_metadata", lambda *args, **kwargs: update_calls.append(args)
    )

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
    monkeypatch.setattr(
        task_handlers, "set_video_public", lambda *args, **kwargs: set_calls.append(args) or {"id": "video-1"}
    )

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
