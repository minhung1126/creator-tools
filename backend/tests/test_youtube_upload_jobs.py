from pathlib import Path
from types import SimpleNamespace

from backend.app.services import youtube_upload_jobs
from backend.app.services.youtube_errors import YouTubeQuotaUnavailable
from backend.app.services.youtube_upload_jobs import UploadJobStore, YouTubeUploadWorker, public_job

JOB_ID = "12345678-1234-1234-1234-123456789abc"


def _fingerprint():
    return {
        "file_id": "drive-1",
        "version": "version-1",
        "md5_checksum": "checksum-1",
        "size": 5,
        "modified_time": "2026-08-19T00:00:00Z",
    }


def _install_worker_credentials(monkeypatch):
    monkeypatch.setattr(
        youtube_upload_jobs.credential_store,
        "get_google_credentials",
        lambda _owner: {"token": "google-token"},
    )
    monkeypatch.setattr(
        youtube_upload_jobs.credential_store,
        "get_youtube_credentials",
        lambda _owner, slot="primary": {"token": f"youtube-{slot}"},
    )
    monkeypatch.setattr(
        youtube_upload_jobs,
        "build_credentials_from_dict",
        lambda *_args, **_kwargs: SimpleNamespace(),
    )
    monkeypatch.setattr(youtube_upload_jobs, "has_drive_read_scope", lambda _credentials: True)
    monkeypatch.setattr(
        youtube_upload_jobs,
        "get_youtube_quota_tracker",
        lambda _slot: SimpleNamespace(),
    )


def _quota_error():
    return YouTubeQuotaUnavailable(
        code="youtube_quota_safety_blocked",
        http_status=None,
        reason="safety_cap_reached",
        method="playlistItems.insert",
        bucket="general",
        reset_at="2026-08-20T00:00:00-07:00",
        confirmed_by_google=False,
        user_message="今日 YouTube 配額已達安全上限。",
    )


def test_upload_jobs_are_account_scoped_and_public_progress_is_redacted(tmp_path: Path):
    store = UploadJobStore(tmp_path / "jobs.json", tmp_path / "tmp")
    job = store.create(
        "owner-a",
        {
            "job_id": JOB_ID,
            "status": "failed",
            "items": [
                {
                    "status": "added",
                    "youtube_video_id": "video-1",
                    "temp_path": "C:/private/video.tmp",
                    "resumable_uri": "https://upload.example/private",
                    "drive_metadata": {"private": "payload"},
                },
                {"status": "skipped", "youtube_video_id": None},
                {"status": "failed", "youtube_video_id": None},
            ],
        },
    )

    assert store.get("owner-b", JOB_ID) is None
    safe = public_job(job)

    assert "owner_sub" not in safe
    assert safe["progress"] == {"completed": 2, "total": 3, "uploaded": 1, "failed": 1}
    assert "temp_path" not in safe["items"][0]
    assert "resumable_uri" not in safe["items"][0]
    assert "drive_metadata" not in safe["items"][0]


def test_worker_uploads_downloaded_file_and_completes_job(monkeypatch, tmp_path: Path):
    _install_worker_credentials(monkeypatch)
    store = UploadJobStore(tmp_path / "jobs.json", tmp_path / "tmp")
    store.create(
        "owner-a",
        {
            "job_id": JOB_ID,
            "status": "queued",
            "playlist_id": "playlist-1",
            "youtube_slot": "secondary",
            "items": [
                {
                    "status": "pending",
                    "drive_file_id": "drive-1",
                    "name": "clip.mp4",
                    "title": "clip",
                    "mime_type": "video/mp4",
                    "size": 5,
                    "fingerprint": _fingerprint(),
                }
            ],
        },
    )
    metadata = {
        "id": "drive-1",
        "version": "version-1",
        "md5Checksum": "checksum-1",
        "size": 5,
        "modifiedTime": "2026-08-19T00:00:00Z",
        "mimeType": "video/mp4",
    }
    calls = []

    monkeypatch.setattr(youtube_upload_jobs, "get_drive_metadata", lambda _credentials, _file_id: metadata)

    def download(_credentials, _metadata, destination):
        calls.append("download")
        Path(destination).write_bytes(b"video")
        return {"size": 5}

    monkeypatch.setattr(youtube_upload_jobs, "download_drive_file", download)

    def upload(_context, file_path, *, title, mime_type, resumable_uri):
        calls.append(("upload", Path(file_path).read_bytes(), title, mime_type, resumable_uri))
        return {"id": "video-1"}

    monkeypatch.setattr(youtube_upload_jobs, "upload_video_resumable", upload)
    monkeypatch.setattr(
        youtube_upload_jobs,
        "insert_video_into_playlist",
        lambda _context, playlist_id, video_id: (
            calls.append(("insert", playlist_id, video_id)) or {"id": "playlist-item-1"}
        ),
    )

    YouTubeUploadWorker(store)._run_job(JOB_ID)

    saved = store.get("owner-a", JOB_ID)
    assert saved["status"] == "completed"
    assert saved["items"][0]["status"] == "added"
    assert saved["items"][0]["youtube_video_id"] == "video-1"
    assert saved["items"][0]["playlist_item_id"] == "playlist-item-1"
    assert calls == [
        "download",
        ("upload", b"video", "clip", "video/mp4", None),
        ("insert", "playlist-1", "video-1"),
    ]
    assert not (tmp_path / "tmp" / JOB_ID).exists()


def test_worker_pauses_after_playlist_quota_failure_and_preserves_uploaded_video(monkeypatch, tmp_path: Path):
    _install_worker_credentials(monkeypatch)
    store = UploadJobStore(tmp_path / "jobs.json", tmp_path / "tmp")
    store.create(
        "owner-a",
        {
            "job_id": JOB_ID,
            "status": "queued",
            "playlist_id": "playlist-1",
            "youtube_slot": "primary",
            "needs_reconciliation": True,
            "items": [
                {
                    "status": "uploaded",
                    "drive_file_id": "drive-1",
                    "youtube_video_id": "video-1",
                    "playlist_item_id": None,
                }
            ],
        },
    )
    monkeypatch.setattr(youtube_upload_jobs, "fetch_playlist_items", lambda *_args: [])
    monkeypatch.setattr(
        youtube_upload_jobs,
        "insert_video_into_playlist",
        lambda *_args: (_ for _ in ()).throw(_quota_error()),
    )

    YouTubeUploadWorker(store)._run_job(JOB_ID)

    saved = store.get("owner-a", JOB_ID)
    assert saved["status"] == "paused"
    assert saved["needs_reconciliation"] is True
    assert saved["items"][0]["status"] == "uploaded"
    assert saved["items"][0]["youtube_video_id"] == "video-1"
    assert saved["error"]["code"] == "youtube_quota_safety_blocked"


def test_worker_switches_auto_slot_after_playlist_quota_failure(monkeypatch, tmp_path: Path):
    _install_worker_credentials(monkeypatch)
    monkeypatch.setattr(
        youtube_upload_jobs,
        "settings",
        SimpleNamespace(youtube_oauth_slot=lambda _slot: SimpleNamespace(configured=True)),
    )
    monkeypatch.setattr(
        youtube_upload_jobs.credential_store,
        "get_youtube_public",
        lambda _owner, slot="primary": {"channel_id": "channel-1"},
    )
    store = UploadJobStore(tmp_path / "jobs.json", tmp_path / "tmp")
    store.create(
        "owner-a",
        {
            "job_id": JOB_ID,
            "status": "queued",
            "playlist_id": "playlist-1",
            "youtube_slot": "primary",
            "youtube_routing_mode": "auto_primary",
            "youtube_channel_id": "channel-1",
            "needs_reconciliation": True,
            "items": [
                {
                    "status": "uploaded",
                    "drive_file_id": "drive-1",
                    "youtube_video_id": "video-1",
                    "playlist_item_id": None,
                }
            ],
        },
    )
    monkeypatch.setattr(youtube_upload_jobs, "fetch_playlist_items", lambda *_args: [])
    calls = []

    def insert(context, _playlist_id, video_id):
        calls.append((context.slot, video_id))
        if context.slot == "primary":
            raise _quota_error()
        return {"id": "playlist-item-1"}

    monkeypatch.setattr(youtube_upload_jobs, "insert_video_into_playlist", insert)

    YouTubeUploadWorker(store)._run_job(JOB_ID)

    saved = store.get("owner-a", JOB_ID)
    assert saved["status"] == "completed"
    assert saved["youtube_slot"] == "secondary"
    assert saved["items"][0]["status"] == "added"
    assert calls == [("primary", "video-1"), ("secondary", "video-1")]
