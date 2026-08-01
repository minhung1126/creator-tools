"""Handlers for the three durable activity-center task types."""

from __future__ import annotations

import mimetypes
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from google.oauth2.credentials import Credentials

from backend.app.core.credential_store import credential_store
from backend.app.core.task_repository import TaskRepository, task_repository
from backend.app.services.google_auth import build_credentials_from_dict
from backend.app.services.task_context import TaskCancellationRequested, TaskContext
from backend.app.services.youtube_service import (
    fetch_video_details,
    remove_playlist_item,
    set_video_public,
    update_single_video_metadata,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_persistent_google_credentials() -> Optional[Credentials]:
    token_dict = credential_store.get_google_credentials()
    if not token_dict or not token_dict.get("token"):
        return None
    return build_credentials_from_dict(token_dict, persistent=True)


def _instagram_dependencies(credentials: Optional[Credentials], client: Any, r2: Any):
    if client is not None and r2 is not None:
        return credentials, client, r2
    # Importing the API module lazily avoids an import cycle during FastAPI
    # startup.  The worker still obtains the Instagram token from the encrypted
    # credential store through the existing API helper.
    from backend.app.api.instagram import get_connected_client, get_r2

    return credentials, client or get_connected_client(refresh_if_needed=True), r2 or get_r2()


def _error_text(exc: Exception) -> str:
    text = str(exc).strip() or type(exc).__name__
    if len(text) > 240 or any(marker in text.casefold() for marker in ("token", "secret", "authorization", "response body")):
        return "外部服務處理失敗，請檢查設定後重試。"
    return text


def _instagram_cleanup(
    context: TaskContext,
    *,
    item: dict[str, Any],
    job: dict[str, Any],
    credentials: Any,
    r2: Any,
) -> list[str]:
    """Finish post-publish cleanup without ever calling publish again."""

    from backend.app.services.drive_service import (
        ensure_published_folder,
        extract_drive_folder_id,
        move_drive_file_to_folder,
    )
    from backend.app.services.r2_service import delete_public_file

    warnings: list[str] = []
    checkpoint: dict[str, Any] = {}
    if not item.get("drive_moved"):
        context.update(stage="moving_drive", progress_percent=96)
        try:
            source_folder_id = extract_drive_folder_id(item.get("source_folder_id") or job.get("source_folder_id") or job.get("folder"))
            if not source_folder_id:
                raise RuntimeError("找不到 Google Drive 來源資料夾 ID，無法移入 Published")
            published_folder_id = item.get("published_folder_id") or job.get("published_folder_id")
            if not published_folder_id:
                published_folder_id = ensure_published_folder(credentials, source_folder_id)
            move_drive_file_to_folder(credentials, item["file_id"], source_folder_id, published_folder_id)
            item["published_folder_id"] = published_folder_id
            item["drive_moved"] = True
            item["drive_moved_at"] = _now()
            item["drive_move_error"] = None
            checkpoint.update(
                published_folder_id=published_folder_id,
                drive_moved=True,
                drive_moved_at=item["drive_moved_at"],
                drive_move_error=None,
            )
        except Exception as exc:
            message = _error_text(exc)
            item["drive_move_error"] = message
            warnings.append(f"Drive 搬移失敗：{message}")
            checkpoint.update(drive_moved=False, drive_move_error=message)
        context.checkpoint(checkpoint, stage="moving_drive", progress_percent=96)

    if item.get("object_key") and not item.get("r2_deleted"):
        context.update(stage="cleaning_r2", progress_percent=98)
        try:
            delete_public_file(r2, item["object_key"])
            item["r2_deleted"] = True
            item["r2_delete_error"] = None
            checkpoint.update(r2_deleted=True, r2_delete_error=None)
        except Exception as exc:
            message = _error_text(exc)
            item["r2_delete_error"] = message
            warnings.append(f"R2 清理失敗：{message}")
            checkpoint.update(r2_deleted=False, r2_delete_error=message)
        context.checkpoint(checkpoint, stage="cleaning_r2", progress_percent=98)
    return warnings


def process_instagram_reel_task(
    task_id: str,
    *,
    credentials: Optional[Credentials] = None,
    client: Any = None,
    r2: Any = None,
    repository: TaskRepository = task_repository,
) -> dict[str, Any]:
    """Process exactly one Instagram Reel task using its own checkpoint."""

    from backend.app.services.drive_service import download_drive_file
    from backend.app.services.instagram_publish_service import ReelValidationError, validate_reel_file
    from backend.app.services.r2_service import ensure_lifecycle, upload_public_file

    context = TaskContext(task_id, repository)
    task = context.task
    payload = dict(task.get("payload") or {})
    item = {**payload, **(task.get("checkpoint") or {})}
    item.setdefault("file_id", task.get("video_id"))
    item.setdefault("file_name", task.get("video_title") or "reel.mp4")
    item.setdefault("status", task.get("status"))
    job = {
        "source_folder_id": payload.get("source_folder_id") or payload.get("folder"),
        "folder": payload.get("folder"),
        "published_folder_id": payload.get("published_folder_id"),
        "share_to_feed": payload.get("share_to_feed", True),
    }
    try:
        credentials, client, r2 = _instagram_dependencies(credentials, client, r2)
        context.raise_if_cancel_requested()
        ensure_lifecycle(r2, days=3)

        if item.get("media_id"):
            # A media id is the durable proof of publication.  Retries only
            # execute Drive/R2 cleanup from this point onward.
            warnings = _instagram_cleanup(context, item=item, job=job, credentials=credentials, r2=r2)
            checkpoint = {key: item.get(key) for key in (
                "media_id", "drive_moved", "drive_moved_at", "published_folder_id", "drive_move_error",
                "r2_deleted", "r2_delete_error", "object_key", "public_url", "creation_id", "preflight",
            ) if key in item}
            context.checkpoint(checkpoint, stage="completed" if not warnings else "cleaning_r2", progress_percent=100 if not warnings else 98)
            return context.finish(
                "succeeded_with_warnings" if warnings else "succeeded",
                stage="completed" if not warnings else "cleaning_r2",
                progress_percent=100 if not warnings else 98,
                error="；".join(warnings) if warnings else None,
                cancel_too_late=bool(task.get("cancel_requested_at")),
            )

        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", str(item.get("file_name") or "reel.mp4")).strip("-._") or "reel.mp4"
        object_key = item.get("object_key") or f"instagram-reels/{datetime.now(timezone.utc):%Y/%m/%d}/{task['sequence_in_batch']:03d}-{item.get('file_id')}-{safe_name}"
        item["object_key"] = object_key
        if not item.get("public_url"):
            context.raise_if_cancel_requested()
            with tempfile.TemporaryDirectory(prefix="creator-tools-instagram-") as directory:
                local = Path(directory) / safe_name
                context.update(stage="downloading", progress_percent=10)
                download_drive_file(credentials, item["file_id"], local)
                context.raise_if_cancel_requested()
                context.update(stage="validating", progress_percent=20)
                item["preflight"] = {**(item.get("preflight") or {}), **validate_reel_file(local)}
                context.checkpoint({"preflight": item["preflight"]}, stage="validating", progress_percent=20)
                context.raise_if_cancel_requested()
                context.update(stage="uploading_r2", progress_percent=38)
                item["public_url"] = upload_public_file(
                    r2,
                    local,
                    object_key,
                    mimetypes.guess_type(safe_name)[0] or "video/mp4",
                )
            context.checkpoint(
                {"public_url": item["public_url"], "object_key": object_key, "preflight": item.get("preflight") or {}},
                stage="uploaded",
                progress_percent=45,
            )

        if not item.get("creation_id"):
            context.raise_if_cancel_requested()
            context.update(stage="creating_container", progress_percent=60)
            item["creation_id"] = client.create_reel_container(
                item["public_url"], payload.get("caption", ""), payload.get("share_to_feed", True)
            )
            context.checkpoint({"creation_id": item["creation_id"]}, stage="container_created", progress_percent=66)

        context.raise_if_cancel_requested()
        context.update(stage="waiting_container", progress_percent=78)
        client.wait_for_container(item["creation_id"])
        context.raise_if_cancel_requested()
        context.update(stage="publishing", progress_percent=92)
        context.raise_if_cancel_requested()
        item["media_id"] = client.publish_container(item["creation_id"])
        item["published_at"] = _now()
        context.checkpoint({"media_id": item["media_id"], "published_at": item["published_at"]}, stage="published", progress_percent=94)
        cancel_too_late = context.is_cancel_requested()
        warnings = _instagram_cleanup(context, item=item, job=job, credentials=credentials, r2=r2)
        context.checkpoint({
            "media_id": item["media_id"],
            "drive_moved": item.get("drive_moved", False),
            "drive_moved_at": item.get("drive_moved_at"),
            "published_folder_id": item.get("published_folder_id"),
            "drive_move_error": item.get("drive_move_error"),
            "r2_deleted": item.get("r2_deleted", False),
            "r2_delete_error": item.get("r2_delete_error"),
        }, stage="completed" if not warnings else "cleaning_r2", progress_percent=100 if not warnings else 98)
        return context.finish(
            "succeeded_with_warnings" if warnings else "succeeded",
            stage="completed" if not warnings else "cleaning_r2",
            progress_percent=100 if not warnings else 98,
            error="；".join(warnings) if warnings else None,
            cancel_too_late=cancel_too_late,
        )
    except TaskCancellationRequested:
        if item.get("media_id"):
            warnings = _instagram_cleanup(context, item=item, job=job, credentials=credentials, r2=r2)
            context.checkpoint(
                {"media_id": item.get("media_id"), "drive_moved": item.get("drive_moved", False), "r2_deleted": item.get("r2_deleted", False), "drive_move_error": item.get("drive_move_error"), "r2_delete_error": item.get("r2_delete_error")},
                stage="completed" if not warnings else "cleaning_r2",
                progress_percent=100 if not warnings else 98,
            )
            return context.finish(
                "succeeded_with_warnings" if warnings else "succeeded",
                stage="completed" if not warnings else "cleaning_r2",
                progress_percent=100 if not warnings else 98,
                error="；".join(warnings) if warnings else None,
                cancel_too_late=True,
            )
        warnings = []
        if item.get("object_key") and r2 is not None:
            try:
                from backend.app.services.r2_service import delete_public_file

                delete_public_file(r2, item["object_key"])
                item["r2_deleted"] = True
                context.checkpoint({"r2_deleted": True, "r2_delete_error": None}, stage="canceled", progress_percent=0)
            except Exception as exc:
                warning = _error_text(exc)
                warnings.append(warning)
                context.checkpoint({"r2_deleted": False, "r2_delete_error": warning}, stage="canceled_with_warnings", progress_percent=0)
        return context.finish(
            "canceled_with_warnings" if warnings else "canceled",
            error="；".join(warnings) if warnings else None,
            message="取消要求在不可逆外部操作前送達，任務已停止。",
        )
    except ReelValidationError as exc:
        return context.finish("skipped", stage="skipped", progress_percent=100, error=str(exc), retryable=False)
    except Exception as exc:
        return context.finish("failed", stage="failed", progress_percent=task.get("progress_percent", 0), error=_error_text(exc), retryable=True)


def process_youtube_metadata_task(
    task_id: str,
    *,
    credentials: Optional[Credentials] = None,
    repository: TaskRepository = task_repository,
) -> dict[str, Any]:
    context = TaskContext(task_id, repository)
    task = context.task
    payload = task.get("payload") or {}
    credentials = credentials or get_persistent_google_credentials()
    if credentials is None:
        return context.finish("paused", stage="paused", error="找不到持久化 Google credential，請重新登入後重試。", retryable=True)
    try:
        context.raise_if_cancel_requested()
        context.update(stage="validating_video", progress_percent=20)
        details = fetch_video_details(credentials, [task.get("video_id")])
        current = next((item for item in details if item.get("id") == task.get("video_id")), None)
        if not current:
            return context.finish("skipped", stage="skipped", progress_percent=100, error="YouTube 找不到此影片或目前帳號無權存取。", retryable=False)
        context.raise_if_cancel_requested()
        context.update(stage="updating_metadata", progress_percent=70)
        update_single_video_metadata(
            credentials,
            task["video_id"],
            str(payload.get("new_title") or ""),
            str(payload.get("new_description") or ""),
            current_snippet=current.get("snippet") or {},
        )
        context.checkpoint({"metadata_updated_at": _now(), "title_applied": True}, stage="completed", progress_percent=100)
        cancel_too_late = context.is_cancel_requested()
        return context.finish("succeeded", stage="completed", progress_percent=100, cancel_too_late=cancel_too_late)
    except TaskCancellationRequested:
        return context.finish("canceled", error=None, message="取消要求在 YouTube metadata 更新前送達。")
    except Exception as exc:
        return context.finish("failed", stage="failed", error=_error_text(exc), retryable=True)


def process_youtube_publish_cleanup_task(
    task_id: str,
    *,
    credentials: Optional[Credentials] = None,
    repository: TaskRepository = task_repository,
) -> dict[str, Any]:
    context = TaskContext(task_id, repository)
    task = context.task
    payload = task.get("payload") or {}
    checkpoint = dict(task.get("checkpoint") or {})
    credentials = credentials or get_persistent_google_credentials()
    if credentials is None:
        return context.finish("paused", stage="paused", error="找不到持久化 Google credential，請重新登入後重試。", retryable=True)
    try:
        context.raise_if_cancel_requested()
        current_details = fetch_video_details(credentials, [task.get("video_id")])
        current_video = next((item for item in current_details if item.get("id") == task.get("video_id")), None)
        if not current_video:
            return context.finish("skipped", stage="skipped", progress_percent=100, error="YouTube 找不到此影片或目前帳號無權存取。", retryable=False)
        if not checkpoint.get("privacy_updated_at"):
            context.raise_if_cancel_requested()
            context.update(stage="setting_public", progress_percent=35)
            set_video_public(credentials, task["video_id"], current_video=current_video)
            checkpoint.update(privacy_updated_at=_now(), privacy_status="public")
            context.checkpoint(checkpoint, stage="public_updated", progress_percent=60)
        cancel_too_late = context.is_cancel_requested()
        if not checkpoint.get("playlist_removed_at"):
            context.update(stage="removing_playlist_item", progress_percent=80)
            remove_playlist_item(credentials, payload.get("playlist_item_id"))
            checkpoint.update(
                playlist_item_id=payload.get("playlist_item_id"),
                playlist_removed_at=_now(),
                playlist_cleanup_error=None,
            )
            context.checkpoint(checkpoint, stage="completed", progress_percent=100)
        cancel_too_late = cancel_too_late or context.is_cancel_requested()
        return context.finish("succeeded", stage="completed", progress_percent=100, cancel_too_late=cancel_too_late)
    except TaskCancellationRequested:
        return context.finish("canceled", message="取消要求在 YouTube 設為 public 前送達，未進行公開。")
    except Exception as exc:
        checkpoint["playlist_cleanup_error"] = _error_text(exc)
        context.checkpoint(checkpoint, stage="removing_playlist_item" if checkpoint.get("privacy_updated_at") else "setting_public", progress_percent=80 if checkpoint.get("privacy_updated_at") else 35)
        if checkpoint.get("privacy_updated_at"):
            return context.finish("succeeded_with_warnings", stage="removing_playlist_item", progress_percent=80, error=_error_text(exc), retryable=True, cancel_too_late=context.is_cancel_requested())
        return context.finish("failed", stage="failed", error=_error_text(exc), retryable=True)
