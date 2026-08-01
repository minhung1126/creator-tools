from backend.app.services import drive_service


class _FakeRequest:
    def __init__(self, response):
        self.response = response

    def execute(self):
        return self.response


class _FakeFiles:
    def __init__(self, item):
        self.item = item
        self.list_kwargs = None

    def list(self, **kwargs):
        self.list_kwargs = kwargs
        return _FakeRequest({"files": [self.item]})

    def get(self, **kwargs):
        return _FakeRequest({"thumbnailLink": "https://drive.example/thumbnail"})


class _FakeService:
    def __init__(self, item):
        self.file_api = _FakeFiles(item)

    def files(self):
        return self.file_api


def test_list_drive_videos_requests_drive_thumbnail_link(monkeypatch):
    service = _FakeService(
        {
            "id": "file-1",
            "name": "reel.mp4",
            "mimeType": "video/mp4",
            "createdTime": "2026-08-01T00:00:00Z",
            "thumbnailLink": "https://drive.example/thumbnail",
            "videoMediaMetadata": {"durationMillis": "1000", "width": "1080", "height": "1920"},
        }
    )
    monkeypatch.setattr(drive_service, "build", lambda *args, **kwargs: service)

    videos = drive_service.list_drive_videos(object(), "folder-1")

    assert videos[0]["thumbnail_link"] == "https://drive.example/thumbnail"
    assert "thumbnailLink" in service.file_api.list_kwargs["fields"]


def test_get_drive_video_thumbnail_uses_authorized_session(monkeypatch):
    service = _FakeService({"id": "file-1"})
    monkeypatch.setattr(drive_service, "build", lambda *args, **kwargs: service)

    class FakeResponse:
        content = b"thumbnail"
        headers = {"content-type": "image/webp; charset=utf-8"}

        def raise_for_status(self):
            return None

    class FakeSession:
        def __init__(self, credentials):
            self.credentials = credentials

        def get(self, url, timeout):
            assert url == "https://drive.example/thumbnail"
            assert timeout == 20
            return FakeResponse()

    monkeypatch.setattr(drive_service, "AuthorizedSession", FakeSession)

    content, media_type = drive_service.get_drive_video_thumbnail("credentials", "file-1")

    assert content == b"thumbnail"
    assert media_type == "image/webp"
