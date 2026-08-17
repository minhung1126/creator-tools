"""Safe normalization for Google Drive item IDs and URLs."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

DRIVE_HOSTS = frozenset({"drive.google.com", "www.drive.google.com"})
DRIVE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,256}$")


@dataclass(frozen=True)
class GoogleDriveInput:
    """A normalized Drive item reference; kind is resolved by the API later."""

    item_id: str
    source_type: str = "drive-item"
    original: str = ""


def _valid_id(value: str) -> str:
    candidate = str(value or "").strip()
    return candidate if DRIVE_ID_RE.fullmatch(candidate) else ""


def parse_google_drive_input(value: str) -> GoogleDriveInput:
    """Accept a raw ID or a common Drive URL, and reject every other host."""

    original = str(value or "").strip()
    if not original:
        raise ValueError("請提供 Google Drive 資料夾或檔案 ID／網址。")

    raw_id = _valid_id(original)
    if raw_id:
        return GoogleDriveInput(raw_id, original=original)

    candidate = original if re.match(r"^https?://", original, re.IGNORECASE) else f"https://{original}"
    try:
        parsed = urlparse(candidate)
    except ValueError as exc:
        raise ValueError("Google Drive 網址格式不正確。") from exc
    if parsed.scheme not in {"http", "https"} or (parsed.hostname or "").casefold() not in DRIVE_HOSTS:
        raise ValueError("只接受 drive.google.com 的 Google Drive 網址。")

    query_values = parse_qs(parsed.query)
    for key in ("id", "folderId", "fileId"):
        values = query_values.get(key) or []
        if values:
            item_id = _valid_id(values[0])
            if item_id:
                return GoogleDriveInput(item_id, original=original)

    parts = [part for part in parsed.path.split("/") if part]
    for marker in ("folders",):
        if marker in parts:
            marker_index = parts.index(marker)
            if marker_index + 1 < len(parts):
                item_id = _valid_id(parts[marker_index + 1])
                if item_id:
                    return GoogleDriveInput(item_id, original=original)

    if "file" in parts:
        marker_index = parts.index("file")
        candidate_index = (
            marker_index + 2 if marker_index + 1 < len(parts) and parts[marker_index + 1] == "d" else marker_index + 1
        )
        if candidate_index < len(parts):
            item_id = _valid_id(parts[candidate_index])
            if item_id:
                return GoogleDriveInput(item_id, original=original)

    if "d" in parts:
        marker_index = parts.index("d")
        if marker_index + 1 < len(parts):
            item_id = _valid_id(parts[marker_index + 1])
            if item_id:
                return GoogleDriveInput(item_id, original=original)

    raise ValueError("找不到 Google Drive 項目 ID，請貼上資料夾或檔案網址。")


def normalize_google_drive_id(value: str) -> str:
    """Return only the normalized ID; invalid input becomes an empty string."""

    try:
        return parse_google_drive_input(value).item_id
    except ValueError:
        return ""


__all__ = ["DRIVE_HOSTS", "GoogleDriveInput", "normalize_google_drive_id", "parse_google_drive_input"]
