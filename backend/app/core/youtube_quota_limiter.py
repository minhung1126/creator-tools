"""JSON-backed YouTube Data API quota ledger and request guard.

The ledger is deliberately an estimate of requests made by Creator Tools. It
is not a Cloud Console usage feed: other applications in the same Google
Cloud project can consume the same official bucket.

The production image runs one Uvicorn process. Instances that point at the
same path therefore share an in-process lock, while every reservation is
atomically persisted before its request is sent. The JSON store is not a
multi-process coordination mechanism.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from threading import Lock, RLock
from typing import Any, Mapping
from uuid import uuid4
from zoneinfo import ZoneInfo

from backend.app.core.runtime_config import runtime_config
from backend.app.services.youtube_errors import YouTubeQuotaUnavailable, parse_youtube_error

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = PROJECT_ROOT / "data"
QUOTA_FILE = DATA_DIR / "youtube_quota_usage.json"
LEGACY_QUOTA_FILE = QUOTA_FILE
LEGACY_SQLITE_FILE = DATA_DIR / "creator_tools.db"
JSON_SCHEMA_VERSION = 2

PACIFIC = ZoneInfo("America/Los_Angeles")
RESET_TIMEZONE = "America/Los_Angeles"
GENERAL_BUCKET = "general"
OFFICIAL_DEFAULT_LIMIT = 10_000
DEFAULT_SAFETY_BUFFER_UNITS = 1_000
QUOTA_SOURCE_URL = "https://developers.google.com/youtube/v3/determine_quota_cost"
QUOTA_RULES_LAST_UPDATED_AT = "2026-06-01"
QUOTA_RULES_VERIFIED_AT = "2026-08-02"

YOUTUBE_QUOTA_METHODS: dict[str, dict[str, Any]] = {
    "playlistItems.list": {"bucket": GENERAL_BUCKET, "cost": 1},
    "videos.list": {"bucket": GENERAL_BUCKET, "cost": 1},
    "videos.update": {"bucket": GENERAL_BUCKET, "cost": 50},
    "playlistItems.delete": {"bucket": GENERAL_BUCKET, "cost": 50},
}

QUOTA_COSTS = {method: int(meta["cost"]) for method, meta in YOUTUBE_QUOTA_METHODS.items()}
DEFAULT_DAILY_LIMIT = OFFICIAL_DEFAULT_LIMIT
QUOTA_COSTS_VERIFIED_AT = QUOTA_RULES_VERIFIED_AT

_PATH_LOCKS: dict[str, RLock] = {}
_PATH_LOCKS_GUARD = Lock()


class _QuotaStorageError(RuntimeError):
    pass


def _path_lock(path: Path) -> RLock:
    key = str(path.resolve())
    with _PATH_LOCKS_GUARD:
        return _PATH_LOCKS.setdefault(key, RLock())


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


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _stored_int(value: Any, field: str, default: int = 0) -> int:
    if value is None:
        return default
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise _QuotaStorageError(f"{field} must be an integer") from exc
    if result < 0:
        raise _QuotaStorageError(f"{field} must not be negative")
    return result


@dataclass(frozen=True)
class QuotaReservation:
    event_key: str
    quota_date: str
    bucket: str
    method: str
    documented_cost: int
    reset_at: str


class YouTubeQuotaLimiter:
    """Persist request reservations in one atomically replaced JSON file."""

    def __init__(
        self,
        path: str | Path = QUOTA_FILE,
        *,
        sqlite_path: str | Path = LEGACY_SQLITE_FILE,
        configured_limit: int | None = None,
        safety_buffer_units: int | None = None,
        daily_limit: int | None = None,
    ) -> None:
        self.path = Path(path)
        self.sqlite_path = Path(sqlite_path)
        self._configured_limit_override = configured_limit if configured_limit is not None else daily_limit
        self._safety_buffer_override = safety_buffer_units
        self._lock = _path_lock(self.path)

    def configured_values(self) -> tuple[int, int]:
        limit = self._configured_limit_override
        if limit is None:
            limit = runtime_config.get("youtube_general_quota_limit", OFFICIAL_DEFAULT_LIMIT)
        buffer = self._safety_buffer_override
        if buffer is None:
            buffer = runtime_config.get("youtube_quota_safety_buffer_units", DEFAULT_SAFETY_BUFFER_UNITS)
        limit = max(_safe_int(limit, OFFICIAL_DEFAULT_LIMIT), 1)
        buffer = max(_safe_int(buffer, DEFAULT_SAFETY_BUFFER_UNITS), 0)
        buffer = min(buffer, max(limit - 1, 0))
        return limit, buffer

    @staticmethod
    def quota_date(now: datetime | None = None) -> str:
        return quota_date_for(now)

    @staticmethod
    def next_reset(now: datetime | None = None) -> datetime:
        return next_reset_at(now)

    def _unavailable(
        self,
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

    def _storage_unavailable(self, method: str, now: datetime | None = None) -> YouTubeQuotaUnavailable:
        return self._unavailable(
            code="youtube_quota_storage_unavailable",
            method=method,
            reset_at=iso_with_offset(next_reset_at(now)),
            reason="quota_store_unavailable",
            confirmed=False,
            message="YouTube 配額紀錄目前無法安全讀寫，系統已阻止新的請求。",
        )

    def _empty_data(
        self,
        quota_date: str,
        now: datetime,
        *,
        migration: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        limit, _buffer = self.configured_values()
        data: dict[str, Any] = {
            "schema_version": JSON_SCHEMA_VERSION,
            "quota_date": quota_date,
            "bucket": GENERAL_BUCKET,
            "configured_limit": limit,
            "estimated_used_units": 0,
            "state": "normal",
            "blocked_reason": None,
            "blocked_until": None,
            "confirmed_exhausted_at": None,
            "last_http_status": None,
            "last_error_reason": None,
            "last_error_method": None,
            "methods": {},
            "updated_at": iso_with_offset(_as_utc(now)),
        }
        if migration:
            data["migration"] = dict(migration)
        return data

    @staticmethod
    def _normalize_methods(value: Any) -> dict[str, dict[str, int]]:
        if isinstance(value, list):
            source = {
                str(item.get("method")): item
                for item in value
                if isinstance(item, dict) and str(item.get("method") or "")
            }
        elif isinstance(value, dict):
            source = value
        else:
            raise _QuotaStorageError("methods must be an object or list")

        methods: dict[str, dict[str, int]] = {}
        for method, raw in source.items():
            if not isinstance(raw, dict):
                raise _QuotaStorageError("method statistics must be objects")
            name = str(method)
            configured_cost = int(YOUTUBE_QUOTA_METHODS.get(name, {}).get("cost", 0))
            cost = _stored_int(raw.get("cost_per_call", raw.get("documented_cost")), f"{name}.cost", configured_cost)
            calls = _stored_int(raw.get("calls"), f"{name}.calls")
            units = _stored_int(raw.get("units"), f"{name}.units", cost * calls)
            methods[name] = {
                "cost_per_call": cost,
                "calls": calls,
                "units": units,
                "succeeded_calls": _stored_int(raw.get("succeeded_calls"), f"{name}.succeeded_calls", calls),
                "failed_calls": _stored_int(raw.get("failed_calls"), f"{name}.failed_calls"),
            }
        return methods

    def _normalize_data(self, raw: Any, quota_date: str, now: datetime) -> tuple[dict[str, Any], bool]:
        if not isinstance(raw, dict):
            raise _QuotaStorageError("quota JSON root must be an object")
        saved_date = str(raw.get("quota_date") or "")
        if not saved_date:
            raise _QuotaStorageError("quota_date is missing")
        if saved_date != quota_date:
            return self._empty_data(quota_date, now), True

        limit, _buffer = self.configured_values()
        state = str(raw.get("state") or "normal")
        if state not in {"normal", "warning", "safety_blocked", "confirmed_exhausted"}:
            raise _QuotaStorageError("invalid quota state")
        used = _stored_int(raw.get("estimated_used_units", raw.get("used_units")), "estimated_used_units")
        methods = self._normalize_methods(raw.get("methods", {}))
        data = {
            "schema_version": JSON_SCHEMA_VERSION,
            "quota_date": quota_date,
            "bucket": str(raw.get("bucket") or GENERAL_BUCKET),
            "configured_limit": limit,
            "estimated_used_units": used,
            "state": state,
            "blocked_reason": raw.get("blocked_reason"),
            "blocked_until": raw.get("blocked_until"),
            "confirmed_exhausted_at": raw.get("confirmed_exhausted_at"),
            "last_http_status": raw.get("last_http_status"),
            "last_error_reason": raw.get("last_error_reason"),
            "last_error_method": raw.get("last_error_method"),
            "methods": methods,
            "updated_at": raw.get("updated_at") or iso_with_offset(_as_utc(now)),
        }
        if isinstance(raw.get("migration"), dict):
            data["migration"] = dict(raw["migration"])
        changed = data != raw
        return data, changed

    def _sqlite_tables(self, connection: sqlite3.Connection) -> set[str]:
        return {
            str(row[0])
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }

    def _import_sqlite_unlocked(self, quota_date: str, now: datetime) -> dict[str, Any] | None:
        if not self.sqlite_path.is_file():
            return None
        try:
            uri = f"{self.sqlite_path.resolve().as_uri()}?mode=ro"
            connection = sqlite3.connect(uri, uri=True)
            connection.row_factory = sqlite3.Row
            try:
                tables = self._sqlite_tables(connection)
                if "youtube_quota_daily" not in tables:
                    return None
                row = connection.execute(
                    "SELECT * FROM youtube_quota_daily WHERE quota_date=? AND bucket=?",
                    (quota_date, GENERAL_BUCKET),
                ).fetchone()
                schema_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
                if row is None:
                    return None

                methods: dict[str, dict[str, int]] = {}
                if "youtube_quota_events" in tables:
                    event_rows = connection.execute(
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
                    methods = {
                        str(event["method"]): {
                            "cost_per_call": int(event["documented_cost"] or 0),
                            "calls": int(event["calls"] or 0),
                            "units": int(event["units"] or 0),
                            "succeeded_calls": int(event["succeeded_calls"] or 0),
                            "failed_calls": int(event["failed_calls"] or 0),
                        }
                        for event in event_rows
                    }
                limit, _buffer = self.configured_values()
                return {
                    "schema_version": JSON_SCHEMA_VERSION,
                    "quota_date": quota_date,
                    "bucket": str(row["bucket"] or GENERAL_BUCKET),
                    "configured_limit": limit,
                    "estimated_used_units": max(int(row["estimated_used_units"] or 0), 0),
                    "state": str(row["state"] or "normal"),
                    "blocked_reason": row["blocked_reason"],
                    "blocked_until": row["blocked_until"],
                    "confirmed_exhausted_at": row["confirmed_exhausted_at"],
                    "last_http_status": row["last_http_status"],
                    "last_error_reason": row["last_error_reason"],
                    "last_error_method": row["last_error_method"],
                    "methods": methods,
                    "updated_at": row["updated_at"] or iso_with_offset(_as_utc(now)),
                    "migration": {
                        "sqlite_imported_at": iso_with_offset(_as_utc(now)),
                        "sqlite_schema_version": schema_version,
                    },
                }
            finally:
                connection.close()
        except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
            raise _QuotaStorageError(f"unable to import legacy SQLite quota: {type(exc).__name__}") from exc

    def _save_unlocked(self, data: Mapping[str, Any]) -> None:
        temp_path = self.path.with_name(f".{self.path.name}.{os.getpid()}.{uuid4().hex}.tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with temp_path.open("w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, self.path)
        except (OSError, TypeError, ValueError) as exc:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise _QuotaStorageError(f"unable to persist quota JSON: {type(exc).__name__}") from exc

    def _load_current_unlocked(self, now: datetime) -> dict[str, Any]:
        quota_date = quota_date_for(now)
        if not self.path.is_file():
            data = self._import_sqlite_unlocked(quota_date, now) or self._empty_data(quota_date, now)
            self._save_unlocked(data)
            return data
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                raw = json.load(handle)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise _QuotaStorageError(f"unable to read quota JSON: {type(exc).__name__}") from exc
        # Pre-SQLite releases may have left this legacy JSON beside a newer
        # SQLite ledger.  Only a current-schema JSON file is authoritative;
        # otherwise prefer today's SQLite aggregate without adding the two.
        if raw.get("schema_version") != JSON_SCHEMA_VERSION:
            imported = self._import_sqlite_unlocked(quota_date, now)
            if imported is not None:
                self._save_unlocked(imported)
                return imported
        data, changed = self._normalize_data(raw, quota_date, now)
        if changed:
            self._save_unlocked(data)
        return data

    @staticmethod
    def _is_breaker_active(data: Mapping[str, Any], now: datetime) -> bool:
        blocked_until = data.get("blocked_until")
        if not blocked_until:
            return False
        try:
            until = datetime.fromisoformat(str(blocked_until))
            if until.tzinfo is None:
                until = until.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            return True
        return until > _as_utc(now)

    def reserve(
        self,
        method: str,
        *,
        now: datetime | None = None,
    ) -> QuotaReservation:
        meta = YOUTUBE_QUOTA_METHODS.get(method)
        current_utc = _as_utc(now)
        reset = iso_with_offset(next_reset_at(current_utc))
        quota_date = quota_date_for(current_utc)
        if meta is None:
            logger.error("Unknown YouTube quota method blocked before request: %s", method)
            raise self._unavailable(
                code="youtube_quota_unknown_method",
                method=method,
                reset_at=reset,
                reason="unknown_method",
                confirmed=False,
                message="YouTube API method 尚未加入官方配額成本設定，系統已阻止此請求。",
            )

        cost = int(meta["cost"])
        with self._lock:
            try:
                data = self._load_current_unlocked(current_utc)
                limit, buffer = self.configured_values()
                used = int(data["estimated_used_units"] or 0)
                policy_cap = max(limit - buffer, 0)
                if str(data["state"]) == "confirmed_exhausted":
                    raise self._unavailable(
                        code="youtube_quota_exhausted",
                        method=method,
                        reset_at=reset,
                        reason=str(data.get("last_error_reason") or "quotaExceeded"),
                        confirmed=True,
                        message="Google 已回報今日 YouTube API 配額用完。",
                    )
                if self._is_breaker_active(data, current_utc):
                    raise self._unavailable(
                        code="youtube_quota_safety_blocked",
                        method=method,
                        reset_at=reset,
                        reason=str(data.get("blocked_reason") or "safety_cap_reached"),
                        confirmed=False,
                        message="Creator Tools 已達 YouTube API 安全上限，新的請求將等待官方配額重設。",
                    )
                if used + cost > policy_cap:
                    data.update(
                        {
                            "state": "safety_blocked",
                            "blocked_reason": "safety_cap_reached",
                            "blocked_until": reset,
                            "last_error_method": method,
                            "updated_at": iso_with_offset(current_utc),
                        }
                    )
                    self._save_unlocked(data)
                    raise self._unavailable(
                        code="youtube_quota_safety_blocked",
                        method=method,
                        reset_at=reset,
                        reason="safety_cap_reached",
                        confirmed=False,
                        message="Creator Tools 已達 YouTube API 安全上限，新的請求將等待官方配額重設。",
                    )

                next_used = used + cost
                method_data = data["methods"].setdefault(
                    method,
                    {
                        "cost_per_call": cost,
                        "calls": 0,
                        "units": 0,
                        "succeeded_calls": 0,
                        "failed_calls": 0,
                    },
                )
                method_data["cost_per_call"] = cost
                method_data["calls"] = int(method_data.get("calls") or 0) + 1
                method_data["units"] = int(method_data.get("units") or 0) + cost
                data.update(
                    {
                        "configured_limit": limit,
                        "estimated_used_units": next_used,
                        "state": "warning" if next_used >= max(int(limit * 0.8), 1) else "normal",
                        "blocked_reason": None,
                        "blocked_until": None,
                        "updated_at": iso_with_offset(current_utc),
                    }
                )
                self._save_unlocked(data)
            except _QuotaStorageError as exc:
                logger.error("YouTube quota storage unavailable during reservation: %s", exc)
                raise self._storage_unavailable(method, current_utc) from exc
        return QuotaReservation(uuid4().hex, quota_date, GENERAL_BUCKET, method, cost, reset)

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
        current_utc = _as_utc(completed_at)
        if quota_date_for(current_utc) != reservation.quota_date:
            return
        with self._lock:
            try:
                data = self._load_current_unlocked(current_utc)
                if str(data["quota_date"]) != reservation.quota_date:
                    return
                method_data = data["methods"].get(reservation.method)
                if not isinstance(method_data, dict):
                    return
                if outcome == "succeeded":
                    method_data["succeeded_calls"] = int(method_data.get("succeeded_calls") or 0) + 1
                elif outcome == "failed":
                    method_data["failed_calls"] = int(method_data.get("failed_calls") or 0) + 1
                    data["last_http_status"] = http_status
                    data["last_error_reason"] = error_reason
                    data["last_error_method"] = reservation.method
                data["updated_at"] = iso_with_offset(current_utc)
                self._save_unlocked(data)
            except _QuotaStorageError as exc:
                logger.error("YouTube quota outcome could not be persisted: %s", exc)
                raise self._storage_unavailable(reservation.method, current_utc) from exc

    def record_google_quota_exhausted(self, reservation: QuotaReservation, exc: BaseException) -> None:
        info = parse_youtube_error(exc, method=reservation.method)
        now = datetime.now(timezone.utc)
        if quota_date_for(now) != reservation.quota_date:
            return
        with self._lock:
            try:
                data = self._load_current_unlocked(now)
                if str(data["quota_date"]) != reservation.quota_date:
                    return
                method_data = data["methods"].get(reservation.method)
                if isinstance(method_data, dict):
                    method_data["failed_calls"] = int(method_data.get("failed_calls") or 0) + 1
                data.update(
                    {
                        "state": "confirmed_exhausted",
                        "blocked_reason": "quotaExceeded",
                        "blocked_until": reservation.reset_at,
                        "confirmed_exhausted_at": iso_with_offset(now),
                        "last_http_status": info.http_status,
                        "last_error_reason": "quotaExceeded",
                        "last_error_method": reservation.method,
                        "updated_at": iso_with_offset(now),
                    }
                )
                self._save_unlocked(data)
            except _QuotaStorageError as storage_exc:
                logger.error("Confirmed YouTube quota exhaustion could not be persisted: %s", storage_exc)
                raise self._storage_unavailable(reservation.method, now) from storage_exc

    def execute(
        self,
        request: Any,
        method: str,
        *,
        now: datetime | None = None,
    ) -> Any:
        reservation = self.reserve(method, now=now)
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
            except YouTubeQuotaUnavailable:
                logger.exception("Unable to persist YouTube quota outcome after request failure")
            raise
        try:
            self.complete(reservation, outcome="succeeded")
        except YouTubeQuotaUnavailable:
            # The reservation itself was durably written before the request.
            # Outcome counters are diagnostic, so avoid making a successful
            # external operation look retryable if only this second write fails.
            logger.exception("Unable to persist successful YouTube quota outcome")
        return response

    def record(self, method: str, calls: int = 1) -> dict[str, Any]:
        for _ in range(max(int(calls), 0)):
            reservation = self.reserve(method)
            self.complete(reservation, outcome="succeeded")
        return self.get_usage()

    @staticmethod
    def _method_list(data: Mapping[str, Any]) -> list[dict[str, Any]]:
        return [
            {"method": method, **dict(values)}
            for method, values in sorted(data.get("methods", {}).items())
            if isinstance(values, dict)
        ]

    def _format_usage(self, data: Mapping[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
        current_utc = _as_utc(now)
        limit, buffer = self.configured_values()
        used = int(data.get("estimated_used_units") or 0)
        policy_cap = max(limit - buffer, 0)
        confirmed = str(data.get("state")) == "confirmed_exhausted"
        safety_blocked = str(data.get("state")) == "safety_blocked" and self._is_breaker_active(data, current_utc)
        effective = 0 if confirmed or safety_blocked else max(policy_cap - used, 0)
        return {
            "quota_date": data.get("quota_date"),
            "bucket": data.get("bucket", GENERAL_BUCKET),
            "state": data.get("state", "normal"),
            "official_default_limit": OFFICIAL_DEFAULT_LIMIT,
            "configured_project_limit": limit,
            "estimated_used_units": used,
            "estimated_remaining_units": max(limit - used, 0),
            "safety_buffer_units": buffer,
            "policy_cap_units": policy_cap,
            "effective_available_units": effective,
            "usage_percent": round((used / limit * 100), 2) if limit else 0,
            "confirmed_by_google": confirmed,
            "blocked_reason": data.get("blocked_reason"),
            "blocked_until": data.get("blocked_until"),
            "confirmed_exhausted_at": data.get("confirmed_exhausted_at"),
            "last_http_status": data.get("last_http_status"),
            "last_error_reason": data.get("last_error_reason"),
            "last_error_method": data.get("last_error_method"),
            "reset_at": iso_with_offset(next_reset_at(current_utc)),
            "reset_timezone": RESET_TIMEZONE,
            "waiting_task_count": 0,
            "affected_batch_count": 0,
            "methods": self._method_list(data),
            "updated_at": data.get("updated_at"),
            "is_estimate": True,
            "calculation_basis": "official-per-request-method-cost",
            "quota_source_url": QUOTA_SOURCE_URL,
            "quota_rules_last_updated_at": QUOTA_RULES_LAST_UPDATED_AT,
            "quota_rules_verified_at": QUOTA_RULES_VERIFIED_AT,
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
        with self._lock:
            try:
                data = self._load_current_unlocked(current_utc)
                limit, buffer = self.configured_values()
                if str(data["state"]) in {"normal", "warning"} and int(
                    data.get("estimated_used_units") or 0
                ) >= max(limit - buffer, 0):
                    data.update(
                        {
                            "state": "safety_blocked",
                            "blocked_reason": "safety_cap_reached",
                            "blocked_until": iso_with_offset(next_reset_at(current_utc)),
                            "updated_at": iso_with_offset(current_utc),
                        }
                    )
                    self._save_unlocked(data)
                return self._format_usage(data, now=current_utc)
            except _QuotaStorageError as exc:
                logger.error("YouTube quota storage unavailable while reading usage: %s", exc)
                raise self._storage_unavailable("quota-usage", current_utc) from exc

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
                    else "Creator Tools 今日安全可用額度不足。"
                ),
            )
        return usage


__all__ = [
    "DEFAULT_DAILY_LIMIT",
    "DEFAULT_SAFETY_BUFFER_UNITS",
    "GENERAL_BUCKET",
    "JSON_SCHEMA_VERSION",
    "LEGACY_QUOTA_FILE",
    "LEGACY_SQLITE_FILE",
    "OFFICIAL_DEFAULT_LIMIT",
    "QUOTA_COSTS",
    "QUOTA_COSTS_VERIFIED_AT",
    "QUOTA_FILE",
    "QUOTA_RULES_LAST_UPDATED_AT",
    "QUOTA_RULES_VERIFIED_AT",
    "QUOTA_SOURCE_URL",
    "RESET_TIMEZONE",
    "YOUTUBE_QUOTA_METHODS",
    "QuotaReservation",
    "YouTubeQuotaLimiter",
    "next_reset_at",
    "quota_date_for",
]
