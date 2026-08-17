"""Durable, single-file-at-a-time Drive-to-YouTube upload jobs."""

from __future__ import annotations

import copy
import json
import logging
import os
import re
import shutil
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from backend.app.core.config import normalize_youtube_slot
from backend.app.core.credential_store import credential_store
from backend.app.core.youtube_context import YouTubeRequestContext
from backend.app.services.drive_service import download_drive_file, get_drive_metadata
from backend.app.services.google_auth import build_credentials_from_dict, has_drive_read_scope
from backend.app.services.provider_errors import map_youtube_error
from backend.app.services.youtube_errors import YouTubeQuotaUnavailable
from backend.app.services.youtube_quota_service import get_youtube_quota_tracker
from backend.app.services.youtube_service import (
    ResumableUploadError,
    insert_video_into_playlist,
    upload_video_resumable,
)

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = PROJECT_ROOT / "data"
JOBS_FILE = DATA_DIR / "youtube_upload_jobs.json"
TEMP_ROOT = DATA_DIR / "youtube_upload_tmp"
JOB_SCHEMA_VERSION = 1
MAX_JOBS = 100
MAX_JOB_AGE_SECONDS = 14 * 24 * 60 * 60
JOB_ID_RE = re.compile(r"^[a-f0-9-]{20,80}$")

ACTIVE_STATUSES = frozenset({"queued", "running", "paused", "cancel_requested"})
WORKER_STATUSES = frozenset({"queued", "running", "cancel_requested"})
TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})
ITEM_DONE = "added"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _safe_job_id(value: str) -> str:
    job_id = str(value or "").strip().casefold()
    if not JOB_ID_RE.fullmatch(job_id):
        raise ValueError("upload job ID 不正確")
    return job_id


def _safe_copy(value: Any) -> Any:
    return copy.deepcopy(value)


def _public_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        key: _safe_copy(value)
        for key, value in item.items()
        if key not in {"temp_path", "resumable_uri", "drive_metadata"}
    }


def public_job(job: dict[str, Any]) -> dict[str, Any]:
    """Return job state safe for the account-bound UI."""

    result = {key: _safe_copy(value) for key, value in job.items() if key != "owner_sub"}
    result["items"] = [_public_item(item) for item in job.get("items", [])]
    result["progress"] = {
        "completed": sum(1 for item in job.get("items", []) if item.get("status") in {ITEM_DONE, "skipped"}),
        "total": len(job.get("items", [])),
        "uploaded": sum(1 for item in job.get("items", []) if item.get("youtube_video_id")),
        "failed": sum(1 for item in job.get("items", []) if item.get("status") == "failed"),
    }
    return result


class UploadJobStore:
    """Atomic JSON persistence for account-scoped upload jobs."""

    def __init__(self, path: Path = JOBS_FILE, temp_root: Path = TEMP_ROOT):
        self.path = Path(path)
        self.temp_root = Path(temp_root)
        self._lock = threading.RLock()
        self._data: dict[str, Any] = {"version": JOB_SCHEMA_VERSION, "jobs": {}}
        self._load()

    def _load(self) -> None:
        if not self.path.is_file():
            return
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                raw = json.load(handle)
            jobs = raw.get("jobs") if isinstance(raw, dict) else None
            if not isinstance(jobs, dict):
                raise ValueError("jobs must be an object")
            normalized: dict[str, dict[str, Any]] = {}
            for raw_id, raw_job in jobs.items():
                if not isinstance(raw_job, dict):
                    continue
                try:
                    job_id = _safe_job_id(raw_id)
                except ValueError:
                    continue
                job = _safe_copy(raw_job)
                if job.get("status") == "running":
                    job["status"] = "queued"
                    job["worker_recovered"] = True
                for item in job.get("items", []):
                    if not isinstance(item, dict):
                        continue
                    if item.get("status") in {"downloading", "uploading"}:
                        item["status"] = "uploaded" if item.get("youtube_video_id") else "pending"
                normalized[job_id] = job
            self._data = {"version": JOB_SCHEMA_VERSION, "jobs": normalized}
            if normalized:
                self._save_unlocked()
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            logger.error("Failed to load YouTube upload jobs: %s", type(exc).__name__)

    def _save_unlocked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_name(f".{self.path.name}.{os.getpid()}.{uuid4().hex}.tmp")
        try:
            with tmp_path.open("w", encoding="utf-8") as handle:
                json.dump(self._data, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.chmod(tmp_path, 0o600)
            except OSError:
                pass
            os.replace(tmp_path, self.path)
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                pass
        except (OSError, TypeError, ValueError):
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    def create(self, owner_sub: str, job: dict[str, Any]) -> dict[str, Any]:
        subject = str(owner_sub or "").strip()
        if not subject:
            raise ValueError("upload job owner is required")
        job_id = _safe_job_id(job.get("job_id"))
        with self._lock:
            if len(self._data["jobs"]) >= MAX_JOBS:
                self._prune_unlocked()
            if len(self._data["jobs"]) >= MAX_JOBS:
                raise RuntimeError("目前上傳工作數量已達上限，請稍後再試。")
            record = _safe_copy(job)
            record.update(
                {
                    "job_id": job_id,
                    "owner_sub": subject,
                    "created_at": record.get("created_at") or utc_now(),
                    "updated_at": utc_now(),
                }
            )
            self._data["jobs"][job_id] = record
            self._save_unlocked()
            return _safe_copy(record)

    def get(self, owner_sub: str, job_id: str) -> dict[str, Any] | None:
        job_key = _safe_job_id(job_id)
        with self._lock:
            job = self._data["jobs"].get(job_key)
            if not isinstance(job, dict) or job.get("owner_sub") != str(owner_sub or "").strip():
                return None
            return _safe_copy(job)

    def list_for_owner(self, owner_sub: str) -> list[dict[str, Any]]:
        subject = str(owner_sub or "").strip()
        with self._lock:
            jobs = [
                job for job in self._data["jobs"].values() if isinstance(job, dict) and job.get("owner_sub") == subject
            ]
            return sorted(
                (_safe_copy(job) for job in jobs), key=lambda job: str(job.get("created_at") or ""), reverse=True
            )

    def list_active_internal(self) -> list[dict[str, Any]]:
        with self._lock:
            jobs = [
                _safe_copy(job)
                for job in self._data["jobs"].values()
                if isinstance(job, dict) and job.get("status") in WORKER_STATUSES
            ]
        return sorted(jobs, key=lambda job: str(job.get("created_at") or ""))

    def update(self, owner_sub: str, job_id: str, updater: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
        job_key = _safe_job_id(job_id)
        with self._lock:
            job = self._data["jobs"].get(job_key)
            if not isinstance(job, dict) or job.get("owner_sub") != str(owner_sub or "").strip():
                raise KeyError("upload job not found")
            updater(job)
            job["updated_at"] = utc_now()
            self._save_unlocked()
            return _safe_copy(job)

    def update_internal(self, job_id: str, updater: Callable[[dict[str, Any]], None]) -> dict[str, Any] | None:
        job_key = _safe_job_id(job_id)
        with self._lock:
            job = self._data["jobs"].get(job_key)
            if not isinstance(job, dict):
                return None
            updater(job)
            job["updated_at"] = utc_now()
            self._save_unlocked()
            return _safe_copy(job)

    def find_source(self, owner_sub: str, source_key: str) -> dict[str, Any] | None:
        subject = str(owner_sub or "").strip()
        with self._lock:
            for job in self._data["jobs"].values():
                if not isinstance(job, dict) or job.get("owner_sub") != subject:
                    continue
                for item in job.get("items", []):
                    if item.get("source_key") == source_key:
                        return _safe_copy({"job_id": job.get("job_id"), "job_status": job.get("status"), **item})
        return None

    def _prune_unlocked(self) -> None:
        candidates = []
        for job_id, job in self._data["jobs"].items():
            if not isinstance(job, dict) or job.get("status") not in TERMINAL_STATUSES:
                continue
            try:
                created = datetime.fromisoformat(str(job.get("updated_at") or job.get("created_at"))).timestamp()
            except (TypeError, ValueError):
                created = 0
            candidates.append((created, job_id))
        for _created, job_id in sorted(candidates)[: max(0, len(self._data["jobs"]) - MAX_JOBS + 1)]:
            self._data["jobs"].pop(job_id, None)
            _remove_temp_dir(self.temp_root, job_id)

    def cleanup_temp_files(self) -> None:
        with self._lock:
            now = datetime.now(timezone.utc).timestamp()
            for job_id, job in self._data["jobs"].items():
                if not isinstance(job, dict) or job.get("status") in ACTIVE_STATUSES:
                    continue
                try:
                    updated = datetime.fromisoformat(str(job.get("updated_at") or "")).timestamp()
                except (TypeError, ValueError):
                    updated = 0
                if now - updated > MAX_JOB_AGE_SECONDS:
                    _remove_temp_dir(self.temp_root, job_id)


def _remove_temp_dir(temp_root: Path, job_id: str) -> None:
    if not JOB_ID_RE.fullmatch(str(job_id or "")):
        return
    target = (temp_root / job_id).resolve()
    root = temp_root.resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return
    shutil.rmtree(target, ignore_errors=True)


def _job_temp_path(store: UploadJobStore, job_id: str) -> Path:
    safe_id = _safe_job_id(job_id)
    root = store.temp_root.resolve()
    target_dir = (root / safe_id).resolve()
    target_dir.relative_to(root)
    target_dir.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(target_dir, 0o700)
    except OSError:
        pass
    target = target_dir / f"{uuid4().hex}.video"
    target.relative_to(root)
    return target


def _error_detail(exc: Exception, *, stage: str) -> dict[str, Any]:
    if isinstance(exc, YouTubeQuotaUnavailable):
        return exc.to_dict()
    if isinstance(exc, ResumableUploadError):
        return {
            "code": "youtube_upload_resumable_interrupted",
            "message": "YouTube resumable upload 中斷，請重試以繼續既有進度。",
            "retryable": True,
        }
    if isinstance(exc, PermissionError):
        return {
            "code": "google_drive_scope_required",
            "message": "Google Drive 權限不足，請重新授權 Google Drive。",
            "retryable": False,
        }
    if isinstance(exc, (ValueError, IOError, OSError)):
        message = str(exc) if str(exc) else "上傳工作輸入或檔案驗證失敗。"
        return {"code": "youtube_upload_file_invalid", "message": message[:300], "retryable": False}
    mapped = map_youtube_error(exc, method="videos.insert" if stage == "upload" else "playlistItems.insert")
    detail = dict(mapped.detail)
    detail["message"] = mapped.message
    return detail


def _is_transient(exc: Exception) -> bool:
    if isinstance(exc, YouTubeQuotaUnavailable):
        return False
    if isinstance(exc, ResumableUploadError):
        return exc.http_status is None or exc.http_status in {429, 500, 502, 503, 504}
    status = getattr(getattr(exc, "resp", None), "status", None)
    return status in {429, 500, 502, 503, 504}


class YouTubeUploadWorker:
    """One process-wide worker; each job is processed strictly in file order."""

    def __init__(self, store: UploadJobStore):
        self.store = store
        self._condition = threading.Condition()
        self._stop = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        with self._condition:
            if self._thread and self._thread.is_alive():
                return
            self._stop = False
            self._thread = threading.Thread(target=self._run, name="youtube-upload-worker", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        with self._condition:
            self._stop = True
            self._condition.notify_all()

    def wake(self) -> None:
        with self._condition:
            self._condition.notify_all()

    def _run(self) -> None:
        while True:
            with self._condition:
                if self._stop:
                    return
            self.store.cleanup_temp_files()
            jobs = self.store.list_active_internal()
            if jobs:
                for job in jobs:
                    try:
                        self._run_job(str(job.get("job_id") or ""))
                    except Exception as exc:  # the next job must not be starved by one corrupt job
                        logger.error("YouTube upload worker failed for job: %s", type(exc).__name__)
                        self.store.update_internal(
                            str(job.get("job_id") or ""),
                            lambda current, error=_error_detail(exc, stage="worker"): current.update(
                                {"status": "failed", "error": error}
                            ),
                        )
                continue
            with self._condition:
                self._condition.wait(timeout=2)

    def _run_job(self, job_id: str) -> None:
        job = self.store.update_internal(
            job_id, lambda current: current.update({"status": "running", "current_index": None})
        )
        if not job:
            return
        owner_sub = str(job.get("owner_sub") or "")
        try:
            login_token = credential_store.get_google_credentials(owner_sub)
            youtube_token = credential_store.get_youtube_credentials(owner_sub, slot=job.get("youtube_slot", "primary"))
            if not login_token or not youtube_token:
                raise PermissionError("Google OAuth 憑證不存在，請重新授權。")
            login_creds = build_credentials_from_dict(login_token, credential_key="google", owner_sub=owner_sub)
            youtube_slot = normalize_youtube_slot(job.get("youtube_slot", "primary"))
            youtube_creds = build_credentials_from_dict(
                youtube_token,
                credential_key="youtube",
                owner_sub=owner_sub,
                slot=youtube_slot,
            )
            if not has_drive_read_scope(login_creds):
                raise PermissionError("Google Drive 權限不足，請重新授權 Google Drive。")
            context = YouTubeRequestContext(
                slot=youtube_slot,
                credentials=youtube_creds,
                quota_limiter=get_youtube_quota_tracker(youtube_slot),
                owner_sub=owner_sub,
                channel_id=job.get("youtube_channel_id"),
                routing_mode=job.get("youtube_routing_mode", "auto_primary"),
                selection_reason="upload_job_pinned_slot",
                estimated_units=int(job.get("estimated_quota", {}).get("total") or 0),
                preferred_slot=job.get("youtube_preferred_slot", youtube_slot),
            )
            for index, item in enumerate(job.get("items", [])):
                current = self.store.get(owner_sub, job_id)
                if not current:
                    return
                current_item = current.get("items", [])[index]
                if current_item.get("status") in {ITEM_DONE, "skipped"}:
                    continue
                if current.get("cancel_requested") and not current_item.get("youtube_video_id"):
                    self._cancel_remaining(owner_sub, job_id, index)
                    return
                self._process_item(login_creds, context, owner_sub, job_id, index)
            self.store.update_internal(
                job_id,
                lambda current: current.update(
                    {"status": "cancelled" if current.get("cancel_requested") else "completed", "current_index": None}
                ),
            )
        except Exception as exc:
            detail = _error_detail(exc, stage="worker")
            status = "paused" if isinstance(exc, YouTubeQuotaUnavailable) else "failed"
            self.store.update_internal(
                job_id,
                lambda current, error=detail, next_status=status: current.update(
                    {"status": next_status, "error": error, "current_index": current.get("current_index")}
                ),
            )
        finally:
            _remove_temp_dir(self.store.temp_root, job_id)

    def _cancel_remaining(self, owner_sub: str, job_id: str, start_index: int) -> None:
        def cancel(current: dict[str, Any]) -> None:
            for item in current.get("items", [])[start_index:]:
                if item.get("status") == "pending":
                    item["status"] = "cancelled"
            current.update({"status": "cancelled", "current_index": None})

        self.store.update(owner_sub, job_id, cancel)

    def _process_item(
        self, login_creds, context: YouTubeRequestContext, owner_sub: str, job_id: str, index: int
    ) -> None:
        job = self.store.get(owner_sub, job_id)
        if not job:
            return
        self.store.update_internal(
            job_id,
            lambda current, item_index=index: current.update(
                {
                    "current_index": item_index,
                    "items": _set_item_status(current.get("items", []), item_index, "downloading"),
                }
            ),
        )
        current_job = self.store.get(owner_sub, job_id) or job
        current_item = current_job["items"][index]
        video_id = str(current_item.get("youtube_video_id") or "").strip()
        temp_path: Path | None = None
        try:
            if not video_id:
                metadata = get_drive_metadata(login_creds, current_item["drive_file_id"])
                if _fingerprint(metadata) != current_item.get("fingerprint"):
                    raise ValueError("Drive 檔案版本或 checksum 已變更，請重新解析預覽。")
                temp_path = _job_temp_path(self.store, job_id)
                verification = _with_retries(
                    lambda: download_drive_file(login_creds, metadata, temp_path),
                    stage="drive",
                )
                if verification.get("size") != int(current_item.get("size") or 0):
                    raise ValueError("Drive 影片大小驗證失敗。")
                self.store.update_internal(
                    job_id,
                    lambda current, item_index=index: current.update(
                        {"items": _set_item_status(current.get("items", []), item_index, "uploading")}
                    ),
                )

                def upload_one():
                    try:
                        return upload_video_resumable(
                            context,
                            str(temp_path),
                            title=str(current_item.get("title") or ""),
                            mime_type=current_item.get("mime_type"),
                            resumable_uri=current_item.get("resumable_uri"),
                        )
                    except ResumableUploadError as exc:
                        if exc.resumable_uri:
                            current_item["resumable_uri"] = exc.resumable_uri
                            self.store.update_internal(
                                job_id,
                                lambda current, item_index=index, session_uri=exc.resumable_uri: current["items"][
                                    item_index
                                ].update({"resumable_uri": session_uri}),
                            )
                        raise

                response = _with_retries(upload_one, stage="upload")
                video_id = str(response.get("id") or "").strip()
                if not video_id:
                    raise ValueError("YouTube 上傳沒有回傳影片 ID。")
                self.store.update_internal(
                    job_id,
                    lambda current, item_index=index, uploaded_id=video_id: current.update(
                        {
                            "items": _set_item_fields(
                                current.get("items", []),
                                item_index,
                                {"youtube_video_id": uploaded_id, "status": "uploaded", "resumable_uri": None},
                            )
                        }
                    ),
                )
            else:
                self.store.update_internal(
                    job_id,
                    lambda current, item_index=index: current.update(
                        {"items": _set_item_status(current.get("items", []), item_index, "uploaded")}
                    ),
                )

            playlist_response = _with_retries(
                lambda: insert_video_into_playlist(context, str(job["playlist_id"]), video_id),
                stage="playlist",
            )
            playlist_item_id = str(playlist_response.get("id") or "").strip()
            self.store.update_internal(
                job_id,
                lambda current, item_index=index, item_id=playlist_item_id: current.update(
                    {
                        "items": _set_item_fields(
                            current.get("items", []),
                            item_index,
                            {"playlist_item_id": item_id, "status": ITEM_DONE, "error": None},
                        )
                    }
                ),
            )
        except Exception as exc:
            detail = _error_detail(exc, stage="playlist" if video_id else "upload")
            is_quota_error = isinstance(exc, YouTubeQuotaUnavailable)
            resumable_uri = getattr(exc, "resumable_uri", None)
            self.store.update_internal(
                job_id,
                lambda current, item_index=index, error=detail, uploaded_id=video_id, quota_error=is_quota_error, session_uri=resumable_uri: (
                    current.update(
                        {
                            "status": "paused" if quota_error else "failed",
                            "error": error,
                            "current_index": item_index,
                            "items": _set_item_fields(
                                current.get("items", []),
                                item_index,
                                {
                                    "status": "uploaded" if uploaded_id else "failed",
                                    "youtube_video_id": uploaded_id or None,
                                    "resumable_uri": session_uri,
                                    "error": error,
                                },
                            ),
                        }
                    )
                ),
            )
            raise
        finally:
            if temp_path:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass


def _set_item_status(items: list[dict[str, Any]], index: int, status: str) -> list[dict[str, Any]]:
    copied = [_safe_copy(item) for item in items]
    copied[index]["status"] = status
    return copied


def _set_item_fields(items: list[dict[str, Any]], index: int, values: dict[str, Any]) -> list[dict[str, Any]]:
    copied = [_safe_copy(item) for item in items]
    copied[index].update(_safe_copy(values))
    return copied


def _fingerprint(metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        "file_id": str(metadata.get("id") or ""),
        "version": str(metadata.get("version") or ""),
        "md5_checksum": str(metadata.get("md5Checksum") or ""),
        "size": int(metadata.get("size") or 0),
        "modified_time": str(metadata.get("modifiedTime") or ""),
    }


def _with_retries(operation: Callable[[], dict[str, Any]], *, stage: str) -> dict[str, Any]:
    del stage
    last_error: Exception | None = None
    for attempt in range(4):
        try:
            return operation()
        except Exception as exc:
            last_error = exc
            if not _is_transient(exc) or attempt >= 3:
                raise
            time.sleep(min(2**attempt, 8))
    raise last_error or RuntimeError("上傳操作失敗。")


upload_job_store = UploadJobStore()
upload_worker = YouTubeUploadWorker(upload_job_store)


def start_upload_worker() -> None:
    upload_worker.start()


def stop_upload_worker() -> None:
    upload_worker.stop()


def wake_upload_worker() -> None:
    upload_worker.start()
    upload_worker.wake()


__all__ = [
    "ACTIVE_STATUSES",
    "ITEM_DONE",
    "JOBS_FILE",
    "TEMP_ROOT",
    "UploadJobStore",
    "YouTubeUploadWorker",
    "public_job",
    "start_upload_worker",
    "stop_upload_worker",
    "upload_job_store",
    "upload_worker",
    "wake_upload_worker",
]
