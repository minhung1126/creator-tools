import logging
import math
from typing import Any, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from google.oauth2.credentials import Credentials
from pydantic import BaseModel, Field

from backend.app.core.account_state import get_account_active_slot, get_account_setting
from backend.app.core.config import normalize_youtube_slot
from backend.app.core.dependencies import (
    require_account_subject,
    require_login_credentials,
    require_youtube_context,
)
from backend.app.core.error_contract import http_error
from backend.app.core.preview import (
    build_preview_token,
    input_digest,
    playlist_snapshot,
    playlist_snapshot_from_preview,
    sheet_snapshot,
    verify_preview_token,
)
from backend.app.core.request_protection import enforce_workflow_rate_limit
from backend.app.core.youtube_context import YouTubeRequestContext
from backend.app.core.youtube_input import normalize_playlist_id
from backend.app.services.provider_errors import map_youtube_error
from backend.app.services.sheets_service import (
    get_all_rows_for_sheet,
    get_sheet_headers,
    matches_team_person,
    normalize_text,
)
from backend.app.services.youtube_errors import YouTubeQuotaUnavailable
from backend.app.services.youtube_quota_service import get_youtube_quota_tracker
from backend.app.services.youtube_service import (
    fetch_playlist_items,
    fetch_playlist_preview,
    fetch_video_details,
    remove_playlist_item,
    set_video_public,
    update_single_video_metadata,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/youtube", tags=["YouTube Operations"])


class PlaylistItemsInput(BaseModel):
    playlist_id: Optional[str] = Field(default="", max_length=256)


class VideoMetadataUpdateInput(BaseModel):
    video_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=5000)


class VideoAssignment(BaseModel):
    video_id: str = Field(min_length=1, max_length=128)
    person: str = Field(max_length=200)


class BatchUpdateInput(BaseModel):
    spreadsheet_url_or_id: Optional[str] = Field(default="", max_length=512)
    playlist_id: Optional[str] = Field(default="", max_length=256)
    youtube_slot: Optional[Literal["primary", "secondary"]] = None
    preview_token: Optional[str] = Field(default=None, max_length=16_384)
    preview_snapshot: Optional[dict[str, Any]] = None
    video_type: str = Field(default="Video", max_length=32)
    worksheet_name: str = Field(min_length=1, max_length=200)
    title_column: str = Field(min_length=1, max_length=200)
    description_column: str = Field(min_length=1, max_length=200)
    team: str = Field(min_length=1, max_length=200)
    assignments: List[VideoAssignment] = Field(min_length=1, max_length=500)


class PublishCleanupInput(BaseModel):
    playlist_id: Optional[str] = Field(default="", max_length=256)
    youtube_slot: Optional[Literal["primary", "secondary"]] = None
    preview_token: Optional[str] = Field(default=None, max_length=16_384)
    preview_snapshot: Optional[dict[str, Any]] = None


class QuotaEstimateInput(BaseModel):
    operation: Literal["youtube.metadata_update", "youtube.publish_cleanup"]
    item_count: int = Field(ge=0, le=500)
    slot: Optional[str] = Field(default=None, max_length=32)


def _resolve_playlist_id(context: YouTubeRequestContext, requested: Optional[str]) -> str:
    # The account-level playlist is authoritative.  The request field remains
    # accepted only as a migration fallback for old clients/accounts that have
    # never saved the shared setting.
    configured_value = get_account_setting(context.owner_sub, "default_playlist_id", "")
    raw_value = configured_value or requested
    if not str(raw_value or "").strip():
        return ""
    playlist_id = normalize_playlist_id(raw_value)
    if not playlist_id:
        raise http_error(400, "playlist_invalid", "播放清單網址或 ID 格式不正確。")
    return playlist_id


def _quota_http_exception(exc: YouTubeQuotaUnavailable) -> HTTPException:
    detail = exc.to_dict()
    return http_error(
        429,
        detail["code"],
        detail["message"],
        retryable=True,
        reset_at=detail.get("reset_at"),
        youtube_slot=detail.get("youtube_slot"),
    )


def _youtube_context_metadata(context: YouTubeRequestContext) -> dict[str, Any]:
    return {
        "youtube_slot": context.slot,
        "youtube_routing_mode": context.routing_mode,
        "youtube_slot_reason": context.selection_reason,
        "youtube_preferred_slot": context.preferred_slot,
        "youtube_estimated_units": context.estimated_units,
    }


def _quota_estimate(operation: str, item_count: int, *, slot: Optional[str] = None) -> dict:
    count = max(int(item_count), 0)
    pages = math.ceil(count / 50) if count else 0
    if operation == "youtube.metadata_update":
        breakdown = [
            {"method": "videos.list", "calls": pages, "units": pages},
            {"method": "videos.update", "calls": count, "units": count * 50},
        ]
    elif operation == "youtube.publish_cleanup":
        breakdown = [
            # The workflow reads To-Post once for the preview snapshot and a
            # second time immediately before the first write.
            {"method": "playlistItems.list", "calls": pages * 2, "units": pages * 2},
            {"method": "videos.list", "calls": pages, "units": pages},
            {"method": "videos.update", "calls": count, "units": count * 50},
            {"method": "playlistItems.delete", "calls": count, "units": count * 50},
        ]
    else:  # defensive for callers outside Pydantic/FastAPI
        raise ValueError("不支援的 YouTube quota estimate operation")

    projected = sum(int(item["units"]) for item in breakdown)
    if slot is None:
        tracker = get_youtube_quota_tracker("primary")
        slot_name = "primary"
    else:
        try:
            slot_name = normalize_youtube_slot(slot)
        except ValueError as exc:
            raise ValueError("不支援的 YouTube OAuth slot") from exc
        tracker = get_youtube_quota_tracker(slot_name)
    usage = tracker.get_usage()
    available = int(usage.get("effective_available_units") or 0)

    def cost_for(number: int) -> int:
        number_pages = math.ceil(number / 50) if number else 0
        if operation == "youtube.metadata_update":
            return number_pages + number * 50
        return number_pages * 3 + number * 100

    max_items_today = 0
    for number in range(1, count + 1):
        if cost_for(number) <= available:
            max_items_today = number
        else:
            break
    return {
        "operation": operation,
        "slot": slot_name,
        "item_count": count,
        "projected_units": projected,
        "worst_case": True,
        "breakdown": breakdown,
        "effective_available_units": available,
        "can_complete_today": projected <= available,
        "max_items_today": max_items_today,
        "reset_at": usage.get("reset_at"),
        "reset_timezone": usage.get("reset_timezone", "America/Los_Angeles"),
    }


def resolve_assignment_row(matches, title_column: str, description_column: str):
    """Accept duplicate matching rows when the selected output values are identical."""
    if not matches:
        return None, "not_found"

    distinct_values = {}
    for row in matches:
        title = normalize_text(row.get(title_column) or "")
        description = str(row.get(description_column) or "")
        distinct_values.setdefault((title, description), row)

    if len(distinct_values) > 1:
        return None, "conflict"
    return next(iter(distinct_values.values())), None


def video_snapshot_digest(details_map: dict[str, dict], video_ids: list[str]) -> str:
    """Digest the mutable YouTube fields used by a metadata update."""

    values = []
    for video_id in video_ids:
        detail = details_map.get(video_id) or {}
        snippet = detail.get("snippet") or {}
        status = detail.get("status") or {}
        values.append(
            {
                "video_id": video_id,
                "title": str(snippet.get("title") or ""),
                "description": str(snippet.get("description") or ""),
                "category_id": str(snippet.get("categoryId") or ""),
                "privacy_status": str(status.get("privacyStatus") or ""),
            }
        )
    return input_digest(values)


def upload_time_sort_key(video_id: str, details_map, original_positions):
    """Sort valid YouTube publishedAt values oldest-first with stable fallbacks."""
    detail = details_map.get(video_id) or {}
    published_at = (detail.get("snippet") or {}).get("publishedAt") or ""
    return (
        not bool(published_at),
        published_at,
        original_positions.get(video_id, 0),
    )


@router.get("/quota-usage")
def get_quota_usage(
    slot: Optional[str] = Query(default=None, max_length=32),
    creds: Credentials = Depends(require_login_credentials),
    owner_sub: str = Depends(require_account_subject),
):
    del creds
    try:
        slot_name = get_account_active_slot(owner_sub) if slot is None else normalize_youtube_slot(slot)
        return get_youtube_quota_tracker(slot_name).get_usage()
    except ValueError as exc:
        raise http_error(400, "youtube_slot_invalid", "不支援的 YouTube OAuth slot。") from exc
    except YouTubeQuotaUnavailable as exc:
        raise _quota_http_exception(exc) from exc


@router.post("/quota-estimate")
def estimate_quota(
    payload: QuotaEstimateInput,
    creds: Credentials = Depends(require_login_credentials),
    owner_sub: str = Depends(require_account_subject),
):
    del creds
    if payload.item_count < 0:
        raise http_error(
            400, "invalid_item_count", "item_count 不可小於 0。", field_errors={"item_count": ["不可小於 0。"]}
        )
    try:
        return _quota_estimate(
            payload.operation,
            payload.item_count,
            slot=payload.slot or get_account_active_slot(owner_sub),
        )
    except ValueError as exc:
        raise http_error(400, "youtube_slot_invalid", "不支援的 YouTube OAuth slot。") from exc
    except YouTubeQuotaUnavailable as exc:
        raise _quota_http_exception(exc) from exc


@router.post("/playlist-items")
def get_playlist_videos(
    payload: PlaylistItemsInput,
    creds: YouTubeRequestContext = Depends(require_youtube_context),
):
    youtube_context = creds
    playlist_id = _resolve_playlist_id(youtube_context, payload.playlist_id)
    if not playlist_id:
        raise http_error(400, "playlist_required", "請提供播放清單 ID。")
    try:
        videos, source, fallback_reason = fetch_playlist_preview(youtube_context, playlist_id)
        videos = [{**video, "youtube_slot": youtube_context.slot} for video in videos]
        preview_snapshot = playlist_snapshot_from_preview(videos)
        preview_snapshot["youtube_slot"] = youtube_context.slot
        preview_snapshot["youtube_routing_mode"] = youtube_context.routing_mode
        preview_snapshot["youtube_slot_reason"] = youtube_context.selection_reason
        return {
            "playlist_id": playlist_id,
            "total": len(videos),
            "videos": videos,
            "source": source,
            "fallback_reason": fallback_reason,
            "youtube_slot": youtube_context.slot,
            "youtube_routing_mode": youtube_context.routing_mode,
            "youtube_slot_reason": youtube_context.selection_reason,
            "youtube_preferred_slot": youtube_context.preferred_slot,
            "youtube_estimated_units": youtube_context.estimated_units,
            "preview_token": _playlist_preview_token(youtube_context, playlist_id, videos),
            "preview_snapshot": preview_snapshot,
            "quota_usage": youtube_context.quota_limiter.get_usage(),
        }
    except YouTubeQuotaUnavailable as exc:
        raise _quota_http_exception(exc) from exc
    except Exception as exc:
        logger.error("Failed to fetch YouTube playlist items: %s", type(exc).__name__)
        raise map_youtube_error(
            exc, method="playlistItems.list", youtube_slot=youtube_context.slot
        ).to_http_exception() from exc


def _youtube_thumbnail(detail: dict, video_id: str) -> str:
    thumbnails = (detail.get("snippet") or {}).get("thumbnails") or {}
    return (
        (thumbnails.get("maxres") or {}).get("url")
        or (thumbnails.get("standard") or {}).get("url")
        or (thumbnails.get("high") or {}).get("url")
        or (thumbnails.get("medium") or {}).get("url")
        or (thumbnails.get("default") or {}).get("url")
        or (f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg" if video_id else "")
    )


@router.post("/video-metadata")
def update_video_metadata(
    payload: VideoMetadataUpdateInput,
    creds: YouTubeRequestContext = Depends(require_youtube_context),
    _rate_limit: None = Depends(enforce_workflow_rate_limit),
):
    """Update one video's title and description while preserving other metadata."""
    youtube_context = creds
    video_id = normalize_text(payload.video_id)
    title = normalize_text(payload.title)
    description = payload.description
    if not video_id or not title:
        raise http_error(400, "youtube_video_input_invalid", "影片 ID 與標題不可為空白。")

    try:
        details = fetch_video_details(youtube_context, [video_id])
        detail = next((item for item in details if item.get("id") == video_id), None)
        if not detail:
            raise http_error(404, "youtube_not_found", "找不到指定的 YouTube 影片。", youtube_slot=youtube_context.slot)

        update_single_video_metadata(
            youtube_context,
            video_id,
            str(title),
            description,
            current_snippet=(detail.get("snippet") or {}),
        )
        return {
            "video_id": video_id,
            **_youtube_context_metadata(youtube_context),
            "title": str(title),
            "description": description,
            "thumbnail_url": _youtube_thumbnail(detail, video_id),
            "status": "succeeded",
        }
    except YouTubeQuotaUnavailable as exc:
        raise _quota_http_exception(exc) from exc
    except HTTPException:
        raise
    except ValueError as exc:
        raise map_youtube_error(
            exc, method="videos.update", youtube_slot=youtube_context.slot
        ).to_http_exception() from exc
    except Exception as exc:
        logger.error("Single YouTube metadata update failed for slot %s: %s", youtube_context.slot, type(exc).__name__)
        raise map_youtube_error(
            exc, method="videos.update", youtube_slot=youtube_context.slot
        ).to_http_exception() from exc


def _safe_workflow_error(exc: Exception) -> str:
    if isinstance(exc, YouTubeQuotaUnavailable):
        return exc.user_message
    return map_youtube_error(exc).message


def _workflow_error_detail(exc: Exception, *, slot: str) -> dict[str, Any]:
    if isinstance(exc, YouTubeQuotaUnavailable):
        return exc.to_dict()
    return map_youtube_error(exc, youtube_slot=slot).detail


def _stale_preview_exception() -> HTTPException:
    return http_error(
        409,
        "stale_preview",
        "預覽已過期或來源已變更，尚未寫入任何資料。請重新讀取後再執行。",
    )


def _playlist_preview_token(context: YouTubeRequestContext, playlist_id: str, videos: list[dict]) -> str:
    return build_preview_token(
        owner_sub=context.owner_sub,
        youtube_slot=context.slot,
        operation="youtube.playlist_preview",
        playlist_id=playlist_id,
        playlist=playlist_snapshot_from_preview(videos),
    )


def _verify_playlist_preview_token(
    context: YouTubeRequestContext,
    playlist_id: str,
    expected_playlist: dict[str, Any],
    preview_token: Optional[str],
    *,
    operation: str = "youtube.playlist_preview",
) -> None:
    if not preview_token or not verify_preview_token(
        preview_token,
        owner_sub=context.owner_sub,
        youtube_slot=context.slot,
        operation=operation,
        playlist_id=playlist_id,
        playlist=expected_playlist,
    ):
        raise _stale_preview_exception()


@router.post("/batch-preview")
def create_batch_metadata_preview(
    payload: BatchUpdateInput,
    creds: YouTubeRequestContext = Depends(require_youtube_context),
    sheet_creds: Credentials = Depends(require_login_credentials),
):
    """Build a signed, account-bound batch plan without performing writes."""

    youtube_context = creds
    spreadsheet_id = (
        payload.spreadsheet_url_or_id or get_account_setting(youtube_context.owner_sub, "default_spreadsheet_id", "")
    ).strip()
    playlist_id = _resolve_playlist_id(youtube_context, payload.playlist_id)
    normalized_team = normalize_text(payload.team)
    title_column = normalize_text(payload.title_column)
    description_column = normalize_text(payload.description_column)
    all_assignments = [(assignment.video_id, normalize_text(assignment.person)) for assignment in payload.assignments]
    active_assignments = [(video_id, person) for video_id, person in all_assignments if person and person != "不編輯"]
    if not spreadsheet_id:
        raise http_error(400, "spreadsheet_required", "請提供試算表 ID 或網址。")
    if title_column == description_column:
        raise http_error(
            400,
            "columns_must_differ",
            "標題欄位與描述欄位必須不同。",
            field_errors={"description_column": ["不可與 title_column 相同。"]},
        )
    if not active_assignments:
        raise http_error(400, "no_active_assignments", "目前沒有任何影片被指定人物，請先選擇人物後再預覽。")

    try:
        headers = get_sheet_headers(sheet_creds, spreadsheet_id, payload.worksheet_name)
        required_headers = ["所屬團體", "人", title_column, description_column]
        missing_headers = [header for header in required_headers if header not in headers]
        if missing_headers:
            raise http_error(
                400,
                "sheet_columns_missing",
                f"工作表「{payload.worksheet_name}」缺少必要欄位，請重新整理後再試。",
                field_errors={"worksheet_name": [f"缺少欄位：{', '.join(missing_headers)}。"]},
            )
        sheet_rows = get_all_rows_for_sheet(sheet_creds, spreadsheet_id, payload.worksheet_name)
        if not sheet_rows:
            raise http_error(400, "sheet_rows_empty", f"工作表「{payload.worksheet_name}」沒有可用資料列。")
        sheet_state = sheet_snapshot(spreadsheet_id, payload.worksheet_name, headers, sheet_rows)
        if playlist_id:
            playlist_state = playlist_snapshot(fetch_playlist_items(youtube_context, playlist_id))
        else:
            playlist_state = playlist_snapshot(
                [{"id": "", "contentDetails": {"videoId": video_id}} for video_id, _ in active_assignments]
            )
        requested_video_ids = [video_id for video_id, _ in all_assignments]
        active_video_ids = [video_id for video_id, _ in active_assignments]
        if playlist_id and not set(requested_video_ids).issubset(set(playlist_state["video_ids"])):
            raise _stale_preview_exception()

        details_map = {
            item["id"]: item for item in fetch_video_details(youtube_context, requested_video_ids) if item.get("id")
        }
        request_state = input_digest(
            {
                "spreadsheet_id": spreadsheet_id,
                "worksheet_name": payload.worksheet_name,
                "title_column": title_column,
                "description_column": description_column,
                "team": normalized_team,
                "assignments": active_assignments,
                "video_snapshot": video_snapshot_digest(details_map, active_video_ids),
            }
        )
        plan = []
        for video_id, person in all_assignments:
            detail = details_map.get(video_id) or {}
            snippet = detail.get("snippet") or {}
            current_title = str(snippet.get("title") or "")
            current_description = str(snippet.get("description") or "")
            matches = [row for row in sheet_rows if matches_team_person(row, normalized_team, person)]
            row, match_error = resolve_assignment_row(matches, title_column, description_column)
            reason = ""
            new_title = ""
            new_description = ""
            status = "ready"
            if not person or person == "不編輯":
                status = "skipped"
                reason = "未指定人物"
            elif not detail:
                status = "skipped"
                reason = "找不到指定的 YouTube 影片，或目前帳號無權存取。"
            elif match_error == "not_found":
                status = "skipped"
                reason = f"找不到團體 {normalized_team} 的選項 {person} 資料"
            elif match_error == "conflict":
                status = "skipped"
                reason = f"團體 {normalized_team} 的選項 {person} 有多筆且標題或描述內容不同"
            else:
                new_title = normalize_text(row.get(title_column) or "")
                new_description = str(row.get(description_column) or "")
                if not new_title:
                    status = "skipped"
                    reason = f"工作表的 {title_column} 為空白"
            plan.append(
                {
                    "videoId": video_id,
                    "video_id": video_id,
                    "person": person,
                    "currentTitle": current_title,
                    "currentDescription": current_description,
                    "newTitle": new_title,
                    "newDescription": new_description,
                    "status": status,
                    "willUpdate": status == "ready",
                    "reason": reason,
                    "thumbnailUrl": _youtube_thumbnail(detail, video_id),
                }
            )

        preview_token = build_preview_token(
            owner_sub=youtube_context.owner_sub,
            youtube_slot=youtube_context.slot,
            operation="youtube.batch_update",
            playlist_id=playlist_id,
            playlist=playlist_state,
            sheet=sheet_state,
            request_digest=request_state,
        )
        preview_snapshot = {
            "spreadsheet_id": spreadsheet_id,
            "worksheet_name": payload.worksheet_name,
            "playlist_id": playlist_id,
            "youtube_slot": youtube_context.slot,
            "youtube_routing_mode": youtube_context.routing_mode,
            "youtube_slot_reason": youtube_context.selection_reason,
            "sheet_digest": sheet_state["sheet_digest"],
            "playlist_digest": playlist_state["playlist_digest"],
            "video_ids": requested_video_ids,
            "plan": plan,
        }
        return {
            "preview_token": preview_token,
            "preview_snapshot": preview_snapshot,
            "plan": plan,
            "playlist_id": playlist_id,
            **_youtube_context_metadata(youtube_context),
        }
    except YouTubeQuotaUnavailable as exc:
        raise _quota_http_exception(exc) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Batch metadata preview failed for slot %s: %s", youtube_context.slot, type(exc).__name__)
        raise map_youtube_error(
            exc, method="videos.list", youtube_slot=youtube_context.slot
        ).to_http_exception() from exc


def _direct_workflow_response(
    operation: str,
    results: list[dict],
    *,
    quota_error: Optional[YouTubeQuotaUnavailable] = None,
    slot: str = "primary",
    context: YouTubeRequestContext | None = None,
) -> dict:
    statuses = [str(item.get("status") or "") for item in results]
    response = {
        "operation": operation,
        "youtube_slot": slot,
        "completed": quota_error is None and "not_attempted" not in statuses,
        "total_count": len(results),
        "succeeded_count": statuses.count("succeeded"),
        "warning_count": statuses.count("succeeded_with_warnings"),
        "skipped_count": statuses.count("skipped"),
        "failed_count": statuses.count("failed"),
        "not_attempted_count": statuses.count("not_attempted"),
        "quota_blocked": quota_error is not None,
        "reset_at": quota_error.reset_at if quota_error else None,
        "results": results,
    }
    if context is not None:
        response.update(_youtube_context_metadata(context))
    if quota_error:
        response["quota_error"] = quota_error.to_dict()
    return response


@router.post("/batch-update")
def run_batch_metadata_update(
    payload: BatchUpdateInput,
    creds: YouTubeRequestContext = Depends(require_youtube_context),
    sheet_creds: Credentials = Depends(require_login_credentials),
    _rate_limit: None = Depends(enforce_workflow_rate_limit),
):
    """Validate and update selected videos synchronously, returning one result per video."""
    youtube_context = creds

    spreadsheet_id = (
        payload.spreadsheet_url_or_id or get_account_setting(youtube_context.owner_sub, "default_spreadsheet_id", "")
    ).strip()
    playlist_id = _resolve_playlist_id(youtube_context, payload.playlist_id)
    if not spreadsheet_id:
        raise http_error(400, "spreadsheet_required", "請提供試算表 ID 或網址。")
    normalized_team = normalize_text(payload.team)
    title_column = normalize_text(payload.title_column)
    description_column = normalize_text(payload.description_column)
    if title_column == description_column:
        raise http_error(
            400,
            "columns_must_differ",
            "標題欄位與描述欄位必須不同。",
            field_errors={"description_column": ["不可與 title_column 相同。"]},
        )

    active_assignments = [
        (assignment.video_id, normalize_text(assignment.person))
        for assignment in payload.assignments
        if normalize_text(assignment.person) and normalize_text(assignment.person) != "不編輯"
    ]
    if not active_assignments:
        raise http_error(400, "no_active_assignments", "目前沒有任何影片被指定人物，請先選擇人物後再執行。")
    try:
        headers = get_sheet_headers(sheet_creds, spreadsheet_id, payload.worksheet_name)
        required_headers = ["所屬團體", "人", title_column, description_column]
        missing_headers = [header for header in required_headers if header not in headers]
        if missing_headers:
            raise http_error(
                400,
                "sheet_columns_missing",
                f"工作表「{payload.worksheet_name}」缺少必要欄位，請重新整理後再試。",
                field_errors={"worksheet_name": [f"缺少欄位：{', '.join(missing_headers)}。"]},
            )
        sheet_rows = get_all_rows_for_sheet(sheet_creds, spreadsheet_id, payload.worksheet_name)
        if not sheet_rows:
            raise http_error(400, "sheet_rows_empty", f"工作表「{payload.worksheet_name}」沒有可用資料列。")

        sheet_state = sheet_snapshot(spreadsheet_id, payload.worksheet_name, headers, sheet_rows)
        if playlist_id:
            initial_playlist_state = playlist_snapshot(fetch_playlist_items(youtube_context, playlist_id))
        else:
            initial_playlist_state = playlist_snapshot(
                [{"id": "", "contentDetails": {"videoId": video_id}} for video_id, _person in active_assignments]
            )
        requested_video_ids = [video_id for video_id, _person in active_assignments]
        if playlist_id and not set(requested_video_ids).issubset(set(initial_playlist_state["video_ids"])):
            raise _stale_preview_exception()

        prepared: list[dict] = []
        for video_id, person in active_assignments:
            matches = [row for row in sheet_rows if matches_team_person(row, normalized_team, person)]
            row, match_error = resolve_assignment_row(matches, title_column, description_column)
            if match_error == "not_found":
                prepared.append(
                    {
                        "video_id": video_id,
                        "person": person,
                        "status": "skipped",
                        "reason": f"找不到團體 {normalized_team} 的選項 {person} 資料",
                    }
                )
            elif match_error == "conflict":
                prepared.append(
                    {
                        "video_id": video_id,
                        "person": person,
                        "status": "skipped",
                        "reason": f"團體 {normalized_team} 的選項 {person} 有多筆且標題或描述內容不同",
                    }
                )
            else:
                new_title = normalize_text(row.get(title_column) or "")
                new_description = str(row.get(description_column) or "")
                if not new_title:
                    prepared.append(
                        {
                            "video_id": video_id,
                            "person": person,
                            "status": "skipped",
                            "reason": f"工作表的 {title_column} 為空白",
                        }
                    )
                else:
                    prepared.append(
                        {
                            "video_id": video_id,
                            "person": person,
                            "status": "pending",
                            "new_title": new_title,
                            "new_description": new_description,
                        }
                    )

        details_map = {
            item["id"]: item
            for item in fetch_video_details(youtube_context, [item["video_id"] for item in prepared])
            if item.get("id")
        }
        request_state = input_digest(
            {
                "spreadsheet_id": spreadsheet_id,
                "worksheet_name": payload.worksheet_name,
                "title_column": title_column,
                "description_column": description_column,
                "team": normalized_team,
                "assignments": active_assignments,
                "video_snapshot": video_snapshot_digest(details_map, requested_video_ids),
            }
        )
        if not payload.preview_token or not verify_preview_token(
            payload.preview_token,
            owner_sub=youtube_context.owner_sub,
            youtube_slot=youtube_context.slot,
            operation="youtube.batch_update",
            playlist_id=playlist_id,
            playlist=initial_playlist_state,
            sheet=sheet_state,
            request_digest=request_state,
        ):
            raise _stale_preview_exception()
        pending_video_ids = [item["video_id"] for item in prepared if item["status"] == "pending"]
        if pending_video_ids:
            current_headers = get_sheet_headers(sheet_creds, spreadsheet_id, payload.worksheet_name)
            current_rows = get_all_rows_for_sheet(sheet_creds, spreadsheet_id, payload.worksheet_name)
            if sheet_snapshot(spreadsheet_id, payload.worksheet_name, current_headers, current_rows) != sheet_state:
                raise _stale_preview_exception()
            if playlist_id:
                current_playlist_items = fetch_playlist_items(youtube_context, playlist_id)
                if playlist_snapshot(current_playlist_items) != initial_playlist_state:
                    raise _stale_preview_exception()
                if not set(requested_video_ids).issubset(set(playlist_snapshot(current_playlist_items)["video_ids"])):
                    raise _stale_preview_exception()
            else:
                current_details = fetch_video_details(youtube_context, pending_video_ids)
                if {item.get("id") for item in current_details if item.get("id")} != {
                    item_id for item_id in details_map if item_id in pending_video_ids
                }:
                    raise _stale_preview_exception()
        results: list[dict] = []
        quota_error: Optional[YouTubeQuotaUnavailable] = None
        for item in prepared:
            detail = details_map.get(item["video_id"])
            missing_video = item["status"] == "pending" and not detail
            skipped = item["status"] != "pending" or missing_video
            snippet = (detail or {}).get("snippet") or {}
            base_result = {
                "video_id": item["video_id"],
                "youtube_slot": youtube_context.slot,
                "title": snippet.get("title") or item["video_id"],
                "description": snippet.get("description") or "",
                "thumbnail_url": _youtube_thumbnail(detail or {}, item["video_id"]),
                "person": item["person"],
            }
            if skipped:
                skipped_error = None
                if missing_video:
                    skipped_error = http_error(
                        404,
                        "youtube_not_found",
                        "找不到指定的 YouTube 影片，或目前帳號無權存取。",
                        youtube_slot=youtube_context.slot,
                    ).detail
                results.append(
                    {
                        **base_result,
                        "status": "skipped",
                        "reason": item.get("reason") or "YouTube 找不到此影片或目前帳號無權存取。",
                        "error": skipped_error,
                    }
                )
                continue
            if quota_error is not None:
                results.append(
                    {
                        **base_result,
                        "status": "not_attempted",
                        "reason": quota_error.user_message,
                        "error": quota_error.to_dict(),
                    }
                )
                continue
            try:
                update_single_video_metadata(
                    youtube_context,
                    item["video_id"],
                    str(item.get("new_title") or ""),
                    str(item.get("new_description") or ""),
                    current_snippet=snippet,
                )
                results.append(
                    {
                        **base_result,
                        "title": item.get("new_title") or base_result["title"],
                        "description": item.get("new_description") or "",
                        "status": "succeeded",
                        "reason": None,
                    }
                )
            except YouTubeQuotaUnavailable as exc:
                quota_error = exc
                results.append(
                    {**base_result, "status": "not_attempted", "reason": exc.user_message, "error": exc.to_dict()}
                )
            except Exception as exc:
                item_error = _workflow_error_detail(exc, slot=youtube_context.slot)
                results.append(
                    {
                        **base_result,
                        "status": "failed",
                        "reason": item_error["message"],
                        "error": item_error,
                    }
                )
        return _direct_workflow_response(
            "youtube.metadata_update",
            results,
            quota_error=quota_error,
            slot=youtube_context.slot,
            context=youtube_context,
        )
    except YouTubeQuotaUnavailable as exc:
        raise _quota_http_exception(exc) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Batch metadata update failed for slot %s: %s", youtube_context.slot, type(exc).__name__)
        raise map_youtube_error(
            exc, method="videos.update", youtube_slot=youtube_context.slot
        ).to_http_exception() from exc


@router.post("/publish-and-cleanup")
def run_publish_and_cleanup(
    payload: PublishCleanupInput,
    creds: YouTubeRequestContext = Depends(require_youtube_context),
    _rate_limit: None = Depends(enforce_workflow_rate_limit),
):
    """Snapshot To-Post, sort oldest-first, then publish each video synchronously."""
    youtube_context = creds

    playlist_id = _resolve_playlist_id(youtube_context, payload.playlist_id)
    if not playlist_id:
        raise http_error(400, "playlist_required", "請提供播放清單 ID。")
    try:
        raw_items = fetch_playlist_items(youtube_context, playlist_id)
        initial_playlist_state = playlist_snapshot(raw_items)
        _verify_playlist_preview_token(
            youtube_context,
            playlist_id,
            initial_playlist_state,
            payload.preview_token,
        )
        if not raw_items:
            response = _direct_workflow_response(
                "youtube.publish_cleanup", [], slot=youtube_context.slot, context=youtube_context
            )
            response["message"] = "To-Post 播放清單目前沒有影片。"
            return response
        playlist_item_map: dict[str, str] = {}
        api_order: list[str] = []
        title_map: dict[str, str] = {}
        for item in raw_items:
            video_id = item.get("contentDetails", {}).get("videoId")
            if not video_id or video_id in playlist_item_map:
                continue
            playlist_item_map[video_id] = item.get("id")
            api_order.append(video_id)
            title_map[video_id] = item.get("snippet", {}).get("title", "")
        details_map = {item["id"]: item for item in fetch_video_details(youtube_context, api_order) if item.get("id")}
        original_positions = {video_id: index for index, video_id in enumerate(api_order)}
        ordered_ids = sorted(
            api_order, key=lambda video_id: upload_time_sort_key(video_id, details_map, original_positions)
        )
        # The preview may have been displayed for minutes. Re-read the
        # playlist immediately before the first write and fail closed if the
        # slot, item IDs, order, or video collection changed.
        latest_playlist_items = fetch_playlist_items(youtube_context, playlist_id)
        if playlist_snapshot(latest_playlist_items) != initial_playlist_state:
            raise _stale_preview_exception()
        results: list[dict] = []
        quota_error: Optional[YouTubeQuotaUnavailable] = None
        stopped_reason: Optional[str] = None
        for video_id in ordered_ids:
            detail = details_map.get(video_id)
            missing = detail is None
            snippet = (detail or {}).get("snippet") or {}
            base_result = {
                "video_id": video_id,
                "youtube_slot": youtube_context.slot,
                "title": title_map.get(video_id) or snippet.get("title") or video_id,
                "description": snippet.get("description") or "",
                "thumbnail_url": _youtube_thumbnail(detail or {}, video_id),
            }
            if missing:
                results.append(
                    {
                        **base_result,
                        "status": "skipped",
                        "reason": "YouTube 找不到此影片或目前帳號無權存取。",
                        "error": http_error(
                            404,
                            "youtube_not_found",
                            "找不到指定的 YouTube 影片，或目前帳號無權存取。",
                            youtube_slot=youtube_context.slot,
                        ).detail,
                    }
                )
                continue
            if quota_error is not None:
                results.append(
                    {
                        **base_result,
                        "status": "not_attempted",
                        "reason": quota_error.user_message,
                        "error": quota_error.to_dict(),
                    }
                )
                continue
            if stopped_reason is not None:
                results.append({**base_result, "status": "not_attempted", "reason": stopped_reason})
                continue

            try:
                set_video_public(youtube_context, video_id, current_video=detail)
            except YouTubeQuotaUnavailable as exc:
                quota_error = exc
                results.append(
                    {**base_result, "status": "not_attempted", "reason": exc.user_message, "error": exc.to_dict()}
                )
                continue
            except Exception as exc:
                item_error = _workflow_error_detail(exc, slot=youtube_context.slot)
                stopped_reason = f"前一支影片無法設為公開，後續影片未執行：{item_error['message']}"
                results.append(
                    {
                        **base_result,
                        "status": "failed",
                        "reason": item_error["message"],
                        "error": item_error,
                    }
                )
                continue

            try:
                remove_playlist_item(youtube_context, playlist_item_map.get(video_id))
                results.append({**base_result, "status": "succeeded", "reason": None})
            except YouTubeQuotaUnavailable as exc:
                quota_error = exc
                results.append(
                    {
                        **base_result,
                        "status": "succeeded_with_warnings",
                        "reason": f"影片已設為公開，但尚未移出 To-Post：{exc.user_message}",
                        "error": exc.to_dict(),
                    }
                )
            except Exception as exc:
                item_error = _workflow_error_detail(exc, slot=youtube_context.slot)
                results.append(
                    {
                        **base_result,
                        "status": "succeeded_with_warnings",
                        "reason": f"影片已設為公開，但移出 To-Post 失敗：{item_error['message']}",
                        "error": item_error,
                    }
                )
        response = _direct_workflow_response(
            "youtube.publish_cleanup",
            results,
            quota_error=quota_error,
            slot=youtube_context.slot,
            context=youtube_context,
        )
        response.update({"playlist_id": playlist_id, "sort_order": "published_at_ascending"})
        return response
    except YouTubeQuotaUnavailable as exc:
        raise _quota_http_exception(exc) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Publish cleanup workflow failed for slot %s: %s", youtube_context.slot, type(exc).__name__)
        raise map_youtube_error(
            exc, method="playlistItems.delete", youtube_slot=youtube_context.slot
        ).to_http_exception() from exc
