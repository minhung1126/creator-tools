"""Preparation and media validation for SQLite-backed Instagram publish tasks."""

import json
import shutil
import subprocess
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
from typing import Any

from backend.app.core.task_repository import task_repository
from backend.app.services.drive_service import extract_drive_folder_id, list_drive_videos
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
META_MAX_AUDIO_SAMPLE_RATE = 48_000
META_VIDEO_CODECS = {"h264", "hevc"}
META_AUDIO_CODECS = {"aac"}
VIDEO_SUFFIXES = {".mp4", ".mov"}

_PREPARATION_STAGES = {
    "queued": ("排隊中", 0),
    "skipped": ("已略過", 100),
}


class ReelValidationError(ValueError):
    """A downloaded video violates a hard Meta Reels upload requirement."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _set_item_stage(item: dict[str, Any], stage: str, *, status: str | None = None) -> None:
    label, progress = _PREPARATION_STAGES.get(stage, (stage, 0))
    item["stage"] = stage
    item["stage_label"] = label
    item["progress_percent"] = progress
    if status is not None:
        item["status"] = status


def _duplicate_item(item: dict[str, Any], record: dict[str, Any]) -> None:
    existing_item = record.get("item") or {}
    already_published = bool(existing_item.get("media_id")) or record.get("task_status") in {
        "succeeded",
        "succeeded_with_warnings",
    }
    item.update(
        status="skipped",
        error=(
            "此影片已發布過，為避免重複上傳已略過。"
            if already_published
            else "此影片已有未完成的發布工作，請回到原工作重試。"
        ),
        duplicate_of_job_id=record.get("batch_id"),
        duplicate_media_id=existing_item.get("media_id"),
    )


def _find_file_record(source_folder_id: str, file_id: str) -> dict[str, Any] | None:
    try:
        return task_repository.find_instagram_record(source_folder_id, file_id)
    except Exception:
        return None


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _check_hard_reel_constraints(
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
        _check_hard_reel_constraints(
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
    """Validate a downloaded file against hard Meta Reels upload requirements."""

    size_bytes = path.stat().st_size
    _check_hard_reel_constraints(suffix=path.suffix, size_bytes=size_bytes)
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
    _check_hard_reel_constraints(duration_seconds=duration, width=width)
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
        if audio_sample_rate is not None and audio_sample_rate > META_MAX_AUDIO_SAMPLE_RATE:
            raise ReelValidationError("音訊 sample rate 不得超過 Meta 規格的 48 kHz")
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
    source_folder_id = extract_drive_folder_id(folder)
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
            "r2_deleted": False,
            "drive_moved": False,
            "preflight": {},
        }
        _set_item_stage(item, "queued")
        existing_record = _find_file_record(source_folder_id, file_id)
        if existing_record:
            existing_item = existing_record.get("item") or {}
            if not item["file_name"]:
                item["file_name"] = existing_item.get("file_name", "")
            _duplicate_item(item, existing_record)
            _set_item_stage(item, "skipped", status="skipped")
            items.append(item)
            continue
        if not file:
            item.update(error="Drive 找不到影片")
            _set_item_stage(item, "skipped", status="skipped")
            items.append(item)
            continue
        ok, reason, metadata = _preflight(file)
        item["preflight"] = metadata
        if not ok:
            item.update(error=reason)
            _set_item_stage(item, "skipped", status="skipped")
            items.append(item)
            continue
        matching = [row for row in rows if matches_team_person(row, normalized_team, person)]
        captions = {
            normalize_text(str(row.get(normalized_caption_column) or ""))
            for row in matching
            if normalize_text(str(row.get(normalized_caption_column) or ""))
        }
        if len(captions) != 1:
            item.update(error="找不到唯一且非空白的內文")
            _set_item_stage(item, "skipped", status="skipped")
            items.append(item)
            continue
        item["caption"] = next(iter(captions))
        items.append(item)

    return {
        "status": "queued",
        "created_at": _now(),
        "updated_at": _now(),
        "sort_order": "name_ascending",
        "worksheet_name": worksheet_name,
        "caption_column": normalized_caption_column,
        "team": normalized_team,
        "spreadsheet": spreadsheet,
        "folder": folder,
        "source_folder_id": source_folder_id,
        "share_to_feed": share_to_feed,
        "items": items,
    }
