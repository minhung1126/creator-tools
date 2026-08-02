"""Compatibility facade for the JSON-backed YouTube quota ledger."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.app.core.youtube_quota_limiter import (
    DEFAULT_DAILY_LIMIT,
    LEGACY_QUOTA_FILE,
    LEGACY_SQLITE_FILE,
    OFFICIAL_DEFAULT_LIMIT,
    QUOTA_COSTS,
    QUOTA_COSTS_VERIFIED_AT,
    QUOTA_RULES_VERIFIED_AT,
    QUOTA_SOURCE_URL,
    YOUTUBE_QUOTA_METHODS,
    YouTubeQuotaLimiter,
    next_reset_at,
    quota_date_for,
)


class YouTubeQuotaTracker:
    """Keep the existing import surface while delegating to the JSON ledger."""

    def __init__(
        self,
        path: str | Path = LEGACY_QUOTA_FILE,
        daily_limit: int | None = None,
        *,
        sqlite_path: str | Path = LEGACY_SQLITE_FILE,
        safety_buffer_units: int | None = None,
    ) -> None:
        self.limiter = YouTubeQuotaLimiter(
            path,
            sqlite_path=sqlite_path,
            configured_limit=daily_limit,
            safety_buffer_units=safety_buffer_units,
        )

    @staticmethod
    def _quota_date(now=None) -> str:
        return quota_date_for(now)

    @staticmethod
    def _next_reset(now=None):
        return next_reset_at(now)

    def record(self, method: str, calls: int = 1) -> dict[str, Any]:
        return self.limiter.record(method, calls)

    def execute(self, request: Any, method: str, **kwargs: Any) -> Any:
        return self.limiter.execute(request, method, **kwargs)

    def get_usage(self, now=None) -> dict[str, Any]:
        return self.limiter.get_usage(now=now)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.limiter, name)


youtube_quota_tracker = YouTubeQuotaTracker()


__all__ = [
    "DEFAULT_DAILY_LIMIT",
    "OFFICIAL_DEFAULT_LIMIT",
    "QUOTA_COSTS",
    "QUOTA_COSTS_VERIFIED_AT",
    "QUOTA_RULES_VERIFIED_AT",
    "QUOTA_SOURCE_URL",
    "YOUTUBE_QUOTA_METHODS",
    "YouTubeQuotaLimiter",
    "YouTubeQuotaTracker",
    "youtube_quota_tracker",
]
