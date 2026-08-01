"""Unified task queue, batch and notification APIs."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from google.oauth2.credentials import Credentials

from backend.app.core.dependencies import require_credentials
from backend.app.core.notification_repository import notification_repository
from backend.app.core.task_repository import task_repository
from backend.app.services.task_queue import task_queue

router = APIRouter(tags=["Activity Center"])


def _validate_platform(value: Optional[str]) -> Optional[str]:
    if value and value not in {"instagram", "youtube"}:
        raise HTTPException(status_code=400, detail="platform 必須為 instagram 或 youtube")
    return value


@router.get("/activity-summary")
def get_activity_summary(creds: Credentials = Depends(require_credentials)):
    del creds
    return task_repository.activity_summary()


@router.get("/tasks")
def list_activity_tasks(
    platform: Optional[str] = Query(None),
    operation: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    batch_id: Optional[str] = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    creds: Credentials = Depends(require_credentials),
):
    del creds
    items, total = task_repository.list_tasks(
        platform=_validate_platform(platform),
        operation=operation,
        status=status,
        batch_id=batch_id,
        offset=offset,
        limit=limit,
    )
    return {"items": items, "tasks": items, "total": total, "offset": offset, "limit": limit}


@router.post("/tasks/cancel-all")
def cancel_all_activity_tasks(creds: Credentials = Depends(require_credentials)):
    del creds
    result = task_repository.cancel_all()
    task_queue.wake()
    return result


@router.get("/tasks/{task_id}")
def get_activity_task(task_id: str, creds: Credentials = Depends(require_credentials)):
    del creds
    task = task_repository.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="找不到影片任務")
    return task


@router.post("/tasks/{task_id}/retry")
def retry_activity_task(task_id: str, creds: Credentials = Depends(require_credentials)):
    del creds
    try:
        task = task_repository.retry_task(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if task is None:
        raise HTTPException(status_code=404, detail="找不到影片任務")
    task_queue.submit(task_id)
    return {"accepted": True, "task": task_repository.get_task(task_id)}


@router.post("/tasks/{task_id}/cancel")
def cancel_activity_task(task_id: str, creds: Credentials = Depends(require_credentials)):
    del creds
    task = task_repository.request_cancel(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="找不到影片任務")
    task_queue.wake()
    return {"task": task_repository.public_task(task)}


@router.get("/task-batches")
def list_activity_batches(
    platform: Optional[str] = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    creds: Credentials = Depends(require_credentials),
):
    del creds
    items, total = task_repository.list_batches(offset=offset, limit=limit, platform=_validate_platform(platform))
    return {"items": items, "batches": items, "total": total, "offset": offset, "limit": limit}


@router.get("/task-batches/{batch_id}")
def get_activity_batch(batch_id: str, creds: Credentials = Depends(require_credentials)):
    del creds
    batch = task_repository.get_batch(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="找不到任務批次")
    return batch


@router.post("/task-batches/{batch_id}/retry")
def retry_activity_batch(batch_id: str, creds: Credentials = Depends(require_credentials)):
    del creds
    try:
        tasks = task_repository.retry_batch(batch_id)
    except ValueError as exc:
        if not task_repository.get_batch(batch_id):
            raise HTTPException(status_code=404, detail="找不到任務批次") from exc
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    task_queue.submit(batch_id)
    return {
        "accepted": True,
        "batch_id": batch_id,
        "task_ids": [task["id"] for task in tasks],
        "batch": task_repository.get_batch(batch_id),
    }


@router.post("/task-batches/{batch_id}/cancel")
def cancel_activity_batch(batch_id: str, creds: Credentials = Depends(require_credentials)):
    del creds
    if not task_repository.get_batch(batch_id):
        raise HTTPException(status_code=404, detail="找不到任務批次")
    result = task_repository.cancel_batch(batch_id)
    task_queue.wake()
    result["batch"] = task_repository.get_batch(batch_id)
    return result


@router.get("/notifications")
def list_activity_notifications(
    unread_only: bool = Query(False),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    creds: Credentials = Depends(require_credentials),
):
    del creds
    items, total = notification_repository.list(unread_only=unread_only, offset=offset, limit=limit)
    return {
        "items": items,
        "notifications": items,
        "total": total,
        "unread_count": notification_repository.unread_count(),
        "offset": offset,
        "limit": limit,
    }


@router.patch("/notifications/{notification_id}")
def mark_activity_notification_read(notification_id: int, creds: Credentials = Depends(require_credentials)):
    del creds
    notification = notification_repository.mark_read(notification_id)
    if not notification:
        raise HTTPException(status_code=404, detail="找不到通知")
    return notification


@router.post("/notifications/read-all")
def mark_all_activity_notifications_read(creds: Credentials = Depends(require_credentials)):
    del creds
    return {"marked_count": notification_repository.mark_all_read()}
