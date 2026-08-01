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
        return _FakeRequest({"thumbnailLink": "https://drive.example/thumbnail=s220"})


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
    assert service.file_api.list_kwargs["orderBy"] == "name asc"


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
            assert url == "https://drive.example/thumbnail=s1600"
            assert timeout == 20
            return FakeResponse()

    monkeypatch.setattr(drive_service, "AuthorizedSession", FakeSession)

    content, media_type = drive_service.get_drive_video_thumbnail("credentials", "file-1")

    assert content == b"thumbnail"
    assert media_type == "image/webp"


def test_get_drive_video_thumbnail_prefers_source_frame_and_caches_it(monkeypatch, tmp_path):
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

    first = drive_service.get_drive_video_thumbnail("credentials", "file-1", prefer_source=True)
    second = drive_service.get_drive_video_thumbnail("credentials", "file-1", prefer_source=True)

    assert first == (b"high-resolution-frame", "image/jpeg")
    assert second == first
    assert downloaded == [("credentials", "file-1")]


class _PublishedFolderFiles:
    def __init__(self, existing=None, parents=None):
        self.existing = existing or []
        self.parents = parents or ["source-1"]
        self.list_kwargs = None
        self.create_kwargs = None
        self.update_kwargs = None

    def list(self, **kwargs):
        self.list_kwargs = kwargs
        return _FakeRequest({"files": self.existing})

    def create(self, **kwargs):
        self.create_kwargs = kwargs
        return _FakeRequest({"id": "published-1", "parents": ["source-1"]})

    def get(self, **kwargs):
        return _FakeRequest({"id": "file-1", "parents": self.parents})

    def update(self, **kwargs):
        self.update_kwargs = kwargs
        self.parents = ["published-1"]
        return _FakeRequest({"id": "file-1", "parents": self.parents})


class _PublishedFolderService:
    def __init__(self, files):
        self.file_api = files

    def files(self):
        return self.file_api


def test_ensure_published_folder_creates_once_and_move_is_idempotent(monkeypatch):
    files = _PublishedFolderFiles()
    service = _PublishedFolderService(files)
    monkeypatch.setattr(drive_service, "build", lambda *args, **kwargs: service)

    folder_id = drive_service.ensure_published_folder("credentials", "https://drive.google.com/drive/folders/source-1")
    first_move = drive_service.move_drive_file_to_folder("credentials", "file-1", "source-1", folder_id)
    second_move = drive_service.move_drive_file_to_folder("credentials", "file-1", "source-1", folder_id)

    assert folder_id == "published-1"
    assert files.create_kwargs["body"]["name"] == "Published"
    assert files.update_kwargs["removeParents"] == "source-1"
    assert first_move["parents"] == ["published-1"]
    assert second_move["parents"] == ["published-1"]
