"""Safe parsing and public error types for YouTube Data API failures."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class YouTubeErrorInfo:
    """The small, non-sensitive subset of a Google error we need to act."""

    http_status: Optional[int]
    reason: str
    message: str


def _json_content(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8", errors="replace")
        except Exception:
            return {}
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def parse_youtube_error(exc: BaseException, *, method: str = "") -> YouTubeErrorInfo:
    """Extract status/reason/message without retaining the raw Google body.

    ``googleapiclient.errors.HttpError`` exposes the HTTP status through
    ``resp.status`` and the JSON response through ``content``.  Test doubles
    and future client versions sometimes expose those values as dictionaries,
    so the parser deliberately accepts both forms.
    """

    response = getattr(exc, "resp", None)
    raw_status = getattr(response, "status", None)
    try:
        status = int(raw_status) if raw_status is not None else None
    except (TypeError, ValueError):
        status = None

    payload = _json_content(getattr(exc, "content", None))
    error = payload.get("error") if isinstance(payload.get("error"), dict) else payload
    errors = error.get("errors") if isinstance(error, dict) else None
    reason = ""
    if isinstance(errors, list):
        for item in errors:
            if isinstance(item, dict) and item.get("reason"):
                reason = str(item["reason"])
                break
    if not reason and isinstance(error, dict) and error.get("reason"):
        reason = str(error["reason"])
    message = str(error.get("message") or "") if isinstance(error, dict) else ""
    # The method is accepted to make call sites self-documenting and to keep
    # this parser useful to callers that want to log a safe diagnostic.  It is
    # intentionally not included in the returned message or raw exception.
    del method
    return YouTubeErrorInfo(http_status=status, reason=reason, message=message[:240])


def is_youtube_quota_exceeded(exc: BaseException) -> bool:
    """Return true only for Google's documented 403/quotaExceeded pair."""

    info = parse_youtube_error(exc)
    return info.http_status == 403 and info.reason == "quotaExceeded"


class YouTubeQuotaUnavailable(RuntimeError):
    """A request was prevented by the local policy or Google's quota breaker."""

    def __init__(
        self,
        *,
        code: str,
        http_status: int | None,
        reason: str,
        method: str,
        bucket: str,
        reset_at: str,
        confirmed_by_google: bool,
        user_message: str,
    ) -> None:
        super().__init__(user_message)
        self.code = code
        self.http_status = http_status
        self.reason = reason
        self.method = method
        self.bucket = bucket
        self.reset_at = reset_at
        self.confirmed_by_google = bool(confirmed_by_google)
        self.user_message = user_message
        self.safe_to_retry = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "http_status": self.http_status,
            "reason": self.reason,
            "method": self.method,
            "bucket": self.bucket,
            "reset_at": self.reset_at,
            "reset_timezone": "America/Los_Angeles",
            "confirmed_by_google": self.confirmed_by_google,
            "message": self.user_message,
        }


__all__ = [
    "YouTubeErrorInfo",
    "YouTubeQuotaUnavailable",
    "is_youtube_quota_exceeded",
    "parse_youtube_error",
]
