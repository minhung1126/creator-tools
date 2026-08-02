"""Structured errors raised by the Instagram Graph API client."""

from __future__ import annotations

import email.utils
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

RATE_LIMIT_CODES = {4, 17, 32, 613}
CONTENT_PUBLISHING_LIMIT_MARKERS = (
    "content_publishing_limit",
    "content publishing limit",
    "publishing limit",
    "24 hour",
    "24-hour",
    "quota limit",
)


def _as_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None and str(value).strip() else None
    except (TypeError, ValueError):
        return None


def _parse_retry_after(value: Any, *, now: datetime | None = None) -> tuple[int | None, str | None]:
    """Return seconds and an ISO recovery timestamp for Retry-After variants."""

    if value in (None, ""):
        return None, None
    current = now or datetime.now(timezone.utc)
    text = str(value).strip()
    seconds = _as_int(text)
    if seconds is not None:
        seconds = max(seconds, 0)
        return seconds, (current + timedelta(seconds=seconds)).isoformat()
    try:
        parsed = email.utils.parsedate_to_datetime(text)
    except (TypeError, ValueError, OverflowError):
        parsed = None
    if parsed is None:
        return None, None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    recovery = parsed.astimezone(timezone.utc)
    return max(int((recovery - current).total_seconds()), 0), recovery.isoformat()


def _format_recovery(value: str | None) -> str:
    if not value:
        return "稍後"
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.astimezone(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return value


class InstagramApiError(RuntimeError):
    """Preserve the actionable fields returned by Meta and transport errors."""

    def __init__(
        self,
        message: str,
        *,
        http_status: int | None = None,
        meta_code: int | None = None,
        error_subcode: int | None = None,
        fbtrace_id: str | None = None,
        retry_after: Any = None,
        x_app_usage: Mapping[str, Any] | None = None,
        estimated_recovery_at: str | None = None,
        endpoint: str | None = None,
        method: str | None = None,
        token_error: bool = False,
        rate_limited: bool = False,
        content_publishing_limit: bool = False,
        uncertain: bool = False,
        safe_to_retry: bool = False,
        from_limiter: bool = False,
    ) -> None:
        self.http_status = http_status
        self.status_code = http_status
        self.meta_code = meta_code
        self.code = meta_code
        self.error_subcode = error_subcode
        self.subcode = error_subcode
        self.fbtrace_id = fbtrace_id
        self.retry_after = retry_after
        self.x_app_usage = dict(x_app_usage or {}) or None
        self.estimated_recovery_at = estimated_recovery_at
        self.endpoint = endpoint
        self.method = method
        self.token_error = bool(token_error)
        self.rate_limited = bool(rate_limited)
        self.content_publishing_limit = bool(content_publishing_limit)
        self.uncertain = bool(uncertain)
        self.safe_to_retry = bool(safe_to_retry)
        self.from_limiter = bool(from_limiter)
        self.retry_after_seconds, parsed_recovery = _parse_retry_after(retry_after)
        if not self.estimated_recovery_at and parsed_recovery:
            self.estimated_recovery_at = parsed_recovery
        self.raw_message = str(message or "Instagram API request failed").strip()
        super().__init__(self.raw_message)

    @classmethod
    def from_response(
        cls,
        response: Any,
        data: Mapping[str, Any] | None,
        *,
        method: str,
        endpoint: str,
        x_app_usage: Mapping[str, Any] | None = None,
    ) -> "InstagramApiError":
        payload = data if isinstance(data, Mapping) else {}
        raw_error = payload.get("error")
        error = raw_error if isinstance(raw_error, Mapping) else {}
        status = _as_int(getattr(response, "status_code", None))
        code = _as_int(error.get("code"))
        subcode = _as_int(error.get("error_subcode"))
        message = str(error.get("message") or error.get("error_user_msg") or "").strip()
        if not message:
            message = f"Instagram API HTTP {status}" if status is not None else "Instagram API request failed"
        raw_text = " ".join(
            str(error.get(key) or "")
            for key in ("type", "message", "error_user_title", "error_user_msg", "error_data")
        ).casefold()
        content_limit = any(marker in raw_text for marker in CONTENT_PUBLISHING_LIMIT_MARKERS)
        rate_limited = status == 429 or code in RATE_LIMIT_CODES or content_limit
        token_error = status == 401 or code == 190
        retry_after = (getattr(response, "headers", {}) or {}).get("retry-after")
        if retry_after is None:
            retry_after = (getattr(response, "headers", {}) or {}).get("Retry-After")
        return cls(
            message,
            http_status=status,
            meta_code=code,
            error_subcode=subcode,
            fbtrace_id=str(error.get("fbtrace_id") or payload.get("fbtrace_id") or "") or None,
            retry_after=retry_after,
            x_app_usage=x_app_usage,
            endpoint=endpoint,
            method=method,
            token_error=token_error,
            rate_limited=rate_limited,
            content_publishing_limit=content_limit,
            safe_to_retry=rate_limited and not token_error,
        )

    @classmethod
    def timeout(cls, *, method: str, endpoint: str, message: str = "Instagram API 網路逾時") -> "InstagramApiError":
        return cls(
            message,
            endpoint=endpoint,
            method=method,
            uncertain=True,
            safe_to_retry=False,
        )

    @classmethod
    def transport(cls, *, method: str, endpoint: str, message: str = "Instagram API 網路連線失敗") -> "InstagramApiError":
        return cls(
            message,
            endpoint=endpoint,
            method=method,
            uncertain=True,
            safe_to_retry=False,
        )

    @classmethod
    def cooldown(
        cls,
        *,
        endpoint: str,
        estimated_recovery_at: str,
        reason: str = "Meta API 暫時限流",
        meta_code: int | None = None,
        content_publishing_limit: bool = False,
    ) -> "InstagramApiError":
        return cls(
            reason,
            meta_code=meta_code,
            endpoint=endpoint,
            rate_limited=True,
            content_publishing_limit=content_publishing_limit,
            estimated_recovery_at=estimated_recovery_at,
            safe_to_retry=True,
            from_limiter=True,
        )

    @property
    def user_message(self) -> str:
        if self.token_error:
            suffix = f"（Meta code {self.meta_code}）" if self.meta_code is not None else ""
            return f"Instagram 授權已失效{suffix}，請重新授權。"
        if self.rate_limited:
            recovery = _format_recovery(self.estimated_recovery_at)
            if "使用率已達硬門檻" in self.raw_message:
                return f"Meta API 使用率已達硬門檻，系統將於 {recovery} 重新檢查並自動恢復。"
            if self.content_publishing_limit:
                return f"Instagram 24 小時發布額度已用盡，系統將於 {recovery} 自動重試。"
            return f"Meta API 暫時限流，系統將於 {recovery} 自動重試。"
        if self.uncertain:
            return "Instagram 網路逾時，外部結果不確定；系統不會盲目重送，請先確認 Meta 狀態。"
        details = []
        if self.http_status is not None:
            details.append(f"HTTP {self.http_status}")
        if self.meta_code is not None:
            details.append(f"Meta code {self.meta_code}")
        detail = f"（{'、'.join(details)}）" if details else ""
        return f"{self.raw_message[:180]}{detail}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "message": self.raw_message[:240],
            "http_status": self.http_status,
            "meta_code": self.meta_code,
            "error_subcode": self.error_subcode,
            "fbtrace_id": self.fbtrace_id,
            "retry_after": self.retry_after,
            "retry_after_seconds": self.retry_after_seconds,
            "x_app_usage": self.x_app_usage,
            "estimated_recovery_at": self.estimated_recovery_at,
            "endpoint": self.endpoint,
            "method": self.method,
            "token_error": self.token_error,
            "rate_limited": self.rate_limited,
            "content_publishing_limit": self.content_publishing_limit,
            "uncertain": self.uncertain,
            "safe_to_retry": self.safe_to_retry,
        }


def parse_retry_after(value: Any, *, now: datetime | None = None) -> tuple[int | None, str | None]:
    """Public helper used by the durable limiter when it receives an error."""

    return _parse_retry_after(value, now=now)
