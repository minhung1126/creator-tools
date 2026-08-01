import hashlib
import mimetypes
import os
import re
import secrets
import tempfile
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
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
from backend.app.services.drive_service import download_drive_file, list_drive_videos
from backend.app.services.instagram_oauth_service import (
    REQUIRED_SCOPES,
    build_authorization_url,
    exchange_authorization_code,
    exchange_long_lived_token,
    normalize_permissions,
    refresh_long_lived_token,
)
from backend.app.services.instagram_service import InstagramClient
from backend.app.services.r2_service import R2Config, test_r2_connection, upload_public_file
from backend.app.services.sheets_service import (
    get_all_rows_for_sheet,
    get_sheet_headers,
    normalize_text,
    team_option_label,
)

router = APIRouter(prefix="/instagram", tags=["Instagram Reels"])
MAX_FILE_SIZE = 1024 * 1024 * 1024
OAUTH_FLOW_COOKIE = "creator_tools_instagram_oauth_flow"
OAUTH_FLOW_MAX_AGE = 10 * 60
TOKEN_REFRESH_WINDOW = timedelta(days=7)


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
    instagram_api_version: str = "v25.0"
    r2_account_id: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket_name: str = ""
    r2_public_base_url: str = ""


def cfg(key: str, env: str = ""):
    return runtime_config.get(key, "") or os.getenv(env or key.upper(), "")


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


def refresh_connection() -> dict:
    connection = credential_store.get_instagram_public()
    token = credential_store.get_instagram_token()
    if not connection or not token:
        raise RuntimeError("Instagram 尚未連線")
    refreshed = refresh_long_lived_token(token)
    credential_store.update_instagram_token(refreshed["access_token"], refreshed.get("expires_in"))
    client = InstagramClient(
        connection["instagram_user_id"],
        refreshed["access_token"],
        cfg("instagram_api_version", "INSTAGRAM_API_VERSION") or "v25.0",
    )
    profile = client.profile()
    credential_store.update_instagram_profile(profile.get("username", ""), profile.get("account_type", ""))
    return credential_store.get_instagram_public() or {}


def get_connected_client(refresh_if_needed: bool = True) -> InstagramClient:
    connection = credential_store.get_instagram_public()
    if not connection:
        raise RuntimeError("Instagram 尚未連線，請先在 Instagram 設定頁完成授權")
    expiration = parse_expiration(connection.get("token_expires_at"))
    now = datetime.now(timezone.utc)
    if expiration and expiration <= now:
        raise RuntimeError("Instagram Access Token 已過期，請重新連線")
    if refresh_if_needed and expiration and expiration - now <= TOKEN_REFRESH_WINDOW:
        connection = refresh_connection()
    token = credential_store.get_instagram_token()
    if not token:
        raise RuntimeError("找不到已儲存的 Instagram Access Token，請重新連線")
    return InstagramClient(
        connection["instagram_user_id"],
        token,
        cfg("instagram_api_version", "INSTAGRAM_API_VERSION") or "v25.0",
    )


def get_r2() -> R2Config:
    secret = credential_store.get_secret("r2_secret_access_key") or settings.R2_SECRET_ACCESS_KEY
    values = {
        "account_id": cfg("r2_account_id", "R2_ACCOUNT_ID"),
        "access_key_id": cfg("r2_access_key_id", "R2_ACCESS_KEY_ID"),
        "secret_access_key": secret,
        "bucket_name": cfg("r2_bucket_name", "R2_BUCKET_NAME"),
        "public_base_url": cfg("r2_public_base_url", "R2_PUBLIC_BASE_URL"),
    }
    if not all(values.values()):
        raise RuntimeError("Cloudflare R2 設定不完整")
    return R2Config(**values)


def matches(row, team: str, person: str) -> bool:
    if normalize_text(row.get("所屬團體") or "") != team:
        return False
    row_person = normalize_text(row.get("人") or "")
    return (not row_person) if person == team_option_label(team) else row_person == person


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
        value=sign_timed_data({
            "state": state,
            "session_fingerprint": fingerprint,
            "redirect_uri": settings.get_instagram_redirect_uri(),
        }, salt=INSTAGRAM_OAUTH_STATE_SALT),
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
        max_age=OAUTH_FLOW_MAX_AGE,
    )
    return {"auth_url": build_authorization_url(settings.instagram_app_id, settings.get_instagram_redirect_uri(), state)}


@router.get("/auth/callback")
def instagram_oauth_callback(
    request: Request,
    code: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    error: Optional[str] = Query(None),
    error_description: Optional[str] = Query(None),
):
    if error:
        return redirect_with_instagram_result(False, error_description or error)
    if not code or not state:
        return redirect_with_instagram_result(False, "Instagram OAuth callback 缺少 code 或 state")
    cookie = request.cookies.get(OAUTH_FLOW_COOKIE)
    flow = verify_timed_data(
        cookie, salt=INSTAGRAM_OAUTH_STATE_SALT, max_age=OAUTH_FLOW_MAX_AGE
    ) if cookie else None
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
        profile = InstagramClient(
            str(user_id or "me"), token, cfg("instagram_api_version", "INSTAGRAM_API_VERSION") or "v25.0"
        ).profile()
        user_id = profile.get("id") or user_id
        if not user_id:
            raise RuntimeError("Instagram 未回傳帳號 ID")
        account_type = str(profile.get("account_type") or "").upper()
        if account_type and account_type not in {"BUSINESS", "CREATOR", "MEDIA_CREATOR"}:
            raise RuntimeError("此帳號不是可發布內容的 Instagram 專業帳號")
        permissions = normalize_permissions(short_lived.get("permissions"))
        missing = [scope for scope in REQUIRED_SCOPES if permissions and scope not in permissions]
        if missing:
            raise RuntimeError(f"Instagram 未授予必要權限：{', '.join(missing)}")
        credential_store.save_instagram_connection(
            access_token=token,
            user_id=str(user_id),
            username=profile.get("username", ""),
            account_type=account_type,
            granted_scopes=permissions or list(REQUIRED_SCOPES),
            expires_in=long_lived.get("expires_in"),
            permissions_verified=bool(permissions),
        )
        return redirect_with_instagram_result(True)
    except Exception as exc:
        return redirect_with_instagram_result(False, str(exc))


@router.get("/auth/status")
def instagram_auth_status(creds: Credentials = Depends(require_credentials)):
    del creds
    connection = credential_store.get_instagram_public()
    expiration = parse_expiration(connection.get("token_expires_at")) if connection else None
    now = datetime.now(timezone.utc)
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
        raise HTTPException(status_code=400, detail=f"Instagram Token 更新失敗：{exc}") from exc


@router.delete("/auth/connection")
def disconnect_instagram(creds: Credentials = Depends(require_credentials)):
    del creds
    credential_store.clear_instagram()
    return {"connected": False, "message": "已刪除本機儲存的 Instagram 授權"}


@router.get("/settings")
def get_instagram_settings(creds: Credentials = Depends(require_credentials)):
    del creds
    return {
        "drive_folder_id": cfg("instagram_drive_folder_id", "DEFAULT_DRIVE_FOLDER_ID"),
        "spreadsheet_id": cfg("instagram_spreadsheet_id", "DEFAULT_SPREADSHEET_ID"),
        "instagram_api_version": cfg("instagram_api_version", "INSTAGRAM_API_VERSION") or "v25.0",
        "r2_account_id": cfg("r2_account_id", "R2_ACCOUNT_ID"),
        "r2_access_key_id": cfg("r2_access_key_id", "R2_ACCESS_KEY_ID"),
        "r2_bucket_name": cfg("r2_bucket_name", "R2_BUCKET_NAME"),
        "r2_public_base_url": cfg("r2_public_base_url", "R2_PUBLIC_BASE_URL"),
        "r2_secret_access_key_configured": bool(
            credential_store.has_secret("r2_secret_access_key") or settings.R2_SECRET_ACCESS_KEY
        ),
    }


@router.put("/settings")
def save_instagram_settings(payload: InstagramSettings, creds: Credentials = Depends(require_credentials)):
    del creds
    values = payload.model_dump()
    if values.pop("r2_secret_access_key", "").strip():
        credential_store.set_secret("r2_secret_access_key", payload.r2_secret_access_key.strip())
    runtime_config.update({
        "instagram_drive_folder_id": values["drive_folder_id"].strip(),
        "instagram_spreadsheet_id": values["spreadsheet_id"].strip(),
        "instagram_api_version": values["instagram_api_version"].strip() or "v25.0",
        "r2_account_id": values["r2_account_id"].strip(),
        "r2_access_key_id": values["r2_access_key_id"].strip(),
        "r2_bucket_name": values["r2_bucket_name"].strip(),
        "r2_public_base_url": values["r2_public_base_url"].strip().rstrip("/"),
    })
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
        instagram_result["error"] = str(exc)
    try:
        test_r2_connection(get_r2())
        r2_result["ok"] = True
    except Exception as exc:
        r2_result["error"] = str(exc)
    return {"ok": instagram_result["ok"] and r2_result["ok"], "instagram": instagram_result, "r2": r2_result}


@router.post("/r2/test")
def test_r2(creds: Credentials = Depends(require_credentials)):
    del creds
    try:
        return test_r2_connection(get_r2())
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"R2 連線測試失敗：{exc}") from exc


@router.post("/drive-videos")
def drive_videos(payload: DriveInput, creds: Credentials = Depends(require_credentials)):
    folder = payload.folder_url_or_id or cfg("instagram_drive_folder_id", "DEFAULT_DRIVE_FOLDER_ID")
    if not folder:
        raise HTTPException(status_code=400, detail="請輸入 Google Drive 資料夾")
    try:
        videos = list_drive_videos(creds, folder)
        return {"videos": videos, "total": len(videos), "sort_order": "created_time_ascending"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"讀取 Drive 影片失敗：{exc}") from exc


@router.post("/publish-reels")
def publish_reels(payload: PublishInput, creds: Credentials = Depends(require_credentials)):
    spreadsheet = payload.spreadsheet_url_or_id or cfg("instagram_spreadsheet_id", "DEFAULT_SPREADSHEET_ID")
    folder = payload.drive_folder_url_or_id or cfg("instagram_drive_folder_id", "DEFAULT_DRIVE_FOLDER_ID")
    if not spreadsheet or not folder:
        raise HTTPException(status_code=400, detail="Google Sheet 與 Drive 資料夾皆為必填")
    active = [(item.file_id, normalize_text(item.person)) for item in payload.assignments if normalize_text(item.person)]
    if not active:
        raise HTTPException(status_code=400, detail="請至少為一支影片指定人物")
    team = normalize_text(payload.team)
    caption_column = normalize_text(payload.caption_column)
    try:
        headers = get_sheet_headers(creds, spreadsheet, payload.worksheet_name)
        missing = [name for name in ("所屬團體", "人", caption_column) if name not in headers]
        if missing:
            raise HTTPException(status_code=400, detail=f"工作表缺少欄位：{', '.join(missing)}")
        rows = get_all_rows_for_sheet(creds, spreadsheet, payload.worksheet_name)
        files = list_drive_videos(creds, folder)
        file_map = {item["id"]: item for item in files}
        positions = {item["id"]: index for index, item in enumerate(files)}
        active.sort(key=lambda item: positions.get(item[0], 999999))
        prepared, results = [], []
        for file_id, person in active:
            file = file_map.get(file_id)
            if not file:
                results.append({"file_id": file_id, "person": person, "status": "skipped", "reason": "Drive 找不到影片"})
                continue
            suffix = Path(file["name"]).suffix.lower()
            if suffix not in {".mp4", ".mov"} or file["size"] > MAX_FILE_SIZE:
                results.append({"file_id": file_id, "file_name": file["name"], "person": person, "status": "skipped", "reason": "影片需為 MP4/MOV 且不超過 1 GB"})
                continue
            matching = [row for row in rows if matches(row, team, person)]
            captions = {str(row.get(caption_column) or "") for row in matching}
            caption = next(iter(captions), "")
            if len(captions) != 1 or not caption.strip():
                results.append({"file_id": file_id, "file_name": file["name"], "person": person, "status": "skipped", "reason": "找不到唯一且非空白的內文"})
                continue
            prepared.append((file, person, caption))
        client = get_connected_client(refresh_if_needed=True)
        r2 = get_r2()
        paused = False
        for index, (file, person, caption) in enumerate(prepared):
            if paused:
                results.append({"file_id": file["id"], "file_name": file["name"], "person": person, "status": "paused", "reason": "前一支影片發布失敗，流程已暫停"})
                continue
            try:
                with tempfile.TemporaryDirectory(prefix="creator-tools-instagram-") as directory:
                    local = Path(directory) / file["name"]
                    download_drive_file(creds, file["id"], local)
                    if local.stat().st_size > MAX_FILE_SIZE:
                        raise RuntimeError("下載後檔案超過 1 GB")
                    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", file["name"]).strip("-._") or "reel.mp4"
                    prefix = datetime.now(timezone.utc).strftime("instagram-reels/%Y/%m/%d")
                    object_key = f"{prefix}/{index + 1:03d}-{file['id']}-{safe_name}"
                    public_url = upload_public_file(r2, local, object_key, file["mime_type"] or mimetypes.guess_type(file["name"])[0] or "video/mp4")
                    published = client.publish_reel(public_url, caption, payload.share_to_feed)
                results.append({"file_id": file["id"], "file_name": file["name"], "person": person, "status": "published", "public_url": public_url, **published})
            except Exception as exc:
                results.append({"file_id": file["id"], "file_name": file["name"], "person": person, "status": "failed", "reason": str(exc)})
                paused = True
        counts = Counter(item["status"] for item in results)
        return {
            "results": results,
            "published_count": counts["published"],
            "skipped_count": counts["skipped"],
            "failed_count": counts["failed"],
            "paused_count": counts["paused"],
            "sort_order": "created_time_ascending",
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Instagram 發布流程失敗：{exc}") from exc
