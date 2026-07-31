import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from google.oauth2.credentials import Credentials
from pydantic import BaseModel

from backend.app.core.dependencies import require_credentials
from backend.app.core.runtime_config import runtime_config
from backend.app.services.sheets_service import get_all_rows_for_sheet, team_option_label
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
    if row.get("所屬團體") != team:
        return False
    row_person = str(row.get("人") or "").strip()
    if assignment_value == team_option_label(team):
        return not row_person
    return row_person == assignment_value


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
    if payload.title_column == payload.description_column:
        raise HTTPException(status_code=400, detail="Title and description columns must be different.")

    try:
        normalized_team = payload.team.strip()
        sheet_rows = get_all_rows_for_sheet(creds, spreadsheet_id, payload.worksheet_name)
        prepared = []
        for assignment in payload.assignments:
            video_id = assignment.video_id
            person = assignment.person.strip()
            if not person or person == "不編輯":
                prepared.append({"video_id": video_id, "person": person, "status": "skipped", "reason": "使用者選擇不編輯"})
                continue

            matches = [
                row for row in sheet_rows
                if assignment_matches_row(row, normalized_team, person)
            ]
            if len(matches) == 0:
                prepared.append({"video_id": video_id, "person": person, "status": "skipped", "reason": f"找不到團體 {normalized_team} 的選項 {person} 資料"})
                continue
            if len(matches) > 1:
                prepared.append({"video_id": video_id, "person": person, "status": "skipped", "reason": f"團體 {normalized_team} 的選項 {person} 有多筆 ({len(matches)} 筆) 資料，為避免誤更新已略過"})
                continue

            row = matches[0]
            new_title = str(row.get(payload.title_column) or "").strip()
            new_description = row.get(payload.description_column)
            if not new_title or new_description is None:
                prepared.append({
                    "video_id": video_id,
                    "person": person,
                    "status": "skipped",
                    "reason": f"工作表缺少 {payload.title_column} 或 {payload.description_column} 的內容",
                })
                continue
            prepared.append({
                "video_id": video_id,
                "person": person,
                "status": "pending",
                "new_title": new_title,
                "new_description": str(new_description),
            })

        pending_ids = [item["video_id"] for item in prepared if item["status"] == "pending"]
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
            "total_processed": len(payload.assignments),
            "updated_count": sum(1 for item in results if item["status"] == "updated"),
            "skipped_count": sum(1 for item in results if item["status"] == "skipped"),
            "failed_count": sum(1 for item in results if item["status"] == "failed"),
            "worksheet_name": payload.worksheet_name,
            "title_column": payload.title_column,
            "description_column": payload.description_column,
            "results": results,
            "quota_usage": youtube_quota_tracker.get_usage(),
        }
    except Exception as exc:
        logger.error("Batch update failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Batch update failed: {str(exc)}") from exc


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
            logger.warning("yt-dlp order lookup failed during publish; using API order: %s", exc)

        details_map = {item["id"]: item for item in fetch_video_details(creds, ordered_ids) if item.get("id")}
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
            "quota_usage": youtube_quota_tracker.get_usage(),
        }
    except Exception as exc:
        logger.error("Publish & Cleanup failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Publish & Cleanup failed: {str(exc)}") from exc
