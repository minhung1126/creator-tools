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
            {"id": "2", "name": "two.mp4", "size": 100, "duration_seconds": 120, "width": 1080, "height": 1920},
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


def test_reels_preflight_uses_meta_limits_only():
    valid, reason, _ = service._preflight(
        {"name": "wide.mp4", "size": None, "duration_seconds": 900, "width": 1920, "height": 400}
    )
    assert valid is True
    assert reason is None

    for duration, expected in ((2.9, "3 秒"), (900.1, "15 分鐘")):
        valid, reason, _ = service._preflight(
            {"name": "reel.mp4", "size": 100, "duration_seconds": duration, "width": 1080, "height": 1920}
        )
        assert valid is False
        assert expected in reason

    valid, reason, _ = service._preflight(
        {"name": "reel.mp4", "size": 100, "duration_seconds": 120, "width": 1921, "height": 1080}
    )
    assert valid is False
    assert "1920" in reason


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
    monkeypatch.setattr(service, "validate_reel_file", lambda path: {"size_bytes": 5})
    deleted = []
    monkeypatch.setattr(service, "delete_public_file", lambda config, object_key: deleted.append(object_key))

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
    assert len(deleted) == 2
    assert all(item["r2_deleted"] for item in second["items"])
    assert all(item["public_url"] is None for item in second["items"])
    assert [item["stage"] for item in second["items"]] == ["completed", "completed"]
    assert second["progress"]["completed_count"] == 2
    assert second["progress"]["percent"] == 100


def test_r2_cleanup_failure_does_not_republish(monkeypatch):
    store = MemoryStore()
    monkeypatch.setattr(service, "instagram_publish_store", store)
    monkeypatch.setattr(service, "ensure_lifecycle", lambda *args, **kwargs: None)

    def fail_delete(*args, **kwargs):
        raise RuntimeError("denied")

    monkeypatch.setattr(service, "delete_public_file", fail_delete)

    class Client:
        def __init__(self):
            self.published = 0

        def publish_container(self, creation_id):
            self.published += 1
            return "media-1"

    job = {
        "id": "job",
        "status": "published",
        "items": [
            {
                "sequence": 1,
                "file_id": "1",
                "file_name": "one.mp4",
                "status": "published",
                "public_url": "https://cdn.example/reel.mp4",
                "object_key": "instagram-reels/one.mp4",
                "creation_id": "creation-1",
                "media_id": "media-1",
            }
        ],
    }
    client = Client()
    result = service.process_job(job=job, credentials=None, client=client, r2=object())
    assert result["items"][0]["status"] == "published"
    assert result["items"][0]["r2_delete_error"]
    assert client.published == 0


def test_r2_public_url_rejects_http_and_private_ip():
    for value in ("http://example.com", "https://127.0.0.1"):
        try:
            validate_public_base_url(value)
        except ValueError:
            continue
        raise AssertionError(f"accepted unsafe URL: {value}")


def test_public_job_reports_current_child_task_stage():
    job = {
        "id": "job",
        "status": "running",
        "items": [
            {
                "sequence": 1,
                "file_id": "1",
                "file_name": "one.mp4",
                "status": "queued",
                "stage": "uploading_r2",
                "stage_label": "上傳到 Cloudflare R2",
                "progress_percent": 38,
            },
            {
                "sequence": 2,
                "file_id": "2",
                "file_name": "two.mp4",
                "status": "queued",
                "stage": "queued",
                "stage_label": "排隊中",
                "progress_percent": 0,
            },
        ],
    }
    result = service.public_job(job)
    assert result["progress"] == {
        "total": 2,
        "completed_count": 0,
        "failed_count": 0,
        "paused_count": 0,
        "percent": 19,
        "current_item_sequence": 1,
        "current_file_name": "one.mp4",
        "current_stage": "uploading_r2",
        "current_stage_label": "上傳到 Cloudflare R2",
        "current_item_percent": 38,
    }
    assert result["results"][0]["stage"] == "uploading_r2"


def test_retry_resets_only_the_child_task_checkpoint():
    item = {
        "status": "failed",
        "stage": "creating_container",
        "progress_percent": 60,
        "error": "Meta API error",
        "public_url": "https://cdn.example/reel.mp4",
        "creation_id": "creation-1",
    }
    service.reset_item_for_retry(item)
    assert item["status"] == "queued"
    assert item["stage"] == "queued"
    assert item["error"] is None
    assert item["public_url"] == "https://cdn.example/reel.mp4"
    assert item["creation_id"] == "creation-1"
