"""Request-scoped YouTube credentials, slot and quota ledger."""

from __future__ import annotations

from dataclasses import dataclass

from google.oauth2.credentials import Credentials

from backend.app.core.config import normalize_youtube_slot
from backend.app.core.youtube_quota_limiter import YouTubeQuotaLimiter


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
    owner_sub: str
    channel_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "slot", normalize_youtube_slot(self.slot))


__all__ = ["YouTubeRequestContext"]
