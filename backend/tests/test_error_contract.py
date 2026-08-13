import asyncio
import json
from types import SimpleNamespace

from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient

from backend.app import main
from backend.app.core.error_contract import error_detail
from backend.app.services.provider_errors import map_google_sheets_error, map_youtube_error


class ProviderFailure(Exception):
    def __init__(self, status: int, reason: str, message: str = "provider secret response"):
        super().__init__(message)
        self.resp = SimpleNamespace(status=status)
        self.content = json.dumps({"error": {"errors": [{"reason": reason}], "message": message}}).encode()


def test_error_detail_has_required_shape_and_drops_unapproved_fields():
    detail = error_detail(
        "safe_code",
        "安全訊息",
        retryable=True,
        field_errors={"title": ["欄位錯誤"]},
        reset_at="2026-08-15T00:00:00Z",
        youtube_slot="primary",
    )

    assert detail == {
        "code": "safe_code",
        "message": "安全訊息",
        "retryable": True,
        "field_errors": {"title": ["欄位錯誤"]},
        "reset_at": "2026-08-15T00:00:00Z",
        "youtube_slot": "primary",
    }
    assert "secret" not in str(detail)


def test_validation_handler_returns_traditional_chinese_field_contract():
    request = SimpleNamespace()
    exc = RequestValidationError(
        [
            {
                "type": "string_too_short",
                "loc": ("body", "title"),
                "msg": "String should have at least 1 character",
                "input": "",
                "ctx": {"min_length": 1},
            }
        ]
    )

    response = asyncio.run(main.request_validation_error_handler(request, exc))
    body = json.loads(response.body)
    detail = body["detail"]
    assert response.status_code == 422
    assert set(("code", "message", "retryable", "field_errors")).issubset(detail)
    assert detail["code"] == "validation_error"
    assert detail["field_errors"] == {"title": ["長度不可少於 1。"]}
    assert "String should" not in str(body)


def test_http_exception_handler_does_not_echo_legacy_provider_detail():
    response = asyncio.run(
        main.http_exception_handler(
            SimpleNamespace(),
            SimpleNamespace(
                status_code=500,
                detail="https://provider.example/private?access_token=secret",
                headers=None,
            ),
        )
    )
    body = json.loads(response.body)
    assert response.status_code == 500
    assert "provider.example" not in str(body)
    assert body["detail"]["code"] == "internal_error"


def test_youtube_provider_mapping_distinguishes_categories_without_raw_body():
    cases = [
        (ProviderFailure(400, "invalidParameter"), "youtube_invalid_request", 400, False),
        (ProviderFailure(404, "videoNotFound"), "youtube_not_found", 404, False),
        (ProviderFailure(403, "forbidden"), "youtube_permission_denied", 403, False),
        (ProviderFailure(401, "authError"), "youtube_reauthorization_required", 401, False),
        (ProviderFailure(403, "quotaExceeded"), "youtube_quota_exhausted", 429, True),
        (ProviderFailure(403, "rateLimitExceeded"), "youtube_rate_limited", 429, True),
        (ProviderFailure(503, "backendError"), "youtube_temporary_unavailable", 503, True),
    ]

    for exc, code, status, retryable in cases:
        mapped = map_youtube_error(exc, youtube_slot="secondary")
        assert (mapped.code, mapped.status_code, mapped.retryable) == (code, status, retryable)
        assert "provider secret response" not in str(mapped.detail)
        assert mapped.detail["youtube_slot"] == "secondary"


def test_sheets_provider_mapping_distinguishes_categories():
    cases = [
        (ProviderFailure(400, "invalidArgument"), "sheets_invalid_request", 400, False),
        (ProviderFailure(404, "notFound"), "sheets_not_found", 404, False),
        (ProviderFailure(403, "permissionDenied"), "sheets_permission_denied", 403, False),
        (ProviderFailure(401, "authError"), "sheets_reauthorization_required", 401, False),
        (ProviderFailure(403, "quotaExceeded"), "sheets_quota_exhausted", 429, True),
        (ProviderFailure(429, "rateLimitExceeded"), "sheets_rate_limited", 429, True),
        (ProviderFailure(503, "backendError"), "sheets_temporary_unavailable", 503, True),
    ]

    for exc, code, status, retryable in cases:
        mapped = map_google_sheets_error(exc)
        assert (mapped.code, mapped.status_code, mapped.retryable) == (code, status, retryable)
        assert "provider secret response" not in str(mapped.detail)


def test_validation_contract_is_used_by_real_app_handler():
    response = TestClient(main.app).get("/api/v1/auth/youtube/not-a-slot/url")
    detail = response.json()["detail"]
    assert response.status_code == 400
    assert set(("code", "message", "retryable", "field_errors")).issubset(detail)
