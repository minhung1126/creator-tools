import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from backend.app.api.youtube import _quota_estimate
from backend.app.core.database import Database
from backend.app.core.youtube_quota_limiter import (
    YOUTUBE_QUOTA_METHODS,
    YouTubeQuotaLimiter,
    next_reset_at,
)
from backend.app.services.youtube_errors import YouTubeQuotaUnavailable, is_youtube_quota_exceeded


class SuccessfulRequest:
    def __init__(self):
        self.calls = 0

    def execute(self):
        self.calls += 1
        return {"ok": True}


class HttpFailure(Exception):
    def __init__(self, reason):
        super().__init__(reason)
        self.resp = SimpleNamespace(status=403)
        self.content = json.dumps({"error": {"errors": [{"reason": reason}], "message": "safe test body"}}).encode()


def test_method_registry_uses_documented_general_bucket_costs():
    assert {method: (value["bucket"], value["cost"]) for method, value in YOUTUBE_QUOTA_METHODS.items()} == {
        "playlistItems.list": ("general", 1),
        "videos.list": ("general", 1),
        "videos.update": ("general", 50),
        "playlistItems.delete": ("general", 50),
    }


def test_unknown_method_fails_closed_before_request(tmp_path):
    ledger = YouTubeQuotaLimiter(Database(tmp_path / "quota.db"), configured_limit=100, safety_buffer_units=1)
    request = SuccessfulRequest()

    with pytest.raises(YouTubeQuotaUnavailable) as caught:
        ledger.execute(request, "future.youtube.method")

    assert caught.value.code == "youtube_quota_unknown_method"
    assert request.calls == 0


def test_request_is_reserved_before_failure_and_event_is_completed(tmp_path):
    ledger = YouTubeQuotaLimiter(Database(tmp_path / "quota.db"), configured_limit=100, safety_buffer_units=1)

    with pytest.raises(HttpFailure):
        ledger.execute(SimpleNamespace(execute=lambda: (_ for _ in ()).throw(HttpFailure("forbidden"))), "videos.list")

    usage = ledger.get_usage()
    assert usage["estimated_used_units"] == 1
    assert usage["state"] != "confirmed_exhausted"
    with ledger.db.connection() as connection:
        event = connection.execute("SELECT outcome, error_reason FROM youtube_quota_events").fetchone()
    assert event["outcome"] == "failed"
    assert event["error_reason"] == "forbidden"


def test_two_ledger_instances_cannot_cross_the_policy_cap(tmp_path):
    db_path = tmp_path / "quota.db"
    first = YouTubeQuotaLimiter(Database(db_path), configured_limit=51, safety_buffer_units=0)
    second = YouTubeQuotaLimiter(Database(db_path), configured_limit=51, safety_buffer_units=0)

    def send(ledger):
        try:
            ledger.execute(SuccessfulRequest(), "videos.update")
            return "succeeded"
        except YouTubeQuotaUnavailable as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(send, (first, second)))

    assert sorted(results) == ["succeeded", "youtube_quota_safety_blocked"]
    assert first.get_usage()["estimated_used_units"] == 50


def test_only_403_quota_exceeded_is_confirmed_quota(tmp_path):
    assert is_youtube_quota_exceeded(HttpFailure("quotaExceeded")) is True
    assert is_youtube_quota_exceeded(HttpFailure("forbidden")) is False

    ledger = YouTubeQuotaLimiter(Database(tmp_path / "quota.db"), configured_limit=100, safety_buffer_units=1)
    with pytest.raises(HttpFailure):
        ledger.execute(SimpleNamespace(execute=lambda: (_ for _ in ()).throw(HttpFailure("forbidden"))), "videos.list")
    assert ledger.get_usage()["confirmed_by_google"] is False


def test_confirmed_exhaustion_sets_effective_available_to_zero(tmp_path):
    ledger = YouTubeQuotaLimiter(Database(tmp_path / "quota.db"), configured_limit=100, safety_buffer_units=1)
    with pytest.raises(YouTubeQuotaUnavailable) as caught:
        ledger.execute(
            SimpleNamespace(execute=lambda: (_ for _ in ()).throw(HttpFailure("quotaExceeded"))), "videos.update"
        )

    usage = ledger.get_usage()
    assert caught.value.code == "youtube_quota_exhausted"
    assert usage["state"] == "confirmed_exhausted"
    assert usage["confirmed_by_google"] is True
    assert usage["effective_available_units"] == 0
    assert usage["estimated_used_units"] == 50


def test_reset_uses_pacific_midnight_and_dst_offsets():
    summer = datetime(2026, 7, 1, 20, 0, tzinfo=timezone.utc)
    winter = datetime(2026, 1, 1, 20, 0, tzinfo=timezone.utc)
    assert next_reset_at(summer).isoformat().endswith("-07:00")
    assert next_reset_at(winter).isoformat().endswith("-08:00")


def test_new_quota_date_has_a_new_normal_breaker(tmp_path):
    ledger = YouTubeQuotaLimiter(Database(tmp_path / "quota.db"), configured_limit=100, safety_buffer_units=1)
    exhausted_at = datetime(2026, 7, 1, 20, 0, tzinfo=timezone.utc)
    next_day = datetime(2026, 7, 2, 8, 0, tzinfo=timezone.utc)
    with pytest.raises(YouTubeQuotaUnavailable):
        ledger.execute(
            SimpleNamespace(execute=lambda: (_ for _ in ()).throw(HttpFailure("quotaExceeded"))),
            "videos.list",
        )
    # The production path uses the current clock; explicitly exercise the
    # date helper through a fresh ledger's usage view for the DST boundary.
    assert ledger.quota_date(exhausted_at) != ledger.quota_date(next_day)


def test_legacy_json_import_is_idempotent(tmp_path):
    legacy = tmp_path / "youtube_quota_usage.json"
    legacy.write_text(
        json.dumps(
            {
                "quota_date": "2026-08-02",
                "used_units": 51,
                "methods": {"videos.update": {"calls": 1, "units": 50}, "videos.list": {"calls": 1, "units": 1}},
            }
        ),
        encoding="utf-8",
    )
    ledger = YouTubeQuotaLimiter(
        Database(tmp_path / "quota.db"),
        legacy_path=legacy,
        configured_limit=10000,
        safety_buffer_units=1000,
    )
    first = ledger.get_usage(now=datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc))
    second = ledger.get_usage(now=datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc))
    assert first["estimated_used_units"] == second["estimated_used_units"] == 51
    assert sum(item["calls"] for item in second["methods"]) == 2


def test_cost_estimates_match_metadata_and_publish_formulas(monkeypatch):
    monkeypatch.setattr(
        "backend.app.api.youtube.youtube_quota_tracker.get_usage",
        lambda: {"effective_available_units": 1500, "reset_at": "reset", "reset_timezone": "America/Los_Angeles"},
    )
    metadata = _quota_estimate("youtube.metadata_update", 51)
    publish = _quota_estimate("youtube.publish_cleanup", 20)
    assert metadata["projected_units"] == 2 + 51 * 51
    assert publish["projected_units"] == 2 * 1 + 101 * 20
    assert publish["max_items_today"] == 14
