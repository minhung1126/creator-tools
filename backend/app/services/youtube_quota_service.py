"""Application-wide YouTube quota ledger."""

from __future__ import annotations

from backend.app.core.youtube_quota_limiter import (
    DEFAULT_SAFETY_BUFFER_UNITS,
    JSON_SCHEMA_VERSION,
    OFFICIAL_DEFAULT_LIMIT,
    QUOTA_COSTS,
    QUOTA_FILE,
    QUOTA_FILE_SECONDARY,
    QUOTA_RULES_VERIFIED_AT,
    QUOTA_SOURCE_URL,
    YOUTUBE_AUXILIARY_QUOTA_METHODS,
    YOUTUBE_QUOTA_METHODS,
    YouTubeQuotaLimiter,
)

_youtube_quota_trackers: dict[str, YouTubeQuotaLimiter] = {
    "primary": YouTubeQuotaLimiter(QUOTA_FILE, slot="primary"),
    "secondary": YouTubeQuotaLimiter(QUOTA_FILE_SECONDARY, slot="secondary"),
}

# Backwards-compatible primary alias. New code should resolve the tracker from
# the request context so a token and its ledger can never be mixed.
youtube_quota_tracker = _youtube_quota_trackers["primary"]


def get_youtube_quota_tracker(slot: str = "primary") -> YouTubeQuotaLimiter:
    slot_name = str(slot or "").strip().casefold()
    if slot_name not in _youtube_quota_trackers:
        raise ValueError("YouTube quota slot must be primary or secondary")
    return _youtube_quota_trackers[slot_name]


__all__ = [
    "DEFAULT_SAFETY_BUFFER_UNITS",
    "JSON_SCHEMA_VERSION",
    "OFFICIAL_DEFAULT_LIMIT",
    "QUOTA_COSTS",
    "QUOTA_FILE",
    "QUOTA_FILE_SECONDARY",
    "QUOTA_RULES_VERIFIED_AT",
    "QUOTA_SOURCE_URL",
    "YOUTUBE_QUOTA_METHODS",
    "YOUTUBE_AUXILIARY_QUOTA_METHODS",
    "YouTubeQuotaLimiter",
    "get_youtube_quota_tracker",
    "youtube_quota_tracker",
]
