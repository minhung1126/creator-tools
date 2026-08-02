import logging
from typing import Any, Dict, List, Optional, Tuple

import googleapiclient.discovery
from google.oauth2.credentials import Credentials

from backend.app.services.youtube_errors import YouTubeQuotaUnavailable
from backend.app.services.youtube_quota_service import youtube_quota_tracker

logger = logging.getLogger(__name__)


def get_youtube_service(credentials: Credentials):
    return googleapiclient.discovery.build("youtube", "v3", credentials=credentials)


def _execute_with_quota(request, method: str):
    """Reserve the documented cost before executing the request."""

    return youtube_quota_tracker.execute(request, method)


def _deduplicate_videos(videos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Keep the first occurrence of each video ID while preserving source order."""
    unique_videos: List[Dict[str, Any]] = []
    seen_video_ids = set()

    for video in videos:
        video_id = str(video.get("video_id") or "").strip()
        if not video_id or video_id in seen_video_ids:
            continue
        seen_video_ids.add(video_id)
        unique_videos.append(
            {
                **video,
                "sequence": len(unique_videos) + 1,
                "video_id": video_id,
            }
        )

    return unique_videos


def _deduplicate_video_ids(video_ids: List[str]) -> List[str]:
    """Return non-empty video IDs in first-appearance order without duplicates."""
    return list(dict.fromkeys(str(video_id).strip() for video_id in video_ids if str(video_id or "").strip()))


def _snippet_thumbnail(snippet: Dict[str, Any], video_id: str) -> str:
    thumbnails = snippet.get("thumbnails") or {}
    return (
        thumbnails.get("maxres", {}).get("url")
        or thumbnails.get("standard", {}).get("url")
        or thumbnails.get("high", {}).get("url")
        or thumbnails.get("medium", {}).get("url")
        or thumbnails.get("default", {}).get("url")
        or (f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg" if video_id else "")
    )


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
    """Fetch detailed info for unique video IDs in batches of 50."""
    video_ids = _deduplicate_video_ids(video_ids)
    if not video_ids:
        return []
    service = get_youtube_service(credentials)
    detailed_videos = []
    for i in range(0, len(video_ids), 50):
        chunk = video_ids[i : i + 50]
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
    details_map = {item["id"]: item for item in fetch_video_details(credentials, video_ids) if item.get("id")}
    parsed_videos = []
    for index, item in enumerate(raw_items, start=1):
        video_id = item.get("contentDetails", {}).get("videoId")
        detail = details_map.get(video_id, {})
        snippet = detail.get("snippet", item.get("snippet", {}))
        parsed_videos.append(
            {
                "sequence": index,
                "video_id": video_id,
                "playlist_item_id": item.get("id"),
                "title": snippet.get("title", ""),
                "description": snippet.get("description", ""),
                "thumbnail_url": _snippet_thumbnail(snippet, video_id),
                "published_at": snippet.get("publishedAt", ""),
                "category_id": snippet.get("categoryId", ""),
            }
        )
    return _deduplicate_videos(parsed_videos)


def fetch_playlist_preview(
    credentials: Credentials,
    playlist_id: str,
) -> Tuple[List[Dict[str, Any]], str, Optional[str]]:
    """Use authenticated playlistItems and videos API data for preview/order."""
    return _api_playlist_preview(credentials, playlist_id), "youtube-api", None


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


def get_video_status(
    credentials: Credentials,
    video_id: str,
    current_video: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Return the status object needed by the idempotent publish handler."""

    if current_video is not None:
        return dict(current_video.get("status", {}))
    service = get_youtube_service(credentials)
    request = service.videos().list(part="status", id=video_id)
    response = _execute_with_quota(request, "videos.list")
    items = response.get("items", [])
    if not items:
        raise ValueError(f"Video {video_id} not found.")
    return dict(items[0].get("status", {}))


def set_video_public(
    credentials: Credentials,
    video_id: str,
    current_video: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Set a video public, treating an already-public video as success."""

    status = get_video_status(credentials, video_id, current_video)
    if status.get("privacyStatus") == "public":
        return {"id": video_id, "status": status, "already_public": True}
    service = get_youtube_service(credentials)
    status["privacyStatus"] = "public"
    request = service.videos().update(part="status", body={"id": video_id, "status": status})
    return _execute_with_quota(request, "videos.update")


def remove_playlist_item(credentials: Credentials, playlist_item_id: Optional[str]) -> Dict[str, Any]:
    """Remove a To-Post item; a 404 is the idempotent 'already removed' case."""

    if not playlist_item_id:
        return {"already_removed": True}
    service = get_youtube_service(credentials)
    try:
        request = service.playlistItems().delete(id=playlist_item_id)
        _execute_with_quota(request, "playlistItems.delete")
        return {"deleted_playlist_item_id": playlist_item_id}
    except Exception as exc:
        response = getattr(exc, "resp", None)
        if getattr(response, "status", None) == 404:
            return {"deleted_playlist_item_id": playlist_item_id, "already_removed": True}
        raise


def publish_and_remove_playlist_item(
    credentials: Credentials,
    video_id: str,
    playlist_item_id: str,
    current_video: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Set a video public and remove its playlist item without deleting it."""
    if current_video is None:
        service = get_youtube_service(credentials)
        request = service.videos().list(part="status", id=video_id)
        response = _execute_with_quota(request, "videos.list")
        items = response.get("items", [])
        if not items:
            raise ValueError(f"Video {video_id} not found.")
        current_video = items[0]
    update_result = set_video_public(credentials, video_id, current_video)
    try:
        playlist_cleanup = remove_playlist_item(credentials, playlist_item_id)
    except YouTubeQuotaUnavailable:
        raise
    except Exception as exc:
        logger.warning("Failed to delete playlist item %s: %s", playlist_item_id, exc)
        playlist_cleanup = {"error": str(exc)}
    return {
        "video": update_result,
        "playlist_cleanup": playlist_cleanup,
    }
