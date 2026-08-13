"""Provider exception classification for safe API responses.

Only status/reason categories are inspected.  The original provider payload
and exception text are never included in the returned detail.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from backend.app.core.error_contract import error_detail, http_error
from backend.app.services.youtube_errors import parse_youtube_error


@dataclass(frozen=True)
class MappedProviderError:
    status_code: int
    detail: dict[str, Any]

    @property
    def code(self) -> str:
        return str(self.detail["code"])

    @property
    def message(self) -> str:
        return str(self.detail["message"])

    @property
    def retryable(self) -> bool:
        return bool(self.detail["retryable"])

    def to_http_exception(self):
        return http_error(
            self.status_code,
            self.detail["code"],
            self.detail["message"],
            retryable=self.detail.get("retryable", False),
            field_errors=self.detail.get("field_errors"),
            retry_after_seconds=self.detail.get("retry_after_seconds"),
            reset_at=self.detail.get("reset_at"),
            youtube_slot=self.detail.get("youtube_slot"),
        )


def _unwrap(exc: BaseException) -> BaseException:
    current = exc
    seen: set[int] = set()
    while id(current) not in seen:
        seen.add(id(current))
        cause = current.__cause__ or current.__context__
        if cause is None:
            break
        current = cause
    return current


def _provider_parts(exc: BaseException) -> tuple[int | None, set[str]]:
    root = _unwrap(exc)
    response = getattr(root, "resp", None)
    raw_status = getattr(response, "status", None)
    try:
        status = int(raw_status) if raw_status is not None else None
    except (TypeError, ValueError):
        status = None

    content = getattr(root, "content", None)
    if isinstance(content, bytes):
        content = content.decode("utf-8", errors="replace")
    payload: dict[str, Any] = {}
    if isinstance(content, dict):
        payload = content
    elif isinstance(content, str):
        try:
            parsed = json.loads(content)
            payload = parsed if isinstance(parsed, dict) else {}
        except (TypeError, ValueError):
            payload = {}
    error = payload.get("error") if isinstance(payload.get("error"), dict) else payload
    reasons: set[str] = set()
    if isinstance(error, dict):
        raw_errors = error.get("errors")
        if isinstance(raw_errors, list):
            reasons.update(
                str(item.get("reason")) for item in raw_errors if isinstance(item, dict) and item.get("reason")
            )
        if error.get("reason"):
            reasons.add(str(error["reason"]))
        if error.get("status"):
            reasons.add(str(error["status"]))
    return status, {reason.casefold() for reason in reasons}


def _text_error(exc: BaseException) -> str:
    # This is used only for category detection, never returned to callers.
    return str(_unwrap(exc)).casefold()[:1_000]


def _mapped(
    status_code: int,
    code: str,
    message: str,
    *,
    retryable: bool = False,
    retry_after_seconds: int | None = None,
    reset_at: str | None = None,
    youtube_slot: str | None = None,
) -> MappedProviderError:
    return MappedProviderError(
        status_code,
        error_detail(
            code,
            message,
            retryable=retryable,
            retry_after_seconds=retry_after_seconds,
            reset_at=reset_at,
            youtube_slot=youtube_slot,
        ),
    )


def map_youtube_error(
    exc: BaseException,
    *,
    method: str = "",
    youtube_slot: str | None = None,
    reset_at: str | None = None,
) -> MappedProviderError:
    """Classify a YouTube error while retaining ``parse_youtube_error`` as the parser."""

    info = parse_youtube_error(_unwrap(exc), method=method)
    status = info.http_status
    reason = info.reason.casefold()
    text = _text_error(exc)
    invalid_reasons = {
        "badrequest",
        "invalidargument",
        "invalidparameter",
        "invalidvalue",
        "required",
    }
    not_found_reasons = {"notfound", "playlistnotfound", "videonotfound"}
    permission_reasons = {"forbidden", "insufficientpermissions", "permissiondenied"}
    reauth_reasons = {"autherror", "unauthorized", "unauthorizedclient", "invalidcredentials"}
    rate_reasons = {"ratelimitexceeded", "userratelimitexceeded", "too_many_requests"}
    transient_reasons = {"backenderror", "internalerror", "serviceunavailable", "unavailable", "deadlineexceeded"}

    if reason == "quotaexceeded" and status in {403, 429, None}:
        return _mapped(
            429,
            "youtube_quota_exhausted",
            "YouTube API 配額已達上限，請於配額重設後再試。",
            retryable=True,
            reset_at=reset_at,
            youtube_slot=youtube_slot,
        )
    if reason in rate_reasons or status == 429:
        return _mapped(
            429,
            "youtube_rate_limited",
            "YouTube 請求過於頻繁，請稍後再試。",
            retryable=True,
            retry_after_seconds=30,
            youtube_slot=youtube_slot,
        )
    if (
        status == 401
        or reason in reauth_reasons
        or any(marker in text for marker in ("invalid_grant", "revoked", "token expired"))
    ):
        return _mapped(
            401,
            "youtube_reauthorization_required",
            "YouTube 授權已失效，請重新授權目前的 YouTube slot。",
            youtube_slot=youtube_slot,
        )
    if reason in not_found_reasons or status == 404:
        return _mapped(404, "youtube_not_found", "找不到指定的 YouTube 影片或播放清單。", youtube_slot=youtube_slot)
    if reason in invalid_reasons:
        return _mapped(
            400,
            "youtube_invalid_request",
            "YouTube 要求資料不正確，請檢查影片或播放清單設定。",
            youtube_slot=youtube_slot,
        )
    if reason in transient_reasons:
        return _mapped(
            503,
            "youtube_temporary_unavailable",
            "YouTube 服務暫時無法使用，請稍後再試。",
            retryable=True,
            retry_after_seconds=30,
            youtube_slot=youtube_slot,
        )
    if reason in permission_reasons or status == 403:
        return _mapped(
            403, "youtube_permission_denied", "目前 YouTube 帳號沒有存取此資源的權限。", youtube_slot=youtube_slot
        )
    if status == 400 or isinstance(_unwrap(exc), ValueError):
        return _mapped(
            400,
            "youtube_invalid_request",
            "YouTube 要求資料不正確，請檢查影片或播放清單設定。",
            youtube_slot=youtube_slot,
        )
    if reason in transient_reasons or status in {500, 502, 503, 504}:
        return _mapped(
            503,
            "youtube_temporary_unavailable",
            "YouTube 服務暫時無法使用，請稍後再試。",
            retryable=True,
            retry_after_seconds=30,
            youtube_slot=youtube_slot,
        )
    if status is None and not reason and isinstance(_unwrap(exc), RuntimeError):
        return _mapped(
            500, "youtube_provider_error", "YouTube 服務目前無法完成要求，請稍後再試。", youtube_slot=youtube_slot
        )
    return _mapped(
        502,
        "youtube_provider_error",
        "YouTube 服務目前無法完成要求，請稍後再試。",
        retryable=True,
        retry_after_seconds=30,
        youtube_slot=youtube_slot,
    )


def map_google_sheets_error(exc: BaseException, *, operation: str = "read") -> MappedProviderError:
    """Classify Google Sheets API and credential failures."""

    status, reasons = _provider_parts(exc)
    text = _text_error(exc)
    invalid_reasons = {"badrequest", "invalidargument", "invalidparameter", "invalidvalue"}
    not_found_reasons = {"notfound", "resourcenotfound"}
    permission_reasons = {"forbidden", "permissiondenied", "accessdenied"}
    reauth_reasons = {"autherror", "unauthorized", "unauthorizedclient", "invalidcredentials"}
    quota_reasons = {"quotaexceeded", "dailylimitexceeded"}
    rate_reasons = {"ratelimitexceeded", "userratelimitexceeded", "too_many_requests"}
    transient_reasons = {"backenderror", "internalerror", "serviceunavailable", "unavailable", "deadlineexceeded"}

    del operation
    if (
        status == 401
        or any(marker in text for marker in ("invalid_grant", "revoked", "token expired"))
        or reasons & reauth_reasons
    ):
        return _mapped(401, "sheets_reauthorization_required", "Google 授權已失效，請重新登入並授權。")
    if reasons & quota_reasons:
        return _mapped(
            429,
            "sheets_quota_exhausted",
            "Google 試算表 API 配額已達上限，請稍後再試。",
            retryable=True,
            retry_after_seconds=60,
        )
    if reasons & rate_reasons or status == 429:
        return _mapped(
            429,
            "sheets_rate_limited",
            "Google 試算表請求過於頻繁，請稍後再試。",
            retryable=True,
            retry_after_seconds=30,
        )
    if reasons & not_found_reasons or status == 404:
        return _mapped(404, "sheets_not_found", "找不到指定的 Google 試算表或工作表。")
    if reasons & invalid_reasons:
        return _mapped(400, "sheets_invalid_request", "Google 試算表要求資料不正確，請檢查試算表、工作表與欄位設定。")
    if reasons & transient_reasons:
        return _mapped(
            503,
            "sheets_temporary_unavailable",
            "Google 試算表服務暫時無法使用，請稍後再試。",
            retryable=True,
            retry_after_seconds=30,
        )
    if reasons & permission_reasons or status == 403:
        return _mapped(403, "sheets_permission_denied", "目前 Google 帳號沒有存取此試算表的權限。")
    if status == 400 or isinstance(_unwrap(exc), ValueError):
        return _mapped(400, "sheets_invalid_request", "Google 試算表要求資料不正確，請檢查試算表、工作表與欄位設定。")
    if status in {500, 502, 503, 504}:
        return _mapped(
            503,
            "sheets_temporary_unavailable",
            "Google 試算表服務暫時無法使用，請稍後再試。",
            retryable=True,
            retry_after_seconds=30,
        )
    if status is None and not reasons and isinstance(_unwrap(exc), RuntimeError):
        return _mapped(500, "sheets_provider_error", "Google 試算表服務目前無法完成要求，請稍後再試。")
    return _mapped(
        502,
        "sheets_provider_error",
        "Google 試算表服務目前無法完成要求，請稍後再試。",
        retryable=True,
        retry_after_seconds=30,
    )


# Short alias for callers that use the provider name rather than the product.
map_sheets_error = map_google_sheets_error


__all__ = ["MappedProviderError", "map_google_sheets_error", "map_sheets_error", "map_youtube_error"]
