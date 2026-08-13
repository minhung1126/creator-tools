"""Signed, account- and slot-bound workflow preview snapshots."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from typing import Any

from backend.app.core.security import sign_timed_data, verify_timed_data

PREVIEW_TOKEN_SALT = "workflow-preview"
PREVIEW_TOKEN_MAX_AGE = 30 * 60


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _owner_binding(owner_sub: str) -> str:
    return _digest(str(owner_sub or "").strip())


def playlist_snapshot(raw_items: Iterable[Mapping[str, Any]] | None) -> dict[str, Any]:
    """Return stable collection digests without retaining provider payloads."""

    entries: list[dict[str, str]] = []
    for item in raw_items or []:
        content = item.get("contentDetails") if isinstance(item, Mapping) else {}
        snippet = item.get("snippet") if isinstance(item, Mapping) else {}
        video_id = str((content or {}).get("videoId") or "").strip()
        playlist_item_id = str(item.get("id") or "").strip() if isinstance(item, Mapping) else ""
        if video_id:
            entries.append({"playlist_item_id": playlist_item_id, "video_id": video_id})
        elif isinstance(item, Mapping) and isinstance(snippet, Mapping):
            # Invalid/incomplete entries still affect the collection shape.
            entries.append({"playlist_item_id": playlist_item_id, "video_id": ""})
    video_ids = [entry["video_id"] for entry in entries]
    return {
        "playlist_digest": _digest(entries),
        "video_digest": _digest(video_ids),
        "video_ids": video_ids,
        "video_count": len(entries),
    }


def playlist_snapshot_from_preview(videos: Iterable[Mapping[str, Any]] | None) -> dict[str, Any]:
    """Build the same public snapshot shape from parsed preview rows."""

    entries = [
        {
            "id": str(video.get("playlist_item_id") or ""),
            "contentDetails": {"videoId": str(video.get("video_id") or "")},
        }
        for video in videos or []
        if isinstance(video, Mapping)
    ]
    return playlist_snapshot(entries)


def sheet_snapshot(
    spreadsheet_id: str,
    worksheet_name: str,
    headers: Iterable[Any] | None,
    rows: Iterable[Mapping[str, Any]] | None,
) -> dict[str, Any]:
    """Digest the selected Sheet, preserving row order and duplicate rows."""

    normalized_headers = [str(header or "").strip() for header in (headers or [])]
    normalized_rows = [dict(row) for row in (rows or []) if isinstance(row, Mapping)]
    payload = {
        "spreadsheet_id": str(spreadsheet_id or "").strip(),
        "worksheet_name": str(worksheet_name or "").strip(),
        "headers": normalized_headers,
        "rows": normalized_rows,
    }
    return {
        "sheet_digest": _digest(payload),
        "spreadsheet_id": payload["spreadsheet_id"],
        "worksheet_name": payload["worksheet_name"],
        "row_count": len(normalized_rows),
    }


def input_digest(value: Any) -> str:
    """Hash workflow inputs without placing arbitrary input in a token."""

    return _digest(value)


def build_preview_token(
    *,
    owner_sub: str,
    youtube_slot: str,
    operation: str,
    playlist_id: str = "",
    playlist: Mapping[str, Any] | None = None,
    sheet: Mapping[str, Any] | None = None,
    request_digest: str | None = None,
) -> str:
    payload: dict[str, Any] = {
        "version": 1,
        "owner": _owner_binding(owner_sub),
        "youtube_slot": str(youtube_slot or ""),
        "operation": str(operation or ""),
        "playlist_id": str(playlist_id or "").strip(),
        "playlist": dict(playlist or {}),
        "sheet": dict(sheet or {}),
    }
    if request_digest:
        payload["request_digest"] = str(request_digest)
    return sign_timed_data(payload, salt=PREVIEW_TOKEN_SALT)


def verify_preview_token(
    token: str | None,
    *,
    owner_sub: str,
    youtube_slot: str,
    operation: str,
    playlist_id: str = "",
    playlist: Mapping[str, Any] | None = None,
    sheet: Mapping[str, Any] | None = None,
    request_digest: str | None = None,
) -> bool:
    if not isinstance(token, str) or not token.strip():
        return False
    payload = verify_timed_data(token, salt=PREVIEW_TOKEN_SALT, max_age=PREVIEW_TOKEN_MAX_AGE)
    if not isinstance(payload, Mapping) or payload.get("version") != 1:
        return False
    if payload.get("owner") != _owner_binding(owner_sub):
        return False
    if payload.get("youtube_slot") != str(youtube_slot or ""):
        return False
    if payload.get("operation") != str(operation or ""):
        return False
    if payload.get("playlist_id", "") != str(playlist_id or "").strip():
        return False
    if playlist is not None and payload.get("playlist") != dict(playlist):
        return False
    if sheet is not None and payload.get("sheet") != dict(sheet):
        return False
    if request_digest is not None and payload.get("request_digest") != str(request_digest):
        return False
    return True


__all__ = [
    "PREVIEW_TOKEN_MAX_AGE",
    "PREVIEW_TOKEN_SALT",
    "build_preview_token",
    "input_digest",
    "playlist_snapshot",
    "playlist_snapshot_from_preview",
    "sheet_snapshot",
    "verify_preview_token",
]
