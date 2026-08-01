import json

import httpx

from backend.app.services.instagram_api_usage_service import InstagramApiUsageTracker


def response(status_code=200, *, headers=None, payload=None):
    request = httpx.Request("GET", "https://graph.instagram.com/v25.0/me")
    return httpx.Response(status_code, headers=headers or {}, json=payload or {}, request=request)


def test_parse_usage_header_supports_meta_field_names():
    parsed = InstagramApiUsageTracker.parse_usage_header(
        json.dumps({"call_count": 12, "total_cputime": 4.5, "total_time": 7})
    )

    assert parsed == {"call_volume": 12.0, "cpu_time": 4.5, "total_time": 7.0}


def test_tracker_records_meta_usage_and_errors(tmp_path):
    tracker = InstagramApiUsageTracker(tmp_path / "instagram_api_usage.json")
    usage_response = response(
        headers={"x-app-usage": json.dumps({"call_volume": 18, "cpu_time": 3, "total_time": 5})},
    )
    tracker.record_response("POST", "123/media", usage_response, usage_response.json())
    error_response = response(
        403,
        headers={"x-app-usage": json.dumps({"call_volume": 100, "cpu_time": 40, "total_time": 50})},
        payload={
            "error": {
                "code": 4,
                "error_subcode": 2045015,
                "message": "Application requests limit reached",
            }
        },
    )
    usage = tracker.record_response("GET", "container-1", error_response, error_response.json())

    assert usage["requests_today"] == 2
    assert usage["total_requests"] == 2
    assert usage["usage_percent"] == 100.0
    assert usage["meta_usage"]["call_volume"] == 100.0
    assert usage["last_error"]["code"] == 4
    assert usage["last_error"]["message"] == "Application requests limit reached"
    assert {item["endpoint"] for item in usage["methods"]} == {
        "POST create media container",
        "GET media container status",
    }


def test_tracker_without_meta_header_still_counts_local_requests(tmp_path):
    tracker = InstagramApiUsageTracker(tmp_path / "instagram_api_usage.json")
    tracker.record_response("GET", "me", response())

    usage = tracker.get_usage()

    assert usage["requests_today"] == 1
    assert usage["meta_usage"]["available"] is False
    assert usage["usage_percent"] is None
