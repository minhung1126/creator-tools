import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import googleapiclient.discovery
from google.oauth2.credentials import Credentials
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from backend.app.services.youtube_quota_service import youtube_quota_tracker

logger = logging.getLogger(__name__)


def get_youtube_service(credentials: Credentials):
    return googleapiclient.discovery.build("youtube", "v3", credentials=credentials)


def _execute_with_quota(request, method: str):
    """Execute a YouTube API request and record its documented quota cost."""
    try:
        return request.execute()
    finally:
        youtube_quota_tracker.record(method)


def _playlist_url(playlist_id_or_url: str) -> str:
    value = (playlist_id_or_url or "").strip()
    if value.startswith("http://") or value.startswith("https://"):
        return value
    return f"https://www.youtube.com/playlist?list={value}"


def _entry_thumbnail(entry: Dict[str, Any], video_id: str) -> str:
    """Return a stable YouTube thumbnail URL instead of yt-dlp placeholder images."""
    if video_id:
        return f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
    if entry.get("thumbnail"):
        return str(entry["thumbnail"])
    thumbnails = entry.get("thumbnails") or []
    if isinstance(thumbnails, list):
        for thumbnail in reversed(thumbnails):
            if isinstance(thumbnail, dict) and thumbnail.get("url"):
                return str(thumbnail["url"])
    return ""


def _entry_published_at(entry: Dict[str, Any]) -> str:
    timestamp = entry.get("timestamp") or entry.get("release_timestamp")
    if isinstance(timestamp, (int, float)):
        return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    upload_date = str(entry.get("upload_date") or "")
    if len(upload_date) == 8 and upload_date.isdigit():
        try:
            return datetime.strptime(upload_date, "%Y%m%d").replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
        except ValueError:
            pass
    return ""


def fetch_playlist_entries_ytdlp(playlist_id: str) -> List[Dict[str, Any]]:
    """Read playlist metadata without consuming YouTube Data API quota."""
    options = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": "in_playlist",
        "ignoreerrors": True,
        "lazy_playlist": False,
    }
    try:
        with YoutubeDL(options) as ydl:
            info = ydl.extract_info(_playlist_url(playlist_id), download=False)
    except DownloadError as exc:
        raise RuntimeError(str(exc)) from exc

    entries = (info or {}).get("entries") or []
    parsed: List[Dict[str, Any]] = []
    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            continue
        video_id = str(entry.get("id") or "").strip()
        if not video_id:
            continue
        parsed.append({
            "sequence": index,
            "video_id": video_id,
            "playlist_item_id": "",
            "title": str(entry.get("title") or ""),
            "thumbnail_url": _entry_thumbnail(entry, video_id),
            "published_at": _entry_published_at(entry),
            "category_id": "",
        })
    if not parsed:
        raise RuntimeError("yt-dlp 未取得任何播放清單項目，可能是私人播放清單或 YouTube 暫時限制存取。")
    return parsed


def fetch_playlist_items(credentials: Credentials, playlist_id: str) -> List[Dict[str, Any]]:
    """Fetch all items from a YouTube playlist (handles pagination)."""
    service = get_youtube_service(credentials)
    items = []
    next_page_token = None
    while True:
        request = service.playlistItems().list(
            part="snippet,contentDetails",
            playlistId=playlist_id,
            maxResults=50,
            pageToken=next_page_token,
        )
        response = _execute_with_quota(request, "playlistItems.list")
        items.extend(response.get("items", []))
        next_page_token = response.get("nextPageToken")
        if not next_page_token:
            break
    return items


def fetch_video_details(credentials: Credentials, video_ids: List[str]) -> List[Dict[str, Any]]:
    """Fetch detailed info for video IDs in batches of 50."""
    if not video_ids:
        return []
    service = get_youtube_service(credentials)
    detailed_videos = []
    for i in range(0, len(video_ids), 50):
        chunk = video_ids[i:i + 50]
        request = service.videos().list(
            part="snippet,contentDetails,status",
            id=",".join(chunk),
        )
        response = _execute_with_quota(request, "videos.list")
        detailed_videos.extend(response.get("items", []))
    return detailed_videos


def _api_playlist_preview(credentials: Credentials, playlist_id: str) -> List[Dict[str, Any]]:
    raw_items = fetch_playlist_items(credentials, playlist_id)
    if not raw_items:
        return []
    video_ids = [
        item.get("contentDetails", {}).get("videoId")
        for item in raw_items
        if item.get("contentDetails", {}).get("videoId")
    ]
    details_map = {
        item["id"]: item
        for item in fetch_video_details(credentials, video_ids)
        if item.get("id")
    }
    parsed_videos = []
    for index, item in enumerate(raw_items, start=1):
        video_id = item.get("contentDetails", {}).get("videoId")
        detail = details_map.get(video_id, {})
        snippet = detail.get("snippet", item.get("snippet", {}))
        thumbnails = snippet.get("thumbnails", {})
        thumbnail_url = (
            thumbnails.get("maxres", {}).get("url")
            or thumbnails.get("high", {}).get("url")
            or thumbnails.get("medium", {}).get("url")
            or thumbnails.get("default", {}).get("url")
            or (f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg" if video_id else "")
        )
        parsed_videos.append({
            "sequence": index,
            "video_id": video_id,
            "playlist_item_id": item.get("id"),
            "title": snippet.get("title", ""),
            "thumbnail_url": thumbnail_url,
            "published_at": snippet.get("publishedAt", ""),
            "category_id": snippet.get("categoryId", ""),
        })
    return parsed_videos


def fetch_playlist_preview(
    credentials: Credentials,
    playlist_id: str,
) -> Tuple[List[Dict[str, Any]], str, Optional[str]]:
    """Prefer yt-dlp for quota-free previews, then fall back to the API."""
    try:
        return fetch_playlist_entries_ytdlp(playlist_id), "yt-dlp", None
    except Exception as exc:
        logger.warning("yt-dlp playlist preview failed; using YouTube API: %s", exc)
        return _api_playlist_preview(credentials, playlist_id), "youtube-api", str(exc)


def update_single_video_metadata(
    credentials: Credentials,
    video_id: str,
    new_title: str,
    new_description: str,
    current_snippet: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Update title/description while preserving existing snippet properties."""
    service = get_youtube_service(credentials)
    if current_snippet is None:
        request = service.videos().list(part="snippet", id=video_id)
        response = _execute_with_quota(request, "videos.list")
        items = response.get("items", [])
        if not items:
            raise ValueError(f"Video ID {video_id} not found on YouTube.")
        current_snippet = items[0]["snippet"]
    category_id = current_snippet.get("categoryId")
    if not category_id:
        raise ValueError(f"Cannot retrieve categoryId for video {video_id}.")
    updated_snippet = {
        "title": new_title,
        "description": new_description,
        "categoryId": category_id,
    }
    if "tags" in current_snippet:
        updated_snippet["tags"] = current_snippet["tags"]
    if current_snippet.get("defaultLanguage"):
        updated_snippet["defaultLanguage"] = current_snippet["defaultLanguage"]
    if current_snippet.get("defaultAudioLanguage"):
        updated_snippet["defaultAudioLanguage"] = current_snippet["defaultAudioLanguage"]
    update_request = service.videos().update(
        part="snippet",
        body={"id": video_id, "snippet": updated_snippet},
    )
    return _execute_with_quota(update_request, "videos.update")


def publish_and_remove_playlist_item(
    credentials: Credentials,
    video_id: str,
    playlist_item_id: str,
    current_video: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Set a video public and remove its playlist item without deleting it."""
    service = get_youtube_service(credentials)
    if current_video is None:
        request = service.videos().list(part="status", id=video_id)
        response = _execute_with_quota(request, "videos.list")
        items = response.get("items", [])
        if not items:
            raise ValueError(f"Video {video_id} not found.")
        current_video = items[0]
    status = dict(current_video.get("status", {}))
    status["privacyStatus"] = "public"
    update_request = service.videos().update(
        part="status",
        body={"id": video_id, "status": status},
    )
    update_result = _execute_with_quota(update_request, "videos.update")
    playlist_cleanup = None
    if playlist_item_id:
        try:
            delete_request = service.playlistItems().delete(id=playlist_item_id)
            _execute_with_quota(delete_request, "playlistItems.delete")
            playlist_cleanup = {"deleted_playlist_item_id": playlist_item_id}
        except Exception as exc:
            logger.warning("Failed to delete playlist item %s: %s", playlist_item_id, exc)
            playlist_cleanup = {"error": str(exc)}
    return {
        "video": update_result,
        "playlist_cleanup": playlist_cleanup,
    }
