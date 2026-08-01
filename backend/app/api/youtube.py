import logging
from collections import Counter
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from google.oauth2.credentials import Credentials
from pydantic import BaseModel

from backend.app.core.dependencies import require_credentials
from backend.app.core.runtime_config import runtime_config
from backend.app.core.task_repository import task_repository
from backend.app.services.sheets_service import (
    get_all_rows_for_sheet,
    get_sheet_headers,
    matches_team_person,
    normalize_text,
)
from backend.app.services.task_queue import task_queue
from backend.app.services.youtube_quota_service import youtube_quota_tracker
from backend.app.services.youtube_service import (
    fetch_playlist_items,
    fetch_playlist_preview,
    fetch_video_details,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/youtube", tags=["YouTube Operations"])


class PlaylistItemsInput(BaseModel):
    playlist_id: Optional[str] = ""


class VideoAssignment(BaseModel):
    video_id: str
    person: str


class BatchUpdateInput(BaseModel):
    spreadsheet_url_or_id: Optional[str] = ""
    playlist_id: Optional[str] = ""
    video_type: str = "Video"
    worksheet_name: str
    title_column: str
    description_column: str
    team: str
    assignments: List[VideoAssignment]


class PublishCleanupInput(BaseModel):
    playlist_id: Optional[str] = ""


def resolve_assignment_row(matches, title_column: str, description_column: str):
    """Accept duplicate matching rows when the selected output values are identical."""
    if not matches:
        return None, "not_found"

    distinct_values = {}
    for row in matches:
        title = normalize_text(row.get(title_column) or "")
        description = str(row.get(description_column) or "")
        distinct_values.setdefault((title, description), row)

    if len(distinct_values) > 1:
        return None, "conflict"
    return next(iter(distinct_values.values())), None


def skip_reason_counts(items):
    counts = Counter(item.get("reason_code", "other") for item in items if item.get("status") == "skipped")
    return dict(counts)


def all_skipped_message(items, attempted_count: int) -> str:
    labels = {
        "not_found": "找不到所選團體／人物資料",
        "conflict": "同一選項有互相衝突的多筆資料",
        "blank_title": "所選標題欄為空白",
        "other": "其他原因",
    }
    counts = skip_reason_counts(items)
    summary = "、".join(f"{labels.get(code, code)} {count} 支" for code, count in counts.items())
    examples = "；".join(f"{item.get('person') or '未指定'}：{item.get('reason')}" for item in items[:3])
    return f"所有已指定人物的 {attempted_count} 支影片都被略過。{summary}。範例：{examples}"


def upload_time_sort_key(video_id: str, details_map, original_positions):
    """Sort valid YouTube publishedAt values oldest-first with stable fallbacks."""
    detail = details_map.get(video_id) or {}
    published_at = (detail.get("snippet") or {}).get("publishedAt") or ""
    return (
        not bool(published_at),
        published_at,
        original_positions.get(video_id, 0),
    )


@router.get("/quota-usage")
def get_quota_usage():
    return youtube_quota_tracker.get_usage()


@router.post("/playlist-items")
def get_playlist_videos(payload: PlaylistItemsInput, creds: Credentials = Depends(require_credentials)):
    playlist_id = payload.playlist_id or runtime_config.get("default_playlist_id")
    if not playlist_id:
        raise HTTPException(status_code=400, detail="Playlist ID is required.")
    try:
        videos, source, fallback_reason = fetch_playlist_preview(creds, playlist_id)
        return {
            "playlist_id": playlist_id,
            "total": len(videos),
            "videos": videos,
            "source": source,
            "fallback_reason": fallback_reason,
            "quota_usage": youtube_quota_tracker.get_usage(),
        }
    except Exception as exc:
        logger.error("Failed to fetch YouTube playlist items: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch YouTube playlist items: {str(exc)}") from exc




def _youtube_thumbnail(detail: dict, video_id: str) -> str:
    thumbnails = (detail.get("snippet") or {}).get("thumbnails") or {}
    return (
        (thumbnails.get("maxres") or {}).get("url")
        or (thumbnails.get("standard") or {}).get("url")
        or (thumbnails.get("high") or {}).get("url")
        or (thumbnails.get("medium") or {}).get("url")
        or (thumbnails.get("default") or {}).get("url")
        or (f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg" if video_id else "")
    )


def _accepted_batch_response(batch_result: dict) -> dict:
    tasks = batch_result.get("tasks", [])
    public_tasks = [task_repository.public_task(task) for task in tasks]
    return {
        "accepted": True,
        "batch_id": batch_result["batch"]["id"],
        "task_ids": [task["id"] for task in tasks],
        "total_count": len(tasks),
        "queued_count": sum(task.get("status") == "queued" for task in tasks),
        "skipped_count": sum(task.get("status") == "skipped" for task in tasks),
        "tasks": public_tasks,
    }


@router.post("/batch-update", status_code=202)
def run_batch_metadata_update(payload: BatchUpdateInput, creds: Credentials = Depends(require_credentials)):
    """Validate synchronously, then enqueue one metadata task per selected video."""

    spreadsheet_id = payload.spreadsheet_url_or_id or runtime_config.get("default_spreadsheet_id")
    if not spreadsheet_id:
        raise HTTPException(status_code=400, detail="Spreadsheet ID or URL is required.")
    normalized_team = normalize_text(payload.team)
    title_column = normalize_text(payload.title_column)
    description_column = normalize_text(payload.description_column)
    if title_column == description_column:
        raise HTTPException(status_code=400, detail="Title and description columns must be different.")

    active_assignments = [
        (assignment.video_id, normalize_text(assignment.person))
        for assignment in payload.assignments
        if normalize_text(assignment.person) and normalize_text(assignment.person) != "不編輯"
    ]
    if not active_assignments:
        raise HTTPException(status_code=400, detail="目前沒有任何影片被指定人物；請先選擇人物或套用批量編輯後再執行。")
    try:
        headers = get_sheet_headers(creds, spreadsheet_id, payload.worksheet_name)
        required_headers = ["所屬團體", "人", title_column, description_column]
        missing_headers = [header for header in required_headers if header not in headers]
        if missing_headers:
            raise HTTPException(
                status_code=400,
                detail=f"工作表「{payload.worksheet_name}」缺少欄位：{', '.join(missing_headers)}。請重新刷新並選擇正確欄位。",
            )
        sheet_rows = get_all_rows_for_sheet(creds, spreadsheet_id, payload.worksheet_name)
        if not sheet_rows:
            raise HTTPException(status_code=400, detail=f"工作表「{payload.worksheet_name}」沒有可用資料列。")

        prepared: list[dict] = []
        for video_id, person in active_assignments:
            matches = [row for row in sheet_rows if matches_team_person(row, normalized_team, person)]
            row, match_error = resolve_assignment_row(matches, title_column, description_column)
            if match_error == "not_found":
                prepared.append(
                    {
                        "video_id": video_id,
                        "person": person,
                        "status": "skipped",
                        "reason": f"找不到團體 {normalized_team} 的選項 {person} 資料",
                    }
                )
            elif match_error == "conflict":
                prepared.append(
                    {
                        "video_id": video_id,
                        "person": person,
                        "status": "skipped",
                        "reason": f"團體 {normalized_team} 的選項 {person} 有多筆且標題或描述內容不同",
                    }
                )
            else:
                new_title = normalize_text(row.get(title_column) or "")
                new_description = str(row.get(description_column) or "")
                if not new_title:
                    prepared.append(
                        {
                            "video_id": video_id,
                            "person": person,
                            "status": "skipped",
                            "reason": f"工作表的 {title_column} 為空白",
                        }
                    )
                else:
                    prepared.append(
                        {
                            "video_id": video_id,
                            "person": person,
                            "status": "pending",
                            "new_title": new_title,
                            "new_description": new_description,
                        }
                    )

        details_map = {
            item["id"]: item
            for item in fetch_video_details(creds, [item["video_id"] for item in prepared])
            if item.get("id")
        }
        specs = []
        for index, item in enumerate(prepared, start=1):
            detail = details_map.get(item["video_id"])
            missing_video = item["status"] == "pending" and not detail
            skipped = item["status"] != "pending" or missing_video
            error = item.get("reason") or ("YouTube 找不到此影片或目前帳號無權存取。" if missing_video else None)
            specs.append(
                {
                    "platform": "youtube",
                    "operation": "youtube.metadata_update",
                    "queue_lane": "youtube",
                    "sequence_in_batch": index,
                    "video_id": item["video_id"],
                    "video_title": ((detail or {}).get("snippet") or {}).get("title") or item["video_id"],
                    "thumbnail_url": _youtube_thumbnail(detail or {}, item["video_id"]),
                    "status": "skipped" if skipped else "queued",
                    "stage": "skipped" if skipped else "queued",
                    "progress_percent": 100 if skipped else 0,
                    "retryable": False if skipped else True,
                    "error": error,
                    "payload": {
                        "person": item["person"],
                        "new_title": item.get("new_title"),
                        "new_description": item.get("new_description"),
                        "video_type": payload.video_type,
                    },
                }
            )
        batch_result = task_repository.create_batch_and_tasks(
            {
                "platform": "youtube",
                "operation": "youtube.metadata_update",
                "failure_policy": "continue",
                "metadata": {
                    "worksheet_name": payload.worksheet_name,
                    "title_column": title_column,
                    "description_column": description_column,
                    "team": normalized_team,
                    "video_type": payload.video_type,
                },
            },
            specs,
        )
        if any(task.get("status") == "queued" for task in batch_result.get("tasks", [])):
            task_queue.submit(batch_result["batch"]["id"])
        return _accepted_batch_response(batch_result)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Batch metadata task creation failed: %s", type(exc).__name__, exc_info=True)
        raise HTTPException(status_code=500, detail="建立 YouTube metadata 任務失敗，請稍後再試。") from exc


@router.post("/publish-and-cleanup", status_code=202)
def run_publish_and_cleanup(payload: PublishCleanupInput, creds: Credentials = Depends(require_credentials)):
    """Snapshot To-Post, sort oldest-first, then enqueue one task per video."""

    playlist_id = payload.playlist_id or runtime_config.get("default_playlist_id")
    if not playlist_id:
        raise HTTPException(status_code=400, detail="Playlist ID is required.")
    try:
        raw_items = fetch_playlist_items(creds, playlist_id)
        if not raw_items:
            return {
                "accepted": True,
                "batch_id": None,
                "task_ids": [],
                "total_count": 0,
                "queued_count": 0,
                "skipped_count": 0,
                "message": "To-Post 播放清單目前沒有影片。",
            }
        playlist_item_map: dict[str, str] = {}
        api_order: list[str] = []
        title_map: dict[str, str] = {}
        for item in raw_items:
            video_id = item.get("contentDetails", {}).get("videoId")
            if not video_id or video_id in playlist_item_map:
                continue
            playlist_item_map[video_id] = item.get("id")
            api_order.append(video_id)
            title_map[video_id] = item.get("snippet", {}).get("title", "")
        details_map = {item["id"]: item for item in fetch_video_details(creds, api_order) if item.get("id")}
        original_positions = {video_id: index for index, video_id in enumerate(api_order)}
        ordered_ids = sorted(
            api_order, key=lambda video_id: upload_time_sort_key(video_id, details_map, original_positions)
        )
        specs = []
        for index, video_id in enumerate(ordered_ids, start=1):
            detail = details_map.get(video_id)
            missing = detail is None
            specs.append(
                {
                    "platform": "youtube",
                    "operation": "youtube.publish_cleanup",
                    "queue_lane": "youtube",
                    "sequence_in_batch": index,
                    "video_id": video_id,
                    "video_title": title_map.get(video_id)
                    or ((detail or {}).get("snippet") or {}).get("title")
                    or video_id,
                    "thumbnail_url": _youtube_thumbnail(detail or {}, video_id),
                    "status": "skipped" if missing else "queued",
                    "stage": "skipped" if missing else "queued",
                    "progress_percent": 100 if missing else 0,
                    "retryable": False if missing else True,
                    "error": "YouTube 找不到此影片或目前帳號無權存取。" if missing else None,
                    "payload": {
                        "playlist_id": playlist_id,
                        "playlist_item_id": playlist_item_map.get(video_id),
                    },
                }
            )
        batch_result = task_repository.create_batch_and_tasks(
            {
                "platform": "youtube",
                "operation": "youtube.publish_cleanup",
                "failure_policy": "pause_remaining_in_batch",
                "metadata": {"playlist_id": playlist_id, "sort_order": "published_at_ascending"},
            },
            specs,
        )
        if any(task.get("status") == "queued" for task in batch_result.get("tasks", [])):
            task_queue.submit(batch_result["batch"]["id"])
        response = _accepted_batch_response(batch_result)
        response.update({"playlist_id": playlist_id, "sort_order": "published_at_ascending"})
        return response
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Publish cleanup task creation failed: %s", type(exc).__name__, exc_info=True)
        raise HTTPException(status_code=500, detail="建立 YouTube 公開清理任務失敗，請稍後再試。") from exc
