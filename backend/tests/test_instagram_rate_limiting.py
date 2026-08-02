from datetime import datetime, timedelta, timezone

import httpx
import pytest

from backend.app.core.config import settings
from backend.app.core.database import Database
from backend.app.core.instagram_limiter import CONTENT_PUBLISHING_LIMIT_FALLBACK_HOURS, InstagramLimiter
from backend.app.core.task_repository import TaskRepository
from backend.app.services.instagram_errors import InstagramApiError
from backend.app.services.instagram_service import InstagramClient
from backend.app.services.task_handlers import process_instagram_reel_task


class FakeHttpClient:
    responses = []
    calls = []

    def __init__(self, *args, **kwargs):
        del args, kwargs

    def __enter__(self):
        return self

    def __exit__(self, *args):
        del args
        return False

    def request(self, method, url, **kwargs):
        self.__class__.calls.append((method, url, kwargs))
        response = self.__class__.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def response(payload, status=200, *, headers=None):
    request = httpx.Request("GET", "https://graph.instagram.com/v25.0")
    return httpx.Response(status, headers=headers or {}, json=payload, request=request)


def make_limiter(tmp_path):
    return InstagramLimiter(Database(tmp_path / "creator_tools.db"))


def test_content_publishing_limit_fallback_is_not_an_environment_setting(tmp_path):
    limiter = make_limiter(tmp_path)
    started = datetime.now(timezone.utc)

    error = limiter.record_content_publishing_limit()

    finished = datetime.now(timezone.utc)
    recovery = datetime.fromisoformat(error.estimated_recovery_at)
    fallback = timedelta(hours=CONTENT_PUBLISHING_LIMIT_FALLBACK_HOURS)
    assert started + fallback <= recovery <= finished + fallback
    assert not hasattr(settings, "INSTAGRAM_PUBLISHING_LIMIT_HOURS")


def test_rate_limit_error_preserves_meta_fields_and_blocks_follow_up_requests(monkeypatch, tmp_path):
    limiter = make_limiter(tmp_path)
    FakeHttpClient.calls = []
    FakeHttpClient.responses = [
        response(
            {
                "error": {
                    "message": "Application requests limit reached",
                    "type": "OAuthException",
                    "code": 4,
                    "error_subcode": 2045015,
                    "fbtrace_id": "trace-1",
                }
            },
            429,
            headers={"Retry-After": "120", "x-app-usage": '{"call_count": 91}'},
        )
    ]
    monkeypatch.setattr("backend.app.services.instagram_service.httpx.Client", FakeHttpClient)
    monkeypatch.setattr(
        "backend.app.services.instagram_service.instagram_api_usage_tracker.record_response",
        lambda *args, **kwargs: None,
    )

    client = InstagramClient("user-1", "token-1", limiter=limiter)
    with pytest.raises(InstagramApiError) as caught:
        client.request("GET", "me")

    error = caught.value
    assert error.http_status == 429
    assert error.meta_code == 4
    assert error.error_subcode == 2045015
    assert error.fbtrace_id == "trace-1"
    assert error.retry_after == "120"
    assert error.x_app_usage == {"call_volume": 91.0}
    assert error.rate_limited is True
    assert error.safe_to_retry is True
    assert "Meta API 暫時限流" in error.user_message

    state = limiter.get_state()
    assert state["is_cooling"] is True
    assert state["last_meta_code"] == 4
    assert state["last_error_subcode"] == 2045015
    assert len(FakeHttpClient.calls) == 1

    with pytest.raises(InstagramApiError) as blocked:
        client.request("GET", "me")
    assert blocked.value.from_limiter is True
    assert len(FakeHttpClient.calls) == 1


def test_code_190_is_auth_error_not_rate_limit(monkeypatch, tmp_path):
    limiter = make_limiter(tmp_path)
    FakeHttpClient.calls = []
    FakeHttpClient.responses = [
        response(
            {"error": {"message": "Invalid OAuth access token", "code": 190, "fbtrace_id": "trace-auth"}},
            400,
        )
    ]
    monkeypatch.setattr("backend.app.services.instagram_service.httpx.Client", FakeHttpClient)
    monkeypatch.setattr(
        "backend.app.services.instagram_service.instagram_api_usage_tracker.record_response",
        lambda *args, **kwargs: None,
    )

    with pytest.raises(InstagramApiError) as caught:
        InstagramClient("user-1", "token-1", limiter=limiter).request("GET", "me")

    assert caught.value.token_error is True
    assert caught.value.rate_limited is False
    assert "重新授權" in caught.value.user_message
    assert limiter.get_state()["is_cooling"] is False


def test_timeout_is_uncertain_and_does_not_retry_post(monkeypatch, tmp_path):
    limiter = make_limiter(tmp_path)
    FakeHttpClient.calls = []
    FakeHttpClient.responses = [httpx.ReadTimeout("timed out")]
    monkeypatch.setattr("backend.app.services.instagram_service.httpx.Client", FakeHttpClient)

    client = InstagramClient("user-1", "token-1", limiter=limiter)
    with pytest.raises(InstagramApiError) as caught:
        client.create_reel_container("https://cdn.example/reel.mp4", "caption")

    assert caught.value.uncertain is True
    assert caught.value.safe_to_retry is False
    assert caught.value.method == "POST"
    assert len(FakeHttpClient.calls) == 1


def test_container_polling_uses_adaptive_intervals_and_fewer_requests(monkeypatch, tmp_path):
    limiter = make_limiter(tmp_path)
    FakeHttpClient.calls = []
    FakeHttpClient.responses = [
        *[response({"status_code": "IN_PROGRESS", "status": "Still processing"}) for _ in range(10)],
        response({"status_code": "FINISHED", "status": "Finished"}),
    ]
    sleeps = []
    monkeypatch.setattr("backend.app.services.instagram_service.httpx.Client", FakeHttpClient)
    monkeypatch.setattr("backend.app.services.instagram_service.time.sleep", sleeps.append)
    monkeypatch.setattr("backend.app.services.instagram_service.random.uniform", lambda *_args: 0)
    monkeypatch.setattr("backend.app.services.instagram_service.instagram_api_usage_tracker.get_usage", lambda: {})
    monkeypatch.setattr(
        "backend.app.services.instagram_service.instagram_api_usage_tracker.record_response",
        lambda *args, **kwargs: None,
    )

    InstagramClient("user-1", "token-1", limiter=limiter).wait_for_container("container-1")

    assert len(FakeHttpClient.calls) == 11
    assert len(sleeps) == 10
    assert sleeps[0] == pytest.approx(5)
    assert sleeps[-1] > sleeps[0]
    assert len(FakeHttpClient.calls) <= 60


def test_queue_only_claims_due_task(tmp_path):
    repo = TaskRepository(Database(tmp_path / "creator_tools.db"))
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    created = repo.create_batch_and_tasks(
        {"platform": "instagram", "operation": "instagram.reels_publish", "failure_policy": "continue"},
        [
            {
                "platform": "instagram",
                "operation": "instagram.reels_publish",
                "queue_lane": "instagram",
                "video_id": "video-1",
                "next_attempt_at": future,
            }
        ],
    )

    assert created["tasks"][0]["next_attempt_at"] == future
    assert repo.claim_next("instagram") is None

    with repo.db.transaction() as connection:
        connection.execute(
            "UPDATE tasks SET next_attempt_at = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), created["tasks"][0]["id"]),
        )

    assert repo.claim_next("instagram")["id"] == created["tasks"][0]["id"]


def test_formal_single_task_path_defers_rate_limit_without_pausing_batch(monkeypatch, tmp_path):
    repo = TaskRepository(Database(tmp_path / "creator_tools.db"))
    created = repo.create_batch_and_tasks(
        {"platform": "instagram", "operation": "instagram.reels_publish", "failure_policy": "pause_remaining_in_batch"},
        [
            {
                "platform": "instagram",
                "operation": "instagram.reels_publish",
                "queue_lane": "instagram",
                "video_id": "video-1",
                "video_title": "reel.mp4",
                "payload": {"file_id": "video-1", "caption": "caption", "source_folder_id": "source"},
                "checkpoint": {"public_url": "https://cdn.example/reel.mp4", "object_key": "r2-key"},
            }
        ],
    )
    task_id = created["tasks"][0]["id"]
    assert repo.claim_next("instagram")["id"] == task_id
    monkeypatch.setattr("backend.app.services.r2_service.ensure_lifecycle", lambda *args, **kwargs: None)

    class RateLimitedClient:
        def create_reel_container(self, *_args, **_kwargs):
            raise InstagramApiError.cooldown(
                endpoint="user-1/media",
                estimated_recovery_at=(datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
                meta_code=4,
            )

    result = process_instagram_reel_task(
        task_id,
        credentials=object(),
        client=RateLimitedClient(),
        r2=object(),
        repository=repo,
    )

    assert result["status"] == "queued"
    assert result["stage"] == "waiting_rate_limit"
    assert result["next_attempt_at"]
    assert "Meta API 暫時限流" in result["error"]
    assert repo.get_batch_internal(result["batch_id"])["status"] == "queued"
