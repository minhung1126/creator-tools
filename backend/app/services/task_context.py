"""Cooperative cancellation and checkpoint helpers for task handlers."""

from __future__ import annotations

from typing import Any, Optional

from backend.app.core.task_repository import TaskRepository, task_repository


class TaskCancellationRequested(RuntimeError):
    """Raised at a safe boundary when a worker should stop before an effect."""

    def __init__(self, task_id: str):
        super().__init__(f"Cancellation requested for task {task_id}")
        self.task_id = task_id


class TaskContext:
    def __init__(self, task_id: str, repository: TaskRepository = task_repository):
        self.task_id = task_id
        self.repository = repository

    @property
    def task(self) -> dict[str, Any]:
        task = self.repository.get_task_internal(self.task_id)
        if not task:
            raise KeyError(f"找不到任務 {self.task_id}")
        return task

    def refresh(self) -> dict[str, Any]:
        return self.task

    def is_cancel_requested(self) -> bool:
        return self.task.get("status") == "cancel_requested"

    def raise_if_cancel_requested(self) -> None:
        if self.is_cancel_requested():
            raise TaskCancellationRequested(self.task_id)

    def update(
        self,
        *,
        stage: Optional[str] = None,
        stage_label: Optional[str] = None,
        progress_percent: Optional[float] = None,
        checkpoint: Optional[dict[str, Any]] = None,
        result: Optional[dict[str, Any]] = None,
        error: Any = None,
        set_error: bool = False,
        message: str = "",
    ) -> dict[str, Any]:
        task = self.task
        kwargs = {
            "stage": stage,
            "stage_label": stage_label,
            "progress_percent": progress_percent,
            "checkpoint": checkpoint,
            "result": result,
            "message": message,
        }
        if set_error:
            kwargs["error"] = error
        return (
            self.repository.update_task(
                self.task_id,
                **kwargs,
            )
            or task
        )

    def checkpoint(
        self, values: dict[str, Any], *, stage: Optional[str] = None, progress_percent: Optional[float] = None
    ) -> dict[str, Any]:
        return self.update(stage=stage, progress_percent=progress_percent, checkpoint=values)

    def finish(
        self,
        status: str,
        *,
        stage: Optional[str] = None,
        progress_percent: Optional[float] = None,
        error: Any = None,
        cancel_too_late: Optional[bool] = None,
        retryable: Optional[bool] = None,
        message: str = "",
    ) -> dict[str, Any]:
        if status in {"canceled", "canceled_with_warnings"}:
            return (
                self.repository.finalize_canceled(
                    self.task_id,
                    warning=status == "canceled_with_warnings",
                    error=error,
                    message=message,
                )
                or self.task
            )
        kwargs = {
            "status": status,
            "stage": stage or status,
            "progress_percent": 100
            if progress_percent is None and status in {"succeeded", "succeeded_with_warnings", "skipped"}
            else progress_percent,
            "cancel_too_late": cancel_too_late,
            "retryable": retryable,
            "message": message,
        }
        if error is not None:
            kwargs["error"] = error
        return self.repository.update_task(self.task_id, **kwargs) or self.task
