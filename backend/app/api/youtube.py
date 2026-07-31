from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from backend.app.core.config import settings
from backend.app.core.security import decrypt_session_data
from backend.app.services.google_auth import get_current_credentials
from backend.app.services.sheets_service import (
    get_all_rows_for_type,
    extract_spreadsheet_id
)
from backend.app.services.youtube_service import (
    fetch_playlist_items,
    fetch_video_details,
    update_single_video_metadata,
    publish_and_remove_playlist_item
)

router = APIRouter(prefix="/youtube", tags=["YouTube Operations"])

class PlaylistItemsInput(BaseModel):
    playlist_id: Optional[str] = ""

class VideoAssignment(BaseModel):
    video_id: str
    person: str  # "不編輯" or person name

class BatchUpdateInput(BaseModel):
    spreadsheet_url_or_id: Optional[str] = ""
    playlist_id: Optional[str] = ""
    video_type: str = "Video" # "Video" or "Shorts"
    team: str
    assignments: List[VideoAssignment]

class PublishCleanupInput(BaseModel):
    playlist_id: Optional[str] = ""

def require_credentials(request: Request):
    cookie = request.cookies.get("creator_tools_session")
    stored_tokens = decrypt_session_data(cookie) if cookie else None
    creds = get_current_credentials(stored_tokens)
    if not creds or not creds.valid:
        raise HTTPException(
            status_code=401,
            detail="Google account not connected or OAuth token expired. Please connect your Google account in Settings."
        )
    return creds

@router.post("/playlist-items")
def get_playlist_videos(payload: PlaylistItemsInput, request: Request):
    creds = require_credentials(request)
    playlist_id = payload.playlist_id or settings.DEFAULT_PLAYLIST_ID
    if not playlist_id:
        raise HTTPException(status_code=400, detail="Playlist ID is required.")
        
    try:
        raw_items = fetch_playlist_items(creds, playlist_id)
        if not raw_items:
            return {"playlist_id": playlist_id, "videos": []}
            
        video_ids = [item.get("contentDetails", {}).get("videoId") for item in raw_items if item.get("contentDetails", {}).get("videoId")]
        video_ids = [vid for vid in video_ids if vid]
        
        details_list = fetch_video_details(creds, video_ids)
        details_map = {vid["id"]: vid for vid in details_list}
        
        # Merge playlist item info with full video details
        parsed_videos = []
        for idx, item in enumerate(raw_items):
            v_id = item.get("contentDetails", {}).get("videoId")
            detail = details_map.get(v_id, {})
            snippet = detail.get("snippet", item.get("snippet", {}))
            thumbnails = snippet.get("thumbnails", {})
            thumb_url = (
                thumbnails.get("maxres", {}).get("url") or
                thumbnails.get("high", {}).get("url") or
                thumbnails.get("medium", {}).get("url") or
                thumbnails.get("default", {}).get("url") or ""
            )
            
            # Map playlist item ID for deletion if needed
            playlist_item_id = item.get("id")
            published_at = snippet.get("publishedAt", "")
            
            parsed_videos.append({
                "sequence": idx + 1,
                "video_id": v_id,
                "playlist_item_id": playlist_item_id,
                "title": snippet.get("title", ""),
                "thumbnail_url": thumb_url,
                "published_at": published_at,
                "category_id": snippet.get("categoryId", "")
            })
            
        # Sort by published_at from oldest to newest
        parsed_videos.sort(key=lambda x: x.get("published_at") or "")
        
        return {
            "playlist_id": playlist_id,
            "total": len(parsed_videos),
            "videos": parsed_videos
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch YouTube playlist items: {str(e)}")

@router.post("/batch-update")
def run_batch_metadata_update(payload: BatchUpdateInput, request: Request):
    creds = require_credentials(request)
    spreadsheet_id = payload.spreadsheet_url_or_id or settings.DEFAULT_SPREADSHEET_ID
    
    if not spreadsheet_id:
        raise HTTPException(status_code=400, detail="Spreadsheet ID or URL is required.")
        
    try:
        # Read Sheet rows for video type
        sheet_rows = get_all_rows_for_type(creds, spreadsheet_id, payload.video_type)
        
        title_key = "Youtube Title" if payload.video_type.lower() == "video" else "Shorts Title"
        desc_key = "Youtube Description" if payload.video_type.lower() == "video" else "Shorts Description"
        
        results = []
        updated_count = 0
        skipped_count = 0
        failed_count = 0
        
        for assignment in payload.assignments:
            vid = assignment.video_id
            person = assignment.person
            
            if not person or person == "不編輯":
                results.append({
                    "video_id": vid,
                    "person": person,
                    "status": "skipped",
                    "reason": "使用者選擇不編輯"
                })
                skipped_count += 1
                continue
                
            # Match team + person
            matches = [
                row for row in sheet_rows 
                if row.get("所屬團體") == payload.team and row.get("人") == person
            ]
            
            if len(matches) == 0:
                results.append({
                    "video_id": vid,
                    "person": person,
                    "status": "skipped",
                    "reason": f"找不到團體 {payload.team} 的人物 {person} 資料"
                })
                skipped_count += 1
                continue
                
            if len(matches) > 1:
                results.append({
                    "video_id": vid,
                    "person": person,
                    "status": "skipped",
                    "reason": f"團體 {payload.team} 的人物 {person} 有多筆 ({len(matches)} 筆) 資料，為避免誤更新已略過"
                })
                skipped_count += 1
                continue
                
            row = matches[0]
            new_title = str(row.get(title_key) or "").strip()
            new_desc = row.get(desc_key)
            
            if not new_title or new_desc is None:
                results.append({
                    "video_id": vid,
                    "person": person,
                    "status": "skipped",
                    "reason": f"Sheet 缺少 {title_key} 或 {desc_key}"
                })
                skipped_count += 1
                continue
                
            # Perform YouTube video metadata update
            try:
                update_res = update_single_video_metadata(
                    credentials=creds,
                    video_id=vid,
                    new_title=new_title,
                    new_description=str(new_desc)
                )
                results.append({
                    "video_id": vid,
                    "person": person,
                    "status": "updated",
                    "new_title": new_title,
                    "new_description_snippet": str(new_desc)[:50] + "..." if len(str(new_desc)) > 50 else str(new_desc)
                })
                updated_count += 1
            except Exception as update_err:
                results.append({
                    "video_id": vid,
                    "person": person,
                    "status": "failed",
                    "reason": str(update_err)
                })
                failed_count += 1
                
        return {
            "total_processed": len(payload.assignments),
            "updated_count": updated_count,
            "skipped_count": skipped_count,
            "failed_count": failed_count,
            "results": results
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Batch update failed: {str(e)}")

@router.post("/publish-and-cleanup")
def run_publish_and_cleanup(payload: PublishCleanupInput, request: Request):
    creds = require_credentials(request)
    playlist_id = payload.playlist_id or settings.DEFAULT_PLAYLIST_ID
    
    if not playlist_id:
        raise HTTPException(status_code=400, detail="Playlist ID is required.")
        
    try:
        raw_items = fetch_playlist_items(creds, playlist_id)
        if not raw_items:
            return {
                "playlist_id": playlist_id,
                "message": "To-Post 播放清單目前沒有影片，未進行任何公開或清理動作。",
                "results": []
            }
            
        video_item_map = {}
        for item in raw_items:
            vid = item.get("contentDetails", {}).get("videoId")
            if vid:
                video_item_map[vid] = item.get("id")
                
        video_ids = list(video_item_map.keys())
        details_list = fetch_video_details(creds, video_ids)
        
        # Sort by publish date
        details_list.sort(key=lambda v: v.get("snippet", {}).get("publishedAt") or "")
        
        results = []
        for v in details_list:
            vid = v["id"]
            playlist_item_id = video_item_map.get(vid)
            try:
                res = publish_and_remove_playlist_item(creds, vid, playlist_item_id)
                results.append({
                    "video_id": vid,
                    "title": v.get("snippet", {}).get("title", ""),
                    "status": "published_and_cleaned",
                    "details": res
                })
            except Exception as pub_err:
                results.append({
                    "video_id": vid,
                    "title": v.get("snippet", {}).get("title", ""),
                    "status": "failed",
                    "reason": str(pub_err)
                })
                
        return {
            "playlist_id": playlist_id,
            "total_processed": len(details_list),
            "results": results
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Publish & Cleanup failed: {str(e)}")
