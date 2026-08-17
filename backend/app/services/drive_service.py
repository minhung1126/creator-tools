"""Authenticated Google Drive metadata and download operations."""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import Any, Iterable

import googleapiclient.discovery
from googleapiclient.http import MediaIoBaseDownload

from backend.app.services.google_auth import DRIVE_READONLY_SCOPE, has_drive_read_scope

logger = logging.getLogger(__name__)

VIDEO_EXTENSIONS = frozenset(
    {
        ".avi",
        ".m4v",
        ".mkv",
        ".mov",
        ".mp4",
        ".mpeg",
        ".mpg",
        ".webm",
        ".wmv",
    }
)
DRIVE_FILE_FIELDS = (
    "id,name,mimeType,size,version,md5Checksum,modifiedTime,driveId,parents,trashed,capabilities(canDownload)"
)


def build_drive_service(credentials):
    if not has_drive_read_scope(credentials):
        raise PermissionError("Google Drive 權限不足，請重新授權 Google Drive。")
    return googleapiclient.discovery.build("drive", "v3", credentials=credentials, cache_discovery=False)


def is_video_file(metadata: dict[str, Any]) -> bool:
    mime_type = str(metadata.get("mimeType") or "").casefold()
    if mime_type.startswith("video/"):
        return True
    name = str(metadata.get("name") or "")
    return Path(name).suffix.casefold() in VIDEO_EXTENSIONS


def _list_kwargs(metadata: dict[str, Any]) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"supportsAllDrives": True, "includeItemsFromAllDrives": True}
    drive_id = str(metadata.get("driveId") or "").strip()
    if drive_id:
        kwargs["corpora"] = "drive"
        kwargs["driveId"] = drive_id
    return kwargs


def _get_kwargs() -> dict[str, Any]:
    return {"supportsAllDrives": True}


def get_drive_metadata(credentials, item_id: str) -> dict[str, Any]:
    service = build_drive_service(credentials)
    return service.files().get(fileId=item_id, fields=DRIVE_FILE_FIELDS, **_get_kwargs()).execute()


def list_folder_children(credentials, folder_metadata: dict[str, Any]) -> list[dict[str, Any]]:
    service = build_drive_service(credentials)
    folder_id = str(folder_metadata.get("id") or "").strip()
    if not folder_id:
        raise ValueError("Google Drive 資料夾缺少 ID。")
    query = f"'{folder_id}' in parents and trashed = false"
    items: list[dict[str, Any]] = []
    page_token = None
    kwargs = _list_kwargs(folder_metadata)
    while True:
        response = (
            service.files()
            .list(
                q=query,
                pageSize=1000,
                pageToken=page_token,
                fields=f"nextPageToken,files({DRIVE_FILE_FIELDS})",
                orderBy="name_natural",
                **kwargs,
            )
            .execute()
        )
        items.extend(response.get("files") or [])
        page_token = response.get("nextPageToken")
        if not page_token:
            return items


def resolve_drive_source(credentials, item_id: str) -> dict[str, Any]:
    """Resolve one Drive file or one first-level folder into preview records."""

    source = get_drive_metadata(credentials, item_id)
    source_type = str(source.get("mimeType") or "")
    if source_type == "application/vnd.google-apps.folder":
        children = list_folder_children(credentials, source)
        records = []
        for child in children:
            record = dict(child)
            record["preview_status"] = "ready" if is_video_file(record) else "skipped"
            record["skip_reason"] = "非影片檔案或子資料夾" if record["preview_status"] == "skipped" else None
            records.append(record)
        return {"source": source, "items": records, "source_kind": "folder"}

    source["preview_status"] = "ready" if is_video_file(source) else "skipped"
    source["skip_reason"] = None if source["preview_status"] == "ready" else "此 Drive 項目不是影片檔案"
    return {"source": source, "items": [source], "source_kind": "file"}


def sort_drive_items(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Use case-insensitive natural filename order with a stable tie-breaker."""

    def natural_key(item: dict[str, Any]) -> tuple[Any, ...]:
        name = str(item.get("name") or "")
        pieces = re.split(r"(\d+)", name.casefold())
        return tuple((1, int(piece)) if piece.isdigit() else (0, piece) for piece in pieces) + (
            (0, name),
            (0, str(item.get("id") or "")),
        )

    return sorted(
        [dict(item) for item in items],
        key=natural_key,
    )


def drive_item_fingerprint(metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        "file_id": str(metadata.get("id") or ""),
        "version": str(metadata.get("version") or ""),
        "md5_checksum": str(metadata.get("md5Checksum") or ""),
        "size": int(metadata.get("size") or 0),
        "modified_time": str(metadata.get("modifiedTime") or ""),
    }


def download_drive_file(credentials, metadata: dict[str, Any], destination: str | Path) -> dict[str, Any]:
    """Download one binary Drive file and return verified local fingerprints."""

    if not is_video_file(metadata):
        raise ValueError("只可下載影片檔案。")
    destination_path = Path(destination)
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    service = build_drive_service(credentials)
    request = service.files().get_media(fileId=str(metadata.get("id") or ""), **_get_kwargs())
    sha256 = hashlib.sha256()
    md5 = hashlib.md5()
    total = 0
    with destination_path.open("wb") as handle:
        downloader = MediaIoBaseDownload(handle, request, chunksize=8 * 1024 * 1024)
        done = False
        while not done:
            _status, done = downloader.next_chunk()
            handle.flush()
        with destination_path.open("rb") as verify_handle:
            for chunk in iter(lambda: verify_handle.read(8 * 1024 * 1024), b""):
                total += len(chunk)
                sha256.update(chunk)
                md5.update(chunk)

    expected_size = int(metadata.get("size") or 0)
    expected_md5 = str(metadata.get("md5Checksum") or "").strip()
    if expected_size and total != expected_size:
        raise IOError("Google Drive 下載大小與預覽不一致。")
    if expected_md5 and md5.hexdigest() != expected_md5:
        raise IOError("Google Drive 下載 checksum 與預覽不一致。")
    return {
        "size": total,
        "sha256": sha256.hexdigest(),
        "md5_checksum": md5.hexdigest(),
    }


__all__ = [
    "DRIVE_FILE_FIELDS",
    "DRIVE_READONLY_SCOPE",
    "VIDEO_EXTENSIONS",
    "build_drive_service",
    "download_drive_file",
    "drive_item_fingerprint",
    "get_drive_metadata",
    "is_video_file",
    "list_folder_children",
    "resolve_drive_source",
    "sort_drive_items",
]
