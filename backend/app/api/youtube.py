import logging
from collections import Counter
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from google.oauth2.credentials import Credentials
from pydantic import BaseModel

from backend.app.core.dependencies import require_credentials
from backend.app.core.runtime_config import runtime_config
from backend.app.services.sheets_service import (
    get_all_rows_for_sheet,
    get_sheet_headers,
    normalize_text,
    team_option_label,
)
from backend.app.services.youtube_quota_service import youtube_quota_tracker
from backend.app.services.youtube_service import (
    fetch_playlist_entries_ytdlp,
    fetch_playlist_items,
    fetch_playlist_preview,
    fetch_video_details,
    publish_and_remove_playlist_item,
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
    playlist_id: Optional[str] = ""
    video_type: str = "Video"
    worksheet_name: str
    title_column: str
    description_column: str
    team: str
    assignments: List[VideoAssignment]


class PublishCleanupInput(BaseModel):
    playlist_id: Optional[str] = ""


def assignment_matches_row(row, team: str, assignment_value: str) -> bool:
    """Match either a named person row or the selected team's blank-person whole-team row."""
    if normalize_text(row.get("所屬團體") or "") != team:
        return False
    row_person = normalize_text(row.get("人") or "")
    if assignment_value == team_option_label(team):
        return not row_person
    return row_person == assignment_value


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
    examples = "；".join(
        f"{item.get('person') or '未指定'}：{item.get('reason')}"
        for item in items[:3]
    )
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


@router.post("/batch-update")
def run_batch_metadata_update(payload: BatchUpdateInput, creds: Credentials = Depends(require_credentials)):
    spreadsheet_id = payload.spreadsheet_url_or_id or runtime_config.get("default_spreadsheet_id")
    if not spreadsheet_id:
        raise HTTPException(status_code=400, detail="Spreadsheet ID or URL is required.")

    normalized_team = normalize_text(payload.team)
    title_column = normalize_text(payload.title_column)
    description_column = normalize_text(payload.description_column)
    if title_column == description_column:
        raise HTTPException(status_code=400, detail="Title and description columns must be different.")

    active_assignments = []
    for assignment in payload.assignments:
        person = normalize_text(assignment.person)
        if person and person != "不編輯":
            active_assignments.append((assignment.video_id, person))
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

        prepared = []
        for video_id, person in active_assignments:
            matches = [
                row for row in sheet_rows
                if assignment_matches_row(row, normalized_team, person)
            ]
            row, match_error = resolve_assignment_row(matches, title_column, description_column)
            if match_error == "not_found":
                prepared.append({
                    "video_id": video_id,
                    "person": person,
                    "status": "skipped",
                    "reason_code": "not_found",
                    "reason": f"找不到團體 {normalized_team} 的選項 {person} 資料",
                })
                continue
            if match_error == "conflict":
                prepared.append({
                    "video_id": video_id,
                    "person": person,
                    "status": "skipped",
                    "reason_code": "conflict",
                    "reason": f"團體 {normalized_team} 的選項 {person} 有多筆且標題或描述內容不同",
                })
                continue

            new_title = normalize_text(row.get(title_column) or "")
            new_description = str(row.get(description_column) or "")
            if not new_title:
                prepared.append({
                    "video_id": video_id,
                    "person": person,
                    "status": "skipped",
                    "reason_code": "blank_title",
                    "reason": f"工作表的 {title_column} 為空白",
                })
                continue
            prepared.append({
                "video_id": video_id,
                "person": person,
                "status": "pending",
                "new_title": new_title,
                "new_description": new_description,
            })

        pending_ids = [item["video_id"] for item in prepared if item["status"] == "pending"]
        if not pending_ids:
            raise HTTPException(
                status_code=400,
                detail=all_skipped_message(prepared, len(active_assignments)),
            )

        details_map = {item["id"]: item for item in fetch_video_details(creds, pending_ids) if item.get("id")}
        results = []
        for item in prepared:
            if item["status"] != "pending":
                results.append(item)
                continue
            video_id = item["video_id"]
            detail = details_map.get(video_id)
            if not detail:
                results.append({"video_id": video_id, "person": item["person"], "status": "failed", "reason": "YouTube 找不到此影片或目前帳號無權存取。"})
                continue
            try:
                update_single_video_metadata(
                    credentials=creds,
                    video_id=video_id,
                    new_title=item["new_title"],
                    new_description=item["new_description"],
                    current_snippet=detail.get("snippet", {}),
                )
                results.append({
                    "video_id": video_id,
                    "person": item["person"],
                    "status": "updated",
                    "new_title": item["new_title"],
                    "new_description_snippet": item["new_description"][:50] + "..." if len(item["new_description"]) > 50 else item["new_description"],
                })
            except Exception as update_error:
                logger.error("Failed to update video %s: %s", video_id, update_error, exc_info=True)
                results.append({"video_id": video_id, "person": item["person"], "status": "failed", "reason": str(update_error)})

        return {
            "total_processed": len(active_assignments),
            "updated_count": sum(1 for item in results if item["status"] == "updated"),
            "skipped_count": sum(1 for item in results if item["status"] == "skipped"),
            "failed_count": sum(1 for item in results if item["status"] == "failed"),
            "skip_reason_counts": skip_reason_counts(results),
            "worksheet_name": payload.worksheet_name,
            "title_column": title_column,
            "description_column": description_column,
            "results": results,
            "quota_usage": youtube_quota_tracker.get_usage(),
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Batch update failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"批次更新失敗：{str(exc)}") from exc


@router.post("/publish-and-cleanup")
def run_publish_and_cleanup(payload: PublishCleanupInput, creds: Credentials = Depends(require_credentials)):
    playlist_id = payload.playlist_id or runtime_config.get("default_playlist_id")
    if not playlist_id:
        raise HTTPException(status_code=400, detail="Playlist ID is required.")
    try:
        raw_items = fetch_playlist_items(creds, playlist_id)
        if not raw_items:
            return {
                "playlist_id": playlist_id,
                "message": "To-Post 播放清單目前沒有影片，未進行任何公開或清理動作。",
                "results": [],
                "quota_usage": youtube_quota_tracker.get_usage(),
            }
        playlist_item_map = {}
        api_order = []
        api_title_map = {}
        for item in raw_items:
            video_id = item.get("contentDetails", {}).get("videoId")
            if not video_id:
                continue
            playlist_item_map[video_id] = item.get("id")
            api_order.append(video_id)
            api_title_map[video_id] = item.get("snippet", {}).get("title", "")

        source = "youtube-api"
        title_map = dict(api_title_map)
        ordered_ids = list(api_order)
        fallback_reason = None
        try:
            ytdlp_entries = fetch_playlist_entries_ytdlp(playlist_id)
            ytdlp_ids = [item["video_id"] for item in ytdlp_entries if item["video_id"] in playlist_item_map]
            ordered_ids = ytdlp_ids + [video_id for video_id in api_order if video_id not in ytdlp_ids]
            title_map.update({item["video_id"]: item.get("title", "") for item in ytdlp_entries})
            source = "yt-dlp"
        except Exception as exc:
            fallback_reason = str(exc)
            logger.warning("yt-dlp lookup failed during publish; using API playlist data: %s", exc)

        details_map = {item["id"]: item for item in fetch_video_details(creds, ordered_ids) if item.get("id")}
        original_positions = {video_id: index for index, video_id in enumerate(ordered_ids)}
        ordered_ids.sort(key=lambda video_id: upload_time_sort_key(video_id, details_map, original_positions))

        results = []
        for video_id in ordered_ids:
            detail = details_map.get(video_id)
            title = title_map.get(video_id) or (detail or {}).get("snippet", {}).get("title", "")
            if not detail:
                results.append({"video_id": video_id, "title": title, "status": "failed", "reason": "YouTube 找不到此影片或目前帳號無權存取。"})
                continue
            try:
                response = publish_and_remove_playlist_item(creds, video_id, playlist_item_map.get(video_id), current_video=detail)
                results.append({"video_id": video_id, "title": title, "status": "published_and_cleaned", "details": response})
            except Exception as publish_error:
                logger.error("Failed to publish video %s: %s", video_id, publish_error, exc_info=True)
                results.append({"video_id": video_id, "title": title, "status": "failed", "reason": str(publish_error)})
        return {
            "playlist_id": playlist_id,
            "total_processed": len(ordered_ids),
            "results": results,
            "source": source,
            "fallback_reason": fallback_reason,
            "sort_order": "published_at_ascending",
            "quota_usage": youtube_quota_tracker.get_usage(),
        }
    except Exception as exc:
        logger.error("Publish & Cleanup failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Publish & Cleanup failed: {str(exc)}") from exc
