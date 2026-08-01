import json

import httpx
import pytest

from backend.app.services.instagram_service import InstagramBatchError, InstagramClient


class FakeHttpClient:
    responses = []
    calls = []

    def __init__(self, *args, **kwargs):
        del args, kwargs

    def __enter__(self):
        return self

    def __exit__(self, *args):
        del args
        return False

    def request(self, method, url, **kwargs):
        self.__class__.calls.append((method, url, kwargs))
        response = self.__class__.responses.pop(0)
        return response


def response(payload, status=200):
    request = httpx.Request("POST", "https://graph.instagram.com/v25.0")
    return httpx.Response(status, json=payload, request=request)


def test_batch_requests_chain_children_and_preserve_input_order(monkeypatch):
    FakeHttpClient.calls = []
    FakeHttpClient.responses = [
        response(
            [
                {"code": 200, "body": json.dumps({"id": "container-1"})},
                {"code": 200, "body": json.dumps({"id": "container-2"})},
            ]
        )
    ]
    monkeypatch.setattr("backend.app.services.instagram_service.httpx.Client", FakeHttpClient)
    monkeypatch.setattr(
        "backend.app.services.instagram_service.instagram_api_usage_tracker.record_response",
        lambda *args, **kwargs: None,
    )

    client = InstagramClient("user-1", "token-1")
    result = client.batch_request(
        [
            {"method": "GET", "path": "container-1", "params": {"fields": "status_code,status"}},
            {"method": "POST", "path": "user-1/media_publish", "data": {"creation_id": "container-1"}},
        ]
    )

    assert [item["data"] for item in result] == [{"id": "container-1"}, {"id": "container-2"}]
    method, url, kwargs = FakeHttpClient.calls[0]
    assert method == "POST"
    assert url == "https://graph.instagram.com/v25.0"
    entries = json.loads(kwargs["data"]["batch"])
    assert entries[0]["relative_url"] == "container-1?fields=status_code%2Cstatus"
    assert "depends_on" not in entries[0]
    assert entries[1]["depends_on"] == entries[0]["name"]
    assert "creation_id=container-1" in entries[1]["body"]
    assert kwargs["data"]["access_token"] == "token-1"


def test_reel_batch_operations_do_not_chain_independent_children(monkeypatch):
    FakeHttpClient.calls = []
    FakeHttpClient.responses = [
        response(
            [
                {"code": 200, "body": json.dumps({"id": "container-1"})},
                {"code": 200, "body": json.dumps({"id": "container-2"})},
            ]
        )
    ]
    monkeypatch.setattr("backend.app.services.instagram_service.httpx.Client", FakeHttpClient)
    monkeypatch.setattr(
        "backend.app.services.instagram_service.instagram_api_usage_tracker.record_response",
        lambda *args, **kwargs: None,
    )

    client = InstagramClient("user-1", "token-1")
    assert client.create_reel_containers(
        [
            {"video_url": "https://cdn.example/one.mp4", "caption": "one"},
            {"video_url": "https://cdn.example/two.mp4", "caption": "two"},
        ]
    ) == ["container-1", "container-2"]

    entries = json.loads(FakeHttpClient.calls[0][2]["data"]["batch"])
    assert all("depends_on" not in entry for entry in entries)


def test_reel_batch_retries_only_rejected_publish_child(monkeypatch):
    FakeHttpClient.calls = []
    FakeHttpClient.responses = [
        response(
            [
                {"code": 200, "body": json.dumps({"id": "media-1"})},
                {"code": 400, "body": json.dumps({"error": {"message": "temporary child failure"}})},
            ]
        ),
        response({"id": "media-2"}),
    ]
    monkeypatch.setattr("backend.app.services.instagram_service.httpx.Client", FakeHttpClient)
    monkeypatch.setattr(
        "backend.app.services.instagram_service.instagram_api_usage_tracker.record_response",
        lambda *args, **kwargs: None,
    )

    client = InstagramClient("user-1", "token-1")
    assert client.publish_containers(["container-1", "container-2"]) == ["media-1", "media-2"]
    assert len(FakeHttpClient.calls) == 2
    assert FakeHttpClient.calls[1][1].endswith("/user-1/media_publish")
    assert FakeHttpClient.calls[1][2]["data"]["creation_id"] == "container-2"


def test_batch_requests_chunk_at_meta_limit_in_sequence(monkeypatch):
    FakeHttpClient.calls = []
    FakeHttpClient.responses = [
        response([{"code": 200, "body": json.dumps({"index": index})} for index in range(50)]),
        response([{"code": 200, "body": json.dumps({"index": 50})}]),
    ]
    monkeypatch.setattr("backend.app.services.instagram_service.httpx.Client", FakeHttpClient)
    monkeypatch.setattr(
        "backend.app.services.instagram_service.instagram_api_usage_tracker.record_response",
        lambda *args, **kwargs: None,
    )

    client = InstagramClient("user-1", "token-1")
    result = client.batch_request([{"method": "GET", "path": f"media-{index}"} for index in range(51)])

    assert len(FakeHttpClient.calls) == 2
    assert len(json.loads(FakeHttpClient.calls[0][2]["data"]["batch"])) == 50
    assert len(json.loads(FakeHttpClient.calls[1][2]["data"]["batch"])) == 1
    assert [item["data"]["index"] for item in result] == list(range(51))


def test_high_level_batch_preserves_partial_success_for_retry(monkeypatch):
    FakeHttpClient.calls = []
    FakeHttpClient.responses = [
        response(
            [
                {"code": 200, "body": json.dumps({"id": "container-1"})},
                {"code": 400, "body": json.dumps({"error": {"message": "bad video"}})},
            ]
        )
    ]
    monkeypatch.setattr("backend.app.services.instagram_service.httpx.Client", FakeHttpClient)
    monkeypatch.setattr(
        "backend.app.services.instagram_service.instagram_api_usage_tracker.record_response",
        lambda *args, **kwargs: None,
    )

    client = InstagramClient("user-1", "token-1")
    with pytest.raises(InstagramBatchError) as raised:
        client.create_reel_containers(
            [
                {"video_url": "https://cdn.example/one.mp4", "caption": "one"},
                {"video_url": "https://cdn.example/two.mp4", "caption": "two"},
            ]
        )

    assert raised.value.index == 1
    assert raised.value.results[0]["ok"] is True
    assert raised.value.results[0]["data"]["id"] == "container-1"
    assert raised.value.results[1]["ok"] is False
