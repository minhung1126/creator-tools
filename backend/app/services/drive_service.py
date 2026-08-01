import io
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
    response = service.files().list(
        q=f"'{folder_id}' in parents and trashed = false and mimeType contains 'video/'",
        fields="files(id,name,mimeType,size,createdTime,videoMediaMetadata,webViewLink)",
        orderBy="createdTime asc",
        pageSize=1000,
    ).execute()
    items = []
    for item in response.get("files", []):
        items.append({
            "id": item.get("id"),
            "name": item.get("name", ""),
            "mime_type": item.get("mimeType", ""),
            "size": int(item.get("size") or 0),
            "created_time": item.get("createdTime", ""),
            "video_metadata": item.get("videoMediaMetadata") or {},
            "web_view_link": item.get("webViewLink", ""),
        })
    return items


def download_drive_file(credentials, file_id: str, destination: Path):
    service = build("drive", "v3", credentials=credentials)
    request = service.files().get_media(fileId=file_id)
    with destination.open("wb") as output:
        downloader = MediaIoBaseDownload(output, request, chunksize=8 * 1024 * 1024)
        done = False
        while not done:
            _, done = downloader.next_chunk()
