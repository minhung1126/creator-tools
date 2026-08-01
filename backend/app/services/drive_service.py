import hashlib
import logging
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from google.auth.transport.requests import AuthorizedSession
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

DRIVE_THUMBNAIL_SIZE = 1600
DRIVE_SOURCE_THUMBNAIL_MAX_BYTES = 512 * 1024 * 1024
DRIVE_SOURCE_THUMBNAIL_TIMEOUT_SECONDS = 90
DRIVE_THUMBNAIL_CACHE_DIR = Path("data") / "drive-thumbnails"
DRIVE_FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"
PUBLISHED_FOLDER_NAME = "Published"
logger = logging.getLogger(__name__)


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


def ensure_published_folder(
    credentials,
    source_folder_url_or_id: str,
    folder_name: str = PUBLISHED_FOLDER_NAME,
) -> str:
    """Return the Published child folder, creating it once when necessary."""
    source_folder_id = extract_drive_folder_id(source_folder_url_or_id)
    if not source_folder_id:
        raise ValueError("Google Drive 來源資料夾 ID 不得為空白")

    service = build("drive", "v3", credentials=credentials)
    escaped_name = folder_name.replace("\\", "\\\\").replace("'", "\\'")
    response = (
        service.files()
        .list(
            q=(
                f"'{source_folder_id}' in parents and trashed = false and "
                f"mimeType = '{DRIVE_FOLDER_MIME_TYPE}' and name = '{escaped_name}'"
            ),
            fields="files(id,name,parents)",
            orderBy="createdTime asc",
            pageSize=100,
        )
        .execute()
    )
    existing = next((item.get("id") for item in response.get("files", []) if item.get("id")), None)
    if existing:
        return existing

    created = (
        service.files()
        .create(
            body={
                "name": folder_name,
                "mimeType": DRIVE_FOLDER_MIME_TYPE,
                "parents": [source_folder_id],
            },
            fields="id,parents",
            supportsAllDrives=True,
        )
        .execute()
    )
    folder_id = created.get("id")
    if not folder_id:
        raise RuntimeError("Google Drive Published 資料夾建立後沒有回傳 ID")
    return folder_id


def move_drive_file_to_folder(
    credentials,
    file_id: str,
    source_folder_id: str,
    destination_folder_id: str,
) -> dict:
    """Move a Drive file into a destination folder idempotently."""
    if not file_id or not source_folder_id or not destination_folder_id:
        raise ValueError("Google Drive 檔案與來源／目的資料夾 ID 皆不可為空白")
    if source_folder_id == destination_folder_id:
        raise ValueError("Google Drive 來源與目的資料夾不可相同")

    service = build("drive", "v3", credentials=credentials)
    metadata = (
        service.files()
        .get(fileId=file_id, fields="id,parents", supportsAllDrives=True)
        .execute()
    )
    parents = set(metadata.get("parents") or [])
    if destination_folder_id in parents:
        if source_folder_id in parents:
            return service.files().update(
                fileId=file_id,
                removeParents=source_folder_id,
                fields="id,parents",
                supportsAllDrives=True,
            ).execute()
        return metadata

    update_kwargs = {
        "fileId": file_id,
        "addParents": destination_folder_id,
        "fields": "id,parents",
        "supportsAllDrives": True,
    }
    if source_folder_id in parents:
        update_kwargs["removeParents"] = source_folder_id
    return service.files().update(**update_kwargs).execute()


def _large_drive_thumbnail_link(thumbnail_link: str) -> str:
    """Request the largest Drive-generated rendition available from the link."""
    match = re.search(
        r"=(?P<variant>s\d+|w\d+(?:-h\d+)?|h\d+)(?P<suffix>(?:-[^&#]*)?)(?=$|[&#])",
        thumbnail_link,
    )
    if not match:
        return thumbnail_link

    variant = match.group("variant")
    if variant.startswith("s"):
        replacement = f"=s{DRIVE_THUMBNAIL_SIZE}"
    elif variant.startswith("w") and "-h" in variant:
        replacement = f"=w{DRIVE_THUMBNAIL_SIZE}-h{DRIVE_THUMBNAIL_SIZE}"
    elif variant.startswith("w"):
        replacement = f"=w{DRIVE_THUMBNAIL_SIZE}"
    else:
        replacement = f"=h{DRIVE_THUMBNAIL_SIZE}"

    return (
        f"{thumbnail_link[:match.start()]}{replacement}{match.group('suffix') or ''}"
        f"{thumbnail_link[match.end():]}"
    )


def _fetch_drive_thumbnail(credentials, thumbnail_link: str):
    response = AuthorizedSession(credentials).get(_large_drive_thumbnail_link(thumbnail_link), timeout=20)
    response.raise_for_status()
    content_type = response.headers.get("content-type", "image/jpeg").split(";", 1)[0].strip()
    if not content_type.startswith("image/"):
        content_type = "image/jpeg"
    return response.content, content_type


def _source_thumbnail_cache_path(file_id: str, metadata: dict) -> Path:
    revision = metadata.get("headRevisionId") or metadata.get("modifiedTime") or "latest"
    cache_key = hashlib.sha256(f"{file_id}:{revision}".encode("utf-8")).hexdigest()
    return DRIVE_THUMBNAIL_CACHE_DIR / f"{cache_key}.jpg"


def _render_drive_source_thumbnail(credentials, file_id: str, metadata: dict):
    """Extract a full-resolution frame from the source video when ffmpeg is available."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return None

    try:
        source_size = int(metadata.get("size") or 0)
    except (TypeError, ValueError):
        source_size = 0
    if source_size > DRIVE_SOURCE_THUMBNAIL_MAX_BYTES:
        logger.info("Skipping source thumbnail for %s because the video is too large", file_id)
        return None

    cache_path = _source_thumbnail_cache_path(file_id, metadata)
    try:
        if cache_path.is_file() and cache_path.stat().st_size:
            return cache_path.read_bytes(), "image/jpeg"
    except OSError:
        logger.warning("Could not read cached Drive thumbnail for %s", file_id)

    try:
        with tempfile.TemporaryDirectory(prefix="creator-drive-video-") as temp_dir:
            source_path = Path(temp_dir) / "source-video"
            download_drive_file(credentials, file_id, source_path)
            result = subprocess.run(
                [
                    ffmpeg,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-ss",
                    "0.5",
                    "-i",
                    str(source_path),
                    "-map",
                    "0:v:0",
                    "-frames:v",
                    "1",
                    "-c:v",
                    "mjpeg",
                    "-q:v",
                    "2",
                    "-f",
                    "image2pipe",
                    "pipe:1",
                ],
                capture_output=True,
                check=False,
                timeout=DRIVE_SOURCE_THUMBNAIL_TIMEOUT_SECONDS,
            )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("Could not render source thumbnail for %s: %s", file_id, type(exc).__name__)
        return None

    if result.returncode != 0 or not result.stdout:
        logger.warning("ffmpeg could not render source thumbnail for %s", file_id)
        return None

    try:
        DRIVE_THUMBNAIL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            dir=DRIVE_THUMBNAIL_CACHE_DIR,
            prefix=f"{cache_path.stem}-",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_file.write(result.stdout)
            temporary_path = Path(temporary_file.name)
        temporary_path.replace(cache_path)
    except OSError:
        logger.warning("Could not cache source thumbnail for %s", file_id)
    finally:
        if "temporary_path" in locals():
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass

    return result.stdout, "image/jpeg"


def get_drive_video_thumbnail(credentials, file_id: str, *, prefer_source: bool = False):
    """Fetch a Drive thumbnail, optionally preferring a frame from the original video."""
    service = build("drive", "v3", credentials=credentials)
    metadata = service.files().get(
        fileId=file_id,
        fields="thumbnailLink,size,headRevisionId,modifiedTime",
    ).execute()
    if prefer_source:
        source_thumbnail = _render_drive_source_thumbnail(credentials, file_id, metadata)
        if source_thumbnail:
            return source_thumbnail

    thumbnail_link = metadata.get("thumbnailLink")
    if not thumbnail_link:
        return None
    return _fetch_drive_thumbnail(credentials, thumbnail_link)


def download_drive_file(credentials, file_id: str, destination: Path):
    service = build("drive", "v3", credentials=credentials)
    request = service.files().get_media(fileId=file_id)
    with destination.open("wb") as output:
        downloader = MediaIoBaseDownload(output, request, chunksize=8 * 1024 * 1024)
        done = False
        while not done:
            _, done = downloader.next_chunk()
