import re
from pathlib import Path

from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload


def extract_drive_folder_id(value: str) -> str:
    value = (value or "").strip()
    match = re.search(r"/folders/([A-Za-z0-9_-]+)", value)
    return match.group(1) if match else value


def list_drive_videos(credentials, folder_url_or_id: str):
    folder_id = extract_drive_folder_id(folder_url_or_id)
    service = build("drive", "v3", credentials=credentials)
    items = []
    page_token = None
    while True:
        response = (
            service.files()
            .list(
                q=f"'{folder_id}' in parents and trashed = false and mimeType contains 'video/'",
                fields="nextPageToken,files(id,name,mimeType,size,createdTime,videoMediaMetadata,webViewLink)",
                orderBy="createdTime asc",
                pageSize=100,
                pageToken=page_token,
            )
            .execute()
        )
        for item in response.get("files", []):
            metadata = item.get("videoMediaMetadata") or {}
            duration_ms = int(metadata.get("durationMillis") or 0) or None
            width = int(metadata.get("width") or 0) or None
            height = int(metadata.get("height") or 0) or None
            items.append(
                {
                    "id": item.get("id"),
                    "name": item.get("name", ""),
                    "mime_type": item.get("mimeType", ""),
                    "size": int(item.get("size") or 0),
                    "created_time": item.get("createdTime", ""),
                    "video_metadata": metadata,
                    "duration_ms": duration_ms,
                    "duration_seconds": duration_ms / 1000 if duration_ms is not None else None,
                    "width": width,
                    "height": height,
                    "web_view_link": item.get("webViewLink", ""),
                }
            )
        page_token = response.get("nextPageToken")
        if not page_token:
            break
    return items


def download_drive_file(credentials, file_id: str, destination: Path):
    service = build("drive", "v3", credentials=credentials)
    request = service.files().get_media(fileId=file_id)
    with destination.open("wb") as output:
        downloader = MediaIoBaseDownload(output, request, chunksize=8 * 1024 * 1024)
        done = False
        while not done:
            _, done = downloader.next_chunk()
