import httpx
import pytest

from backend.app.services.instagram_service import InstagramClient


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
        return self.__class__.responses.pop(0)


def response(payload, status=200):
    request = httpx.Request("POST", "https://graph.instagram.com/v25.0")
    return httpx.Response(status, json=payload, request=request)


@pytest.fixture(autouse=True)
def disable_usage_tracking(monkeypatch):
    monkeypatch.setattr(
        "backend.app.services.instagram_service.instagram_api_usage_tracker.record_response",
        lambda *args, **kwargs: None,
    )


def test_reel_flow_uses_separate_normal_requests(monkeypatch):
    FakeHttpClient.calls = []
    FakeHttpClient.responses = [
        response({"id": "container-1"}),
        response({"status_code": "FINISHED", "status": "Finished"}),
        response({"id": "media-1"}),
    ]
    monkeypatch.setattr("backend.app.services.instagram_service.httpx.Client", FakeHttpClient)

    client = InstagramClient("user-1", "token-1")
    result = client.publish_reel("https://cdn.example/one.mp4", "caption")

    assert result == {"creation_id": "container-1", "media_id": "media-1"}
    assert [(method, url) for method, url, _ in FakeHttpClient.calls] == [
        ("POST", "https://graph.instagram.com/v25.0/user-1/media"),
        ("GET", "https://graph.instagram.com/v25.0/container-1"),
        ("POST", "https://graph.instagram.com/v25.0/user-1/media_publish"),
    ]
    assert all("batch" not in kwargs.get("data", {}) for _, _, kwargs in FakeHttpClient.calls)


def test_create_reel_container_sends_one_video(monkeypatch):
    FakeHttpClient.calls = []
    FakeHttpClient.responses = [response({"id": "container-1"})]
    monkeypatch.setattr("backend.app.services.instagram_service.httpx.Client", FakeHttpClient)

    client = InstagramClient("user-1", "token-1")
    assert client.create_reel_container("https://cdn.example/one.mp4", "one", False) == "container-1"

    method, url, kwargs = FakeHttpClient.calls[0]
    assert method == "POST"
    assert url.endswith("/user-1/media")
    assert kwargs["data"] == {
        "media_type": "REELS",
        "video_url": "https://cdn.example/one.mp4",
        "caption": "one",
        "share_to_feed": "false",
    }


def test_content_publishing_limit_uses_live_account_capacity(monkeypatch):
    client = InstagramClient("user-1", "token-1")
    monkeypatch.setattr(
        client,
        "request",
        lambda *args, **kwargs: {"data": [{"quota_usage": 97, "config": {"quota_total": 100}}]},
    )

    assert client.get_content_publishing_limit() == {"used": 97, "total": 100, "remaining": 3}
