"""Safe, stable API error responses.

The API deliberately exposes only a small, documented error shape.  Provider
exceptions and validation internals must never be serialized directly because
they can contain request URLs, authorization data, or implementation details.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import HTTPException

_KNOWN_OPTIONAL_FIELDS = ("retry_after_seconds", "reset_at", "youtube_slot")
_DEFAULT_MESSAGES = {
    400: "請檢查輸入資料後再試。",
    401: "登入已失效，請重新登入。",
    403: "目前帳號沒有執行此操作的權限。",
    404: "找不到要求的資源。",
    409: "要求與目前資料狀態不一致，請重新整理後再試。",
    422: "輸入資料格式不正確，請檢查欄位。",
    429: "請求過於頻繁，請稍後再試。",
    500: "伺服器發生錯誤，請稍後再試。",
    502: "外部服務目前無法回應，請稍後再試。",
    503: "服務目前暫時無法使用，請稍後再試。",
    504: "外部服務回應逾時，請稍後再試。",
}
_SENSITIVE_MARKERS = ("access_token", "refresh_token", "client_secret", "authorization:", "bearer ", "token=")


def _safe_text(value: Any, fallback: str, *, limit: int = 500) -> str:
    if not isinstance(value, str):
        return fallback
    normalized = value.strip()
    if any(marker in normalized.casefold() for marker in _SENSITIVE_MARKERS):
        return fallback
    return normalized[:limit] or fallback


def _safe_field_errors(value: Any) -> dict[str, list[str]]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, list[str]] = {}
    for raw_field, raw_messages in value.items():
        field = _safe_text(raw_field, "欄位", limit=160)
        if isinstance(raw_messages, (list, tuple)):
            messages = raw_messages
        else:
            messages = [raw_messages]
        safe_messages = [
            _safe_text(message, "欄位值不正確。", limit=240)
            for message in messages
            if isinstance(message, str) or message is not None
        ]
        result[field] = safe_messages or ["欄位值不正確。"]
    return result


def error_detail(
    code: str,
    message: str,
    *,
    retryable: bool = False,
    field_errors: Mapping[str, Any] | None = None,
    retry_after_seconds: int | None = None,
    reset_at: str | None = None,
    youtube_slot: str | None = None,
) -> dict[str, Any]:
    """Build the only error detail shape that may be returned by the API."""

    safe_code = _safe_text(code, "api_error", limit=100)
    detail: dict[str, Any] = {
        "code": safe_code,
        "message": _safe_text(message, "發生未預期錯誤，請稍後再試。"),
        "retryable": bool(retryable),
        "field_errors": _safe_field_errors(field_errors),
    }
    if retry_after_seconds is not None:
        try:
            retry_seconds = max(0, min(int(retry_after_seconds), 86_400))
        except (TypeError, ValueError):
            retry_seconds = None
        if retry_seconds is not None:
            detail["retry_after_seconds"] = retry_seconds
    if reset_at is not None:
        safe_reset = _safe_text(reset_at, "", limit=80)
        if safe_reset:
            detail["reset_at"] = safe_reset
    if youtube_slot in {"primary", "secondary"}:
        detail["youtube_slot"] = youtube_slot
    return detail


def http_error(
    status_code: int,
    code: str,
    message: str,
    *,
    retryable: bool = False,
    field_errors: Mapping[str, Any] | None = None,
    retry_after_seconds: int | None = None,
    reset_at: str | None = None,
    youtube_slot: str | None = None,
    headers: Mapping[str, str] | None = None,
) -> HTTPException:
    """Return a FastAPI exception carrying a sanitized contract detail."""

    return HTTPException(
        status_code=status_code,
        detail=error_detail(
            code,
            message,
            retryable=retryable,
            field_errors=field_errors,
            retry_after_seconds=retry_after_seconds,
            reset_at=reset_at,
            youtube_slot=youtube_slot,
        ),
        headers=dict(headers) if headers else None,
    )


def normalize_http_detail(status_code: int, detail: Any) -> dict[str, Any]:
    """Normalize legacy ``HTTPException.detail`` values at the app boundary.

    Unknown dictionary fields are intentionally discarded.  This prevents a
    provider response or an internal diagnostic field from becoming public just
    because a route raised an older-style HTTPException.
    """

    default_code = {
        400: "invalid_request",
        401: "login_required",
        403: "permission_denied",
        404: "not_found",
        409: "conflict",
        422: "validation_error",
        429: "rate_limited",
    }.get(status_code, "internal_error" if status_code >= 500 else "api_error")
    default_message = _DEFAULT_MESSAGES.get(status_code, "要求無法完成，請稍後再試。")

    if isinstance(detail, Mapping):
        code = detail.get("code") or default_code
        # A legacy/internal mapping is not trusted merely because it has a
        # ``message`` key.  Only details created by ``error_detail`` carry
        # the complete contract and may retain their safe localized message.
        if not {"code", "message", "retryable", "field_errors"}.issubset(detail):
            return error_detail(
                str(code),
                default_message,
                retryable=status_code in {429, 502, 503, 504},
            )
        message = detail.get("message") or default_message
        slot = detail.get("youtube_slot") or detail.get("slot")
        return error_detail(
            str(code),
            str(message),
            retryable=bool(detail.get("retryable", status_code in {429, 502, 503, 504})),
            field_errors=detail.get("field_errors"),
            retry_after_seconds=detail.get("retry_after_seconds"),
            reset_at=detail.get("reset_at"),
            youtube_slot=slot if isinstance(slot, str) else None,
        )

    # Never echo an arbitrary exception/detail string.  It may contain a
    # provider URL, token fragment, or stack-trace-like implementation data.
    return error_detail(
        default_code,
        default_message,
        retryable=status_code in {429, 502, 503, 504},
    )


def validation_field_errors(errors: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Translate Pydantic errors without exposing their raw input/context."""

    result: dict[str, list[str]] = {}
    for item in errors:
        location = item.get("loc") or ("body",)
        parts = [str(part) for part in location if part not in {"body", "query", "path", "header"}]
        field = ".".join(parts) or "request"
        error_type = str(item.get("type") or "")
        context = item.get("ctx") if isinstance(item.get("ctx"), Mapping) else {}
        if error_type == "missing":
            message = "此欄位為必填。"
        elif error_type in {"string_too_short", "too_short"}:
            message = f"長度不可少於 {context.get('min_length', context.get('min_items', 1))}。"
        elif error_type in {"string_too_long", "too_long"}:
            message = f"長度不可超過 {context.get('max_length', context.get('max_items', 1))}。"
        elif error_type in {"list_too_short", "set_too_short"}:
            message = f"至少需要 {context.get('min_length', 1)} 筆資料。"
        elif error_type in {"list_too_long", "set_too_long"}:
            message = f"最多只能有 {context.get('max_length', 1)} 筆資料。"
        elif error_type in {"greater_than_equal", "greater_than"}:
            message = f"數值不可小於 {context.get('ge', context.get('gt', '指定值'))}。"
        elif error_type in {"less_than_equal", "less_than"}:
            message = f"數值不可大於 {context.get('le', context.get('lt', '指定值'))}。"
        elif error_type in {"literal_error", "enum"}:
            message = "欄位值不受支援。"
        elif error_type in {"int_parsing", "float_parsing", "finite_number"}:
            message = "請輸入有效的數字。"
        elif error_type in {"bool_parsing", "bool_type"}:
            message = "請輸入有效的布林值。"
        elif error_type in {"string_type", "string_unicode"}:
            message = "請輸入文字。"
        elif error_type in {"list_type", "dict_type", "model_type"}:
            message = "請輸入正確的資料結構。"
        else:
            message = "欄位值不正確。"
        result.setdefault(field, []).append(message)
    return result


__all__ = [
    "error_detail",
    "http_error",
    "normalize_http_detail",
    "validation_field_errors",
]
