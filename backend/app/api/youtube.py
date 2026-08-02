import logging
import math
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from google.oauth2.credentials import Credentials
from pydantic import BaseModel

from backend.app.core.dependencies import require_credentials
from backend.app.core.runtime_config import runtime_config
from backend.app.services.sheets_service import (
    get_all_rows_for_sheet,
    get_sheet_headers,
    matches_team_person,
    normalize_text,
)
from backend.app.services.youtube_errors import YouTubeQuotaUnavailable
from backend.app.services.youtube_quota_service import youtube_quota_tracker
from backend.app.services.youtube_service import (
    fetch_playlist_items,
    fetch_playlist_preview,
    fetch_video_details,
    remove_playlist_item,
    set_video_public,
    update_single_video_metadata,
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
    video_type: str = "Video"
    worksheet_name: str
    title_column: str
    description_column: str
    team: str
    assignments: List[VideoAssignment]


class PublishCleanupInput(BaseModel):
    playlist_id: Optional[str] = ""


class QuotaEstimateInput(BaseModel):
    operation: Literal["youtube.metadata_update", "youtube.publish_cleanup"]
    item_count: int


def _quota_http_exception(exc: YouTubeQuotaUnavailable) -> HTTPException:
    return HTTPException(status_code=429, detail=exc.to_dict())


def _quota_estimate(operation: str, item_count: int) -> dict:
    count = max(int(item_count), 0)
    pages = math.ceil(count / 50) if count else 0
    if operation == "youtube.metadata_update":
        breakdown = [
            {"method": "videos.list", "calls": pages, "units": pages},
            {"method": "videos.update", "calls": count, "units": count * 50},
        ]
    elif operation == "youtube.publish_cleanup":
        breakdown = [
            {"method": "playlistItems.list", "calls": pages, "units": pages},
            {"method": "videos.list", "calls": pages, "units": pages},
            {"method": "videos.update", "calls": count, "units": count * 50},
            {"method": "playlistItems.delete", "calls": count, "units": count * 50},
        ]
    else:  # defensive for callers outside Pydantic/FastAPI
        raise ValueError("不支援的 YouTube quota estimate operation")

    projected = sum(int(item["units"]) for item in breakdown)
    usage = youtube_quota_tracker.get_usage()
    available = int(usage.get("effective_available_units") or 0)

    def cost_for(number: int) -> int:
        number_pages = math.ceil(number / 50) if number else 0
        if operation == "youtube.metadata_update":
            return number_pages + number * 50
        return number_pages * 2 + number * 100

    max_items_today = 0
    for number in range(1, count + 1):
        if cost_for(number) <= available:
            max_items_today = number
        else:
            break
    return {
        "operation": operation,
        "item_count": count,
        "projected_units": projected,
        "worst_case": True,
        "breakdown": breakdown,
        "effective_available_units": available,
        "can_complete_today": projected <= available,
        "max_items_today": max_items_today,
        "reset_at": usage.get("reset_at"),
        "reset_timezone": usage.get("reset_timezone", "America/Los_Angeles"),
    }


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
    try:
        return youtube_quota_tracker.get_usage()
    except YouTubeQuotaUnavailable as exc:
        raise _quota_http_exception(exc) from exc


@router.post("/quota-estimate")
def estimate_quota(payload: QuotaEstimateInput, creds: Credentials = Depends(require_credentials)):
    del creds
    if payload.item_count < 0:
        raise HTTPException(status_code=400, detail="item_count 不可小於 0")
    try:
        return _quota_estimate(payload.operation, payload.item_count)
    except YouTubeQuotaUnavailable as exc:
        raise _quota_http_exception(exc) from exc


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
    except YouTubeQuotaUnavailable as exc:
        raise _quota_http_exception(exc) from exc
    except Exception as exc:
        logger.error("Failed to fetch YouTube playlist items: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="讀取 YouTube 播放清單失敗，請稍後再試。") from exc


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


def _safe_workflow_error(exc: Exception) -> str:
    if isinstance(exc, YouTubeQuotaUnavailable):
        return exc.user_message
    message = str(exc).strip() or type(exc).__name__
    if len(message) > 240 or any(
        marker in message.casefold() for marker in ("token", "secret", "authorization", "response body")
    ):
        return "YouTube 處理失敗，請檢查設定後重試。"
    return message


def _direct_workflow_response(
    operation: str,
    results: list[dict],
    *,
    quota_error: Optional[YouTubeQuotaUnavailable] = None,
) -> dict:
    statuses = [str(item.get("status") or "") for item in results]
    response = {
        "operation": operation,
        "completed": quota_error is None and "not_attempted" not in statuses,
        "total_count": len(results),
        "succeeded_count": statuses.count("succeeded"),
        "warning_count": statuses.count("succeeded_with_warnings"),
        "skipped_count": statuses.count("skipped"),
        "failed_count": statuses.count("failed"),
        "not_attempted_count": statuses.count("not_attempted"),
        "quota_blocked": quota_error is not None,
        "reset_at": quota_error.reset_at if quota_error else None,
        "results": results,
    }
    if quota_error:
        response["quota_error"] = quota_error.to_dict()
    return response


@router.post("/batch-update")
def run_batch_metadata_update(payload: BatchUpdateInput, creds: Credentials = Depends(require_credentials)):
    """Validate and update selected videos synchronously, returning one result per video."""

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
        results: list[dict] = []
        quota_error: Optional[YouTubeQuotaUnavailable] = None
        for item in prepared:
            detail = details_map.get(item["video_id"])
            missing_video = item["status"] == "pending" and not detail
            skipped = item["status"] != "pending" or missing_video
            snippet = (detail or {}).get("snippet") or {}
            base_result = {
                "video_id": item["video_id"],
                "title": snippet.get("title") or item["video_id"],
                "description": snippet.get("description") or "",
                "thumbnail_url": _youtube_thumbnail(detail or {}, item["video_id"]),
                "person": item["person"],
            }
            if skipped:
                results.append(
                    {
                        **base_result,
                        "status": "skipped",
                        "reason": item.get("reason") or "YouTube 找不到此影片或目前帳號無權存取。",
                    }
                )
                continue
            if quota_error is not None:
                results.append({**base_result, "status": "not_attempted", "reason": quota_error.user_message})
                continue
            try:
                update_single_video_metadata(
                    creds,
                    item["video_id"],
                    str(item.get("new_title") or ""),
                    str(item.get("new_description") or ""),
                    current_snippet=snippet,
                )
                results.append(
                    {
                        **base_result,
                        "title": item.get("new_title") or base_result["title"],
                        "description": item.get("new_description") or "",
                        "status": "succeeded",
                        "reason": None,
                    }
                )
            except YouTubeQuotaUnavailable as exc:
                quota_error = exc
                results.append({**base_result, "status": "not_attempted", "reason": exc.user_message})
            except Exception as exc:
                results.append({**base_result, "status": "failed", "reason": _safe_workflow_error(exc)})
        return _direct_workflow_response("youtube.metadata_update", results, quota_error=quota_error)
    except YouTubeQuotaUnavailable as exc:
        raise _quota_http_exception(exc) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Batch metadata update failed: %s", type(exc).__name__, exc_info=True)
        raise HTTPException(status_code=500, detail="執行 YouTube metadata 更新失敗，請稍後再試。") from exc


@router.post("/publish-and-cleanup")
def run_publish_and_cleanup(payload: PublishCleanupInput, creds: Credentials = Depends(require_credentials)):
    """Snapshot To-Post, sort oldest-first, then publish each video synchronously."""

    playlist_id = payload.playlist_id or runtime_config.get("default_playlist_id")
    if not playlist_id:
        raise HTTPException(status_code=400, detail="Playlist ID is required.")
    try:
        raw_items = fetch_playlist_items(creds, playlist_id)
        if not raw_items:
            response = _direct_workflow_response("youtube.publish_cleanup", [])
            response["message"] = "To-Post 播放清單目前沒有影片。"
            return response
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
        results: list[dict] = []
        quota_error: Optional[YouTubeQuotaUnavailable] = None
        stopped_reason: Optional[str] = None
        for video_id in ordered_ids:
            detail = details_map.get(video_id)
            missing = detail is None
            snippet = (detail or {}).get("snippet") or {}
            base_result = {
                "video_id": video_id,
                "title": title_map.get(video_id) or snippet.get("title") or video_id,
                "description": snippet.get("description") or "",
                "thumbnail_url": _youtube_thumbnail(detail or {}, video_id),
            }
            if missing:
                results.append(
                    {
                        **base_result,
                        "status": "skipped",
                        "reason": "YouTube 找不到此影片或目前帳號無權存取。",
                    }
                )
                continue
            if quota_error is not None:
                results.append({**base_result, "status": "not_attempted", "reason": quota_error.user_message})
                continue
            if stopped_reason is not None:
                results.append({**base_result, "status": "not_attempted", "reason": stopped_reason})
                continue

            try:
                set_video_public(creds, video_id, current_video=detail)
            except YouTubeQuotaUnavailable as exc:
                quota_error = exc
                results.append({**base_result, "status": "not_attempted", "reason": exc.user_message})
                continue
            except Exception as exc:
                stopped_reason = f"前一支影片無法設為公開，後續影片未執行：{_safe_workflow_error(exc)}"
                results.append({**base_result, "status": "failed", "reason": _safe_workflow_error(exc)})
                continue

            try:
                remove_playlist_item(creds, playlist_item_map.get(video_id))
                results.append({**base_result, "status": "succeeded", "reason": None})
            except YouTubeQuotaUnavailable as exc:
                quota_error = exc
                results.append(
                    {
                        **base_result,
                        "status": "succeeded_with_warnings",
                        "reason": f"影片已設為公開，但尚未移出 To-Post：{exc.user_message}",
                    }
                )
            except Exception as exc:
                results.append(
                    {
                        **base_result,
                        "status": "succeeded_with_warnings",
                        "reason": f"影片已設為公開，但移出 To-Post 失敗：{_safe_workflow_error(exc)}",
                    }
                )
        response = _direct_workflow_response("youtube.publish_cleanup", results, quota_error=quota_error)
        response.update({"playlist_id": playlist_id, "sort_order": "published_at_ascending"})
        return response
    except YouTubeQuotaUnavailable as exc:
        raise _quota_http_exception(exc) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Publish cleanup workflow failed: %s", type(exc).__name__, exc_info=True)
        raise HTTPException(status_code=500, detail="執行 YouTube 公開清理失敗，請稍後再試。") from exc
