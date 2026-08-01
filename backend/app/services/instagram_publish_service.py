"""Preparation and durable execution of ordered Instagram publish jobs."""

import json
import mimetypes
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
from typing import Any

from backend.app.core.instagram_publish_store import instagram_publish_store
from backend.app.services.drive_service import download_drive_file, list_drive_videos
from backend.app.services.instagram_service import InstagramClient
from backend.app.services.r2_service import R2Config, delete_public_file, ensure_lifecycle, upload_public_file
from backend.app.services.sheets_service import (
    get_all_rows_for_sheet,
    get_sheet_headers,
    matches_team_person,
    normalize_text,
)

META_MAX_FILE_SIZE_BYTES = 1024 * 1024 * 1024
META_MIN_REEL_DURATION_SECONDS = 3
META_MAX_REEL_DURATION_SECONDS = 15 * 60
META_MAX_HORIZONTAL_PIXELS = 1920
META_MIN_FRAME_RATE = 23
META_MAX_FRAME_RATE = 60
META_MAX_VIDEO_BITRATE = 25_000_000
META_MAX_AUDIO_BITRATE = 128_000
META_AUDIO_SAMPLE_RATE = 48_000
META_VIDEO_CODECS = {"h264", "hevc"}
META_AUDIO_CODECS = {"aac"}
VIDEO_SUFFIXES = {".mp4", ".mov"}


class ReelValidationError(ValueError):
    """A downloaded video violates a documented Meta Reels requirement."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _error_text(exc: Exception) -> str:
    message = str(exc).strip() or type(exc).__name__
    lowered = message.casefold()
    if len(message) > 200 or any(
        marker in lowered for marker in ("access_token", "client_secret", "authorization", "bearer ", "response body")
    ):
        return "外部服務處理失敗，請檢查設定後重試。"
    return message


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _check_meta_constraints(
    *,
    suffix: str | None = None,
    size_bytes: float | None = None,
    duration_seconds: float | None = None,
    width: float | None = None,
) -> None:
    if suffix is not None and suffix.lower() not in VIDEO_SUFFIXES:
        raise ReelValidationError("影片容器必須為 Meta 支援的 MP4 或 MOV")
    if size_bytes is not None and size_bytes > META_MAX_FILE_SIZE_BYTES:
        raise ReelValidationError("影片超過 Meta 允許的 1 GB 檔案大小")
    if duration_seconds is not None:
        if duration_seconds < META_MIN_REEL_DURATION_SECONDS:
            raise ReelValidationError("影片短於 Meta 允許的 3 秒")
        if duration_seconds > META_MAX_REEL_DURATION_SECONDS:
            raise ReelValidationError("影片超過 Meta 允許的 15 分鐘")
    if width is not None and width > META_MAX_HORIZONTAL_PIXELS:
        raise ReelValidationError("影片水平寬度超過 Meta 允許的 1920 pixels")


def _preflight(file: dict[str, Any]) -> tuple[bool, str | None, dict[str, Any]]:
    duration = _number(file.get("duration_seconds"))
    width = _number(file.get("width"))
    height = _number(file.get("height"))
    size = _number(file.get("size"))
    metadata = {
        "size_bytes": file.get("size"),
        "duration_seconds": duration,
        "width": width,
        "height": height,
    }
    try:
        _check_meta_constraints(
            suffix=Path(file.get("name", "")).suffix,
            size_bytes=size,
            duration_seconds=duration,
            width=width,
        )
    except ReelValidationError as exc:
        return False, str(exc), metadata
    return True, None, metadata


def _frame_rate(value: Any) -> float | None:
    if not value or value in {"0/0", "N/A"}:
        return None
    try:
        return float(Fraction(str(value)))
    except (ValueError, ZeroDivisionError):
        return None


def _probe_reel_file(path: Path) -> dict[str, Any] | None:
    """Read media metadata when ffprobe is available in the runtime image."""
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None
    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=format_name,duration:stream=codec_type,codec_name,width,height,avg_frame_rate,r_frame_rate,bit_rate,sample_rate,duration",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise ReelValidationError("影片不是 Meta 支援的有效 MP4/MOV 媒體")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ReelValidationError("無法讀取影片媒體資訊") from exc


def validate_reel_file(path: Path) -> dict[str, Any]:
    """Validate a downloaded file against Meta's documented Reels requirements."""
    size_bytes = path.stat().st_size
    _check_meta_constraints(
        suffix=path.suffix,
        size_bytes=size_bytes,
    )
    metadata: dict[str, Any] = {"size_bytes": size_bytes}
    probe = _probe_reel_file(path)
    if not probe:
        return metadata

    format_info = probe.get("format") or {}
    format_names = set(str(format_info.get("format_name") or "").split(","))
    if not format_names.intersection({"mov", "mp4"}):
        raise ReelValidationError("影片容器必須為 Meta 支援的 MP4 或 MOV")

    streams = probe.get("streams") or []
    video = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
    if not video:
        raise ReelValidationError("影片缺少 video stream")
    video_codec = str(video.get("codec_name") or "").lower()
    if video_codec and video_codec not in META_VIDEO_CODECS:
        raise ReelValidationError("影片編碼必須為 Meta 支援的 H.264 或 HEVC")

    duration = _number(format_info.get("duration")) or _number(video.get("duration"))
    width = _number(video.get("width"))
    height = _number(video.get("height"))
    frame_rate = _frame_rate(video.get("avg_frame_rate") or video.get("r_frame_rate"))
    video_bitrate = _number(video.get("bit_rate"))
    metadata.update(
        {
            "duration_seconds": duration,
            "width": width,
            "height": height,
            "video_codec": video_codec or None,
            "frame_rate": frame_rate,
            "video_bitrate": video_bitrate,
        }
    )
    _check_meta_constraints(duration_seconds=duration, width=width)
    if frame_rate is not None and not META_MIN_FRAME_RATE <= frame_rate <= META_MAX_FRAME_RATE:
        raise ReelValidationError("影片 frame rate 必須介於 Meta 規格的 23–60 FPS")
    if video_bitrate is not None and video_bitrate > META_MAX_VIDEO_BITRATE:
        raise ReelValidationError("影片 bitrate 超過 Meta 允許的 25 Mbps")

    audio = next((stream for stream in streams if stream.get("codec_type") == "audio"), None)
    if audio:
        audio_codec = str(audio.get("codec_name") or "").lower()
        audio_sample_rate = _number(audio.get("sample_rate"))
        audio_bitrate = _number(audio.get("bit_rate"))
        metadata.update(
            {
                "audio_codec": audio_codec or None,
                "audio_sample_rate": audio_sample_rate,
                "audio_bitrate": audio_bitrate,
            }
        )
        if audio_codec and audio_codec not in META_AUDIO_CODECS:
            raise ReelValidationError("音訊編碼必須為 Meta 支援的 AAC")
        if audio_sample_rate is not None and audio_sample_rate != META_AUDIO_SAMPLE_RATE:
            raise ReelValidationError("音訊 sample rate 必須為 Meta 規格的 48 kHz")
        if audio_bitrate is not None and audio_bitrate > META_MAX_AUDIO_BITRATE:
            raise ReelValidationError("音訊 bitrate 超過 Meta 規格的 128 kbps")
    return metadata


def prepare_job(
    *,
    credentials,
    spreadsheet: str,
    folder: str,
    worksheet_name: str,
    caption_column: str,
    team: str,
    assignments: list[dict[str, str]],
    share_to_feed: bool,
) -> dict[str, Any]:
    headers = get_sheet_headers(credentials, spreadsheet, worksheet_name)
    missing = [name for name in ("所屬團體", "人", caption_column) if name not in headers]
    if missing:
        raise ValueError(f"工作表缺少欄位：{', '.join(missing)}")
    rows = get_all_rows_for_sheet(credentials, spreadsheet, worksheet_name)
    files = list_drive_videos(credentials, folder)
    file_map = {item["id"]: item for item in files}
    positions = {item["id"]: index for index, item in enumerate(files)}
    normalized_team = normalize_text(team)
    normalized_caption_column = normalize_text(caption_column)
    active = [
        (item["file_id"], normalize_text(item["person"]))
        for item in assignments
        if normalize_text(item.get("person", ""))
    ]
    active.sort(key=lambda item: positions.get(item[0], 999999))

    items = []
    for index, (file_id, person) in enumerate(active):
        file = file_map.get(file_id)
        item = {
            "sequence": index + 1,
            "file_id": file_id,
            "file_name": file.get("name", "") if file else "",
            "person": person,
            "status": "queued",
            "error": None,
            "public_url": None,
            "object_key": None,
            "r2_deleted": False,
            "r2_delete_error": None,
            "creation_id": None,
            "media_id": None,
            "preflight": {},
        }
        if not file:
            item.update(status="skipped", error="Drive 找不到影片")
            items.append(item)
            continue
        ok, reason, metadata = _preflight(file)
        item["preflight"] = metadata
        if not ok:
            item.update(status="skipped", error=reason)
            items.append(item)
            continue
        matching = [row for row in rows if matches_team_person(row, normalized_team, person)]
        captions = {
            normalize_text(str(row.get(normalized_caption_column) or ""))
            for row in matching
            if normalize_text(str(row.get(normalized_caption_column) or ""))
        }
        if len(captions) != 1:
            item.update(status="skipped", error="找不到唯一且非空白的內文")
            items.append(item)
            continue
        item["caption"] = next(iter(captions))
        items.append(item)

    return {
        "status": "queued",
        "created_at": _now(),
        "updated_at": _now(),
        "sort_order": "created_time_ascending",
        "worksheet_name": worksheet_name,
        "caption_column": normalized_caption_column,
        "team": normalized_team,
        "spreadsheet": spreadsheet,
        "folder": folder,
        "share_to_feed": share_to_feed,
        "items": items,
    }


def _counts(job: dict[str, Any]) -> dict[str, int]:
    statuses = [item.get("status") for item in job.get("items", [])]
    return {
        f"{status}_count": statuses.count(status)
        for status in ("queued", "uploaded", "container_created", "published", "failed", "paused", "skipped")
    }


def _cleanup_r2_file(item: dict[str, Any], r2: R2Config) -> None:
    if item.get("r2_deleted") or not item.get("object_key"):
        return
    try:
        delete_public_file(r2, item["object_key"])
    except Exception:
        item["r2_deleted"] = False
        item["r2_delete_error"] = "R2 影片刪除失敗，請重試。"
    else:
        item["r2_deleted"] = True
        item["r2_delete_error"] = None
        item["public_url"] = None


def public_job(job: dict[str, Any]) -> dict[str, Any]:
    result = {key: value for key, value in job.items() if key not in {"caption", "spreadsheet", "folder"}}
    result.pop("items", None)
    result.update(_counts(job))
    result["r2_cleanup_failed_count"] = sum(bool(item.get("r2_delete_error")) for item in job.get("items", []))
    result["results"] = [
        {key: value for key, value in item.items() if key != "caption"} for item in job.get("items", [])
    ]
    return result


def process_job(*, job: dict[str, Any], credentials, client: InstagramClient, r2: R2Config) -> dict[str, Any]:
    ensure_lifecycle(r2, days=3)
    failed = False
    for item in job.get("items", []):
        if item.get("status") == "skipped":
            continue
        if item.get("status") == "published":
            _cleanup_r2_file(item, r2)
            job["updated_at"] = _now()
            instagram_publish_store.save(job)
            continue
        if failed:
            item.update(status="paused", error="前一支影片發布失敗，流程已暫停")
            job["updated_at"] = _now()
            instagram_publish_store.save(job)
            continue
        try:
            safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", item["file_name"]).strip("-._") or "reel.mp4"
            object_key = (
                item.get("object_key")
                or f"instagram-reels/{datetime.now(timezone.utc):%Y/%m/%d}/{item['sequence']:03d}-{item['file_id']}-{safe_name}"
            )
            item["object_key"] = object_key
            if not item.get("public_url"):
                with tempfile.TemporaryDirectory(prefix="creator-tools-instagram-") as directory:
                    local = Path(directory) / item["file_name"]
                    download_drive_file(credentials, item["file_id"], local)
                    item["preflight"] = {**item.get("preflight", {}), **validate_reel_file(local)}
                    item["public_url"] = upload_public_file(
                        r2,
                        local,
                        object_key,
                        mimetypes.guess_type(item["file_name"])[0] or "video/mp4",
                    )
                item["status"] = "uploaded"
                job["updated_at"] = _now()
                instagram_publish_store.save(job)
            if not item.get("creation_id"):
                item["creation_id"] = client.create_reel_container(
                    item["public_url"], item.get("caption", ""), job.get("share_to_feed", True)
                )
                item["status"] = "container_created"
                job["updated_at"] = _now()
                instagram_publish_store.save(job)
            if not item.get("media_id"):
                client.wait_for_container(item["creation_id"])
                item["media_id"] = client.publish_container(item["creation_id"])
            item["status"] = "published"
            item["error"] = None
            job["updated_at"] = _now()
            instagram_publish_store.save(job)
            _cleanup_r2_file(item, r2)
            job["updated_at"] = _now()
            instagram_publish_store.save(job)
        except ReelValidationError as exc:
            item.update(status="skipped", error=str(exc), object_key=None)
            job["updated_at"] = _now()
            instagram_publish_store.save(job)
        except Exception as exc:
            item.update(status="failed", error=_error_text(exc))
            failed = True
            job["updated_at"] = _now()
            instagram_publish_store.save(job)
    job["status"] = "paused" if any(item.get("status") == "failed" for item in job.get("items", [])) else "completed"
    job["updated_at"] = _now()
    return instagram_publish_store.save(job)
