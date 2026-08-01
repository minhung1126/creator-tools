"""Preparation and durable execution of ordered Instagram publish jobs."""

import mimetypes
import re
import tempfile
from datetime import datetime, timezone
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

MAX_FILE_SIZE = 1024 * 1024 * 1024
MAX_REEL_DURATION_SECONDS = 90
VIDEO_SUFFIXES = {".mp4", ".mov"}


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


def _preflight(file: dict[str, Any]) -> tuple[bool, str | None, dict[str, Any]]:
    duration = file.get("duration_seconds")
    width = file.get("width")
    height = file.get("height")
    metadata = {
        "size_bytes": file.get("size", 0),
        "duration_seconds": duration,
        "width": width,
        "height": height,
    }
    if Path(file.get("name", "")).suffix.lower() not in VIDEO_SUFFIXES:
        return False, "影片需為 MP4 或 MOV", metadata
    if not file.get("size") or int(file["size"]) > MAX_FILE_SIZE:
        return False, "Drive 檔案大小缺失或超過 1 GB", metadata
    if duration is None or duration <= 0 or duration > MAX_REEL_DURATION_SECONDS:
        return False, "影片 duration 缺失或超過 90 秒", metadata
    if not width or not height:
        return False, "Drive 未提供影片 dimensions", metadata
    return True, None, metadata


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
                    if local.stat().st_size > MAX_FILE_SIZE:
                        raise RuntimeError("下載後檔案超過 1 GB")
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
        except Exception as exc:
            item.update(status="failed", error=_error_text(exc))
            failed = True
            job["updated_at"] = _now()
            instagram_publish_store.save(job)
    job["status"] = "paused" if any(item.get("status") == "failed" for item in job.get("items", [])) else "completed"
    job["updated_at"] = _now()
    return instagram_publish_store.save(job)
