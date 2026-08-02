"""SQLite-backed YouTube Data API quota ledger and request guard.

The ledger is deliberately an estimate of requests made by Creator Tools.  It
is not a Cloud Console usage feed: other applications in the same Google
Cloud project can consume the same official bucket.
"""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, Optional
from uuid import uuid4
from zoneinfo import ZoneInfo

from backend.app.core.database import DATA_DIR, Database, database
from backend.app.core.runtime_config import runtime_config
from backend.app.services.youtube_errors import YouTubeQuotaUnavailable, parse_youtube_error

logger = logging.getLogger(__name__)

PACIFIC = ZoneInfo("America/Los_Angeles")
RESET_TIMEZONE = "America/Los_Angeles"
GENERAL_BUCKET = "general"
OFFICIAL_DEFAULT_LIMIT = 10_000
DEFAULT_SAFETY_BUFFER_UNITS = 1_000
QUOTA_SOURCE_URL = "https://developers.google.com/youtube/v3/determine_quota_cost"
QUOTA_RULES_LAST_UPDATED_AT = "2026-06-01"
QUOTA_RULES_VERIFIED_AT = "2026-08-02"
LEGACY_QUOTA_FILE = DATA_DIR / "youtube_quota_usage.json"

YOUTUBE_QUOTA_METHODS: dict[str, dict[str, Any]] = {
    "playlistItems.list": {"bucket": GENERAL_BUCKET, "cost": 1},
    "videos.list": {"bucket": GENERAL_BUCKET, "cost": 1},
    "videos.update": {"bucket": GENERAL_BUCKET, "cost": 50},
    "playlistItems.delete": {"bucket": GENERAL_BUCKET, "cost": 50},
}

# Compatibility aliases used by the previous JSON tracker and by integrations
# that imported these values directly.
QUOTA_COSTS = {method: int(meta["cost"]) for method, meta in YOUTUBE_QUOTA_METHODS.items()}
DEFAULT_DAILY_LIMIT = OFFICIAL_DEFAULT_LIMIT
QUOTA_COSTS_VERIFIED_AT = QUOTA_RULES_VERIFIED_AT


def _as_utc(value: datetime | None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc)


def quota_date_for(now: datetime | None = None) -> str:
    return _as_utc(now).astimezone(PACIFIC).date().isoformat()


def next_reset_at(now: datetime | None = None) -> datetime:
    current_pt = _as_utc(now).astimezone(PACIFIC)
    return datetime.combine(current_pt.date() + timedelta(days=1), time.min, tzinfo=PACIFIC)


def iso_with_offset(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


@dataclass(frozen=True)
class QuotaReservation:
    event_key: str
    quota_date: str
    bucket: str
    method: str
    documented_cost: int
    reset_at: str


@dataclass(frozen=True)
class YouTubeQuotaContext:
    limiter: "YouTubeQuotaLimiter"
    task_id: Optional[str] = None
    batch_id: Optional[str] = None
    operation: Optional[str] = None


_quota_context: ContextVar[YouTubeQuotaContext | None] = ContextVar("youtube_quota_context", default=None)


@contextmanager
def youtube_quota_context(
    *,
    limiter: "YouTubeQuotaLimiter",
    task_id: Optional[str] = None,
    batch_id: Optional[str] = None,
    operation: Optional[str] = None,
) -> Iterator[None]:
    token = _quota_context.set(
        YouTubeQuotaContext(limiter=limiter, task_id=task_id, batch_id=batch_id, operation=operation)
    )
    try:
        yield
    finally:
        _quota_context.reset(token)


def current_youtube_quota_context() -> YouTubeQuotaContext | None:
    return _quota_context.get()


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class YouTubeQuotaLimiter:
    """Coordinate request reservations with SQLite ``BEGIN IMMEDIATE``."""

    def __init__(
        self,
        db: Database = database,
        *,
        legacy_path: str | Path = LEGACY_QUOTA_FILE,
        configured_limit: int | None = None,
        safety_buffer_units: int | None = None,
        daily_limit: int | None = None,
    ) -> None:
        self.db = db
        self.legacy_path = Path(legacy_path)
        self._configured_limit_override = configured_limit if configured_limit is not None else daily_limit
        self._safety_buffer_override = safety_buffer_units
        self.db.initialize()

    def configured_values(self) -> tuple[int, int]:
        limit = self._configured_limit_override
        if limit is None:
            limit = runtime_config.get("youtube_general_quota_limit", OFFICIAL_DEFAULT_LIMIT)
        buffer = self._safety_buffer_override
        if buffer is None:
            buffer = runtime_config.get("youtube_quota_safety_buffer_units", DEFAULT_SAFETY_BUFFER_UNITS)
        limit = max(_safe_int(limit, OFFICIAL_DEFAULT_LIMIT), 1)
        buffer = max(_safe_int(buffer, DEFAULT_SAFETY_BUFFER_UNITS), 0)
        # Invalid persisted values fail closed at the API boundary.  The
        # ledger still remains usable if an older installation contains one.
        buffer = min(buffer, max(limit - 1, 0))
        return limit, buffer

    @staticmethod
    def quota_date(now: datetime | None = None) -> str:
        return quota_date_for(now)

    @staticmethod
    def next_reset(now: datetime | None = None) -> datetime:
        return next_reset_at(now)

    def _empty_row_values(self, quota_date: str, limit: int, now: str, used: int = 0) -> tuple[Any, ...]:
        return (
            quota_date,
            GENERAL_BUCKET,
            limit,
            max(used, 0),
            "normal",
            None,
            None,
            None,
            None,
            None,
            None,
            now,
        )

    def _load_legacy(self) -> dict[str, Any] | None:
        if not self.legacy_path.is_file():
            return None
        try:
            value = json.loads(self.legacy_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            logger.warning("Failed to import legacy YouTube quota usage: %s", type(exc).__name__)
            return None
        return value if isinstance(value, dict) else None

    def _ensure_daily_row(self, connection, quota_date: str, now: datetime) -> Any:
        limit, _buffer = self.configured_values()
        existing = connection.execute(
            "SELECT * FROM youtube_quota_daily WHERE quota_date = ? AND bucket = ?",
            (quota_date, GENERAL_BUCKET),
        ).fetchone()
        if existing is not None:
            # Settings changes take effect on the next read/reservation without
            # rewriting the estimate or clearing a confirmed breaker.
            connection.execute(
                "UPDATE youtube_quota_daily SET configured_limit = ?, updated_at = ? WHERE quota_date = ? AND bucket = ?",
                (limit, iso_with_offset(_as_utc(now)), quota_date, GENERAL_BUCKET),
            )
            return connection.execute(
                "SELECT * FROM youtube_quota_daily WHERE quota_date = ? AND bucket = ?",
                (quota_date, GENERAL_BUCKET),
            ).fetchone()

        legacy = self._load_legacy()
        imported_used = 0
        imported_methods: dict[str, Any] = {}
        if legacy and str(legacy.get("quota_date") or "") == quota_date:
            imported_used = max(_safe_int(legacy.get("used_units"), 0), 0)
            imported_methods = legacy.get("methods") if isinstance(legacy.get("methods"), dict) else {}

        connection.execute(
            """
            INSERT INTO youtube_quota_daily
              (quota_date,bucket,configured_limit,estimated_used_units,state,blocked_reason,
               blocked_until,confirmed_exhausted_at,last_http_status,last_error_reason,
               last_error_method,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            self._empty_row_values(quota_date, limit, iso_with_offset(_as_utc(now)), imported_used),
        )

        if imported_used and imported_methods:
            for method, raw_data in imported_methods.items():
                if method not in YOUTUBE_QUOTA_METHODS or not isinstance(raw_data, dict):
                    logger.warning("Skipped unknown legacy YouTube quota method: %s", method)
                    continue
                calls = max(_safe_int(raw_data.get("calls"), 0), 0)
                cost = int(YOUTUBE_QUOTA_METHODS[method]["cost"])
                for index in range(calls):
                    event_key = f"youtube-quota-legacy:{quota_date}:{GENERAL_BUCKET}:{method}:{index}"
                    connection.execute(
                        """
                        INSERT OR IGNORE INTO youtube_quota_events
                          (event_key,quota_date,bucket,method,documented_cost,outcome,
                           http_status,error_reason,task_id,batch_id,operation,created_at,completed_at)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            event_key,
                            quota_date,
                            GENERAL_BUCKET,
                            method,
                            cost,
                            "succeeded",
                            None,
                            "legacy_json_import",
                            None,
                            None,
                            None,
                            iso_with_offset(_as_utc(now)),
                            iso_with_offset(_as_utc(now)),
                        ),
                    )
        return connection.execute(
            "SELECT * FROM youtube_quota_daily WHERE quota_date = ? AND bucket = ?",
            (quota_date, GENERAL_BUCKET),
        ).fetchone()

    @staticmethod
    def _is_breaker_active(row: Any, now: datetime) -> bool:
        state = str(row["state"] or "normal")
        if state == "confirmed_exhausted":
            return True
        if state != "safety_blocked":
            return False
        blocked_until = row["blocked_until"]
        if not blocked_until:
            return True
        try:
            until = datetime.fromisoformat(str(blocked_until))
        except ValueError:
            return True
        return until > _as_utc(now)

    @staticmethod
    def _unavailable(
        *,
        code: str,
        method: str,
        reset_at: str,
        reason: str,
        confirmed: bool,
        message: str,
        http_status: int | None = None,
    ) -> YouTubeQuotaUnavailable:
        return YouTubeQuotaUnavailable(
            code=code,
            http_status=http_status,
            reason=reason,
            method=method,
            bucket=GENERAL_BUCKET,
            reset_at=reset_at,
            confirmed_by_google=confirmed,
            user_message=message,
        )

    def reserve(
        self,
        method: str,
        *,
        task_id: Optional[str] = None,
        batch_id: Optional[str] = None,
        operation: Optional[str] = None,
        now: datetime | None = None,
    ) -> QuotaReservation:
        meta = YOUTUBE_QUOTA_METHODS.get(method)
        current_utc = _as_utc(now)
        reset = iso_with_offset(next_reset_at(current_utc))
        quota_date = quota_date_for(current_utc)
        event_key = f"youtube-quota:{quota_date}:{GENERAL_BUCKET}:{method}:{uuid4().hex}"
        if meta is None:
            logger.error("Unknown YouTube quota method blocked before request: %s", method)
            with self.db.transaction() as connection:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO youtube_quota_events
                      (event_key,quota_date,bucket,method,documented_cost,outcome,error_reason,
                       task_id,batch_id,operation,created_at,completed_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        event_key,
                        quota_date,
                        GENERAL_BUCKET,
                        method,
                        0,
                        "blocked",
                        "unknown_method",
                        task_id,
                        batch_id,
                        operation,
                        iso_with_offset(current_utc),
                        iso_with_offset(current_utc),
                    ),
                )
            raise self._unavailable(
                code="youtube_quota_unknown_method",
                method=method,
                reset_at=reset,
                reason="unknown_method",
                confirmed=False,
                message="YouTube API method 尚未加入官方配額成本設定，系統已阻止此請求。",
            )

        cost = int(meta["cost"])
        unavailable: YouTubeQuotaUnavailable | None = None
        with self.db.transaction() as connection:
            row = self._ensure_daily_row(connection, quota_date, current_utc)
            limit, buffer = self.configured_values()
            used = int(row["estimated_used_units"] or 0)
            policy_cap = max(limit - buffer, 0)
            if str(row["state"]) == "confirmed_exhausted":
                unavailable = self._unavailable(
                    code="youtube_quota_exhausted",
                    method=method,
                    reset_at=reset,
                    reason=str(row["last_error_reason"] or "quotaExceeded"),
                    confirmed=True,
                    message="Google 已回報今日 YouTube API 配額用完。",
                )
            elif self._is_breaker_active(row, current_utc):
                unavailable = self._unavailable(
                    code="youtube_quota_safety_blocked",
                    method=method,
                    reset_at=reset,
                    reason=str(row["blocked_reason"] or "safety_cap_reached"),
                    confirmed=False,
                    message="Creator Tools 已達 YouTube API 安全上限，新的請求將等待官方配額重設。",
                )
            elif used + cost > policy_cap:
                unavailable = self._unavailable(
                    code="youtube_quota_safety_blocked",
                    method=method,
                    reset_at=reset,
                    reason="safety_cap_reached",
                    confirmed=False,
                    message="Creator Tools 已達 YouTube API 安全上限，新的請求將等待官方配額重設。",
                )
                connection.execute(
                    """
                    UPDATE youtube_quota_daily
                    SET state='safety_blocked', blocked_reason='safety_cap_reached', blocked_until=?,
                        last_error_method=?, updated_at=?
                    WHERE quota_date=? AND bucket=?
                    """,
                    (reset, method, iso_with_offset(current_utc), quota_date, GENERAL_BUCKET),
                )
            else:
                next_used = used + cost
                next_state = "warning" if next_used >= max(int(limit * 0.8), 1) else "normal"
                connection.execute(
                    """
                    UPDATE youtube_quota_daily
                    SET estimated_used_units=?, state=?, blocked_reason=NULL, updated_at=?
                    WHERE quota_date=? AND bucket=?
                    """,
                    (next_used, next_state, iso_with_offset(current_utc), quota_date, GENERAL_BUCKET),
                )
                connection.execute(
                    """
                    INSERT INTO youtube_quota_events
                      (event_key,quota_date,bucket,method,documented_cost,outcome,
                       task_id,batch_id,operation,created_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        event_key,
                        quota_date,
                        GENERAL_BUCKET,
                        method,
                        cost,
                        "attempted",
                        task_id,
                        batch_id,
                        operation,
                        iso_with_offset(current_utc),
                    ),
                )
        if unavailable is not None:
            with self.db.transaction() as connection:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO youtube_quota_events
                      (event_key,quota_date,bucket,method,documented_cost,outcome,error_reason,
                       task_id,batch_id,operation,created_at,completed_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        event_key,
                        quota_date,
                        GENERAL_BUCKET,
                        method,
                        cost,
                        "blocked",
                        unavailable.reason,
                        task_id,
                        batch_id,
                        operation,
                        iso_with_offset(current_utc),
                        iso_with_offset(current_utc),
                    ),
                )
            raise unavailable
        return QuotaReservation(event_key, quota_date, GENERAL_BUCKET, method, cost, reset)

    def complete(
        self,
        reservation: QuotaReservation,
        *,
        outcome: str,
        http_status: int | None = None,
        error_reason: str | None = None,
        completed_at: datetime | None = None,
    ) -> None:
        if outcome not in {"succeeded", "failed", "attempted"}:
            raise ValueError(f"Invalid YouTube quota event outcome: {outcome}")
        with self.db.transaction() as connection:
            connection.execute(
                """
                UPDATE youtube_quota_events
                SET outcome=?, http_status=?, error_reason=?, completed_at=?
                WHERE event_key=?
                """,
                (
                    outcome,
                    http_status,
                    error_reason,
                    iso_with_offset(_as_utc(completed_at)) if outcome != "attempted" else None,
                    reservation.event_key,
                ),
            )
            if outcome == "failed":
                connection.execute(
                    """
                    UPDATE youtube_quota_daily
                    SET last_http_status=?, last_error_reason=?, last_error_method=?, updated_at=?
                    WHERE quota_date=? AND bucket=?
                    """,
                    (
                        http_status,
                        error_reason,
                        reservation.method,
                        iso_with_offset(_as_utc(completed_at)),
                        reservation.quota_date,
                        reservation.bucket,
                    ),
                )

    def record_google_quota_exhausted(self, reservation: QuotaReservation, exc: BaseException) -> None:
        info = parse_youtube_error(exc, method=reservation.method)
        reset = reservation.reset_at
        now = datetime.now(timezone.utc)
        with self.db.transaction() as connection:
            connection.execute(
                """
                UPDATE youtube_quota_events
                SET outcome='failed', http_status=?, error_reason=?, completed_at=?
                WHERE event_key=?
                """,
                (info.http_status, "quotaExceeded", iso_with_offset(now), reservation.event_key),
            )
            connection.execute(
                """
                UPDATE youtube_quota_daily
                SET state='confirmed_exhausted', blocked_reason='quotaExceeded', blocked_until=?,
                    confirmed_exhausted_at=?, last_http_status=?, last_error_reason='quotaExceeded',
                    last_error_method=?, updated_at=?
                WHERE quota_date=? AND bucket=?
                """,
                (
                    reset,
                    iso_with_offset(now),
                    info.http_status,
                    reservation.method,
                    iso_with_offset(now),
                    reservation.quota_date,
                    reservation.bucket,
                ),
            )

    def execute(
        self,
        request: Any,
        method: str,
        *,
        task_id: Optional[str] = None,
        batch_id: Optional[str] = None,
        operation: Optional[str] = None,
        now: datetime | None = None,
    ) -> Any:
        reservation = self.reserve(
            method,
            task_id=task_id,
            batch_id=batch_id,
            operation=operation,
            now=now,
        )
        try:
            response = request.execute()
        except Exception as exc:
            info = parse_youtube_error(exc, method=method)
            if info.http_status == 403 and info.reason == "quotaExceeded":
                self.record_google_quota_exhausted(reservation, exc)
                raise self._unavailable(
                    code="youtube_quota_exhausted",
                    method=method,
                    reset_at=reservation.reset_at,
                    reason="quotaExceeded",
                    confirmed=True,
                    http_status=403,
                    message="Google 已回報今日 YouTube API 配額用完。",
                ) from exc
            try:
                self.complete(
                    reservation,
                    outcome="failed",
                    http_status=info.http_status,
                    error_reason=info.reason or type(exc).__name__,
                )
            except Exception:
                logger.exception("Unable to complete YouTube quota event after request failure")
            raise
        self.complete(reservation, outcome="succeeded")
        return response

    def record(self, method: str, calls: int = 1) -> dict[str, Any]:
        """Compatibility helper that records already-issued requests.

        New call sites must use :meth:`execute`; this helper exists so older
        integrations still use the same SQLite ledger and fail closed for an
        unknown method.
        """

        for _ in range(max(int(calls), 0)):
            reservation = self.reserve(method)
            self.complete(reservation, outcome="succeeded")
        return self.get_usage()

    def _methods(self, connection, quota_date: str) -> list[dict[str, Any]]:
        rows = connection.execute(
            """
            SELECT method, documented_cost, COUNT(*) AS calls,
                   SUM(documented_cost) AS units,
                   SUM(CASE WHEN outcome='succeeded' THEN 1 ELSE 0 END) AS succeeded_calls,
                   SUM(CASE WHEN outcome='failed' THEN 1 ELSE 0 END) AS failed_calls
            FROM youtube_quota_events
            WHERE quota_date=? AND bucket=? AND outcome IN ('attempted','succeeded','failed')
            GROUP BY method, documented_cost ORDER BY method
            """,
            (quota_date, GENERAL_BUCKET),
        ).fetchall()
        return [
            {
                "method": str(row["method"]),
                "calls": int(row["calls"] or 0),
                "units": int(row["units"] or 0),
                "cost_per_call": int(row["documented_cost"] or 0),
                "succeeded_calls": int(row["succeeded_calls"] or 0),
                "failed_calls": int(row["failed_calls"] or 0),
            }
            for row in rows
        ]

    def _format_usage(self, connection, row: Any, *, now: datetime | None = None) -> dict[str, Any]:
        current_utc = _as_utc(now)
        limit, buffer = self.configured_values()
        used = int(row["estimated_used_units"] or 0)
        policy_cap = max(limit - buffer, 0)
        confirmed = str(row["state"]) == "confirmed_exhausted"
        safety_blocked = str(row["state"]) == "safety_blocked" and self._is_breaker_active(row, current_utc)
        effective = 0 if confirmed or safety_blocked else max(policy_cap - used, 0)
        waiting = connection.execute(
            """
            SELECT COUNT(*) AS count, COUNT(DISTINCT batch_id) AS batches
            FROM tasks
            WHERE platform='youtube' AND status='queued' AND stage='waiting_youtube_quota'
              AND next_attempt_at IS NOT NULL AND julianday(next_attempt_at) > julianday(?)
            """,
            (iso_with_offset(current_utc),),
        ).fetchone()
        return {
            "quota_date": row["quota_date"],
            "bucket": row["bucket"],
            "state": row["state"],
            "official_default_limit": OFFICIAL_DEFAULT_LIMIT,
            "configured_project_limit": limit,
            "estimated_used_units": used,
            "estimated_remaining_units": max(limit - used, 0),
            "safety_buffer_units": buffer,
            "policy_cap_units": policy_cap,
            "effective_available_units": effective,
            "usage_percent": round((used / limit * 100), 2) if limit else 0,
            "confirmed_by_google": confirmed,
            "blocked_reason": row["blocked_reason"],
            "blocked_until": row["blocked_until"],
            "confirmed_exhausted_at": row["confirmed_exhausted_at"],
            "last_http_status": row["last_http_status"],
            "last_error_reason": row["last_error_reason"],
            "last_error_method": row["last_error_method"],
            "reset_at": iso_with_offset(next_reset_at(current_utc)),
            "reset_timezone": RESET_TIMEZONE,
            "waiting_task_count": int(waiting["count"] or 0),
            "affected_batch_count": int(waiting["batches"] or 0),
            "methods": self._methods(connection, str(row["quota_date"])),
            "is_estimate": True,
            "calculation_basis": "official-per-request-method-cost",
            "quota_source_url": QUOTA_SOURCE_URL,
            "quota_rules_last_updated_at": QUOTA_RULES_LAST_UPDATED_AT,
            "quota_rules_verified_at": QUOTA_RULES_VERIFIED_AT,
            # Old clients can continue rendering while new clients use the
            # explicitly named fields above.
            "daily_limit": limit,
            "used_units": used,
            "remaining_units": max(limit - used, 0),
            "quota_costs_verified_at": QUOTA_RULES_VERIFIED_AT,
            "note": (
                "本數字只統計 Creator Tools 送出的 YouTube request，屬於本地估算；"
                "同一 Google Cloud project 的其他應用程式可能也會消耗官方額度。"
            ),
        }

    def get_usage(self, now: datetime | None = None) -> dict[str, Any]:
        current_utc = _as_utc(now)
        quota_date = quota_date_for(current_utc)
        with self.db.transaction() as connection:
            row = self._ensure_daily_row(connection, quota_date, current_utc)
            limit, buffer = self.configured_values()
            if str(row["state"]) in {"normal", "warning"} and int(row["estimated_used_units"] or 0) >= max(
                limit - buffer, 0
            ):
                reset = iso_with_offset(next_reset_at(current_utc))
                connection.execute(
                    """
                    UPDATE youtube_quota_daily
                    SET state='safety_blocked', blocked_reason='safety_cap_reached', blocked_until=?, updated_at=?
                    WHERE quota_date=? AND bucket=? AND state IN ('normal','warning')
                    """,
                    (reset, iso_with_offset(current_utc), quota_date, GENERAL_BUCKET),
                )
                row = connection.execute(
                    "SELECT * FROM youtube_quota_daily WHERE quota_date=? AND bucket=?",
                    (quota_date, GENERAL_BUCKET),
                ).fetchone()
            return self._format_usage(connection, row, now=current_utc)

    def assert_can_spend(self, units: int, *, now: datetime | None = None) -> dict[str, Any]:
        usage = self.get_usage(now=now)
        if int(units) > int(usage["effective_available_units"]):
            raise self._unavailable(
                code=("youtube_quota_exhausted" if usage["confirmed_by_google"] else "youtube_quota_safety_blocked"),
                method="batch-estimate",
                reset_at=str(usage["reset_at"]),
                reason=str(usage.get("blocked_reason") or "safety_cap_reached"),
                confirmed=bool(usage["confirmed_by_google"]),
                message=(
                    "Google 已回報今日 YouTube API 配額用完。"
                    if usage["confirmed_by_google"]
                    else "Creator Tools 今日安全可用額度不足，超出的工作將自動跨日續跑。"
                ),
            )
        return usage


youtube_quota_limiter = YouTubeQuotaLimiter()


__all__ = [
    "DEFAULT_DAILY_LIMIT",
    "DEFAULT_SAFETY_BUFFER_UNITS",
    "GENERAL_BUCKET",
    "LEGACY_QUOTA_FILE",
    "OFFICIAL_DEFAULT_LIMIT",
    "PACIFIC",
    "QUOTA_COSTS",
    "QUOTA_COSTS_VERIFIED_AT",
    "QUOTA_RULES_LAST_UPDATED_AT",
    "QUOTA_RULES_VERIFIED_AT",
    "QUOTA_SOURCE_URL",
    "YOUTUBE_QUOTA_METHODS",
    "QuotaReservation",
    "YouTubeQuotaContext",
    "YouTubeQuotaLimiter",
    "current_youtube_quota_context",
    "iso_with_offset",
    "next_reset_at",
    "quota_date_for",
    "youtube_quota_context",
    "youtube_quota_limiter",
]
