import json

import pytest

from backend.app.core.database import Database
from backend.app.core.notification_repository import NotificationRepository
from backend.app.core.task_repository import TaskRepository, migrate_legacy_instagram_jobs
from backend.app.services.task_context import TaskCancellationRequested, TaskContext


def make_repo(tmp_path):
    return TaskRepository(Database(tmp_path / "creator_tools.db"))


def make_specs(count, platform="youtube", operation="youtube.metadata_update", status="queued"):
    return [
        {
            "platform": platform,
            "operation": operation,
            "queue_lane": platform,
            "sequence_in_batch": index,
            "video_id": f"video-{index}",
            "video_title": f"Video {index}",
            "status": status,
            "stage": "queued" if status == "queued" else "skipped",
            "progress_percent": 0 if status == "queued" else 100,
            "payload": {"new_title": "Safe title", "new_description": "secret body", "token": "must not persist"},
        }
        for index in range(1, count + 1)
    ]


def test_atomic_batch_enqueue_assigns_contiguous_lane_sequences(tmp_path):
    repo = make_repo(tmp_path)
    created = repo.create_batch_and_tasks(
        {"platform": "youtube", "operation": "youtube.metadata_update", "failure_policy": "continue"},
        make_specs(5),
    )
    assert created["created"] is True
    assert len(created["tasks"]) == 5
    assert [task["queue_sequence"] for task in created["tasks"]] == [1, 2, 3, 4, 5]
    assert len({task["id"] for task in created["tasks"]}) == 5


def test_list_tasks_shows_oldest_submitted_task_first(tmp_path):
    repo = make_repo(tmp_path)
    created = repo.create_batch_and_tasks(
        {"platform": "youtube", "operation": "youtube.metadata_update", "failure_policy": "continue"},
        [
            {
                **make_specs(1)[0],
                "id": "latest-task",
                "created_at": "2026-01-01T00:00:03+00:00",
                "sequence_in_batch": 2,
            },
            {
                **make_specs(1)[0],
                "id": "oldest-task",
                "created_at": "2026-01-01T00:00:01+00:00",
                "sequence_in_batch": 1,
            },
        ],
    )

    items, total = repo.list_tasks(limit=100)

    assert total == 2
    assert [task["id"] for task in items] == ["oldest-task", "latest-task"]
    assert [task["id"] for task in repo.get_batch_internal(created["batch"]["id"])["tasks"]] == [
        "oldest-task",
        "latest-task",
    ]


def test_list_tasks_can_poll_most_recent_updates(tmp_path):
    repo = make_repo(tmp_path)
    created = repo.create_batch_and_tasks(
        {"platform": "youtube", "operation": "youtube.metadata_update", "failure_policy": "continue"},
        make_specs(2),
    )
    repo.update_task(created["tasks"][0]["id"], stage="updating_metadata")

    items, _ = repo.list_tasks(limit=1, sort="updated_desc")

    assert [task["id"] for task in items] == [created["tasks"][0]["id"]]


def test_retry_batch_requeues_and_claims_tasks_in_batch_order(tmp_path):
    repo = make_repo(tmp_path)
    created = repo.create_batch_and_tasks(
        {"platform": "youtube", "operation": "youtube.metadata_update", "failure_policy": "continue"},
        [
            {
                **make_specs(1)[0],
                "id": "retry-third",
                "sequence_in_batch": 3,
                "status": "failed",
                "stage": "failed",
                "retryable": True,
            },
            {
                **make_specs(1)[0],
                "id": "retry-first",
                "sequence_in_batch": 1,
                "status": "failed",
                "stage": "failed",
                "retryable": True,
            },
            {
                **make_specs(1)[0],
                "id": "retry-second",
                "sequence_in_batch": 2,
                "status": "failed",
                "stage": "failed",
                "retryable": True,
            },
        ],
    )

    retried = repo.retry_batch(created["batch"]["id"])

    assert [task["id"] for task in retried] == ["retry-first", "retry-second", "retry-third"]
    assert [task["queue_sequence"] for task in retried] == [4, 5, 6]
    assert [repo.claim_next("youtube")["id"] for _ in range(3)] == [
        "retry-first",
        "retry-second",
        "retry-third",
    ]


def test_lanes_are_independent_and_claim_keeps_order(tmp_path):
    repo = make_repo(tmp_path)
    instagram = repo.create_batch_and_tasks(
        {"platform": "instagram", "operation": "instagram.reels_publish", "failure_policy": "pause_remaining_in_batch"},
        make_specs(2, "instagram", "instagram.reels_publish"),
    )
    youtube = repo.create_batch_and_tasks(
        {"platform": "youtube", "operation": "youtube.metadata_update", "failure_policy": "continue"},
        make_specs(1),
    )
    first_instagram = repo.claim_next("instagram")
    first_youtube = repo.claim_next("youtube")
    assert first_instagram["id"] == instagram["tasks"][0]["id"]
    assert first_youtube["id"] == youtube["tasks"][0]["id"]
    assert repo.claim_next("instagram")["id"] == instagram["tasks"][1]["id"]


def test_instagram_batch_claim_is_bounded_and_preserves_remaining_order(tmp_path):
    repo = make_repo(tmp_path)
    created = repo.create_batch_and_tasks(
        {"platform": "instagram", "operation": "instagram.reels_publish", "failure_policy": "pause_remaining_in_batch"},
        make_specs(55, "instagram", "instagram.reels_publish"),
    )

    first_claim = repo.claim_batch("instagram", limit=50)

    assert len(first_claim) == 50
    assert [task["id"] for task in first_claim] == [task["id"] for task in created["tasks"][:50]]
    assert [task["status"] for task in repo.get_batch_internal(created["batch"]["id"])["tasks"][-5:]] == ["queued"] * 5


def test_batch_failure_does_not_overwrite_a_claimed_sibling_cancellation(tmp_path):
    repo = make_repo(tmp_path)
    created = repo.create_batch_and_tasks(
        {"platform": "instagram", "operation": "instagram.reels_publish", "failure_policy": "pause_remaining_in_batch"},
        make_specs(3, "instagram", "instagram.reels_publish"),
    )
    claimed = repo.claim_batch("instagram")
    repo.request_cancel(claimed[1]["id"])

    repo.pause_or_cancel_claimed_tasks(created["batch"]["id"], after_sequence=1, reason="前一支失敗")

    tasks = repo.get_batch_internal(created["batch"]["id"])["tasks"]
    assert [task["status"] for task in tasks] == ["running", "canceled", "paused"]


def test_queued_cancel_is_never_claimed_and_running_cancel_is_cooperative(tmp_path):
    repo = make_repo(tmp_path)
    created = repo.create_batch_and_tasks(
        {"platform": "youtube", "operation": "youtube.metadata_update", "failure_policy": "continue"},
        make_specs(2),
    )
    canceled = repo.request_cancel(created["tasks"][0]["id"])
    assert canceled["status"] == "canceled"
    assert repo.claim_next("youtube")["id"] == created["tasks"][1]["id"]
    running = repo.request_cancel(created["tasks"][1]["id"])
    assert running["status"] == "cancel_requested"
    with pytest.raises(TaskCancellationRequested):
        TaskContext(running["id"], repo).raise_if_cancel_requested()


def test_failure_policy_pauses_only_later_tasks(tmp_path):
    repo = make_repo(tmp_path)
    created = repo.create_batch_and_tasks(
        {"platform": "instagram", "operation": "instagram.reels_publish", "failure_policy": "pause_remaining_in_batch"},
        make_specs(3, "instagram", "instagram.reels_publish"),
    )
    failed = repo.claim_next("instagram")
    repo.update_task(failed["id"], status="failed", stage="failed", error="Meta failed", retryable=True)
    repo.pause_remaining_tasks(created["batch"]["id"], after_sequence=1, reason="前一支失敗")
    statuses = [task["status"] for task in repo.get_batch_internal(created["batch"]["id"])["tasks"]]
    assert statuses == ["failed", "paused", "paused"]
    assert repo.activity_summary()["tasks"]["paused"] == 2


def test_cancel_all_covers_both_lanes_and_is_idempotent(tmp_path):
    repo = make_repo(tmp_path)
    repo.create_batch_and_tasks(
        {"platform": "instagram", "operation": "instagram.reels_publish", "failure_policy": "pause_remaining_in_batch"},
        make_specs(2, "instagram", "instagram.reels_publish"),
    )
    repo.create_batch_and_tasks(
        {"platform": "youtube", "operation": "youtube.metadata_update", "failure_policy": "continue"},
        make_specs(2),
    )
    first = repo.cancel_all()
    second = repo.cancel_all()
    assert first["requested_count"] == 4
    assert first["canceled_immediately_count"] == 4
    assert second["requested_count"] == 0
    assert repo.activity_summary()["tasks"]["canceled"] == 4


def test_cancel_all_does_not_repeat_a_running_cancel_request(tmp_path):
    repo = make_repo(tmp_path)
    repo.create_batch_and_tasks(
        {"platform": "youtube", "operation": "youtube.metadata_update", "failure_policy": "continue"},
        make_specs(1),
    )
    repo.claim_next("youtube")
    first = repo.cancel_all()
    second = repo.cancel_all()
    assert first["requested_count"] == 1
    assert first["cancel_requested_count"] == 1
    assert second["requested_count"] == 1
    assert second["cancel_requested_count"] == 1
    assert NotificationRepository(repo.db).unread_count() == 1


def test_retry_preserves_checkpoint_but_get_task_is_a_safe_public_dto(tmp_path):
    repo = make_repo(tmp_path)
    created = repo.create_batch_and_tasks(
        {"platform": "instagram", "operation": "instagram.reels_publish", "failure_policy": "pause_remaining_in_batch"},
        [
            {
                **make_specs(1, "instagram", "instagram.reels_publish")[0],
                "payload": {"caption": "private caption", "object_key": "private-key"},
                "checkpoint": {
                    "media_id": "media-1",
                    "object_key": "private-key",
                    "drive_moved": False,
                    "r2_delete_error": "denied",
                },
            }
        ],
    )
    task_id = created["tasks"][0]["id"]
    repo.update_task(task_id, status="succeeded_with_warnings", stage="cleaning_r2", error="denied", retryable=True)
    public = repo.get_task(task_id)
    assert "payload" not in public and "checkpoint" not in public and "result" not in public
    assert "caption" not in json.dumps(public)
    retried = repo.retry_task(task_id)
    assert retried["status"] == "queued"
    assert retried["attempt"] == 2
    assert retried["checkpoint"]["media_id"] == "media-1"


def test_all_skipped_batch_gets_one_summary_notification(tmp_path):
    repo = make_repo(tmp_path)
    repo.create_batch_and_tasks(
        {"platform": "youtube", "operation": "youtube.metadata_update", "failure_policy": "continue"},
        make_specs(1, status="skipped"),
    )
    items, total = NotificationRepository(repo.db).list()
    assert total == 1
    assert items[0]["type"] == "batch_completed"


def test_cancel_instagram_reservations_releases_only_matching_old_tasks(tmp_path):
    repo = make_repo(tmp_path)
    old = repo.create_batch_and_tasks(
        {"platform": "instagram", "operation": "instagram.reels_publish"},
        [
            {
                **make_specs(1, "instagram", "instagram.reels_publish")[0],
                "id": "old-queued",
                "video_id": "drive-1",
                "payload": {"source_folder_id": "source-folder"},
            },
            {
                **make_specs(1, "instagram", "instagram.reels_publish")[0],
                "id": "other-folder",
                "sequence_in_batch": 2,
                "video_id": "drive-1",
                "payload": {"source_folder_id": "other-folder"},
            },
        ],
    )
    running = repo.create_batch_and_tasks(
        {"platform": "instagram", "operation": "instagram.reels_publish"},
        [
            {
                **make_specs(1, "instagram", "instagram.reels_publish")[0],
                "id": "old-running",
                "video_id": "drive-2",
                "payload": {"source_folder_id": "source-folder"},
            }
        ],
    )
    repo.claim_next("instagram")
    assert repo.get_task_internal("old-queued")["status"] == "running"

    result = repo.cancel_instagram_reservations(
        "source-folder",
        ["drive-1", "drive-2"],
        exclude_batch_id="current-skipped-batch",
    )

    assert result["requested_count"] == 2
    assert result["cancel_requested_count"] == 1
    assert result["canceled_immediately_count"] == 1
    assert repo.get_task_internal("old-queued")["status"] == "cancel_requested"
    assert repo.get_task_internal("old-running")["status"] == "canceled"
    assert repo.get_task_internal("other-folder")["status"] == "queued"
    assert old["batch"]["id"] in result["batch_ids"]
    assert running["batch"]["id"] in result["batch_ids"]


def test_notification_event_key_is_deduplicated(tmp_path):
    repo = make_repo(tmp_path)
    notifications = NotificationRepository(repo.db)
    first = notifications.create(
        event_key="same-event",
        notification_type="task_failed",
        severity="error",
        title="Failure",
        message="Safe failure",
    )
    second = notifications.create(
        event_key="same-event",
        notification_type="task_failed",
        severity="error",
        title="Duplicate",
        message="Should be ignored",
    )
    assert first["id"] == second["id"]
    assert notifications.unread_count() == 1
    assert notifications.mark_all_read() == 1


def test_restart_pauses_interrupted_task_and_keeps_checkpoint(tmp_path):
    repo = make_repo(tmp_path)
    repo.create_batch_and_tasks(
        {"platform": "youtube", "operation": "youtube.publish_cleanup", "failure_policy": "pause_remaining_in_batch"},
        [
            {
                **make_specs(1, "youtube", "youtube.publish_cleanup")[0],
                "payload": {"playlist_item_id": "playlist-item"},
                "checkpoint": {"privacy_updated_at": "2026-01-01T00:00:00+00:00"},
            }
        ],
    )
    claimed = repo.claim_next("youtube")
    repo.request_cancel(claimed["id"])
    assert repo.recover_after_restart() == 1
    recovered = repo.get_task_internal(claimed["id"])
    assert recovered["status"] == "paused"
    assert recovered["checkpoint"]["privacy_updated_at"] == "2026-01-01T00:00:00+00:00"
    assert NotificationRepository(repo.db).unread_count() == 1


def test_legacy_migration_is_idempotent_and_has_no_unread_history_notice(tmp_path):
    legacy_path = tmp_path / "instagram_publish_jobs.json"
    legacy_path.write_text(
        json.dumps(
            {
                "version": 1,
                "jobs": {
                    "legacy-job": {
                        "status": "completed",
                        "items": [
                            {
                                "sequence": 1,
                                "file_id": "drive-1",
                                "file_name": "one.mp4",
                                "status": "published",
                                "media_id": "media-1",
                            }
                        ],
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    repo = make_repo(tmp_path)
    assert migrate_legacy_instagram_jobs(repository=repo, legacy_path=legacy_path) == 1
    assert migrate_legacy_instagram_jobs(repository=repo, legacy_path=legacy_path) == 0
    batch = repo.list_batches()[0][0]
    assert batch["legacy_job_id"] == "legacy-job"
    assert repo.get_batch_internal(batch["id"])["tasks"][0]["legacy_item_sequence"] == 1
    assert NotificationRepository(repo.db).unread_count() == 0
