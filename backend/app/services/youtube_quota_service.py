"""Application-wide YouTube quota ledger."""

from __future__ import annotations

from backend.app.core.youtube_quota_limiter import (
    DEFAULT_SAFETY_BUFFER_UNITS,
    JSON_SCHEMA_VERSION,
    OFFICIAL_DEFAULT_LIMIT,
    QUOTA_COSTS,
    QUOTA_FILE,
    QUOTA_RULES_VERIFIED_AT,
    QUOTA_SOURCE_URL,
    YOUTUBE_QUOTA_METHODS,
    YouTubeQuotaLimiter,
)

youtube_quota_tracker = YouTubeQuotaLimiter(QUOTA_FILE)


__all__ = [
    "DEFAULT_SAFETY_BUFFER_UNITS",
    "JSON_SCHEMA_VERSION",
    "OFFICIAL_DEFAULT_LIMIT",
    "QUOTA_COSTS",
    "QUOTA_FILE",
    "QUOTA_RULES_VERIFIED_AT",
    "QUOTA_SOURCE_URL",
    "YOUTUBE_QUOTA_METHODS",
    "YouTubeQuotaLimiter",
    "youtube_quota_tracker",
]
