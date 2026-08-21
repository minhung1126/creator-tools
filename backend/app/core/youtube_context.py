"""Request-scoped YouTube credentials, slot and quota ledger."""

from __future__ import annotations

from dataclasses import dataclass

from google.oauth2.credentials import Credentials

from backend.app.core.config import normalize_youtube_slot
from backend.app.core.youtube_quota_limiter import YouTubeQuotaLimiter


@dataclass(frozen=True)
class YouTubeRequestContext:
    """The YouTube resources selected for one operation boundary.

    A workflow starts with one context. Auto mode may construct a second
    context only after a quota failure, then retry the single failed operation
    on the other verified slot; ordinary account-setting changes never mutate
    an in-flight context.
    """

    slot: str
    credentials: Credentials
    quota_limiter: YouTubeQuotaLimiter
    owner_sub: str
    channel_id: str | None = None
    routing_mode: str = "manual"
    selection_reason: str = "manual_active_slot"
    estimated_units: int = 0
    preferred_slot: str = "primary"
    session_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "slot", normalize_youtube_slot(self.slot))


__all__ = ["YouTubeRequestContext"]
