"""Persistent request-level estimate of YouTube Data API quota usage."""

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Dict
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_DATA_DIR = _PROJECT_ROOT / "data"
_QUOTA_FILE = _DATA_DIR / "youtube_quota_usage.json"
_PACIFIC = ZoneInfo("America/Los_Angeles")

# Official YouTube Data API v3 quota costs for every method currently called by
# this application. Costs are per HTTP request, not per returned item. That
# means pagination and videos.list batches of at most 50 IDs each count as
# separate requests.
QUOTA_COSTS = {
    "playlistItems.list": 1,
    "videos.list": 1,
    "videos.update": 50,
    "playlistItems.delete": 50,
}

QUOTA_SOURCE_URL = "https://developers.google.com/youtube/v3/determine_quota_cost"
QUOTA_COSTS_VERIFIED_AT = "2026-08-01"
DEFAULT_DAILY_LIMIT = 10_000


class YouTubeQuotaTracker:
    """Thread-safe JSON-backed tracker for requests sent by this application."""

    def __init__(self, path: Path = _QUOTA_FILE, daily_limit: int = DEFAULT_DAILY_LIMIT):
        self._path = path
        self._daily_limit = daily_limit
        self._lock = Lock()

    @staticmethod
    def _quota_date(now: datetime | None = None) -> str:
        current = now or datetime.now(timezone.utc)
        return current.astimezone(_PACIFIC).date().isoformat()

    @staticmethod
    def _next_reset(now: datetime | None = None) -> datetime:
        current = (now or datetime.now(timezone.utc)).astimezone(_PACIFIC)
        next_day = current.date() + timedelta(days=1)
        return datetime.combine(next_day, datetime.min.time(), tzinfo=_PACIFIC)

    def _empty_data(self, quota_date: str) -> Dict[str, Any]:
        return {
            "quota_date": quota_date,
            "daily_limit": self._daily_limit,
            "used_units": 0,
            "methods": {},
            "updated_at": None,
        }

    def _load_unlocked(self) -> Dict[str, Any]:
        quota_date = self._quota_date()
        if not self._path.is_file():
            return self._empty_data(quota_date)

        try:
            with self._path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Failed to load YouTube quota usage: %s", exc)
            return self._empty_data(quota_date)

        if data.get("quota_date") != quota_date:
            return self._empty_data(quota_date)

        data.setdefault("daily_limit", self._daily_limit)
        data.setdefault("used_units", 0)
        data.setdefault("methods", {})
        data.setdefault("updated_at", None)
        return data

    def _save_unlocked(self, data: Dict[str, Any]) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self._path.with_suffix(".tmp")
            with tmp_path.open("w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            tmp_path.replace(self._path)
        except OSError as exc:
            logger.error("Failed to persist YouTube quota usage: %s", exc)

    def record(self, method: str, calls: int = 1) -> Dict[str, Any]:
        """Record requests using Google's documented per-request method cost."""
        if calls <= 0:
            return self.get_usage()

        cost_per_call = QUOTA_COSTS.get(method)
        if cost_per_call is None:
            # Do not silently invent a cost. New API methods must be added from
            # the official quota table before they can be tracked accurately.
            logger.error("Unknown YouTube quota method was not recorded: %s", method)
            return self.get_usage()

        with self._lock:
            data = self._load_unlocked()
            units = cost_per_call * calls
            method_data = data["methods"].setdefault(
                method,
                {"calls": 0, "units": 0, "cost_per_call": cost_per_call},
            )
            # Refresh the displayed cost if an official method cost changes in
            # a future release while retaining today's accumulated totals.
            method_data["cost_per_call"] = cost_per_call
            method_data["calls"] += calls
            method_data["units"] += units
            data["used_units"] += units
            data["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._save_unlocked(data)
            return self._format_usage(data)

    def get_usage(self) -> Dict[str, Any]:
        with self._lock:
            return self._format_usage(self._load_unlocked())

    def _format_usage(self, data: Dict[str, Any]) -> Dict[str, Any]:
        used = int(data.get("used_units", 0))
        limit = int(data.get("daily_limit", self._daily_limit))
        return {
            "quota_date": data.get("quota_date", self._quota_date()),
            "daily_limit": limit,
            "used_units": used,
            "remaining_units": max(limit - used, 0),
            "usage_percent": round((used / limit * 100), 2) if limit else 0,
            "methods": [
                {"method": method, **values}
                for method, values in sorted(data.get("methods", {}).items())
            ],
            "updated_at": data.get("updated_at"),
            "reset_at": self._next_reset().isoformat(),
            "reset_timezone": "America/Los_Angeles",
            "is_estimate": True,
            "calculation_basis": "official-per-request-method-cost",
            "quota_source_url": QUOTA_SOURCE_URL,
            "quota_costs_verified_at": QUOTA_COSTS_VERIFIED_AT,
            "note": (
                "依 YouTube 官方各方法的每次 request 配額成本計算；分頁與每 50 部影片一批的 "
                "videos.list 都分別計次。僅統計此系統送出的請求，不含同一 Google Cloud 專案的其他應用程式。"
            ),
        }


youtube_quota_tracker = YouTubeQuotaTracker()
