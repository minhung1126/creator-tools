"""Operation-to-handler dispatch for the unified task queue."""

from __future__ import annotations

import logging
from typing import Any

from backend.app.core.task_repository import TaskRepository, task_repository
from backend.app.services.instagram_errors import InstagramApiError
from backend.app.services.task_handlers import (
    _defer_youtube_quota,
    get_persistent_google_credentials,
    process_instagram_reel_task,
    process_instagram_reel_tasks,
    process_youtube_metadata_task,
    process_youtube_publish_cleanup_task,
)
from backend.app.services.youtube_errors import YouTubeQuotaUnavailable

logger = logging.getLogger(__name__)


class TaskDispatcher:
    def __init__(self, repository: TaskRepository = task_repository):
        self.repository = repository

    def dispatch(self, task: dict[str, Any]) -> dict[str, Any] | None:
        task_id = task["id"]
        operation = task.get("operation")
        try:
            credentials = get_persistent_google_credentials()
        except Exception:
            logger.exception("Unable to load persistent Google credentials for %s", task_id)
            credentials = None
        if credentials is None:
            return self.repository.update_task(
                task_id,
                status="paused",
                stage="paused",
                progress_percent=task.get("progress_percent", 0),
                error="找不到持久化 Google credential，請重新登入後確認並重試。",
                retryable=True,
                message="找不到持久化 Google credential",
            )
        try:
            if operation == "instagram.reels_publish":
                result = process_instagram_reel_task(task_id, credentials=credentials, repository=self.repository)
            elif operation == "youtube.metadata_update":
                result = process_youtube_metadata_task(task_id, credentials=credentials, repository=self.repository)
            elif operation == "youtube.publish_cleanup":
                result = process_youtube_publish_cleanup_task(
                    task_id, credentials=credentials, repository=self.repository
                )
            else:
                result = self.repository.update_task(
                    task_id,
                    status="failed",
                    stage="failed",
                    error=f"不支援的任務類型：{operation}",
                    retryable=False,
                )
        except YouTubeQuotaUnavailable as exc:
            logger.warning("YouTube quota unavailable for %s: %s", task_id, exc.user_message)
            if exc.code in {"youtube_quota_safety_blocked", "youtube_quota_exhausted"}:
                result = _defer_youtube_quota(task_id, exc, repository=self.repository)
            else:
                result = self.repository.update_task(
                    task_id,
                    status="failed",
                    stage="failed",
                    error=exc.user_message,
                    retryable=False,
                    message="YouTube quota method 尚未完成設定",
                )
        except InstagramApiError as exc:
            logger.warning("Instagram API error for %s: %s", task_id, exc.user_message)
            if exc.rate_limited and exc.safe_to_retry and hasattr(self.repository, "defer_task"):
                next_attempt_at = exc.estimated_recovery_at
                if not next_attempt_at:
                    state = self.repository.instagram_limiter.get_state()
                    next_attempt_at = state.get("cooldown_until")
                if not next_attempt_at:
                    from datetime import datetime, timedelta, timezone

                    next_attempt_at = (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()
                result = self.repository.defer_task(
                    task_id,
                    next_attempt_at=str(next_attempt_at),
                    error=exc.user_message,
                    checkpoint={"instagram_api_error": exc.to_dict()},
                )
            elif exc.uncertain:
                result = self.repository.update_task(
                    task_id,
                    status="paused",
                    stage="external_state_unknown",
                    error=exc.user_message,
                    retryable=False,
                    message="網路結果不確定，未自動重送 Instagram POST。",
                    checkpoint={"instagram_api_error": exc.to_dict(), "external_operation_uncertain": True},
                )
            else:
                result = self.repository.update_task(
                    task_id,
                    status="failed",
                    stage="failed",
                    error=exc.user_message,
                    retryable=not exc.token_error,
                    message=exc.user_message,
                )
        except Exception as exc:  # The lane must not die on one unexpected handler error.
            logger.exception("Task handler crashed for %s", task_id)
            result = self.repository.update_task(
                task_id,
                status="failed",
                stage="failed",
                error="背景任務處理失敗，請檢查後重試。",
                retryable=True,
                message=type(exc).__name__,
            )

        final = self.repository.get_task_internal(task_id) or result
        if final and final.get("status") == "failed":
            batch = self.repository.get_batch_internal(final["batch_id"])
            if batch and batch.get("failure_policy") == "pause_remaining_in_batch":
                self.repository.pause_remaining_tasks(
                    final["batch_id"],
                    after_sequence=final.get("sequence_in_batch"),
                    reason="前一支影片任務失敗，後續任務已暫停。",
                )
                final = self.repository.get_task_internal(task_id) or final
        return final

    def dispatch_batch(self, tasks: list[dict[str, Any]]) -> dict[str, Any] | None:
        """Dispatch one claimed Instagram batch without losing child order."""

        if not tasks:
            return None
        if len(tasks) == 1:
            return self.dispatch(tasks[0])
        try:
            credentials = get_persistent_google_credentials()
        except Exception:
            logger.exception("Unable to load persistent Google credentials for Instagram batch")
            credentials = None
        if credentials is None:
            for task in tasks:
                self.repository.update_task(
                    task["id"],
                    status="paused",
                    stage="paused",
                    progress_percent=task.get("progress_percent", 0),
                    error="找不到持久化 Google credential，請重新登入後確認並重試。",
                    retryable=True,
                    message="找不到持久化 Google credential",
                )
            return self.repository.get_task_internal(tasks[-1]["id"])

        try:
            results = process_instagram_reel_tasks(tasks, credentials=credentials, repository=self.repository)
        except Exception:
            logger.exception("Instagram batch handler crashed for %s", tasks[0].get("batch_id"))
            for task in tasks:
                current = self.repository.get_task_internal(task["id"])
                if current and current.get("status") in {"running", "cancel_requested"}:
                    self.repository.update_task(
                        task["id"],
                        status="failed",
                        stage="failed",
                        error="背景任務處理失敗，請檢查後重試。",
                        retryable=True,
                        message="Instagram 批次處理失敗",
                    )
            return self.repository.get_task_internal(tasks[-1]["id"])

        for result in results:
            if result and result.get("status") == "failed":
                batch = self.repository.get_batch_internal(result["batch_id"])
                if batch and batch.get("failure_policy") == "pause_remaining_in_batch":
                    self.repository.pause_remaining_tasks(
                        result["batch_id"],
                        after_sequence=result.get("sequence_in_batch"),
                        reason="前一支影片任務失敗，後續任務已暫停。",
                    )
        return self.repository.get_task_internal(tasks[-1]["id"])


task_dispatcher = TaskDispatcher()
