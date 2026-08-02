"""Durable, process-wide Instagram request limiter and circuit breaker."""

from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from backend.app.core.config import settings
from backend.app.core.database import Database, database
from backend.app.services.instagram_errors import InstagramApiError, parse_retry_after

# Meta's live content_publishing_limit response is authoritative. This is only
# a local recovery-time estimate for the case where Meta does not provide one.
CONTENT_PUBLISHING_LIMIT_FALLBACK_HOURS = 24.0


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class InstagramLimiter:
    """Store one global cooldown row in the same SQLite database as tasks."""

    def __init__(self, db: Database = database):
        self.db = db
        self.db.initialize()

    @staticmethod
    def _default_state() -> dict[str, Any]:
        return {
            "id": 1,
            "cooldown_until": None,
            "last_reason": None,
            "last_http_status": None,
            "last_meta_code": None,
            "last_error_subcode": None,
            "last_fbtrace_id": None,
            "last_endpoint": None,
            "last_retry_after": None,
            "estimated_recovery_at": None,
            "consecutive_failures": 0,
            "recent_success_at": None,
            "last_failure_at": None,
            "last_success_endpoint": None,
            "last_app_usage_json": None,
            "updated_at": None,
        }

    def _row(self, connection) -> dict[str, Any]:
        row = connection.execute("SELECT * FROM instagram_limiter WHERE id = 1").fetchone()
        if row is None:
            connection.execute("INSERT INTO instagram_limiter (id) VALUES (1)")
            row = connection.execute("SELECT * FROM instagram_limiter WHERE id = 1").fetchone()
        data = dict(row) if row else self._default_state()
        raw_usage = data.get("last_app_usage_json")
        try:
            data["last_app_usage"] = json.loads(raw_usage) if raw_usage else None
        except (TypeError, ValueError):
            data["last_app_usage"] = None
        return data

    @staticmethod
    def _usage_percent(usage: Mapping[str, Any] | None) -> float | None:
        if not isinstance(usage, Mapping):
            return None
        values = []
        for value in usage.values():
            try:
                values.append(float(value))
            except (TypeError, ValueError):
                continue
        return round(max(values), 2) if values else None

    def get_state(self) -> dict[str, Any]:
        with self.db.transaction(immediate=False) as connection:
            data = self._row(connection)
        now = _now()
        cooldown = _parse_time(data.get("cooldown_until"))
        usage = data.get("last_app_usage")
        usage_percent = self._usage_percent(usage)
        data.update(
            {
                "cooldown_until": _iso(cooldown) if cooldown else None,
                "is_cooling": bool(cooldown and cooldown > now),
                "usage_percent": usage_percent,
                "usage_soft_threshold": float(settings.INSTAGRAM_USAGE_SOFT_THRESHOLD),
                "usage_hard_threshold": float(settings.INSTAGRAM_USAGE_HARD_THRESHOLD),
                "usage_throttled": usage_percent is not None
                and usage_percent >= float(settings.INSTAGRAM_USAGE_SOFT_THRESHOLD),
                "new_tasks_paused": usage_percent is not None
                and usage_percent >= float(settings.INSTAGRAM_USAGE_HARD_THRESHOLD),
            }
        )
        return data

    def assert_request_allowed(self, *, method: str, endpoint: str) -> None:
        state = self.get_state()
        if state.get("is_cooling"):
            raise InstagramApiError.cooldown(
                endpoint=endpoint,
                estimated_recovery_at=str(state.get("cooldown_until")),
                reason="Meta API 暫時限流",
                meta_code=state.get("last_meta_code"),
                content_publishing_limit=state.get("last_reason") == "content_publishing_limit",
            )

    def assert_can_start_task(self, *, endpoint: str = "task preflight") -> None:
        state = self.get_state()
        if state.get("is_cooling"):
            raise InstagramApiError.cooldown(
                endpoint=endpoint,
                estimated_recovery_at=str(state.get("cooldown_until")),
                reason="Meta API 暫時限流",
                meta_code=state.get("last_meta_code"),
                content_publishing_limit=state.get("last_reason") == "content_publishing_limit",
            )
        if state.get("new_tasks_paused"):
            retry_at = _iso(_now() + timedelta(seconds=max(float(settings.INSTAGRAM_USAGE_RECHECK_SECONDS), 1)))
            raise InstagramApiError.cooldown(
                endpoint=endpoint,
                estimated_recovery_at=retry_at,
                reason="Meta API 使用率已達硬門檻，暫停建立新的 Instagram container",
                meta_code=None,
            )

    def observe_usage(self, usage: Mapping[str, Any] | None) -> None:
        if not isinstance(usage, Mapping):
            return
        try:
            serialized = json.dumps(dict(usage), ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError):
            return
        with self.db.transaction() as connection:
            now = _iso(_now())
            self._row(connection)
            connection.execute(
                "UPDATE instagram_limiter SET last_app_usage_json=?, updated_at=? WHERE id=1",
                (serialized, now),
            )
            usage_percent = self._usage_percent(usage)
            soft = float(settings.INSTAGRAM_USAGE_SOFT_THRESHOLD)
            hard = float(settings.INSTAGRAM_USAGE_HARD_THRESHOLD)
            if usage_percent is not None and usage_percent >= soft:
                bucket = "hard" if usage_percent >= hard else "soft"
                severity = "error" if bucket == "hard" else "warning"
                title = "Instagram Meta 使用率已達硬門檻" if bucket == "hard" else "Instagram Meta 使用率接近門檻"
                message = (
                    f"目前觀測使用率約 {usage_percent:.2f}%，"
                    + ("系統已暫停建立新的 Instagram container。" if bucket == "hard" else "系統將降低輪詢頻率。")
                )
                event_key = f"instagram:usage-threshold:{datetime.now(timezone.utc).date().isoformat()}:{bucket}"
                connection.execute(
                    """
                    INSERT OR IGNORE INTO notifications
                      (event_key,type,severity,title,message,created_at)
                    VALUES (?,?,?,?,?,?)
                    """,
                    (event_key, "instagram_usage_threshold", severity, title, message, now),
                )

    def record_success(self, *, endpoint: str) -> None:
        with self.db.transaction() as connection:
            now = _iso(_now())
            current = self._row(connection)
            cooldown = _parse_time(current.get("cooldown_until"))
            next_cooldown = None if not cooldown or cooldown <= _now() else current.get("cooldown_until")
            connection.execute(
                """
                UPDATE instagram_limiter
                SET cooldown_until=?, consecutive_failures=0, recent_success_at=?,
                    last_success_endpoint=?, updated_at=?
                WHERE id=1
                """,
                (next_cooldown, now, endpoint, now),
            )

    def record_rate_limit(self, error: InstagramApiError, *, endpoint: str, usage: Mapping[str, Any] | None = None) -> dict[str, Any]:
        current_time = _now()
        with self.db.transaction() as connection:
            current = self._row(connection)
            previous_failures = int(current.get("consecutive_failures") or 0)
            failures = previous_failures + 1
            existing = _parse_time(current.get("cooldown_until"))
            recovery = _parse_time(error.estimated_recovery_at)
            if recovery is None and error.retry_after not in (None, ""):
                _, recovery_iso = parse_retry_after(error.retry_after, now=current_time)
                recovery = _parse_time(recovery_iso)
            if recovery is None and error.content_publishing_limit:
                recovery = current_time + timedelta(hours=CONTENT_PUBLISHING_LIMIT_FALLBACK_HOURS)
            if recovery is None:
                base = max(float(settings.INSTAGRAM_COOLDOWN_BASE_SECONDS), 1)
                cap = max(float(settings.INSTAGRAM_COOLDOWN_MAX_SECONDS), base)
                seconds = min(base * (2 ** max(failures - 1, 0)), cap)
                seconds += random.uniform(0, max(float(settings.INSTAGRAM_COOLDOWN_JITTER_SECONDS), 0))
                recovery = current_time + timedelta(seconds=seconds)
            if existing and existing > recovery:
                recovery = existing
            usage_value = usage if isinstance(usage, Mapping) else current.get("last_app_usage")
            serialized_usage = None
            if isinstance(usage_value, Mapping):
                serialized_usage = json.dumps(dict(usage_value), ensure_ascii=False, separators=(",", ":"))
            now = _iso(current_time)
            connection.execute(
                """
                UPDATE instagram_limiter
                SET cooldown_until=?, last_reason=?, last_http_status=?, last_meta_code=?,
                    last_error_subcode=?, last_fbtrace_id=?, last_endpoint=?, last_retry_after=?,
                    estimated_recovery_at=?, consecutive_failures=?, last_failure_at=?,
                    last_app_usage_json=COALESCE(?, last_app_usage_json), updated_at=?
                WHERE id=1
                """,
                (
                    _iso(recovery),
                    "content_publishing_limit" if error.content_publishing_limit else "rate_limit",
                    error.http_status,
                    error.meta_code,
                    error.error_subcode,
                    error.fbtrace_id,
                    endpoint,
                    str(error.retry_after) if error.retry_after not in (None, "") else None,
                    _iso(recovery),
                    failures,
                    now,
                    serialized_usage,
                    now,
                ),
            )
            return self._row(connection)

    def record_content_publishing_limit(self, *, endpoint: str = "content_publishing_limit") -> InstagramApiError:
        error = InstagramApiError.cooldown(
            endpoint=endpoint,
            estimated_recovery_at=_iso(_now() + timedelta(hours=CONTENT_PUBLISHING_LIMIT_FALLBACK_HOURS)),
            reason="Instagram 24 小時發布額度已用盡",
            content_publishing_limit=True,
        )
        self.record_rate_limit(error, endpoint=endpoint)
        return error


instagram_limiter = InstagramLimiter()
