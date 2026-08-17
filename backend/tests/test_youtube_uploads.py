from pathlib import Path
from types import SimpleNamespace

from backend.app.api import youtube_uploads
from backend.app.core.google_drive_input import parse_google_drive_input
from backend.app.core.youtube_quota_limiter import YouTubeQuotaLimiter
from backend.app.services.drive_service import sort_drive_items
from backend.app.services.youtube_upload_jobs import UploadJobStore, YouTubeUploadWorker, public_job


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


def _install_upload_quota_usage(monkeypatch, general_available: int, upload_available: int = 100):
    monkeypatch.setattr(
        youtube_uploads,
        "get_youtube_quota_tracker",
        lambda _slot: SimpleNamespace(
            get_usage=lambda: {
                "estimated_used_units": 0,
                "configured_project_limit": 10_000,
                "effective_available_units": general_available,
                "reset_at": "general-reset",
            }
        ),
    )
    monkeypatch.setattr(
        youtube_uploads,
        "get_youtube_upload_quota_tracker",
        lambda _slot: SimpleNamespace(
            get_usage=lambda: {
                "estimated_used_units": 0,
                "configured_project_limit": 100,
                "effective_available_units": upload_available,
                "reset_at": "upload-reset",
            }
        ),
    )


def test_upload_quota_plan_matches_two_validations_and_execution(monkeypatch):
    for insertion_count in (1, 10, 50):
        _install_upload_quota_usage(monkeypatch, general_available=2 + 50 * insertion_count)

        preview = youtube_uploads._quota_summary_at_stage(
            "primary",
            upload_count=insertion_count,
            insertion_count=insertion_count,
            general_reads_spent=1,
        )
        after_create = youtube_uploads._quota_summary_at_stage(
            "primary",
            upload_count=insertion_count,
            insertion_count=insertion_count,
            general_reads_spent=2,
        )

        assert preview["projected_full_workflow"]["general"] == 2 + 50 * insertion_count
        assert preview["remaining_required"]["general"] == 1 + 50 * insertion_count
        assert after_create["remaining_required"]["general"] == 50 * insertion_count
        assert preview["video_uploads"]["projected_units"] == insertion_count
        assert preview["can_complete"] is True
        assert preview["preview_read"] == {"general": 1, "video_uploads": 0}
        assert preview["job_required"] == {"general": 1 + 50 * insertion_count, "video_uploads": insertion_count}
        assert preview["total"] == {"general": 2 + 50 * insertion_count, "video_uploads": insertion_count}
        assert preview["create_can_execute"] is True


def test_upload_quota_boundary_after_preview_requires_revalidation_read(monkeypatch):
    insertion_count = 10
    for available, expected in (
        (50 * insertion_count, False),
        (50 * insertion_count + 1, True),
        (50 * insertion_count + 2, True),
    ):
        _install_upload_quota_usage(monkeypatch, general_available=available, upload_available=10)
        plan = youtube_uploads._quota_summary_at_stage(
            "primary",
            upload_count=10,
            insertion_count=insertion_count,
            general_reads_spent=1,
        )
        assert plan["remaining_required"]["general"] == 50 * insertion_count + 1
        assert plan["general"]["can_complete"] is expected


def test_upload_preview_requires_both_playlist_reads_before_start(monkeypatch):
    insertion_count = 10
    for available, expected in (
        (50 * insertion_count, False),
        (50 * insertion_count + 1, False),
        (50 * insertion_count + 2, True),
    ):
        _install_upload_quota_usage(monkeypatch, general_available=available, upload_available=10)
        plan = youtube_uploads._quota_summary_at_stage(
            "primary",
            upload_count=10,
            insertion_count=insertion_count,
            general_reads_spent=0,
        )
        assert plan["remaining_required"]["general"] == 50 * insertion_count + 2
        assert plan["general"]["can_complete"] is expected


def test_resume_playlist_does_not_consume_video_upload_bucket(monkeypatch):
    _install_upload_quota_usage(monkeypatch, general_available=500, upload_available=0)
    plan = youtube_uploads._quota_summary_at_stage(
        "primary",
        upload_count=0,
        insertion_count=10,
        general_reads_spent=2,
    )

    assert plan["estimated_units"]["complete_workflow"] == {"video_uploads": 0, "general": 502, "total": 502}
    assert plan["remaining_required"] == {"general": 500, "video_uploads": 0}
    assert plan["can_complete"] is True


def test_preview_slot_uses_secondary_when_primary_only_fits_partial_workflow(monkeypatch):
    _install_upload_quota_usage(monkeypatch, general_available=501, upload_available=10)
    usage_by_slot = {"primary": 501, "secondary": 502}
    selected_hints = []

    def choose(_session, _owner, **kwargs):
        hint = kwargs.get("slot_hint")
        selected_hints.append(hint)
        slot = hint or "primary"
        return SimpleNamespace(slot=slot, routing_mode="auto_primary")

    monkeypatch.setattr(youtube_uploads, "choose_youtube_upload_slot", choose)
    monkeypatch.setattr(
        youtube_uploads,
        "get_youtube_quota_tracker",
        lambda slot: SimpleNamespace(
            get_usage=lambda: {
                "estimated_used_units": 0,
                "configured_project_limit": 10_000,
                "effective_available_units": usage_by_slot[slot],
            }
        ),
    )

    decision = youtube_uploads._choose_preview_slot(
        SimpleNamespace(cookies={}),
        "owner",
        ready_count=10,
        upload_count=10,
        insertion_count=10,
    )

    assert decision.slot == "secondary"
    assert selected_hints == [None, "secondary"]


def test_reconciliation_marks_existing_playlist_item_without_inserting_again(monkeypatch, tmp_path: Path):
    store = UploadJobStore(tmp_path / "jobs.json", tmp_path / "tmp")
    job_id = "12345678-1234-1234-1234-123456789abc"
    store.create(
        "owner",
        {
            "job_id": job_id,
            "status": "paused",
            "youtube_slot": "primary",
            "playlist_id": "playlist",
            "needs_reconciliation": True,
            "items": [
                {"status": "uploaded", "youtube_video_id": "video-1", "playlist_item_id": None},
            ],
        },
    )
    monkeypatch.setattr(
        "backend.app.services.youtube_upload_jobs.fetch_playlist_items",
        lambda _context, _playlist_id: [
            {"id": "playlist-item-1", "contentDetails": {"videoId": "video-1"}},
        ],
    )
    worker = YouTubeUploadWorker(store)

    worker._reconcile_playlist_if_needed(SimpleNamespace(), "owner", job_id)

    item = store.get("owner", job_id)["items"][0]
    assert item["status"] == "added"
    assert item["playlist_item_id"] == "playlist-item-1"
    assert store.get("owner", job_id)["needs_reconciliation"] is False
