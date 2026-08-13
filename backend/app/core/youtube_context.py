"""Request-scoped YouTube credentials, slot and quota ledger."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from google.oauth2.credentials import Credentials

from backend.app.core.config import normalize_youtube_slot
from backend.app.core.youtube_quota_limiter import YouTubeQuotaLimiter
from backend.app.services.youtube_quota_service import get_youtube_quota_tracker


@dataclass(frozen=True)
class YouTubeRequestContext:
    """The immutable YouTube resources selected at request start.

    A workflow receives one instance for its whole lifetime. Changing the
    control-panel active slot therefore cannot move an in-flight batch to a
    different token or quota ledger.
    """

    slot: str
    credentials: Credentials
    quota_limiter: YouTubeQuotaLimiter
    channel_id: str | None = None
    owner_sub: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "slot", normalize_youtube_slot(self.slot))


def legacy_youtube_context(credentials: Any, slot: str = "primary") -> YouTubeRequestContext:
    """Adapt direct/unit-test callers that still pass only credentials."""
    slot_name = normalize_youtube_slot(slot)
    return YouTubeRequestContext(
        slot=slot_name,
        credentials=credentials,
        quota_limiter=get_youtube_quota_tracker(slot_name),
    )


def coerce_youtube_context(value: Any, slot: str = "primary") -> YouTubeRequestContext:
    if isinstance(value, YouTubeRequestContext):
        return value
    return legacy_youtube_context(value, slot=slot)


__all__ = ["YouTubeRequestContext", "coerce_youtube_context", "legacy_youtube_context"]
