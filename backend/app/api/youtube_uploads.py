"""Drive-to-YouTube preview and durable background upload APIs."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from google.oauth2.credentials import Credentials
from pydantic import BaseModel, Field, model_validator

from backend.app.core.account_state import get_account_setting
from backend.app.core.config import settings
from backend.app.core.dependencies import require_account_subject, require_login_credentials
from backend.app.core.error_contract import http_error
from backend.app.core.google_drive_input import parse_google_drive_input
from backend.app.core.preview import build_preview_token, input_digest, verify_preview_token
from backend.app.core.youtube_context import YouTubeRequestContext
from backend.app.core.youtube_routing import choose_youtube_upload_slot, estimate_youtube_upload_quota
from backend.app.services.drive_service import (
    drive_item_fingerprint,
    resolve_drive_source,
    sort_drive_items,
)
from backend.app.services.google_auth import has_drive_read_scope
from backend.app.services.provider_errors import map_youtube_error
from backend.app.services.youtube_errors import YouTubeQuotaUnavailable
from backend.app.services.youtube_quota_service import (
    get_youtube_quota_tracker,
    get_youtube_upload_quota_tracker,
)
from backend.app.services.youtube_service import validate_playlist
from backend.app.services.youtube_upload_jobs import (
    ITEM_DONE,
    TERMINAL_STATUSES,
    public_job,
    upload_job_store,
    wake_upload_worker,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/youtube/uploads", tags=["YouTube Drive Uploads"])

DRIVE_NAME_RE = re.compile(r"[\\/]", re.ASCII)
YOUTUBE_TITLE_MAX_LENGTH = 100


class DriveUploadPreviewInput(BaseModel):
    drive_source: str = Field(default="", max_length=2048)
    source: Optional[str] = Field(default=None, max_length=2048)

    @model_validator(mode="after")
    def normalize_source(self):
        if not self.drive_source.strip() and self.source:
            self.drive_source = self.source
        if not self.drive_source.strip():
            raise ValueError("請提供 Google Drive 資料夾或檔案 ID／網址。")
        return self


class DriveUploadJobInput(BaseModel):
    preview_token: str = Field(min_length=1, max_length=16_384)
    preview_snapshot: dict[str, Any]


def _drive_error(exc: Exception) -> HTTPException:
    status = getattr(getattr(exc, "resp", None), "status", None)
    if status in {401, 403} or isinstance(exc, PermissionError):
        return http_error(
            403,
            "google_drive_scope_required",
            "Google Drive 權限不足，請重新授權 Google Drive。",
            retryable=False,
            reauthorization_required=True,
        )
    if status == 404:
        return http_error(404, "google_drive_not_found", "找不到指定的 Google Drive 項目，或目前帳號沒有權限。")
    return http_error(502, "google_drive_unavailable", "Google Drive 目前無法讀取，請稍後重試。", retryable=True)


def _playlist_id(owner_sub: str) -> str:
    raw = str(get_account_setting(owner_sub, "default_playlist_id", "") or "").strip()
    if not raw:
        raise http_error(400, "youtube_playlist_required", "請先至 YouTube 設定指定共用 To-Post 播放清單。")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", raw):
        raise http_error(
            400, "youtube_playlist_invalid", "共用 To-Post 播放清單設定不正確，請至 YouTube 設定重新儲存。"
        )
    return raw


def _session_id(request: Request) -> str:
    return str(request.cookies.get(settings.session_cookie_name) or "")


def _context(decision, owner_sub: str) -> YouTubeRequestContext:
    return YouTubeRequestContext(
        slot=decision.slot,
        credentials=decision.credentials,
        quota_limiter=get_youtube_quota_tracker(decision.slot),
        owner_sub=owner_sub,
        channel_id=decision.channel_id,
        routing_mode=decision.routing_mode,
        selection_reason=decision.reason,
        estimated_units=decision.estimated_units,
        preferred_slot=decision.preferred_slot,
    )


def _clean_name(value: Any) -> str:
    # Drive names can contain path-looking characters; keep the display name
    # but never use it as a filesystem path.
    return DRIVE_NAME_RE.sub("／", str(value or "").strip())


def _title_from_name(name: str) -> str:
    return Path(name).stem.strip()[:YOUTUBE_TITLE_MAX_LENGTH]


def _source_key(metadata: dict[str, Any]) -> str:
    fingerprint = drive_item_fingerprint(metadata)
    return ":".join(
        [
            str(fingerprint.get("file_id") or ""),
            str(fingerprint.get("version") or ""),
            str(fingerprint.get("md5_checksum") or ""),
            str(fingerprint.get("size") or 0),
        ]
    )


def _file_snapshot(owner_sub: str, source_data: dict[str, Any]) -> tuple[list[dict[str, Any]], int, int]:
    items = []
    pending_uploads = 0
    playlist_insertions = 0
    for sequence, metadata in enumerate(sort_drive_items(source_data.get("items") or []), start=1):
        file_id = str(metadata.get("id") or "").strip()
        name = _clean_name(metadata.get("name"))
        fingerprint = drive_item_fingerprint(metadata)
        source_key = _source_key(metadata)
        is_ready = metadata.get("preview_status") == "ready"
        title = _title_from_name(name)
        skip_reason = metadata.get("skip_reason")
        if is_ready and not title:
            is_ready = False
            skip_reason = "檔名去除副檔名後不可為空白"
        existing = upload_job_store.find_source(owner_sub, source_key) if is_ready else None
        action = "upload"
        already_uploaded = False
        existing_video_id = ""
        if existing:
            existing_video_id = str(existing.get("youtube_video_id") or "").strip()
            if existing.get("status") == ITEM_DONE:
                is_ready = False
                already_uploaded = True
                action = "already_uploaded"
                skip_reason = "相同 Drive 檔案版本已成功上傳"
            elif existing_video_id:
                action = "resume_playlist"
                playlist_insertions += 1
            elif existing.get("job_status") in {"queued", "running", "paused", "cancel_requested"}:
                is_ready = False
                action = "already_queued"
                skip_reason = "相同檔案已有未完成的上傳工作"
        if is_ready and action == "upload":
            pending_uploads += 1
            playlist_insertions += 1
        elif is_ready and action == "resume_playlist":
            is_ready = True
        item = {
            "sequence": sequence,
            "upload_sequence": pending_uploads
            + sum(1 for previous in items if previous.get("action") == "resume_playlist")
            if is_ready
            else None,
            "drive_file_id": file_id,
            "file_id": file_id,
            "name": name,
            "size": int(metadata.get("size") or 0),
            "mime_type": str(metadata.get("mimeType") or "") or None,
            "title": title,
            "fingerprint": fingerprint,
            "source_key": source_key,
            "uploadable": bool(is_ready),
            "can_upload": bool(is_ready),
            "action": action if is_ready or action != "upload" else "skipped",
            "skip_reason": skip_reason,
            "existing_video_id": existing_video_id or None,
            "already_uploaded": already_uploaded,
        }
        items.append(item)
    # Re-number upload_sequence after all actions are known, so skipped files
    # never create gaps in the actual worker order.
    upload_sequence = 0
    for item in items:
        if item.get("uploadable"):
            upload_sequence += 1
            item["upload_sequence"] = upload_sequence
    return items, pending_uploads, playlist_insertions


def _snapshot(
    *,
    source_id: str,
    source_kind: str,
    playlist_id: str,
    decision,
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "version": 1,
        "drive_source_id": source_id,
        "drive_source_kind": source_kind,
        "playlist_id": playlist_id,
        "youtube_slot": decision.slot,
        "youtube_channel_id": decision.channel_id,
        "youtube_routing_mode": decision.routing_mode,
        "youtube_slot_reason": decision.reason,
        "items": items,
    }


def _token_for(owner_sub: str, snapshot: dict[str, Any]) -> str:
    digest = input_digest(snapshot)
    token_playlist = {
        "drive_source_id": snapshot.get("drive_source_id"),
        "drive_source_kind": snapshot.get("drive_source_kind"),
        "files": [
            {
                "file_id": item.get("file_id"),
                "fingerprint": item.get("fingerprint"),
                "action": item.get("action"),
            }
            for item in snapshot.get("items", [])
        ],
        "youtube_channel_id": snapshot.get("youtube_channel_id"),
        "youtube_slot": snapshot.get("youtube_slot"),
    }
    return build_preview_token(
        owner_sub=owner_sub,
        youtube_slot=str(snapshot.get("youtube_slot") or ""),
        operation="youtube.drive_upload",
        playlist_id=str(snapshot.get("playlist_id") or ""),
        playlist=token_playlist,
        request_digest=digest,
    )


def _token_playlist(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "drive_source_id": snapshot.get("drive_source_id"),
        "drive_source_kind": snapshot.get("drive_source_kind"),
        "files": [
            {
                "file_id": item.get("file_id"),
                "fingerprint": item.get("fingerprint"),
                "action": item.get("action"),
            }
            for item in snapshot.get("items", [])
        ],
        "youtube_channel_id": snapshot.get("youtube_channel_id"),
        "youtube_slot": snapshot.get("youtube_slot"),
    }


def _verify_snapshot(owner_sub: str, token: str, snapshot: dict[str, Any]) -> None:
    if not verify_preview_token(
        token,
        owner_sub=owner_sub,
        youtube_slot=str(snapshot.get("youtube_slot") or ""),
        operation="youtube.drive_upload",
        playlist_id=str(snapshot.get("playlist_id") or ""),
        playlist=_token_playlist(snapshot),
        request_digest=input_digest(snapshot),
    ):
        raise http_error(409, "stale_preview", "預覽已過期或來源已變更，請重新解析 Drive 內容。")


def _quota_summary(slot: str, *, upload_count: int, insertion_count: int) -> dict[str, Any]:
    general = get_youtube_quota_tracker(slot).get_usage()
    uploads = get_youtube_upload_quota_tracker(slot).get_usage()
    general_required = insertion_count * 50
    upload_required = upload_count
    return {
        "general": {
            "bucket": "general",
            "used": general.get("estimated_used_units", 0),
            "limit": general.get("configured_project_limit", 10000),
            "effective_available_units": general.get("effective_available_units", 0),
            "projected_units": general_required,
            "projected_with_preview_reads": general_required + 1,
            "can_complete": general_required <= int(general.get("effective_available_units") or 0),
            "reset_at": general.get("reset_at"),
        },
        "video_uploads": {
            "bucket": "video_uploads",
            "used": uploads.get("estimated_used_units", 0),
            "limit": uploads.get("configured_project_limit", 100),
            "effective_available_units": uploads.get("effective_available_units", 0),
            "projected_units": upload_required,
            "can_complete": upload_required <= int(uploads.get("effective_available_units") or 0),
            "reset_at": uploads.get("reset_at"),
        },
        "can_complete": (
            general_required <= int(general.get("effective_available_units") or 0)
            and upload_required <= int(uploads.get("effective_available_units") or 0)
        ),
        "estimated_units": estimate_youtube_upload_quota(max(upload_count, insertion_count)),
    }


def _recheck_drive_snapshot(credentials: Credentials, snapshot: dict[str, Any]) -> None:
    try:
        source = parse_google_drive_input(str(snapshot.get("drive_source_id") or ""))
        resolved = resolve_drive_source(credentials, source.item_id)
    except Exception as exc:
        raise _drive_error(exc) from exc
    current_items = {str(item.get("id") or ""): item for item in resolved.get("items", [])}
    expected_items = snapshot.get("items") or []
    if str(resolved.get("source", {}).get("id") or "") != source.item_id:
        raise http_error(409, "stale_preview", "Drive 來源已變更，請重新解析預覽。")
    if str(resolved.get("source_kind") or "") != str(snapshot.get("drive_source_kind") or ""):
        raise http_error(409, "stale_preview", "Drive 來源類型已變更，請重新解析預覽。")
    expected_ids = {str(item.get("file_id") or "") for item in expected_items}
    if expected_ids != set(current_items):
        raise http_error(409, "stale_preview", "Drive 資料夾內容已變更，請重新解析預覽。")
    for item in expected_items:
        file_id = str(item.get("file_id") or "")
        current = current_items.get(file_id)
        if not current or drive_item_fingerprint(current) != item.get("fingerprint"):
            raise http_error(409, "stale_preview", "Drive 檔案版本已變更，請重新解析預覽。")


@router.post("/preview")
def preview_drive_upload(
    payload: DriveUploadPreviewInput,
    request: Request,
    creds: Credentials = Depends(require_login_credentials),
    owner_sub: str = Depends(require_account_subject),
):
    if not has_drive_read_scope(creds):
        raise http_error(
            403,
            "google_drive_scope_required",
            "Google Drive 權限不足，請重新授權 Google Drive。",
            reauthorization_required=True,
        )
    try:
        source_ref = parse_google_drive_input(payload.drive_source)
        source_data = resolve_drive_source(creds, source_ref.item_id)
    except ValueError as exc:
        raise http_error(400, "google_drive_input_invalid", str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise _drive_error(exc) from exc

    playlist_id = _playlist_id(owner_sub)
    items, pending_uploads, insertion_count = _file_snapshot(owner_sub, source_data)
    ready_count = sum(1 for item in items if item.get("uploadable"))
    try:
        decision = choose_youtube_upload_slot(
            _session_id(request),
            owner_sub,
            item_count=ready_count,
            upload_count=pending_uploads,
            insertion_count=insertion_count,
        )
        context = _context(decision, owner_sub)
        playlist = validate_playlist(context, playlist_id)
    except YouTubeQuotaUnavailable as exc:
        raise http_error(
            429,
            exc.code,
            exc.user_message,
            retryable=True,
            reset_at=exc.reset_at,
            youtube_slot=decision.slot if "decision" in locals() else None,
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:
        mapped = map_youtube_error(
            exc, method="playlists.list", youtube_slot=decision.slot if "decision" in locals() else None
        )
        raise mapped.to_http_exception() from exc

    snapshot = _snapshot(
        source_id=source_ref.item_id,
        source_kind=str(source_data.get("source_kind") or "file"),
        playlist_id=playlist_id,
        decision=decision,
        items=items,
    )
    token = _token_for(owner_sub, snapshot)
    quota = _quota_summary(decision.slot, upload_count=pending_uploads, insertion_count=insertion_count)
    return {
        "status": "preview_ready",
        "source": {
            "id": source_ref.item_id,
            "kind": source_data.get("source_kind"),
            "name": source_data.get("source", {}).get("name"),
            "url": f"https://drive.google.com/open?id={source_ref.item_id}",
        },
        "playlist": {
            "id": playlist_id,
            "title": (playlist.get("snippet") or {}).get("title") or playlist_id,
            "url": f"https://www.youtube.com/playlist?list={playlist_id}",
        },
        "youtube": {
            "slot": decision.slot,
            "channel_id": decision.channel_id,
            "routing_mode": decision.routing_mode,
            "slot_reason": decision.reason,
        },
        "items": items,
        "preview_snapshot": snapshot,
        "preview_token": token,
        "quota": quota,
        "summary": {
            "total": len(items),
            "uploadable": ready_count,
            "pending_uploads": pending_uploads,
            "skipped": sum(1 for item in items if not item.get("uploadable")),
        },
    }


@router.post("/jobs", status_code=202)
def create_upload_job(
    payload: DriveUploadJobInput,
    request: Request,
    creds: Credentials = Depends(require_login_credentials),
    owner_sub: str = Depends(require_account_subject),
):
    snapshot = payload.preview_snapshot
    _verify_snapshot(owner_sub, payload.preview_token, snapshot)
    playlist_id = _playlist_id(owner_sub)
    if playlist_id != str(snapshot.get("playlist_id") or ""):
        raise http_error(409, "stale_preview", "共用 To-Post 播放清單已變更，請重新解析預覽。")
    if not has_drive_read_scope(creds):
        raise http_error(
            403,
            "google_drive_scope_required",
            "Google Drive 權限不足，請重新授權 Google Drive。",
            reauthorization_required=True,
        )
    _recheck_drive_snapshot(creds, snapshot)

    requested_slot = str(snapshot.get("youtube_slot") or "").strip()
    items = snapshot.get("items") if isinstance(snapshot.get("items"), list) else []
    for item in items:
        if not item.get("uploadable"):
            continue
        existing = upload_job_store.find_source(owner_sub, str(item.get("source_key") or ""))
        if not existing:
            continue
        existing_status = str(existing.get("job_status") or "")
        has_video_id = bool(str(existing.get("youtube_video_id") or "").strip())
        if existing_status in {"queued", "running", "paused", "cancel_requested"} or (
            has_video_id and item.get("action") != "resume_playlist"
        ):
            raise http_error(409, "stale_preview", "相同 Drive 檔案已有上傳工作或 YouTube 影片，請重新解析預覽。")
    upload_count = sum(1 for item in items if item.get("uploadable") and item.get("action") == "upload")
    insertion_count = sum(1 for item in items if item.get("uploadable"))
    try:
        # The preview already spent its playlist metadata read. Pin the same
        # slot, then reserve-check only work that this job will still perform.
        decision = choose_youtube_upload_slot(
            _session_id(request),
            owner_sub,
            item_count=0,
            upload_count=upload_count,
            insertion_count=insertion_count,
            slot_hint=requested_slot,
        )
        snapshot_channel_id = str(snapshot.get("youtube_channel_id") or "").strip()
        if snapshot_channel_id and decision.channel_id != snapshot_channel_id:
            raise http_error(409, "stale_preview", "YouTube 頻道已變更，請重新解析預覽。")
        context = _context(decision, owner_sub)
        validate_playlist(context, playlist_id)
        quota = _quota_summary(decision.slot, upload_count=upload_count, insertion_count=insertion_count)
        if not quota["can_complete"]:
            raise http_error(
                429, "youtube_quota_no_available_slot", "目前 quota 不足以完成這批上傳，請稍後重試。", retryable=True
            )
    except YouTubeQuotaUnavailable as exc:
        raise http_error(429, exc.code, exc.user_message, retryable=True, reset_at=exc.reset_at) from exc
    except HTTPException:
        raise
    except Exception as exc:
        mapped = map_youtube_error(exc, method="playlists.list", youtube_slot=requested_slot)
        raise mapped.to_http_exception() from exc

    job_id = str(__import__("uuid").uuid4())
    job_items = []
    for item in items:
        existing_video_id = str(item.get("existing_video_id") or "").strip()
        if item.get("uploadable") and item.get("action") == "resume_playlist" and existing_video_id:
            status = "uploaded"
        elif item.get("uploadable") and item.get("action") == "upload":
            status = "pending"
        else:
            status = "skipped"
        job_items.append(
            {
                "sequence": item.get("sequence"),
                "upload_sequence": item.get("upload_sequence"),
                "drive_file_id": item.get("drive_file_id"),
                "name": item.get("name"),
                "size": item.get("size"),
                "mime_type": item.get("mime_type"),
                "title": item.get("title"),
                "fingerprint": item.get("fingerprint"),
                "source_key": item.get("source_key"),
                "status": status,
                "youtube_video_id": existing_video_id or None,
                "playlist_item_id": None,
                "error": None,
            }
        )
    status = "queued" if any(item.get("status") in {"pending", "uploaded"} for item in job_items) else "completed"
    job = upload_job_store.create(
        owner_sub,
        {
            "job_id": job_id,
            "status": status,
            "cancel_requested": False,
            "current_index": None,
            "error": None,
            "drive_source_id": snapshot.get("drive_source_id"),
            "drive_source_kind": snapshot.get("drive_source_kind"),
            "playlist_id": playlist_id,
            "youtube_slot": decision.slot,
            "youtube_channel_id": decision.channel_id,
            "youtube_routing_mode": decision.routing_mode,
            "youtube_preferred_slot": decision.preferred_slot,
            "estimated_quota": quota.get("estimated_units", {}),
            "preview_digest": input_digest(snapshot),
            "items": job_items,
        },
    )
    if status == "queued":
        wake_upload_worker()
    return JSONResponse(status_code=202, content=public_job(job))


@router.get("/jobs/{job_id}")
def get_upload_job(
    job_id: str,
    creds: Credentials = Depends(require_login_credentials),
    owner_sub: str = Depends(require_account_subject),
):
    del creds
    job = upload_job_store.get(owner_sub, job_id)
    if not job:
        raise http_error(404, "youtube_upload_job_not_found", "找不到指定的上傳工作。")
    return public_job(job)


@router.post("/jobs/{job_id}/cancel")
def cancel_upload_job(
    job_id: str,
    creds: Credentials = Depends(require_login_credentials),
    owner_sub: str = Depends(require_account_subject),
):
    del creds
    job = upload_job_store.get(owner_sub, job_id)
    if not job:
        raise http_error(404, "youtube_upload_job_not_found", "找不到指定的上傳工作。")
    if job.get("status") in TERMINAL_STATUSES:
        return public_job(job)
    updated = upload_job_store.update(
        owner_sub,
        job_id,
        lambda current: current.update({"cancel_requested": True, "status": "cancel_requested"}),
    )
    wake_upload_worker()
    return public_job(updated)


@router.post("/jobs/{job_id}/retry")
def retry_upload_job(
    job_id: str,
    creds: Credentials = Depends(require_login_credentials),
    owner_sub: str = Depends(require_account_subject),
):
    del creds
    job = upload_job_store.get(owner_sub, job_id)
    if not job:
        raise http_error(404, "youtube_upload_job_not_found", "找不到指定的上傳工作。")
    if job.get("status") not in {"failed", "paused"}:
        return public_job(job)

    def reset(current: dict[str, Any]) -> None:
        for item in current.get("items", []):
            if item.get("status") == "failed":
                item["status"] = "uploaded" if item.get("youtube_video_id") else "pending"
                item["error"] = None
        current.update({"status": "queued", "cancel_requested": False, "error": None})

    updated = upload_job_store.update(owner_sub, job_id, reset)
    wake_upload_worker()
    return public_job(updated)


__all__ = ["DriveUploadJobInput", "DriveUploadPreviewInput", "router"]
