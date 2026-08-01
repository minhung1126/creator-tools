import re
from pathlib import Path

from google.auth.transport.requests import AuthorizedSession
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

DRIVE_THUMBNAIL_SIZE = 1600


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
                fields="nextPageToken,files(id,name,mimeType,size,createdTime,videoMediaMetadata,webViewLink,thumbnailLink)",
                orderBy="name asc",
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
            size_value = item.get("size")
            items.append(
                {
                    "id": item.get("id"),
                    "name": item.get("name", ""),
                    "mime_type": item.get("mimeType", ""),
                    "size": int(size_value) if size_value is not None else None,
                    "created_time": item.get("createdTime", ""),
                    "video_metadata": metadata,
                    "duration_ms": duration_ms,
                    "duration_seconds": duration_ms / 1000 if duration_ms is not None else None,
                    "width": width,
                    "height": height,
                    "web_view_link": item.get("webViewLink", ""),
                    "thumbnail_link": item.get("thumbnailLink", ""),
                }
            )
        page_token = response.get("nextPageToken")
        if not page_token:
            break
    return items


def get_drive_video_thumbnail(credentials, file_id: str):
    """Fetch a Drive-generated video thumbnail through the authenticated API client."""
    service = build("drive", "v3", credentials=credentials)
    metadata = service.files().get(fileId=file_id, fields="thumbnailLink").execute()
    thumbnail_link = metadata.get("thumbnailLink")
    if not thumbnail_link:
        return None

    # Drive commonly returns a link ending in ``=s220``. Request a larger
    # rendition while keeping the original link shape for newer variants.
    high_resolution_link = re.sub(
        r"=s\d+(?=$|[&#])",
        f"=s{DRIVE_THUMBNAIL_SIZE}",
        thumbnail_link,
        count=1,
    )
    response = AuthorizedSession(credentials).get(high_resolution_link, timeout=20)
    response.raise_for_status()
    content_type = response.headers.get("content-type", "image/jpeg").split(";", 1)[0].strip()
    if not content_type.startswith("image/"):
        content_type = "image/jpeg"
    return response.content, content_type


def download_drive_file(credentials, file_id: str, destination: Path):
    service = build("drive", "v3", credentials=credentials)
    request = service.files().get_media(fileId=file_id)
    with destination.open("wb") as output:
        downloader = MediaIoBaseDownload(output, request, chunksize=8 * 1024 * 1024)
        done = False
        while not done:
            _, done = downloader.next_chunk()
