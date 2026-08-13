"""Validation and normalization for user-provided YouTube identifiers."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

_PLAYLIST_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


def normalize_playlist_id(value: str | None) -> str:
    """Return a playlist ID from a supported URL or ID, or ``""`` if invalid."""

    trimmed = str(value or "").strip()
    if not trimmed:
        return ""
    if _PLAYLIST_ID.fullmatch(trimmed):
        return trimmed

    candidate = trimmed if "://" in trimmed else f"https://{trimmed}"
    try:
        parsed = urlparse(candidate)
    except ValueError:
        return ""
    if parsed.scheme not in {"http", "https"}:
        return ""
    hostname = (parsed.hostname or "").lower()
    if hostname not in {"youtube.com", "youtu.be"} and not hostname.endswith(".youtube.com"):
        return ""
    playlist_id = (parse_qs(parsed.query).get("list") or [""])[0].strip()
    return playlist_id if _PLAYLIST_ID.fullmatch(playlist_id) else ""


__all__ = ["normalize_playlist_id"]
