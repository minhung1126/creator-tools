import json
import mimetypes
import os
import re
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from google.oauth2.credentials import Credentials
from pydantic import BaseModel, Field

from backend.app.core.dependencies import require_credentials
from backend.app.core.runtime_config import runtime_config
from backend.app.services.drive_service import download_drive_file, list_drive_videos
from backend.app.services.instagram_service import InstagramClient
from backend.app.services.r2_service import R2Config, upload_public_file
from backend.app.services.sheets_service import get_all_rows_for_sheet, get_sheet_headers, normalize_text, team_option_label

router = APIRouter(prefix="/instagram", tags=["Instagram Reels"])
MAX_FILE_SIZE = 1024 * 1024 * 1024


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
    instagram_user_id: str = ""
    instagram_access_token: str = ""
    instagram_api_version: str = "v25.0"
    r2_account_id: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket_name: str = ""
    r2_public_base_url: str = ""


def cfg(key: str, env: str = ""):
    return runtime_config.get(key, "") or os.getenv(env or key.upper(), "")


def get_client():
    user_id = cfg("instagram_user_id", "INSTAGRAM_USER_ID")
    token = cfg("instagram_access_token", "INSTAGRAM_ACCESS_TOKEN")
    if not user_id or not token:
        raise RuntimeError("尚未設定 Instagram User ID 或 Access Token")
    return InstagramClient(user_id, token, cfg("instagram_api_version", "INSTAGRAM_API_VERSION") or "v25.0")


def get_r2():
    values = {
        "account_id": cfg("r2_account_id", "R2_ACCOUNT_ID"),
        "access_key_id": cfg("r2_access_key_id", "R2_ACCESS_KEY_ID"),
        "secret_access_key": cfg("r2_secret_access_key", "R2_SECRET_ACCESS_KEY"),
        "bucket_name": cfg("r2_bucket_name", "R2_BUCKET_NAME"),
        "public_base_url": cfg("r2_public_base_url", "R2_PUBLIC_BASE_URL"),
    }
    if not all(values.values()):
        raise RuntimeError("Cloudflare R2 設定不完整")
    return R2Config(**values)


def matches(row, team, person):
    if normalize_text(row.get("所屬團體") or "") != team:
        return False
    row_person = normalize_text(row.get("人") or "")
    return (not row_person) if person == team_option_label(team) else row_person == person


@router.get("/settings")
def get_settings(creds: Credentials = Depends(require_credentials)):
    return {
        "drive_folder_id": cfg("instagram_drive_folder_id", "DEFAULT_DRIVE_FOLDER_ID"),
        "spreadsheet_id": cfg("instagram_spreadsheet_id", "DEFAULT_SPREADSHEET_ID"),
        "instagram_user_id": cfg("instagram_user_id", "INSTAGRAM_USER_ID"),
        "instagram_api_version": cfg("instagram_api_version", "INSTAGRAM_API_VERSION") or "v25.0",
        "instagram_access_token_configured": bool(cfg("instagram_access_token", "INSTAGRAM_ACCESS_TOKEN")),
        "r2_account_id": cfg("r2_account_id", "R2_ACCOUNT_ID"),
        "r2_access_key_id": cfg("r2_access_key_id", "R2_ACCESS_KEY_ID"),
        "r2_bucket_name": cfg("r2_bucket_name", "R2_BUCKET_NAME"),
        "r2_public_base_url": cfg("r2_public_base_url", "R2_PUBLIC_BASE_URL"),
        "r2_secret_access_key_configured": bool(cfg("r2_secret_access_key", "R2_SECRET_ACCESS_KEY")),
    }


@router.put("/settings")
def save_settings(payload: InstagramSettings, creds: Credentials = Depends(require_credentials)):
    data = payload.model_dump()
    mapping = {"drive_folder_id": "instagram_drive_folder_id", "spreadsheet_id": "instagram_spreadsheet_id"}
    for field, value in data.items():
        if not value.strip():
            continue
        runtime_config.set(mapping.get(field, field), value.strip())
    return get_settings(creds)


@router.get("/connection-status")
def connection_status(creds: Credentials = Depends(require_credentials)):
    errors = []
    profile = None
    try:
        profile = get_client().profile()
    except Exception as exc:
        errors.append(str(exc))
    try:
        get_r2()
    except Exception as exc:
        errors.append(str(exc))
    return {"ok": not errors, "profile": profile, "errors": errors}


@router.post("/drive-videos")
def drive_videos(payload: DriveInput, creds: Credentials = Depends(require_credentials)):
    folder = payload.folder_url_or_id or cfg("instagram_drive_folder_id", "DEFAULT_DRIVE_FOLDER_ID")
    if not folder:
        raise HTTPException(400, "請輸入 Google Drive 資料夾")
    try:
        videos = list_drive_videos(creds, folder)
        return {"videos": videos, "total": len(videos), "sort_order": "created_time_ascending"}
    except Exception as exc:
        raise HTTPException(500, f"讀取 Drive 影片失敗：{exc}") from exc


@router.post("/publish-reels")
def publish_reels(payload: PublishInput, creds: Credentials = Depends(require_credentials)):
    spreadsheet = payload.spreadsheet_url_or_id or cfg("instagram_spreadsheet_id", "DEFAULT_SPREADSHEET_ID")
    folder = payload.drive_folder_url_or_id or cfg("instagram_drive_folder_id", "DEFAULT_DRIVE_FOLDER_ID")
    active = [(a.file_id, normalize_text(a.person)) for a in payload.assignments if normalize_text(a.person)]
    if not active:
        raise HTTPException(400, "請至少為一支影片指定人物")
    team = normalize_text(payload.team)
    caption_column = normalize_text(payload.caption_column)
    try:
        headers = get_sheet_headers(creds, spreadsheet, payload.worksheet_name)
        missing = [name for name in ("所屬團體", "人", caption_column) if name not in headers]
        if missing:
            raise HTTPException(400, f"工作表缺少欄位：{', '.join(missing)}")
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
            if len(captions) != 1 or not next(iter(captions), "").strip():
                results.append({"file_id": file_id, "file_name": file["name"], "person": person, "status": "skipped", "reason": "找不到唯一且非空白的內文"})
                continue
            prepared.append((file, person, next(iter(captions))))
        client, r2 = get_client(), get_r2()
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
        return {"results": results, "published_count": counts["published"], "skipped_count": counts["skipped"], "failed_count": counts["failed"], "paused_count": counts["paused"], "sort_order": "created_time_ascending"}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, f"Instagram 發布流程失敗：{exc}") from exc
