import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

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


def make_ledger(tmp_path, **kwargs):
    return YouTubeQuotaLimiter(
        tmp_path / "youtube_quota_usage.json",
        sqlite_path=tmp_path / "missing.db",
        configured_limit=kwargs.pop("configured_limit", 100),
        safety_buffer_units=kwargs.pop("safety_buffer_units", 1),
        **kwargs,
    )


def create_legacy_sqlite(path, quota_date):
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE youtube_quota_daily (
            quota_date TEXT NOT NULL,
            bucket TEXT NOT NULL,
            configured_limit INTEGER NOT NULL,
            estimated_used_units INTEGER NOT NULL,
            state TEXT NOT NULL,
            blocked_reason TEXT,
            blocked_until TEXT,
            confirmed_exhausted_at TEXT,
            last_http_status INTEGER,
            last_error_reason TEXT,
            last_error_method TEXT,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (quota_date, bucket)
        );
        CREATE TABLE youtube_quota_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_key TEXT NOT NULL UNIQUE,
            quota_date TEXT NOT NULL,
            bucket TEXT NOT NULL,
            method TEXT NOT NULL,
            documented_cost INTEGER NOT NULL,
            outcome TEXT NOT NULL,
            http_status INTEGER,
            error_reason TEXT,
            task_id TEXT,
            batch_id TEXT,
            operation TEXT,
            created_at TEXT NOT NULL,
            completed_at TEXT
        );
        PRAGMA user_version = 3;
        """
    )
    connection.execute(
        """
        INSERT INTO youtube_quota_daily
          (quota_date,bucket,configured_limit,estimated_used_units,state,blocked_reason,
           blocked_until,confirmed_exhausted_at,last_http_status,last_error_reason,
           last_error_method,updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            quota_date,
            "general",
            10_000,
            51,
            "warning",
            None,
            None,
            None,
            403,
            "forbidden",
            "videos.list",
            "2026-08-02T01:00:00+00:00",
        ),
    )
    connection.executemany(
        """
        INSERT INTO youtube_quota_events
          (event_key,quota_date,bucket,method,documented_cost,outcome,created_at,completed_at)
        VALUES (?,?,?,?,?,?,?,?)
        """,
        [
            ("one", quota_date, "general", "videos.update", 50, "succeeded", "now", "now"),
            ("two", quota_date, "general", "videos.list", 1, "failed", "now", "now"),
        ],
    )
    connection.commit()
    connection.close()


def test_method_registry_uses_documented_general_bucket_costs():
    assert {method: (value["bucket"], value["cost"]) for method, value in YOUTUBE_QUOTA_METHODS.items()} == {
        "playlistItems.list": ("general", 1),
        "videos.list": ("general", 1),
        "videos.update": ("general", 50),
        "playlistItems.delete": ("general", 50),
    }


def test_unknown_method_fails_closed_before_request(tmp_path):
    ledger = make_ledger(tmp_path)
    request = SuccessfulRequest()

    with pytest.raises(YouTubeQuotaUnavailable) as caught:
        ledger.execute(request, "future.youtube.method")

    assert caught.value.code == "youtube_quota_unknown_method"
    assert request.calls == 0


def test_request_is_reserved_before_failure_and_outcome_is_persisted(tmp_path):
    ledger = make_ledger(tmp_path)

    with pytest.raises(HttpFailure):
        ledger.execute(SimpleNamespace(execute=lambda: (_ for _ in ()).throw(HttpFailure("forbidden"))), "videos.list")

    usage = ledger.get_usage()
    assert usage["estimated_used_units"] == 1
    assert usage["state"] != "confirmed_exhausted"
    assert usage["methods"] == [
        {
            "method": "videos.list",
            "cost_per_call": 1,
            "calls": 1,
            "units": 1,
            "succeeded_calls": 0,
            "failed_calls": 1,
        }
    ]


def test_two_instances_share_a_path_lock_and_cannot_cross_policy_cap(tmp_path):
    path = tmp_path / "youtube_quota_usage.json"
    sqlite_path = tmp_path / "missing.db"
    first = YouTubeQuotaLimiter(path, sqlite_path=sqlite_path, configured_limit=51, safety_buffer_units=0)
    second = YouTubeQuotaLimiter(path, sqlite_path=sqlite_path, configured_limit=51, safety_buffer_units=0)

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

    ledger = make_ledger(tmp_path)
    with pytest.raises(HttpFailure):
        ledger.execute(SimpleNamespace(execute=lambda: (_ for _ in ()).throw(HttpFailure("forbidden"))), "videos.list")
    assert ledger.get_usage()["confirmed_by_google"] is False


def test_confirmed_exhaustion_sets_effective_available_to_zero(tmp_path):
    ledger = make_ledger(tmp_path)
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


def test_new_quota_date_replaces_the_previous_day_with_a_normal_ledger(tmp_path):
    ledger = make_ledger(tmp_path)
    first_day = datetime(2026, 7, 1, 20, 0, tzinfo=timezone.utc)
    next_day = datetime(2026, 7, 2, 8, 0, tzinfo=timezone.utc)
    first = ledger.get_usage(now=first_day)
    second = ledger.get_usage(now=next_day)

    assert first["quota_date"] != second["quota_date"]
    assert second["state"] == "normal"
    assert second["estimated_used_units"] == 0


def test_existing_legacy_json_is_upgraded_without_double_counting(tmp_path):
    path = tmp_path / "youtube_quota_usage.json"
    now = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)
    path.write_text(
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
        path,
        sqlite_path=tmp_path / "missing.db",
        configured_limit=10_000,
        safety_buffer_units=1_000,
    )
    first = ledger.get_usage(now=now)
    second = ledger.get_usage(now=now)

    assert first["estimated_used_units"] == second["estimated_used_units"] == 51
    assert sum(item["calls"] for item in second["methods"]) == 2
    assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] == 2


def test_missing_json_imports_current_sqlite_quota_and_events_once(tmp_path):
    now = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)
    quota_date = "2026-08-02"
    sqlite_path = tmp_path / "creator_tools.db"
    json_path = tmp_path / "youtube_quota_usage.json"
    create_legacy_sqlite(sqlite_path, quota_date)
    ledger = YouTubeQuotaLimiter(
        json_path,
        sqlite_path=sqlite_path,
        configured_limit=10_000,
        safety_buffer_units=1_000,
    )

    imported = ledger.get_usage(now=now)
    assert imported["estimated_used_units"] == 51
    assert {item["method"]: item["calls"] for item in imported["methods"]} == {
        "videos.list": 1,
        "videos.update": 1,
    }
    saved = json.loads(json_path.read_text(encoding="utf-8"))
    assert saved["migration"]["sqlite_schema_version"] == 3

    connection = sqlite3.connect(sqlite_path)
    connection.execute(
        "UPDATE youtube_quota_daily SET estimated_used_units=999 WHERE quota_date=? AND bucket='general'",
        (quota_date,),
    )
    connection.commit()
    connection.close()

    assert ledger.get_usage(now=now)["estimated_used_units"] == 51


def test_sqlite_wins_over_stale_legacy_json_without_double_counting(tmp_path):
    now = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)
    quota_date = "2026-08-02"
    sqlite_path = tmp_path / "creator_tools.db"
    json_path = tmp_path / "youtube_quota_usage.json"
    create_legacy_sqlite(sqlite_path, quota_date)
    json_path.write_text(
        json.dumps(
            {
                "quota_date": quota_date,
                "used_units": 1,
                "methods": {"videos.list": {"calls": 1, "units": 1}},
            }
        ),
        encoding="utf-8",
    )
    ledger = YouTubeQuotaLimiter(
        json_path,
        sqlite_path=sqlite_path,
        configured_limit=10_000,
        safety_buffer_units=1_000,
    )

    imported = ledger.get_usage(now=now)

    assert imported["estimated_used_units"] == 51
    assert sum(item["units"] for item in imported["methods"]) == 51
    assert json.loads(json_path.read_text(encoding="utf-8"))["migration"]["sqlite_schema_version"] == 3


def test_corrupt_json_fails_closed_without_falling_back_to_sqlite(tmp_path):
    path = tmp_path / "youtube_quota_usage.json"
    path.write_text("{not-json", encoding="utf-8")
    request = SuccessfulRequest()
    ledger = YouTubeQuotaLimiter(path, sqlite_path=tmp_path / "missing.db")

    with pytest.raises(YouTubeQuotaUnavailable) as caught:
        ledger.execute(request, "videos.list")

    assert caught.value.code == "youtube_quota_storage_unavailable"
    assert request.calls == 0


def test_atomic_write_failure_fails_closed_before_request(monkeypatch, tmp_path):
    request = SuccessfulRequest()
    ledger = make_ledger(tmp_path)

    def fail_replace(_source, _target):
        raise OSError("disk unavailable")

    monkeypatch.setattr("backend.app.core.youtube_quota_limiter.os.replace", fail_replace)
    with pytest.raises(YouTubeQuotaUnavailable) as caught:
        ledger.execute(request, "videos.list")

    assert caught.value.code == "youtube_quota_storage_unavailable"
    assert request.calls == 0


def test_cost_estimates_match_direct_metadata_and_publish_formulas(monkeypatch):
    from backend.app.api.youtube import _quota_estimate

    monkeypatch.setattr(
        "backend.app.api.youtube.youtube_quota_tracker.get_usage",
        lambda: {"effective_available_units": 1500, "reset_at": "reset", "reset_timezone": "America/Los_Angeles"},
    )
    metadata = _quota_estimate("youtube.metadata_update", 51)
    publish = _quota_estimate("youtube.publish_cleanup", 20)
    assert metadata["projected_units"] == 2 + 51 * 50
    assert publish["projected_units"] == 2 * 1 + 100 * 20
    assert publish["max_items_today"] == 14
