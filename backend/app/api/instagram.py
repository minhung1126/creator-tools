import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from threading import RLock
from typing import List, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse
from google.oauth2.credentials import Credentials
from pydantic import BaseModel, Field

from backend.app.core.config import settings
from backend.app.core.credential_store import credential_store
from backend.app.core.dependencies import require_credentials
from backend.app.core.runtime_config import runtime_config
from backend.app.core.security import (
    INSTAGRAM_OAUTH_STATE_SALT,
    sign_timed_data,
    verify_timed_data,
)
from backend.app.core.task_repository import task_repository
from backend.app.services.drive_service import (
    extract_drive_folder_id,
    get_drive_video_thumbnail,
    list_drive_videos,
    move_drive_file_to_folder,
)
from backend.app.services.instagram_api_usage_service import instagram_api_usage_tracker
from backend.app.services.instagram_oauth_service import (
    REQUIRED_SCOPES,
    build_authorization_url,
    exchange_authorization_code,
    exchange_long_lived_token,
    normalize_permissions,
    refresh_long_lived_token,
)
from backend.app.services.instagram_publish_service import (
    prepare_job,
)
from backend.app.services.instagram_service import InstagramClient
from backend.app.services.r2_service import R2Config, test_r2_connection
from backend.app.services.sheets_service import normalize_text
from backend.app.services.task_queue import task_queue

router = APIRouter(prefix="/instagram", tags=["Instagram Reels"])
logger = logging.getLogger(__name__)
OAUTH_FLOW_COOKIE = "creator_tools_instagram_oauth_flow"
OAUTH_FLOW_MAX_AGE = 10 * 60
TOKEN_REFRESH_WINDOW = timedelta(days=7)
_instagram_refresh_lock = RLock()


class Assignment(BaseModel):
    file_id: str
    person: str


class DriveInput(BaseModel):
    folder_url_or_id: str = ""


class PublishInput(BaseModel):
    drive_folder_url_or_id: str = ""
    spreadsheet_url_or_id: str = ""
    worksheet_name: str
    caption_column: str
    team: str
    share_to_feed: bool = True
    assignments: List[Assignment] = Field(default_factory=list)


class InstagramSettings(BaseModel):
    drive_folder_id: str = ""
    spreadsheet_id: str = ""
    r2_account_id: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket_name: str = ""
    r2_public_base_url: str = ""


def cfg(key: str):
    return runtime_config.get(key, "")


def session_fingerprint(request: Request) -> str:
    session_cookie = request.cookies.get("creator_tools_session", "")
    return hashlib.sha256(session_cookie.encode("utf-8")).hexdigest() if session_cookie else ""


def redirect_with_instagram_result(success: bool, message: str = "") -> RedirectResponse:
    if success:
        url = f"{settings.frontend_url}/#instagram_auth_success=1"
    else:
        url = f"{settings.frontend_url}/#instagram_auth_error={quote(message, safe='')}"
    response = RedirectResponse(url=url)
    response.delete_cookie(OAUTH_FLOW_COOKIE)
    return response


def parse_expiration(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def refresh_connection(*, force: bool = True) -> dict:
    """Refresh the long-lived Instagram token once per process at a time."""
    with _instagram_refresh_lock:
        connection = credential_store.get_instagram_public()
        token = credential_store.get_instagram_token()
        if not connection or not token:
            raise RuntimeError("Instagram 尚未連線")

        if not force:
            expiration = parse_expiration(connection.get("token_expires_at"))
            if expiration and expiration - datetime.now(timezone.utc) > TOKEN_REFRESH_WINDOW:
                return connection

        try:
            refreshed = refresh_long_lived_token(token)
            credential_store.update_instagram_token(refreshed["access_token"], refreshed.get("expires_in"))
        except Exception as exc:
            requires_reauthorization = any(marker in str(exc).lower() for marker in ("expired", "invalid", "oauth"))
            credential_store.mark_instagram_refresh_failed(str(exc) or type(exc).__name__, requires_reauthorization)
            logger.error("Instagram token refresh failed: %s", type(exc).__name__)
            raise

        # Profile refresh is useful metadata, but must not make a successfully
        # refreshed access token look unusable when the profile endpoint has a
        # transient failure.
        try:
            client = InstagramClient(
                connection["instagram_user_id"],
                refreshed["access_token"],
                settings.instagram_api_version,
            )
            profile = client.profile()
            credential_store.update_instagram_profile(profile.get("username", ""), profile.get("account_type", ""))
        except Exception as exc:
            logger.warning("Instagram profile refresh failed after token refresh: %s", type(exc).__name__)
        return credential_store.get_instagram_public() or {}


def refresh_token_for_api_request() -> str:
    refresh_connection(force=True)
    return credential_store.get_instagram_token() or ""


def get_connected_client(refresh_if_needed: bool = True) -> InstagramClient:
    connection = credential_store.get_instagram_public()
    if not connection:
        raise RuntimeError("Instagram 尚未連線，請先在 Instagram 設定頁完成授權")
    expiration = parse_expiration(connection.get("token_expires_at"))
    now = datetime.now(timezone.utc)
    if expiration and expiration <= now:
        raise RuntimeError("Instagram Access Token 已過期，請重新連線")
    if refresh_if_needed and expiration and expiration - now <= TOKEN_REFRESH_WINDOW:
        connection = refresh_connection(force=False)
    token = credential_store.get_instagram_token()
    if not token:
        raise RuntimeError("找不到已儲存的 Instagram Access Token，請重新連線")
    return InstagramClient(
        connection["instagram_user_id"],
        token,
        settings.instagram_api_version,
        on_token_refresh=refresh_token_for_api_request,
    )


def get_r2() -> R2Config:
    secret = credential_store.get_secret("r2_secret_access_key")
    values = {
        "account_id": cfg("r2_account_id"),
        "access_key_id": cfg("r2_access_key_id"),
        "secret_access_key": secret,
        "bucket_name": cfg("r2_bucket_name"),
        "public_base_url": cfg("r2_public_base_url"),
    }
    if not all(values.values()):
        raise RuntimeError("Cloudflare R2 設定不完整")
    return R2Config(**values)


def _unified_instagram_batch_specs(job: dict) -> list[dict]:
    """Translate the existing preparation result into one SQLite task/video."""

    specs = []
    seen_file_ids: set[str] = set()
    for index, item in enumerate(job.get("items", []), start=1):
        checkpoint = {
            key: item.get(key)
            for key in (
                "public_url",
                "object_key",
                "creation_id",
                "media_id",
                "drive_moved",
                "drive_moved_at",
                "published_folder_id",
                "drive_move_error",
                "r2_deleted",
                "r2_delete_error",
                "preflight",
            )
            if key in item
        }
        status = item.get("status") or "queued"
        duplicate_in_batch = bool(item.get("file_id") and item.get("file_id") in seen_file_ids)
        if item.get("file_id"):
            seen_file_ids.add(item.get("file_id"))
        if duplicate_in_batch and status == "queued":
            status = "skipped"
            item["error"] = "同一支影片在本次批次中重複指定，已略過。"
        if status not in {"queued", "skipped"}:
            status = "queued"
        specs.append(
            {
                "platform": "instagram",
                "operation": "instagram.reels_publish",
                "queue_lane": "instagram",
                "sequence_in_batch": int(item.get("sequence") or index),
                "video_id": item.get("file_id"),
                "video_title": item.get("file_name"),
                "status": status,
                "stage": "skipped" if status == "skipped" else "queued",
                "stage_label": item.get("stage_label"),
                "progress_percent": item.get("progress_percent", 100 if status == "skipped" else 0),
                "retryable": False if status == "skipped" else True,
                "error": item.get("error"),
                "payload": {
                    "file_id": item.get("file_id"),
                    "file_name": item.get("file_name"),
                    "person": item.get("person"),
                    "caption": item.get("caption"),
                    "source_folder_id": job.get("source_folder_id"),
                    "folder": job.get("folder"),
                    "published_folder_id": item.get("published_folder_id") or job.get("published_folder_id"),
                    "share_to_feed": job.get("share_to_feed", True),
                },
                "checkpoint": checkpoint,
            }
        )
    return specs


def _accepted_publish_response(batch_result: dict) -> dict:
    batch_id = batch_result["batch"]["id"]
    tasks = batch_result.get("tasks", [])
    return {
        "accepted": True,
        "batch_id": batch_id,
        "total_count": len(tasks),
        "task_ids": [task["id"] for task in tasks],
        "batch": task_repository.get_batch(batch_id),
    }


@router.get("/auth/url")
def get_instagram_auth_url(request: Request, response: Response, creds: Credentials = Depends(require_credentials)):
    del creds
    if not settings.instagram_app_id or not settings.instagram_app_secret:
        raise HTTPException(status_code=400, detail="尚未設定 INSTAGRAM_APP_ID 與 INSTAGRAM_APP_SECRET")
    fingerprint = session_fingerprint(request)
    if not fingerprint:
        raise HTTPException(status_code=401, detail="Google 登入 Session 已失效，請重新登入")
    state = secrets.token_urlsafe(32)
    response.set_cookie(
        key=OAUTH_FLOW_COOKIE,
        value=sign_timed_data(
            {
                "state": state,
                "session_fingerprint": fingerprint,
                "redirect_uri": settings.get_instagram_redirect_uri(),
            },
            salt=INSTAGRAM_OAUTH_STATE_SALT,
        ),
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=OAUTH_FLOW_MAX_AGE,
    )
    return {
        "auth_url": build_authorization_url(settings.instagram_app_id, settings.get_instagram_redirect_uri(), state)
    }


@router.get("/auth/callback")
def instagram_oauth_callback(
    request: Request,
    code: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    error: Optional[str] = Query(None),
    error_description: Optional[str] = Query(None),
):
    if error:
        logger.info("Instagram OAuth provider returned an error: %s", error)
        return redirect_with_instagram_result(False, "Instagram OAuth 授權遭拒，請重新嘗試。")
    if not code or not state:
        return redirect_with_instagram_result(False, "Instagram OAuth callback 缺少 code 或 state")
    cookie = request.cookies.get(OAUTH_FLOW_COOKIE)
    flow = verify_timed_data(cookie, salt=INSTAGRAM_OAUTH_STATE_SALT, max_age=OAUTH_FLOW_MAX_AGE) if cookie else None
    if not flow:
        return redirect_with_instagram_result(False, "Instagram 授權 Session 已逾時，請重新連線")
    if not flow.get("state") or not secrets.compare_digest(state, flow["state"]):
        return redirect_with_instagram_result(False, "Instagram OAuth state 驗證失敗")
    current_fingerprint = session_fingerprint(request)
    if not current_fingerprint or not secrets.compare_digest(current_fingerprint, flow.get("session_fingerprint", "")):
        return redirect_with_instagram_result(False, "Google 登入 Session 已變更，請重新登入後再連接 Instagram")
    try:
        short_lived = exchange_authorization_code(
            app_id=settings.instagram_app_id,
            app_secret=settings.instagram_app_secret,
            redirect_uri=flow.get("redirect_uri") or settings.get_instagram_redirect_uri(),
            code=code,
        )
        long_lived = exchange_long_lived_token(short_lived["access_token"], settings.instagram_app_secret)
        user_id = short_lived.get("user_id") or short_lived.get("id")
        token = long_lived["access_token"]
        profile = InstagramClient(str(user_id or "me"), token, settings.instagram_api_version).profile()
        user_id = profile.get("id") or user_id
        if not user_id:
            raise RuntimeError("Instagram 未回傳帳號 ID")
        account_type = str(profile.get("account_type") or "").upper()
        if account_type and account_type not in {"BUSINESS", "CREATOR", "MEDIA_CREATOR"}:
            raise RuntimeError("此帳號不是可發布內容的 Instagram 專業帳號")
        permissions = normalize_permissions(short_lived.get("permissions") or long_lived.get("permissions"))
        missing = [scope for scope in REQUIRED_SCOPES if permissions and scope not in permissions]
        if missing:
            raise RuntimeError(f"Instagram 未授予必要權限：{', '.join(missing)}")
        credential_store.save_instagram_connection(
            access_token=token,
            user_id=str(user_id),
            username=profile.get("username", ""),
            account_type=account_type,
            granted_scopes=permissions,
            expires_in=long_lived.get("expires_in"),
            permissions_verified=bool(permissions),
        )
        return redirect_with_instagram_result(True)
    except Exception as exc:
        logger.error("Instagram OAuth callback failed: %s", type(exc).__name__, exc_info=True)
        return redirect_with_instagram_result(False, "Instagram OAuth 登入失敗，請重新嘗試。")


@router.get("/auth/status")
def instagram_auth_status(creds: Credentials = Depends(require_credentials)):
    del creds
    connection = credential_store.get_instagram_public()
    expiration = parse_expiration(connection.get("token_expires_at")) if connection else None
    now = datetime.now(timezone.utc)
    if connection and not (expiration and expiration <= now):
        try:
            # Reading the status page also performs the normal proactive
            # refresh, so a token does not sit in the UI as "expires soon".
            get_connected_client(refresh_if_needed=True)
            connection = credential_store.get_instagram_public()
            expiration = parse_expiration(connection.get("token_expires_at")) if connection else None
        except Exception as exc:
            logger.warning("Instagram status refresh check failed: %s", type(exc).__name__)
    return {
        "app_configured": bool(settings.instagram_app_id and settings.instagram_app_secret),
        "redirect_uri": settings.get_instagram_redirect_uri(),
        "required_scopes": list(REQUIRED_SCOPES),
        "connected": bool(connection),
        "expired": bool(expiration and expiration <= now),
        "expires_soon": bool(expiration and now < expiration <= now + TOKEN_REFRESH_WINDOW),
        "account": connection,
    }


@router.post("/auth/refresh")
def refresh_instagram_auth(creds: Credentials = Depends(require_credentials)):
    del creds
    try:
        return {"connected": True, "account": refresh_connection()}
    except Exception as exc:
        logger.error("Instagram token refresh failed: %s", type(exc).__name__, exc_info=True)
        raise HTTPException(status_code=400, detail="Instagram Token 更新失敗，請重新授權。") from exc


@router.delete("/auth/connection")
def disconnect_instagram(creds: Credentials = Depends(require_credentials)):
    del creds
    credential_store.clear_instagram()
    return {"connected": False, "message": "已刪除本機儲存的 Instagram 授權"}


@router.get("/settings")
def get_instagram_settings(creds: Credentials = Depends(require_credentials)):
    del creds
    return {
        "drive_folder_id": cfg("instagram_drive_folder_id"),
        "spreadsheet_id": cfg("instagram_spreadsheet_id"),
        "instagram_api_version": settings.instagram_api_version,
        "r2_account_id": cfg("r2_account_id"),
        "r2_access_key_id": cfg("r2_access_key_id"),
        "r2_bucket_name": cfg("r2_bucket_name"),
        "r2_public_base_url": cfg("r2_public_base_url"),
        "r2_secret_access_key_configured": credential_store.has_secret("r2_secret_access_key"),
    }


@router.get("/api-usage")
def get_instagram_api_usage(creds: Credentials = Depends(require_credentials)):
    """Return locally observed Meta usage without making another Instagram request."""

    del creds
    return instagram_api_usage_tracker.get_usage()


@router.put("/settings")
def save_instagram_settings(payload: InstagramSettings, creds: Credentials = Depends(require_credentials)):
    del creds
    values = payload.model_dump()
    if values.pop("r2_secret_access_key", "").strip():
        credential_store.set_secret("r2_secret_access_key", payload.r2_secret_access_key.strip())
    runtime_config.update(
        {
            "instagram_drive_folder_id": values["drive_folder_id"].strip(),
            "instagram_spreadsheet_id": values["spreadsheet_id"].strip(),
            "r2_account_id": values["r2_account_id"].strip(),
            "r2_access_key_id": values["r2_access_key_id"].strip(),
            "r2_bucket_name": values["r2_bucket_name"].strip(),
            "r2_public_base_url": values["r2_public_base_url"].strip().rstrip("/"),
        }
    )
    return get_instagram_settings()


@router.get("/connection-status")
def connection_status(creds: Credentials = Depends(require_credentials)):
    del creds
    instagram_result = {"ok": False, "profile": None, "error": None}
    r2_result = {"ok": False, "error": None}
    try:
        profile = get_connected_client(refresh_if_needed=True).profile()
        credential_store.update_instagram_profile(profile.get("username", ""), profile.get("account_type", ""))
        instagram_result.update({"ok": True, "profile": profile})
    except Exception as exc:
        logger.error("Instagram connection check failed: %s", type(exc).__name__, exc_info=True)
        instagram_result["error"] = "Instagram 連線驗證失敗"
    try:
        test_r2_connection(get_r2())
        r2_result["ok"] = True
    except Exception as exc:
        logger.error("R2 connection check failed: %s", type(exc).__name__, exc_info=True)
        r2_result["error"] = "R2 連線驗證失敗"
    return {"ok": instagram_result["ok"] and r2_result["ok"], "instagram": instagram_result, "r2": r2_result}


@router.post("/r2/test")
def test_r2(creds: Credentials = Depends(require_credentials)):
    del creds
    try:
        return test_r2_connection(get_r2())
    except Exception as exc:
        logger.error("R2 test failed: %s", type(exc).__name__, exc_info=True)
        raise HTTPException(status_code=400, detail="R2 連線測試失敗，請檢查設定。") from exc


@router.post("/drive-videos")
def drive_videos(payload: DriveInput, creds: Credentials = Depends(require_credentials)):
    folder = payload.folder_url_or_id or cfg("instagram_drive_folder_id")
    if not folder:
        raise HTTPException(status_code=400, detail="請輸入 Google Drive 資料夾")
    try:
        source_folder_id = extract_drive_folder_id(folder)
        videos = list_drive_videos(creds, folder)
        for video in videos:
            thumbnail_link = video.pop("thumbnail_link", "")
            if video.get("id") and thumbnail_link:
                thumbnail_endpoint = f"/api/v1/instagram/drive-videos/{quote(video['id'], safe='')}/thumbnail"
                video["thumbnail_url"] = f"{thumbnail_endpoint}?quality=preview"
                video["thumbnail_full_url"] = f"{thumbnail_endpoint}?quality=source"
            else:
                video["thumbnail_url"] = ""
                video["thumbnail_full_url"] = ""
            record = task_repository.find_instagram_record(source_folder_id, video.get("id", ""), published_only=True)
            if record:
                record = {"job_id": record.get("batch_id"), "item": record.get("item") or {}}
            published_item = (record or {}).get("item") or {}
            video["already_published"] = bool(record)
            video["published_job_id"] = (record or {}).get("job_id")
            video["published_media_id"] = published_item.get("media_id")
        return {"videos": videos, "total": len(videos), "sort_order": "name_ascending"}
    except Exception as exc:
        logger.error("Failed to list Drive videos: %s", type(exc).__name__, exc_info=True)
        raise HTTPException(status_code=500, detail="讀取 Drive 影片失敗，請稍後再試。") from exc


@router.get("/publish-history")
def get_publish_history(creds: Credentials = Depends(require_credentials)):
    del creds
    records = task_repository.list_instagram_history()
    return {"records": records, "total": len(records)}


@router.delete("/publish-history/{job_id}/{file_id}")
def delete_publish_history(job_id: str, file_id: str, creds: Credentials = Depends(require_credentials)):
    record = next(
        (
            item
            for item in task_repository.list_instagram_history()
            if item.get("job_id") == job_id and item.get("file_id") == file_id
        ),
        None,
    )
    if not record:
        raise HTTPException(status_code=404, detail="找不到 Instagram 歷史紀錄")

    drive_restored = False
    if record.get("drive_moved"):
        published_folder_id = record.get("published_folder_id")
        source_folder_id = record.get("source_folder_id")
        if not published_folder_id or not source_folder_id:
            raise HTTPException(status_code=409, detail="找不到 Drive 資料夾資訊，請先手動將影片移回來源資料夾。")
        try:
            move_drive_file_to_folder(
                creds,
                file_id,
                extract_drive_folder_id(published_folder_id),
                extract_drive_folder_id(source_folder_id),
            )
            drive_restored = True
        except Exception as exc:
            logger.error("Failed to restore Drive file %s from Instagram history: %s", file_id, type(exc).__name__)
            raise HTTPException(status_code=502, detail="影片無法移回 Drive 來源資料夾，歷史紀錄尚未刪除。") from exc

    deleted = task_repository.release_instagram_history(job_id, file_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="找不到 Instagram 歷史紀錄")
    return {
        "deleted": deleted,
        "drive_restored": drive_restored,
        "message": "歷史紀錄已刪除，可重新讀取 Drive 影片並上傳。",
    }


@router.get("/drive-videos/{file_id}/thumbnail")
def drive_video_thumbnail(
    file_id: str,
    creds: Credentials = Depends(require_credentials),
    quality: str = "preview",
):
    if quality not in {"preview", "source"}:
        raise HTTPException(status_code=400, detail="無效的縮圖品質選項")
    try:
        thumbnail = get_drive_video_thumbnail(creds, file_id, prefer_source=quality == "source")
    except Exception as exc:
        logger.warning("Failed to fetch Drive thumbnail for %s: %s", file_id, type(exc).__name__)
        raise HTTPException(status_code=404, detail="找不到影片縮圖") from exc
    if not thumbnail:
        raise HTTPException(status_code=404, detail="此影片沒有可用縮圖")
    content, media_type = thumbnail
    return Response(
        content=content,
        media_type=media_type,
        headers={"Cache-Control": "private, max-age=86400" if quality == "source" else "private, max-age=3600"},
    )


@router.post("/publish-jobs", status_code=202)
def create_publish_job(payload: PublishInput, creds: Credentials = Depends(require_credentials)):
    spreadsheet = payload.spreadsheet_url_or_id or cfg("instagram_spreadsheet_id")
    folder = payload.drive_folder_url_or_id or cfg("instagram_drive_folder_id")
    if not spreadsheet or not folder:
        raise HTTPException(status_code=400, detail="Google Sheet 與 Drive 資料夾皆為必填")
    if not any(normalize_text(item.person) for item in payload.assignments):
        raise HTTPException(status_code=400, detail="請至少為一支影片指定人物")
    try:
        job = prepare_job(
            credentials=creds,
            spreadsheet=spreadsheet,
            folder=folder,
            worksheet_name=payload.worksheet_name,
            caption_column=payload.caption_column,
            team=payload.team,
            assignments=[item.model_dump() for item in payload.assignments],
            share_to_feed=payload.share_to_feed,
        )
        batch_result = task_repository.create_batch_and_tasks(
            {
                "platform": "instagram",
                "operation": "instagram.reels_publish",
                "failure_policy": "pause_remaining_in_batch",
                "metadata": {
                    "worksheet_name": job.get("worksheet_name"),
                    "caption_column": job.get("caption_column"),
                    "team": job.get("team"),
                    "source_folder_id": job.get("source_folder_id"),
                    "share_to_feed": job.get("share_to_feed", True),
                },
            },
            _unified_instagram_batch_specs(job),
        )
        batch_id = batch_result["batch"]["id"]
        if any(task.get("status") == "queued" for task in batch_result.get("tasks", [])):
            task_queue.submit(batch_id)
        return _accepted_publish_response(batch_result)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to create Instagram publish job: %s", type(exc).__name__, exc_info=True)
        raise HTTPException(status_code=500, detail="建立 Instagram 發布工作失敗，請稍後再試。") from exc


@router.post("/publish-jobs/{job_id}/stop-blocking-jobs")
def stop_blocking_publish_jobs(job_id: str, creds: Credentials = Depends(require_credentials)):
    """Stop older unfinished tasks that caused items in this batch to be skipped."""

    del creds
    batch = task_repository.get_batch_internal(job_id)
    if not batch or batch.get("platform") != "instagram":
        raise HTTPException(status_code=404, detail="找不到 Instagram 發布工作")

    blocking_items = [
        task
        for task in batch.get("tasks", [])
        if task.get("status") == "skipped" and "已有未完成的發布工作" in str(task.get("error") or "")
    ]
    if not blocking_items:
        raise HTTPException(status_code=409, detail="此批次沒有被舊工作占用的影片")

    source_folder_id = str((batch.get("metadata") or {}).get("source_folder_id") or "")
    result = task_repository.cancel_instagram_reservations(
        source_folder_id,
        [task.get("video_id") for task in blocking_items],
        exclude_batch_id=job_id,
    )
    task_queue.wake()
    result.update(
        {
            "batch_id": job_id,
            "blocked_item_count": len(blocking_items),
            "ready_to_recreate": result["cancel_requested_count"] == 0
            and result["canceled_immediately_count"] > 0,
        }
    )
    return result
