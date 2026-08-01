from copy import deepcopy
from pathlib import Path

from backend.app.services import instagram_publish_service as service
from backend.app.services.r2_service import validate_public_base_url


class MemoryStore:
    def __init__(self):
        self.job = None

    def save(self, job):
        self.job = deepcopy(job)
        return deepcopy(job)


def test_reels_preflight_and_order(monkeypatch):
    team_header = "\u6240\u5c6c\u5718\u9ad4"
    person_header = "\u4eba"
    monkeypatch.setattr(service, "get_sheet_headers", lambda *args: [team_header, person_header, "Caption"])
    monkeypatch.setattr(
        service,
        "get_all_rows_for_sheet",
        lambda *args: [
            {team_header: "Team", person_header: "A", "Caption": "caption A"},
            {team_header: "Team", person_header: "B", "Caption": "caption B"},
        ],
    )
    monkeypatch.setattr(
        service,
        "list_drive_videos",
        lambda *args: [
            {"id": "2", "name": "two.mp4", "size": 100, "duration_seconds": 10, "width": 1080, "height": 1920},
            {"id": "1", "name": "one.mp4", "size": 100, "duration_seconds": 10, "width": 1080, "height": 1920},
        ],
    )
    job = service.prepare_job(
        credentials=None,
        spreadsheet="sheet",
        folder="folder",
        worksheet_name="ws",
        caption_column="Caption",
        team="Team",
        assignments=[{"file_id": "1", "person": "A"}, {"file_id": "2", "person": "B"}],
        share_to_feed=True,
    )
    assert [item["file_id"] for item in job["items"]] == ["2", "1"]
    assert all(item["status"] == "queued" for item in job["items"])


def test_first_failure_pauses_and_retry_reuses_creation_id(monkeypatch, tmp_path: Path):
    store = MemoryStore()
    monkeypatch.setattr(service, "instagram_publish_store", store)
    monkeypatch.setattr(service, "ensure_lifecycle", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        service,
        "download_drive_file",
        lambda credentials, file_id, destination: Path(destination).write_bytes(b"video"),
    )
    monkeypatch.setattr(service, "upload_public_file", lambda *args, **kwargs: "https://cdn.example/reel.mp4")

    class Client:
        def __init__(self):
            self.created = []
            self.waits = []
            self.fail_once = True

        def create_reel_container(self, url, caption, share):
            self.created.append(caption)
            return f"creation-{len(self.created)}"

        def wait_for_container(self, creation_id):
            self.waits.append(creation_id)
            if self.fail_once:
                self.fail_once = False
                raise RuntimeError("mock failure")

        def publish_container(self, creation_id):
            return f"media-{creation_id}"

    client = Client()
    job = {
        "id": "job",
        "status": "queued",
        "share_to_feed": True,
        "items": [
            {
                "sequence": 1,
                "file_id": "1",
                "file_name": "one.mp4",
                "caption": "A",
                "status": "queued",
                "public_url": None,
                "object_key": None,
                "creation_id": None,
                "media_id": None,
            },
            {
                "sequence": 2,
                "file_id": "2",
                "file_name": "two.mp4",
                "caption": "B",
                "status": "queued",
                "public_url": None,
                "object_key": None,
                "creation_id": None,
                "media_id": None,
            },
        ],
    }
    first = service.process_job(job=job, credentials=None, client=client, r2=object())
    assert [item["status"] for item in first["items"]] == ["failed", "paused"]
    assert first["items"][0]["creation_id"] == "creation-1"
    second = service.process_job(job=first, credentials=None, client=client, r2=object())
    assert [item["status"] for item in second["items"]] == ["published", "published"]
    assert client.created == ["A", "B"]


def test_r2_public_url_rejects_http_and_private_ip():
    for value in ("http://example.com", "https://127.0.0.1"):
        try:
            validate_public_base_url(value)
        except ValueError:
            continue
        raise AssertionError(f"accepted unsafe URL: {value}")
