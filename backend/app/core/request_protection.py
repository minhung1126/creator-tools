"""Small, process-local request protections for the dashboard API."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import RLock
from urllib.parse import urlparse

from fastapi import HTTPException, Request

from backend.app.core.config import settings


class _SlidingWindowLimiter:
    def __init__(self) -> None:
        self._events: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._lock = RLock()

    def check(self, key: str, bucket: str, limit: int, window_seconds: int = 60) -> None:
        now = time.monotonic()
        cutoff = now - window_seconds
        with self._lock:
            events = self._events[(key, bucket)]
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= limit:
                retry_after = max(1, int(events[0] + window_seconds - now) + 1)
                raise HTTPException(
                    status_code=429,
                    headers={"Retry-After": str(retry_after)},
                    detail={
                        "code": "rate_limited",
                        "message": "請求過於頻繁，請稍後再試。",
                    },
                )
            events.append(now)

            # Prevent attacker-controlled client identities from growing this
            # process-local map without bound.
            if len(self._events) > 4096:
                stale_keys = [
                    event_key
                    for event_key, event_times in self._events.items()
                    if not event_times or event_times[-1] <= cutoff
                ]
                for event_key in stale_keys[:1024]:
                    self._events.pop(event_key, None)


_limiter = _SlidingWindowLimiter()


def _client_key(request: Request) -> str:
    client = request.client
    return client.host if client and client.host else "unknown"


def enforce_api_rate_limit(request: Request) -> None:
    """Apply a modest per-client limit to every versioned API request."""
    _limiter.check(_client_key(request), "api", limit=240)


def enforce_workflow_rate_limit(request: Request) -> None:
    """Apply a stricter limit to synchronous, quota-consuming workflows."""
    _limiter.check(_client_key(request), "workflow", limit=12)


def _origin_from_referer(referer: str) -> str:
    parsed = urlparse(referer)
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")


def _normalise_origin(value: str) -> str:
    parsed = urlparse(value)
    if not parsed.scheme or not parsed.netloc or parsed.username or parsed.password:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")


def _allowed_origins() -> set[str]:
    allowed = {_normalise_origin(settings.frontend_url), _normalise_origin(settings.base_url)}
    allowed.discard("")
    if not settings.is_production:
        allowed.update(
            {
                "http://localhost:3000",
                "http://localhost:5173",
                "http://127.0.0.1:3000",
                "http://127.0.0.1:5173",
                "http://testserver",
            }
        )
    return allowed


def require_same_origin(request: Request) -> None:
    """Reject cross-site mutation requests before route dependencies run.

    Browsers send Origin for fetch/XHR mutations. Production also requires a
    valid Referer when a browser omits Origin. Development keeps headerless
    programmatic tests/CLI calls working, while still rejecting an explicit
    foreign Origin.
    """
    if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return

    origin_header = request.headers.get("origin")
    referer_header = request.headers.get("referer")
    origin = _normalise_origin(origin_header) if origin_header else _origin_from_referer(referer_header or "")
    if origin and origin in _allowed_origins():
        return
    if not origin and not settings.is_production:
        return
    raise HTTPException(
        status_code=403,
        detail={
            "code": "csrf_origin_denied",
            "message": "要求來源未通過驗證。",
        },
    )
