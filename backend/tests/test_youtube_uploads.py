from pathlib import Path
from types import SimpleNamespace

from backend.app.core.google_drive_input import parse_google_drive_input
from backend.app.core.youtube_quota_limiter import YouTubeQuotaLimiter
from backend.app.services.drive_service import sort_drive_items
from backend.app.services.youtube_upload_jobs import UploadJobStore, public_job


def test_drive_raw_id_and_common_urls_normalize_to_the_same_id():
    values = [
        "drive-file_123",
        "https://drive.google.com/drive/folders/drive-file_123?usp=sharing",
        "https://drive.google.com/file/d/drive-file_123/view",
        "https://drive.google.com/open?id=drive-file_123",
    ]
    assert [parse_google_drive_input(value).item_id for value in values] == ["drive-file_123"] * len(values)


def test_drive_parser_rejects_non_drive_hosts():
    try:
        parse_google_drive_input("https://example.com/file/d/drive-file_123")
    except ValueError as exc:
        assert "drive.google.com" in str(exc)
    else:
        raise AssertionError("Expected a non-Drive host to be rejected")


def test_drive_items_use_case_insensitive_natural_order():
    items = [{"id": name, "name": name} for name in ["10.mp4", "2.mp4", "1.mp4", "A.mp4"]]
    assert [item["name"] for item in sort_drive_items(items)] == ["1.mp4", "2.mp4", "10.mp4", "A.mp4"]


def test_upload_quota_bucket_tracks_videos_insert_separately(tmp_path: Path):
    ledger = YouTubeQuotaLimiter(
        tmp_path / "uploads.json",
        slot="primary",
        bucket="video_uploads",
        configured_limit=2,
        safety_buffer_units=0,
    )
    ledger.execute(SimpleNamespace(execute=lambda: {"id": "video-1"}), "videos.insert")
    usage = ledger.get_usage()
    assert usage["bucket"] == "video_uploads"
    assert usage["estimated_used_units"] == 1
    assert usage["effective_available_units"] == 1


def test_recovered_jobs_do_not_expose_temp_paths_and_resume_upload_id(tmp_path: Path):
    path = tmp_path / "jobs.json"
    store = UploadJobStore(path, tmp_path / "tmp")
    store.create(
        "owner",
        {
            "job_id": "12345678-1234-1234-1234-123456789abc",
            "status": "running",
            "items": [
                {
                    "status": "uploading",
                    "youtube_video_id": "video-1",
                    "temp_path": "C:/secret/temp.video",
                    "resumable_uri": "https://upload.example/session",
                }
            ],
        },
    )
    recovered = UploadJobStore(path, tmp_path / "tmp").get("owner", "12345678-1234-1234-1234-123456789abc")
    assert recovered["status"] == "queued"
    assert recovered["items"][0]["status"] == "uploaded"
    assert "temp_path" not in public_job(recovered)["items"][0]
    assert "resumable_uri" not in public_job(recovered)["items"][0]
