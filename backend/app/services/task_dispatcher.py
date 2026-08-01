"""Operation-to-handler dispatch for the unified task queue."""

from __future__ import annotations

import logging
from typing import Any

from backend.app.core.task_repository import TaskRepository, task_repository
from backend.app.services.task_handlers import (
    get_persistent_google_credentials,
    process_instagram_reel_task,
    process_youtube_metadata_task,
    process_youtube_publish_cleanup_task,
)

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


task_dispatcher = TaskDispatcher()
