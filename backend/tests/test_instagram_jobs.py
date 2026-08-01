from pathlib import Path

import pytest

from backend.app.services import instagram_publish_service as service
from backend.app.services.r2_service import validate_public_base_url


def test_reels_preflight_and_order(monkeypatch):
    team_header = "所屬團體"
    person_header = "人"
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


def test_reels_audio_bitrate_is_non_blocking(monkeypatch, tmp_path: Path):
    media = tmp_path / "reel.mp4"
    media.write_bytes(b"video")
    monkeypatch.setattr(
        service,
        "_probe_reel_file",
        lambda path: {
            "format": {"format_name": "mov,mp4", "duration": "10"},
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 1080,
                    "height": 1920,
                    "avg_frame_rate": "30/1",
                    "bit_rate": "8000000",
                },
                {
                    "codec_type": "audio",
                    "codec_name": "aac",
                    "sample_rate": "48000",
                    "bit_rate": "256000",
                },
            ],
        },
    )

    assert service.validate_reel_file(media)["audio_bitrate"] == 256000


def test_reels_audio_sample_rate_only_blocks_above_maximum(monkeypatch, tmp_path: Path):
    media = tmp_path / "reel.mp4"
    media.write_bytes(b"video")
    probe = {
        "format": {"format_name": "mov,mp4", "duration": "10"},
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1080,
                "height": 1920,
                "avg_frame_rate": "30/1",
                "bit_rate": "8000000",
            },
            {"codec_type": "audio", "codec_name": "aac", "sample_rate": "44100", "bit_rate": "128000"},
        ],
    }
    monkeypatch.setattr(service, "_probe_reel_file", lambda path: probe)

    assert service.validate_reel_file(media)["audio_sample_rate"] == 44100

    probe["streams"][1]["sample_rate"] = "48001"
    with pytest.raises(service.ReelValidationError, match="48 kHz"):
        service.validate_reel_file(media)


def test_r2_public_url_rejects_http_and_private_ip():
    for value in ("http://example.com", "https://127.0.0.1"):
        with pytest.raises(ValueError):
            validate_public_base_url(value)
