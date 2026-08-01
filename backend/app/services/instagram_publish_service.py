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
from backend.app.services.drive_service import (
    download_drive_file,
    ensure_published_folder,
    extract_drive_folder_id,
    list_drive_videos,
    move_drive_file_to_folder,
)
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

# The job is intentionally more granular than the public item status.  Statuses
# are useful for retry logic, while stages describe what the user is waiting
# for right now and give the UI a stable progress signal.
PIPELINE_STAGES = (
    ("queued", "排隊中", 0),
    ("downloading", "從 Google Drive 下載影片", 10),
    ("validating", "驗證 Meta 影片規格", 20),
    ("uploading_r2", "上傳到 Cloudflare R2", 38),
    ("uploaded", "R2 上傳完成", 45),
    ("creating_container", "透過 Meta API 建立 container", 60),
    ("container_created", "Meta container 已建立", 66),
    ("waiting_container", "等待 Meta 處理影片", 78),
    ("publishing", "透過 Meta API 發布", 92),
    ("moving_drive", "移入 Google Drive Published 資料夾", 96),
    ("cleaning_r2", "清理 R2 暫存影片", 98),
    ("completed", "已完成", 100),
)
_STAGE_META = {
    key: {"label": label, "progress": progress, "index": index}
    for index, (key, label, progress) in enumerate(PIPELINE_STAGES)
}
_STAGE_META.update(
    {
        "skipped": {"label": "已略過", "progress": 100, "index": len(PIPELINE_STAGES) - 1},
        "failed": {"label": "失敗", "progress": 0, "index": 0},
        "paused": {"label": "等待重試", "progress": 0, "index": 0},
        "drive_move_failed": {"label": "移入 Published 失敗", "progress": 96, "index": len(PIPELINE_STAGES) - 3},
        "r2_cleanup_failed": {"label": "R2 清理失敗", "progress": 97, "index": len(PIPELINE_STAGES) - 2},
    }
)
_PIPELINE_STAGE_COUNT = len(PIPELINE_STAGES)


class ReelValidationError(ValueError):
    """A downloaded video violates a documented Meta Reels requirement."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _set_item_stage(item: dict[str, Any], stage: str, *, status: str | None = None) -> None:
    """Attach a user-facing stage to an item without changing retry status by default."""
    meta = _STAGE_META.get(stage, _STAGE_META["queued"])
    previous_progress = float(item.get("progress_percent") or 0)
    item["stage"] = stage
    item["stage_label"] = meta["label"]
    item["stage_index"] = meta["index"]
    item["stage_count"] = _PIPELINE_STAGE_COUNT
    if stage == "failed":
        item["progress_percent"] = min(max(previous_progress, 0), 99)
    elif stage == "paused":
        item["progress_percent"] = min(max(previous_progress, 0), 99)
    else:
        item["progress_percent"] = meta["progress"]
    if status is not None:
        item["status"] = status


def _item_progress(item: dict[str, Any]) -> float:
    if "progress_percent" in item:
        try:
            return min(max(float(item["progress_percent"]), 0), 100)
        except (TypeError, ValueError):
            pass
    status = item.get("status") or "queued"
    published_stage = "completed"
    if item.get("drive_move_error"):
        published_stage = "drive_move_failed"
    elif item.get("r2_delete_error"):
        published_stage = "r2_cleanup_failed"
    fallback_stage = {
        "uploaded": "uploaded",
        "container_created": "container_created",
        "published": published_stage,
        "skipped": "skipped",
        "failed": "failed",
        "paused": "paused",
    }.get(status, "queued")
    return float(_STAGE_META[fallback_stage]["progress"])


def _progress_snapshot(job: dict[str, Any]) -> dict[str, Any]:
    items = job.get("items", [])
    total = len(items)
    completed_count = sum(1 for item in items if item.get("status") == "skipped" or item.get("stage") == "completed")
    failed_count = sum(
        1
        for item in items
        if item.get("status") == "failed" or item.get("stage") in {"drive_move_failed", "r2_cleanup_failed"}
    )
    paused_count = sum(1 for item in items if item.get("status") == "paused")
    current_item = None
    if job.get("status") == "failed":
        current_item = next((item for item in items if item.get("status") == "failed"), None)
    elif job.get("status") not in {"completed", "completed_with_warnings"}:
        current_item = next((item for item in items if item.get("status") == "failed"), None)
        if current_item is None:
            current_item = next(
                (
                    item
                    for item in items
                    if item.get("status") not in {"published", "skipped", "paused"}
                    or item.get("stage") in {"moving_drive", "drive_move_failed", "cleaning_r2", "r2_cleanup_failed"}
                ),
                None,
            )
    percent = round(sum(_item_progress(item) for item in items) / total) if total else 100
    current_stage = job.get("current_stage")
    current_stage_label = job.get("current_stage_label")
    current_sequence = None
    current_file_name = None
    current_item_percent = None
    if current_item is not None:
        current_stage = current_item.get("stage") or current_stage or "queued"
        current_stage_label = current_item.get("stage_label") or _STAGE_META.get(current_stage, {}).get(
            "label", "處理中"
        )
        current_sequence = current_item.get("sequence")
        current_file_name = current_item.get("file_name")
        current_item_percent = round(_item_progress(current_item))
    elif job.get("status") in {"completed", "completed_with_warnings"}:
        current_stage = "completed"
        current_stage_label = "發布工作完成"
    return {
        "total": total,
        "completed_count": completed_count,
        "failed_count": failed_count,
        "paused_count": paused_count,
        "percent": percent,
        "current_item_sequence": current_sequence,
        "current_file_name": current_file_name,
        "current_stage": current_stage,
        "current_stage_label": current_stage_label or "準備中",
        "current_item_percent": current_item_percent,
    }


def _save_job(job: dict[str, Any]) -> dict[str, Any]:
    job["updated_at"] = _now()
    job["progress"] = _progress_snapshot(job)
    return instagram_publish_store.save(job)


def reset_item_for_retry(item: dict[str, Any]) -> None:
    """Put one failed child task back in the queue without discarding checkpoints."""
    item["error"] = None
    if item.get("status") == "published" and (
        item.get("r2_delete_error") or item.get("drive_move_error") or not item.get("drive_moved")
    ):
        _set_item_stage(
            item,
            "moving_drive" if item.get("drive_move_error") or not item.get("drive_moved") else "cleaning_r2",
            status="published",
        )
        return
    _set_item_stage(item, "queued", status="queued")


def mark_job_failed(job: dict[str, Any], error: Exception) -> dict[str, Any]:
    job["status"] = "failed"
    job["error"] = _error_text(error)
    job["current_stage"] = "failed"
    job["current_stage_label"] = "發布工作失敗"
    return _save_job(job)


def _error_text(exc: Exception) -> str:
    message = str(exc).strip() or type(exc).__name__
    lowered = message.casefold()
    if len(message) > 200 or any(
        marker in lowered for marker in ("access_token", "client_secret", "authorization", "bearer ", "response body")
    ):
        return "外部服務處理失敗，請檢查設定後重試。"
    return message


def _duplicate_item(item: dict[str, Any], record: dict[str, Any]) -> None:
    existing_item = record.get("item") or {}
    already_published = existing_item.get("status") == "published" or bool(existing_item.get("media_id"))
    item.update(
        status="skipped",
        error=(
            "此影片已發布過，為避免重複上傳已略過。"
            if already_published
            else "此影片已有未完成的發布工作，請回到原工作重試。"
        ),
        duplicate_of_job_id=record.get("job_id"),
        duplicate_media_id=existing_item.get("media_id"),
    )


def _find_file_record(source_folder_id: str, file_id: str) -> dict[str, Any] | None:
    finder = getattr(instagram_publish_store, "find_file_record", None)
    if not callable(finder):
        return None
    return finder(source_folder_id, file_id)


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
            "public_url": None,
            "object_key": None,
            "r2_deleted": False,
            "r2_delete_error": None,
            "creation_id": None,
            "media_id": None,
            "drive_moved": False,
            "drive_moved_at": None,
            "drive_move_error": None,
            "published_folder_id": None,
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
        "published_folder_id": None,
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
    _set_item_stage(item, "cleaning_r2")
    try:
        delete_public_file(r2, item["object_key"])
    except Exception:
        item["r2_deleted"] = False
        item["r2_delete_error"] = "R2 影片刪除失敗，請重試。"
        _set_item_stage(item, "r2_cleanup_failed")
    else:
        item["r2_deleted"] = True
        item["r2_delete_error"] = None
        item["public_url"] = None
        _set_item_stage(item, "completed")


def _move_drive_item_to_published(job: dict[str, Any], item: dict[str, Any], credentials) -> None:
    """Move a successfully published source file without ever republishing it."""
    if item.get("drive_moved"):
        return

    source_folder_id = extract_drive_folder_id(job.get("source_folder_id") or job.get("folder", ""))
    if not source_folder_id:
        raise RuntimeError("找不到 Google Drive 來源資料夾 ID，無法移入 Published")

    published_folder_id = item.get("published_folder_id") or job.get("published_folder_id")
    if not published_folder_id:
        published_folder_id = ensure_published_folder(credentials, source_folder_id)
        job["published_folder_id"] = published_folder_id
    item["published_folder_id"] = published_folder_id
    move_drive_file_to_folder(credentials, item["file_id"], source_folder_id, published_folder_id)
    item["drive_moved"] = True
    item["drive_moved_at"] = _now()
    item["drive_move_error"] = None


def _finish_published_item(job: dict[str, Any], item: dict[str, Any], credentials, r2: R2Config) -> None:
    """Complete post-publish cleanup while keeping Instagram publication idempotent."""
    _set_item_stage(item, "moving_drive")
    try:
        _move_drive_item_to_published(job, item, credentials)
    except Exception as exc:
        item["drive_moved"] = False
        item["drive_move_error"] = _error_text(exc)
        _set_item_stage(item, "drive_move_failed")

    _set_item_stage(item, "cleaning_r2")
    _cleanup_r2_file(item, r2)
    if item.get("r2_delete_error"):
        _set_item_stage(item, "r2_cleanup_failed")
    elif item.get("drive_move_error"):
        _set_item_stage(item, "drive_move_failed")
    else:
        _set_item_stage(item, "completed")


def public_job(job: dict[str, Any]) -> dict[str, Any]:
    result = {key: value for key, value in job.items() if key not in {"caption", "spreadsheet", "folder"}}
    result.pop("items", None)
    result.update(_counts(job))
    result["progress"] = _progress_snapshot(job)
    result["r2_cleanup_failed_count"] = sum(bool(item.get("r2_delete_error")) for item in job.get("items", []))
    result["drive_move_failed_count"] = sum(bool(item.get("drive_move_error")) for item in job.get("items", []))
    result["drive_move_pending_count"] = sum(
        item.get("status") == "published" and not item.get("drive_moved") for item in job.get("items", [])
    )
    result["results"] = [
        {key: value for key, value in item.items() if key != "caption"} for item in job.get("items", [])
    ]
    return result


def process_job(*, job: dict[str, Any], credentials, client: InstagramClient, r2: R2Config) -> dict[str, Any]:
    job["status"] = "running"
    _save_job(job)
    ensure_lifecycle(r2, days=3)
    failed = False
    for item in job.get("items", []):
        if item.get("status") == "skipped":
            continue
        if item.get("status") == "published":
            _set_item_stage(item, "moving_drive")
            _save_job(job)
            _finish_published_item(job, item, credentials, r2)
            _save_job(job)
            continue
        if failed:
            item.update(error="前一支影片發布失敗，流程已暫停")
            _set_item_stage(item, "paused", status="paused")
            _save_job(job)
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
                    _set_item_stage(item, "downloading")
                    _save_job(job)
                    download_drive_file(credentials, item["file_id"], local)
                    _set_item_stage(item, "validating")
                    _save_job(job)
                    item["preflight"] = {**item.get("preflight", {}), **validate_reel_file(local)}
                    _set_item_stage(item, "uploading_r2")
                    _save_job(job)
                    item["public_url"] = upload_public_file(
                        r2,
                        local,
                        object_key,
                        mimetypes.guess_type(item["file_name"])[0] or "video/mp4",
                    )
                _set_item_stage(item, "uploaded", status="uploaded")
                _save_job(job)
            if not item.get("creation_id"):
                _set_item_stage(item, "creating_container")
                _save_job(job)
                item["creation_id"] = client.create_reel_container(
                    item["public_url"], item.get("caption", ""), job.get("share_to_feed", True)
                )
                _set_item_stage(item, "container_created", status="container_created")
                _save_job(job)
            if not item.get("media_id"):
                _set_item_stage(item, "waiting_container")
                _save_job(job)
                client.wait_for_container(item["creation_id"])
                _set_item_stage(item, "publishing")
                _save_job(job)
                item["media_id"] = client.publish_container(item["creation_id"])
            item["error"] = None
            _set_item_stage(item, "moving_drive", status="published")
            _save_job(job)
            _finish_published_item(job, item, credentials, r2)
            _save_job(job)
        except ReelValidationError as exc:
            item.update(error=str(exc), object_key=None)
            _set_item_stage(item, "skipped", status="skipped")
            _save_job(job)
        except Exception as exc:
            item.update(error=_error_text(exc))
            _set_item_stage(item, "failed", status="failed")
            failed = True
            _save_job(job)
    if any(item.get("status") == "failed" for item in job.get("items", [])):
        job["status"] = "paused"
    elif any(item.get("r2_delete_error") or item.get("drive_move_error") for item in job.get("items", [])):
        job["status"] = "completed_with_warnings"
    else:
        job["status"] = "completed"
    return _save_job(job)
