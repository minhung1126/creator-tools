"""Compatibility facade for the SQLite-backed YouTube quota ledger."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.app.core.database import Database, database
from backend.app.core.youtube_quota_limiter import (
    DEFAULT_DAILY_LIMIT,
    LEGACY_QUOTA_FILE,
    OFFICIAL_DEFAULT_LIMIT,
    QUOTA_COSTS,
    QUOTA_COSTS_VERIFIED_AT,
    QUOTA_RULES_VERIFIED_AT,
    QUOTA_SOURCE_URL,
    YOUTUBE_QUOTA_METHODS,
    YouTubeQuotaLimiter,
    current_youtube_quota_context,
    next_reset_at,
    quota_date_for,
    youtube_quota_limiter,
)


class YouTubeQuotaTracker:
    """Keep the old import surface while delegating every operation to SQLite."""

    def __init__(
        self,
        path: str | Path = LEGACY_QUOTA_FILE,
        daily_limit: int | None = None,
        *,
        db: Database = database,
        safety_buffer_units: int | None = None,
    ) -> None:
        self.limiter = YouTubeQuotaLimiter(
            db,
            legacy_path=path,
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


# The application-wide instance is retained for callers that imported the
# previous tracker.  Task handlers can override it with a repository-scoped
# limiter through youtube_quota_context().
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
    "current_youtube_quota_context",
    "youtube_quota_limiter",
    "youtube_quota_tracker",
]
