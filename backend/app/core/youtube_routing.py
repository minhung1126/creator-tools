"""Quota-aware Primary-first routing for YouTube workflow requests."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException
from google.oauth2.credentials import Credentials

from backend.app.core.account_state import (
    get_account_active_slot,
    get_account_youtube_routing_mode,
)
from backend.app.core.config import normalize_youtube_slot, settings
from backend.app.core.credential_store import credential_store
from backend.app.core.error_contract import http_error
from backend.app.services.google_auth import get_youtube_credentials
from backend.app.services.youtube_errors import YouTubeQuotaUnavailable
from backend.app.services.youtube_quota_service import (
    get_youtube_quota_tracker,
    get_youtube_upload_quota_tracker,
)

MAX_PLAYLIST_ITEMS = 5_000
MAX_BATCH_ASSIGNMENTS = 500
PLAYLIST_ITEMS_MAX_UNITS = math.ceil(MAX_PLAYLIST_ITEMS / 50)
PLAYLIST_PREVIEW_MAX_UNITS = PLAYLIST_ITEMS_MAX_UNITS * 2
QUOTA_FAILURE_REASONS = frozenset({"quota_insufficient", "youtube_quota_exhausted", "youtube_quota_safety_blocked"})
UPLOAD_GENERAL_COST = 50
UPLOAD_QUOTA_COST = 1
UPLOAD_PLAYLIST_VALIDATION_READS = 2


@dataclass(frozen=True)
class YouTubeSlotDecision:
    """The slot and routing explanation fixed for one workflow request."""

    slot: str
    preferred_slot: str
    routing_mode: str
    estimated_units: int
    reason: str
    credentials: Credentials
    channel_id: str | None


@dataclass(frozen=True)
class _Candidate:
    slot: str
    credentials: Credentials | None
    channel_id: str | None
    eligible: bool
    reason: str
    reset_at: str | None = None


def _bounded_count(value: Any, maximum: int = MAX_BATCH_ASSIGNMENTS) -> int:
    if isinstance(value, list):
        return min(len(value), maximum)
    try:
        return max(0, min(int(value), maximum))
    except (TypeError, ValueError):
        return 0


def _pages(count: int) -> int:
    return math.ceil(max(int(count), 0) / 50) if count else 0


def estimate_youtube_request_units(
    path: str,
    body: Mapping[str, Any] | None = None,
    *,
    default_playlist_id: str = "",
) -> int:
    """Return a conservative whole-workflow quota estimate for routing.

    The estimate intentionally errs high so Auto mode does not start a
    workflow on Primary when the known request shape cannot fit its remaining
    safe quota. Unknown or small read requests still reserve at least one unit.
    """

    payload = body if isinstance(body, Mapping) else {}
    route = str(path or "").rstrip("/")

    if route.endswith("/playlist-items"):
        # The playlist length is unknown until the first API call. Use the
        # configured application cap as a safe upper bound for the two read
        # families used by the preview.
        return PLAYLIST_PREVIEW_MAX_UNITS

    if route.endswith("/video-metadata"):
        return 51  # videos.list + videos.update

    assignments = _bounded_count(payload.get("assignments"))
    pages = _pages(assignments)
    has_playlist = bool(str(payload.get("playlist_id") or "").strip() or str(default_playlist_id or "").strip())

    if route.endswith("/batch-preview"):
        playlist_reads = PLAYLIST_ITEMS_MAX_UNITS if has_playlist else 0
        return max(playlist_reads + pages, 1)

    if route.endswith("/batch-update"):
        playlist_reads = 2 * PLAYLIST_ITEMS_MAX_UNITS if has_playlist else 0
        video_reads = pages if has_playlist else 2 * pages
        return max(playlist_reads + video_reads + assignments * 50, 1)

    if route.endswith("/publish-and-cleanup"):
        snapshot = payload.get("preview_snapshot")
        video_ids = snapshot.get("video_ids") if isinstance(snapshot, Mapping) else None
        count = _bounded_count(video_ids, MAX_PLAYLIST_ITEMS)
        if not count:
            count = MAX_PLAYLIST_ITEMS
        playlist_pages = _pages(count)
        return max((2 * playlist_pages) + _pages(count) + count * 100, 1)

    return 1


def _channel_mismatch(owner_sub: str) -> bool:
    public = {
        slot: credential_store.get_youtube_public(owner_sub, slot=slot) or {} for slot in ("primary", "secondary")
    }
    primary_channel = str(public["primary"].get("channel_id") or "").strip()
    secondary_channel = str(public["secondary"].get("channel_id") or "").strip()
    return bool(primary_channel and secondary_channel and primary_channel != secondary_channel)


def _candidate(
    session_id: str,
    owner_sub: str,
    slot: str,
    *,
    estimated_units: int,
    check_quota: bool,
) -> _Candidate:
    slot_config = settings.youtube_oauth_slot(slot)
    if not slot_config.configured:
        return _Candidate(slot, None, None, False, "not_configured")

    credentials = get_youtube_credentials(session_id, slot=slot)
    public = credential_store.get_youtube_public(owner_sub, slot=slot) or {}
    channel_id = str(public.get("channel_id") or "").strip() or None
    if not credentials or not credentials.valid or not channel_id:
        return _Candidate(slot, credentials, channel_id, False, "not_connected")

    if not check_quota:
        return _Candidate(slot, credentials, channel_id, True, "available")

    try:
        usage = get_youtube_quota_tracker(slot).get_usage()
    except YouTubeQuotaUnavailable as exc:
        return _Candidate(slot, credentials, channel_id, False, exc.code, exc.reset_at)

    available = int(usage.get("effective_available_units") or 0)
    if available < estimated_units:
        return _Candidate(slot, credentials, channel_id, False, "quota_insufficient", usage.get("reset_at"))
    return _Candidate(slot, credentials, channel_id, True, "available", usage.get("reset_at"))


def _routing_failure(candidates: list[_Candidate], preferred_slot: str) -> HTTPException:
    if candidates and all(candidate.reason == "not_configured" for candidate in candidates):
        return http_error(
            503,
            "youtube_slot_not_configured",
            "目前作用中的 YouTube OAuth slot 尚未完成伺服器設定。",
            retryable=True,
            youtube_slot=preferred_slot,
        )
    authenticated_candidates = [candidate for candidate in candidates if candidate.credentials and candidate.channel_id]
    if authenticated_candidates and all(
        candidate.reason in QUOTA_FAILURE_REASONS for candidate in authenticated_candidates
    ):
        reset_at = next((candidate.reset_at for candidate in authenticated_candidates if candidate.reset_at), None)
        return http_error(
            429,
            "youtube_quota_no_available_slot",
            "Primary 與 Secondary 目前都沒有足夠的 YouTube quota，請稍後重試。",
            retryable=True,
            reset_at=reset_at,
            youtube_slot=preferred_slot,
        )
    if any("storage" in candidate.reason for candidate in authenticated_candidates):
        return http_error(
            503,
            "youtube_quota_storage_unavailable",
            "YouTube 配額紀錄目前無法安全讀寫，系統已阻止新的請求。",
            retryable=True,
            youtube_slot=preferred_slot,
        )
    return http_error(
        403,
        "youtube_not_connected",
        "尚未連結可用的 YouTube 頻道 Google 帳號，請至「YouTube 設定」完成授權。",
        youtube_slot=preferred_slot,
    )


def choose_youtube_slot(
    session_id: str,
    owner_sub: str,
    *,
    estimated_units: int,
    slot_hint: str | None = None,
) -> YouTubeSlotDecision:
    """Choose a valid slot using account policy and safe quota availability."""

    routing_mode = get_account_youtube_routing_mode(owner_sub)
    preferred_slot = get_account_active_slot(owner_sub) if routing_mode == "manual" else "primary"
    normalized_estimate = max(int(estimated_units or 0), 1)

    if _channel_mismatch(owner_sub):
        raise http_error(
            409,
            "youtube_channel_mismatch",
            "Primary 與 secondary 必須管理同一個 YouTube Channel，請重新授權其中一個 slot。",
            youtube_slot=preferred_slot,
        )

    normalized_hint = None
    if slot_hint:
        try:
            normalized_hint = normalize_youtube_slot(slot_hint)
        except ValueError as exc:
            raise http_error(400, "youtube_slot_invalid", "不支援的 YouTube OAuth slot。") from exc

    if normalized_hint and (routing_mode == "auto_primary" or normalized_hint == preferred_slot):
        # A preview hint is a preference, not permission to ignore a quota
        # change that happened while the user was reviewing the preview. In
        # Auto mode, try the hinted slot first and immediately fall back to
        # the other authenticated slot when its latest safe quota is short.
        hinted = _candidate(
            session_id,
            owner_sub,
            normalized_hint,
            estimated_units=normalized_estimate,
            check_quota=routing_mode == "auto_primary",
        )
        candidates = [hinted]
        if hinted.eligible:
            return YouTubeSlotDecision(
                slot=normalized_hint,
                preferred_slot=preferred_slot,
                routing_mode=routing_mode,
                estimated_units=normalized_estimate,
                reason="preview_pinned_slot",
                credentials=hinted.credentials,
                channel_id=hinted.channel_id,
            )
        if routing_mode == "auto_primary":
            fallback_slot = "secondary" if normalized_hint == "primary" else "primary"
            fallback = _candidate(
                session_id,
                owner_sub,
                fallback_slot,
                estimated_units=normalized_estimate,
                check_quota=True,
            )
            candidates.append(fallback)
            if fallback.eligible:
                return YouTubeSlotDecision(
                    slot=fallback.slot,
                    preferred_slot=preferred_slot,
                    routing_mode=routing_mode,
                    estimated_units=normalized_estimate,
                    reason=f"auto_{fallback.slot}_{hinted.reason}",
                    credentials=fallback.credentials,
                    channel_id=fallback.channel_id,
                )
        raise _routing_failure(candidates, normalized_hint)

    candidate_slots = [preferred_slot] if routing_mode == "manual" else ["primary", "secondary"]
    candidates = [
        _candidate(
            session_id,
            owner_sub,
            slot,
            estimated_units=normalized_estimate,
            check_quota=routing_mode == "auto_primary",
        )
        for slot in candidate_slots
    ]

    for index, candidate in enumerate(candidates):
        if not candidate.eligible:
            continue
        if routing_mode == "manual":
            reason = "manual_active_slot"
        elif index == 0:
            reason = "auto_primary_available"
        else:
            reason = f"auto_secondary_{candidates[0].reason}"
        return YouTubeSlotDecision(
            slot=candidate.slot,
            preferred_slot=preferred_slot,
            routing_mode=routing_mode,
            estimated_units=normalized_estimate,
            reason=reason,
            credentials=candidate.credentials,
            channel_id=candidate.channel_id,
        )

    raise _routing_failure(candidates, preferred_slot)


def plan_youtube_upload_quota(
    item_count: int,
    insertion_count: int | None = None,
    *,
    general_reads_spent: int = 0,
) -> dict[str, Any]:
    """Return stage and complete-workflow costs for a Drive upload.

    A complete Drive upload workflow performs two one-unit playlist
    validations: one for preview and one before creating the durable job.
    ``general_reads_spent`` makes the stage explicit for callers that already
    performed one of those reads.  Uploads and playlist insertions are tracked
    independently so a resume-only job (``upload_count=0``) never reserves
    ``video_uploads`` quota.
    """

    upload_count = max(int(item_count or 0), 0)
    playlist_count = upload_count if insertion_count is None else max(int(insertion_count or 0), 0)
    reads_spent = max(int(general_reads_spent or 0), 0)
    validation_reads = max(UPLOAD_PLAYLIST_VALIDATION_READS - reads_spent, 0)
    complete_general = UPLOAD_PLAYLIST_VALIDATION_READS + playlist_count * UPLOAD_GENERAL_COST
    video_uploads = upload_count * UPLOAD_QUOTA_COST
    complete_workflow = {
        "general": complete_general,
        "video_uploads": video_uploads,
        "total": complete_general + video_uploads,
    }
    # The first validation belongs to preview; the second validation and all
    # uploads/insertions belong to job execution.  Once a read is spent, the
    # remaining_required value is what routing must admit against quota.
    preview_read = {"general": 1 if reads_spent == 0 else 0, "video_uploads": 0}
    job_required_general = max(complete_general - max(reads_spent, 1), 0)
    job_required = {
        "general": job_required_general,
        "video_uploads": video_uploads,
    }
    remaining_required = {
        "general": validation_reads + playlist_count * UPLOAD_GENERAL_COST,
        "video_uploads": video_uploads,
    }
    return {
        "preview_read": preview_read,
        "job_required": job_required,
        "remaining_required": remaining_required,
        "complete_workflow": complete_workflow,
        "general": complete_general,
        "video_uploads": video_uploads,
        "total": complete_workflow["total"],
        "remaining_total": sum(remaining_required.values()),
    }


def estimate_youtube_upload_quota(
    item_count: int,
    insertion_count: int | None = None,
    *,
    general_reads_spent: int = 0,
) -> dict[str, Any]:
    """Return the complete-workflow estimate plus its stage contract."""

    return plan_youtube_upload_quota(
        item_count,
        insertion_count,
        general_reads_spent=general_reads_spent,
    )


def _upload_candidate(
    session_id: str,
    owner_sub: str,
    slot: str,
    *,
    item_count: int,
    upload_count: int | None = None,
    insertion_count: int | None = None,
    general_reads_spent: int = 0,
    check_quota: bool,
) -> _Candidate:
    candidate = _candidate(
        session_id,
        owner_sub,
        slot,
        estimated_units=1,
        check_quota=False,
    )
    if not candidate.eligible or not check_quota:
        return candidate
    costs = plan_youtube_upload_quota(
        item_count if upload_count is None else upload_count,
        item_count if insertion_count is None else insertion_count,
        general_reads_spent=general_reads_spent,
    )["remaining_required"]
    try:
        general = get_youtube_quota_tracker(slot).get_usage() if costs["general"] else {}
        uploads = get_youtube_upload_quota_tracker(slot).get_usage() if costs["video_uploads"] else {}
    except YouTubeQuotaUnavailable as exc:
        return _Candidate(slot, candidate.credentials, candidate.channel_id, False, exc.code, exc.reset_at)
    if costs["general"] and int(general.get("effective_available_units") or 0) < costs["general"]:
        return _Candidate(
            slot, candidate.credentials, candidate.channel_id, False, "quota_insufficient", general.get("reset_at")
        )
    if costs["video_uploads"] and int(uploads.get("effective_available_units") or 0) < costs["video_uploads"]:
        return _Candidate(
            slot, candidate.credentials, candidate.channel_id, False, "quota_insufficient", uploads.get("reset_at")
        )
    return _Candidate(
        slot,
        candidate.credentials,
        candidate.channel_id,
        True,
        "available",
        general.get("reset_at") or uploads.get("reset_at"),
    )


def choose_youtube_upload_slot(
    session_id: str,
    owner_sub: str,
    *,
    item_count: int,
    upload_count: int | None = None,
    insertion_count: int | None = None,
    slot_hint: str | None = None,
    general_reads_spent: int | None = None,
) -> YouTubeSlotDecision:
    """Select one slot that can fit both upload buckets.

    ``general_reads_spent`` is the stage contract shared with the upload
    preview/job flow.  For compatibility with the existing create-job caller,
    a pinned request with ``item_count=0`` means the preview validation has
    already been spent and therefore has one read left to reserve.
    """

    routing_mode = get_account_youtube_routing_mode(owner_sub)
    preferred_slot = get_account_active_slot(owner_sub) if routing_mode == "manual" else "primary"
    normalized_count = max(int(item_count or 0), 0)
    normalized_upload_count = normalized_count if upload_count is None else max(int(upload_count or 0), 0)
    normalized_insertion_count = normalized_count if insertion_count is None else max(int(insertion_count or 0), 0)
    normalized_hint = None
    if slot_hint:
        try:
            normalized_hint = normalize_youtube_slot(slot_hint)
        except ValueError as exc:
            raise http_error(400, "youtube_slot_invalid", "不支援的 YouTube OAuth slot。") from exc
    if general_reads_spent is None:
        general_reads_spent = 1 if normalized_hint and normalized_count == 0 else 0
    normalized_reads_spent = max(int(general_reads_spent or 0), 0)
    if _channel_mismatch(owner_sub):
        raise http_error(
            409,
            "youtube_channel_mismatch",
            "Primary 與 secondary 必須管理同一個 YouTube Channel，請重新授權其中一個 slot。",
            youtube_slot=preferred_slot,
        )

    if normalized_hint:
        hinted = _upload_candidate(
            session_id,
            owner_sub,
            normalized_hint,
            item_count=normalized_count,
            upload_count=normalized_upload_count,
            insertion_count=normalized_insertion_count,
            general_reads_spent=normalized_reads_spent,
            check_quota=True,
        )
        candidates = [hinted]
        if hinted.eligible:
            return YouTubeSlotDecision(
                slot=normalized_hint,
                preferred_slot=preferred_slot,
                routing_mode=routing_mode,
                estimated_units=estimate_youtube_upload_quota(
                    normalized_upload_count,
                    normalized_insertion_count,
                    general_reads_spent=normalized_reads_spent,
                )["total"],
                reason="preview_pinned_slot",
                credentials=hinted.credentials,
                channel_id=hinted.channel_id,
            )
        if routing_mode == "auto_primary":
            fallback_slot = "secondary" if normalized_hint == "primary" else "primary"
            fallback = _upload_candidate(
                session_id,
                owner_sub,
                fallback_slot,
                item_count=normalized_count,
                upload_count=normalized_upload_count,
                insertion_count=normalized_insertion_count,
                general_reads_spent=normalized_reads_spent,
                check_quota=True,
            )
            candidates.append(fallback)
            if fallback.eligible:
                return YouTubeSlotDecision(
                    slot=fallback.slot,
                    preferred_slot=preferred_slot,
                    routing_mode=routing_mode,
                    estimated_units=estimate_youtube_upload_quota(
                        normalized_upload_count,
                        normalized_insertion_count,
                        general_reads_spent=normalized_reads_spent,
                    )["total"],
                    reason=f"auto_{fallback.slot}_{hinted.reason}",
                    credentials=fallback.credentials,
                    channel_id=fallback.channel_id,
                )
        raise _routing_failure(candidates, normalized_hint)

    candidate_slots = [preferred_slot] if routing_mode == "manual" else ["primary", "secondary"]
    candidates = [
        _upload_candidate(
            session_id,
            owner_sub,
            slot,
            item_count=normalized_count,
            upload_count=normalized_upload_count,
            insertion_count=normalized_insertion_count,
            general_reads_spent=normalized_reads_spent,
            check_quota=True,
        )
        for slot in candidate_slots
    ]
    for index, candidate in enumerate(candidates):
        if not candidate.eligible:
            continue
        reason = (
            "manual_active_slot"
            if routing_mode == "manual"
            else ("auto_primary_available" if index == 0 else f"auto_secondary_{candidates[0].reason}")
        )
        return YouTubeSlotDecision(
            slot=candidate.slot,
            preferred_slot=preferred_slot,
            routing_mode=routing_mode,
            estimated_units=estimate_youtube_upload_quota(
                normalized_upload_count,
                normalized_insertion_count,
                general_reads_spent=normalized_reads_spent,
            )["total"],
            reason=reason,
            credentials=candidate.credentials,
            channel_id=candidate.channel_id,
        )
    raise _routing_failure(candidates, preferred_slot)


__all__ = [
    "YouTubeSlotDecision",
    "choose_youtube_slot",
    "choose_youtube_upload_slot",
    "estimate_youtube_request_units",
    "estimate_youtube_upload_quota",
    "plan_youtube_upload_quota",
    "UPLOAD_PLAYLIST_VALIDATION_READS",
]
