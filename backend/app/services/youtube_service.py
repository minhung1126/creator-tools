from typing import List, Dict, Any, Optional
import googleapiclient.discovery
from google.oauth2.credentials import Credentials

def get_youtube_service(credentials: Credentials):
    return googleapiclient.discovery.build("youtube", "v3", credentials=credentials)

def fetch_playlist_items(credentials: Credentials, playlist_id: str) -> List[Dict[str, Any]]:
    service = get_youtube_service(credentials)
    items = []
    next_page_token = None
    
    while True:
        request = service.playlistItems().list(
            part="snippet,contentDetails",
            playlistId=playlist_id,
            maxResults=50,
            pageToken=next_page_token
        )
        response = request.execute()
        items.extend(response.get("items", []))
        
        next_page_token = response.get("nextPageToken")
        if not next_page_token:
            break
            
    return items

def fetch_video_details(credentials: Credentials, video_ids: List[str]) -> List[Dict[str, Any]]:
    if not video_ids:
        return []
    
    service = get_youtube_service(credentials)
    detailed_videos = []
    
    # Process in chunks of 50
    for i in range(0, len(video_ids), 50):
        chunk = video_ids[i:i+50]
        request = service.videos().list(
            part="snippet,contentDetails,status",
            id=",".join(chunk)
        )
        response = request.execute()
        detailed_videos.extend(response.get("items", []))
        
    return detailed_videos

def update_single_video_metadata(
    credentials: Credentials,
    video_id: str,
    new_title: str,
    new_description: str
) -> Dict[str, Any]:
    service = get_youtube_service(credentials)
    
    # 1. Fetch current video details to preserve existing snippet properties
    request = service.videos().list(part="snippet", id=video_id)
    response = request.execute()
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
        "categoryId": category_id
    }
    
    if "tags" in current_snippet:
        updated_snippet["tags"] = current_snippet["tags"]
    if current_snippet.get("defaultLanguage"):
        updated_snippet["defaultLanguage"] = current_snippet["defaultLanguage"]
    if current_snippet.get("defaultAudioLanguage"):
        updated_snippet["defaultAudioLanguage"] = current_snippet["defaultAudioLanguage"]
        
    # 2. Execute update
    update_body = {
        "id": video_id,
        "snippet": updated_snippet
    }
    
    update_request = service.videos().update(
        part="snippet",
        body=update_body
    )
    result = update_request.execute()
    return result

def publish_and_remove_playlist_item(
    credentials: Credentials,
    video_id: str,
    playlist_item_id: str
) -> Dict[str, Any]:
    service = get_youtube_service(credentials)
    
    # 1. Get current video snippet & status
    request = service.videos().list(part="snippet,status", id=video_id)
    response = request.execute()
    items = response.get("items", [])
    if not items:
        raise ValueError(f"Video {video_id} not found.")
        
    v = items[0]
    snippet = v["snippet"]
    status = v.get("status", {})
    
    # 2. Set privacyStatus to public
    status["privacyStatus"] = "public"
    
    update_body = {
        "id": video_id,
        "snippet": {
            "title": snippet.get("title", ""),
            "description": snippet.get("description", ""),
            "categoryId": snippet.get("categoryId", "22")
        },
        "status": status
    }
    
    update_res = service.videos().update(
        part="snippet,status",
        body=update_body
    ).execute()
    
    # 3. Delete from playlist
    delete_res = None
    if playlist_item_id:
        try:
            service.playlistItems().delete(id=playlist_item_id).execute()
            delete_res = {"deleted_playlist_item_id": playlist_item_id}
        except Exception as e:
            print(f"Warning: Failed to delete playlist item {playlist_item_id}: {e}")
            delete_res = {"error": str(e)}
            
    return {
        "video": update_res,
        "playlist_cleanup": delete_res
    }
