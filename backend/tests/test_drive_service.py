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


def test_get_drive_video_thumbnail_prefers_source_frame_and_caches_it(
    monkeypatch, tmp_path
):
    service = _FakeService({"id": "file-1"})
    monkeypatch.setattr(drive_service, "build", lambda *args, **kwargs: service)
    monkeypatch.setattr(drive_service, "DRIVE_THUMBNAIL_CACHE_DIR", tmp_path)
    monkeypatch.setattr(drive_service.shutil, "which", lambda name: "ffmpeg")

    downloaded = []

    def fake_download(credentials, file_id, destination):
        downloaded.append((credentials, file_id))
        destination.write_bytes(b"video")

    monkeypatch.setattr(drive_service, "download_drive_file", fake_download)

    class FakeResult:
        returncode = 0
        stdout = b"high-resolution-frame"

    def fake_run(command, **kwargs):
        assert "-ss" in command
        assert command[-1] == "pipe:1"
        assert kwargs["timeout"] == drive_service.DRIVE_SOURCE_THUMBNAIL_TIMEOUT_SECONDS
        return FakeResult()

    monkeypatch.setattr(drive_service.subprocess, "run", fake_run)

    first = drive_service.get_drive_video_thumbnail(
        "credentials", "file-1", prefer_source=True
    )
    second = drive_service.get_drive_video_thumbnail(
        "credentials", "file-1", prefer_source=True
    )

    assert first == (b"high-resolution-frame", "image/jpeg")
    assert second == first
    assert downloaded == [("credentials", "file-1")]
