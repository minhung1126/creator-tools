from types import SimpleNamespace

from backend.app.core.database import Database
from backend.app.core.task_repository import TaskRepository
from backend.app.core.youtube_quota_limiter import YouTubeQuotaLimiter
from backend.app.services import task_handlers
from backend.app.services.youtube_errors import YouTubeQuotaUnavailable


def make_repo(tmp_path):
    db = Database(tmp_path / "creator_tools.db")
    return TaskRepository(db, youtube_limiter=YouTubeQuotaLimiter(db, configured_limit=10000, safety_buffer_units=1000))


def make_task(repo, operation="youtube.metadata_update", count=1):
    created = repo.create_batch_and_tasks(
        {"platform": "youtube", "operation": operation, "failure_policy": "continue"},
        [
            {
                "platform": "youtube",
                "operation": operation,
                "queue_lane": "youtube",
                "sequence_in_batch": index,
                "video_id": f"video-{index}",
                "payload": {"playlist_item_id": f"playlist-{index}"},
            }
            for index in range(1, count + 1)
        ],
    )
    return created


def test_bulk_youtube_defer_creates_one_notification(tmp_path):
    repo = make_repo(tmp_path)
    created = make_task(repo, count=3)
    first = repo.claim_next("youtube")
    usage = repo.youtube_limiter.get_usage()
    reset = usage["reset_at"]

    repo.defer_youtube_quota_task(
        first["id"],
        next_attempt_at=reset,
        error="Google 已回報今日 YouTube API 配額用完。",
    )
    repo.defer_youtube_lane(
        next_attempt_at=reset,
        quota_date=usage["quota_date"],
        state="confirmed_exhausted",
        exclude_task_id=first["id"],
    )

    tasks = repo.get_batch_internal(created["batch"]["id"])["tasks"]
    assert [task["stage"] for task in tasks] == ["waiting_youtube_quota"] * 3
    assert all(task["status"] == "queued" for task in tasks)
    with repo.db.connection() as connection:
        notifications = connection.execute(
            "SELECT event_key, type FROM notifications WHERE type='youtube_quota_exhausted'"
        ).fetchall()
    assert len(notifications) == 1
    assert notifications[0]["event_key"] == f"youtube-quota:{usage['quota_date']}:general:confirmed_exhausted"


def test_manual_retry_cannot_bypass_youtube_breaker(tmp_path):
    repo = make_repo(tmp_path)
    ledger = repo.youtube_limiter

    class QuotaRequest:
        def execute(self):
            class QuotaHttpError(RuntimeError):
                resp = SimpleNamespace(status=403)
                content = b'{"error":{"errors":[{"reason":"quotaExceeded"}]}}'

            raise QuotaHttpError("quotaExceeded")

    # Use a request-shaped exception directly so the ledger records the
    # confirmed state without involving the task handler.
    try:
        ledger.execute(QuotaRequest(), "videos.list")
    except YouTubeQuotaUnavailable:
        pass

    created = make_task(repo)
    task_id = created["tasks"][0]["id"]
    repo.update_task(task_id, status="failed", stage="failed", error="retryable", retryable=True)
    retried = repo.retry_task(task_id)
    assert retried["status"] == "queued"
    assert retried["stage"] == "waiting_youtube_quota"
    assert retried["next_attempt_at"] == ledger.get_usage()["reset_at"]


def test_publish_quota_failure_after_public_checkpoint_is_deferred(monkeypatch, tmp_path):
    repo = make_repo(tmp_path)
    make_task(repo, operation="youtube.publish_cleanup")
    task_id = repo.claim_next("youtube")["id"]
    reset = repo.youtube_limiter.get_usage()["reset_at"]
    quota_error = YouTubeQuotaUnavailable(
        code="youtube_quota_exhausted",
        http_status=403,
        reason="quotaExceeded",
        method="playlistItems.delete",
        bucket="general",
        reset_at=reset,
        confirmed_by_google=True,
        user_message="Google 已回報今日 YouTube API 配額用完。",
    )
    monkeypatch.setattr(
        task_handlers,
        "fetch_video_details",
        lambda *_args: [{"id": "video-1", "status": {"privacyStatus": "private"}, "snippet": {}}],
    )
    monkeypatch.setattr(task_handlers, "set_video_public", lambda *_args, **_kwargs: {"id": "video-1"})
    monkeypatch.setattr(task_handlers, "remove_playlist_item", lambda *_args, **_kwargs: (_ for _ in ()).throw(quota_error))

    result = task_handlers.process_youtube_publish_cleanup_task(
        task_id, credentials=object(), repository=repo
    )
    assert result["status"] == "queued"
    assert result["stage"] == "waiting_youtube_quota"
    assert result["checkpoint"]["privacy_updated_at"]
    assert not result["checkpoint"].get("playlist_removed_at")
