"""Durable task, batch, event and activity-center persistence.

This repository is deliberately the only layer that mutates the activity
center tables.  API handlers and workers receive plain dictionaries, while
payload/checkpoint/result JSON remains internal and is never used to build a
public DTO directly.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from backend.app.core.database import DATA_DIR, Database, database

ACTIVE_STATUSES = {"queued", "running", "cancel_requested"}
UNFINISHED_STATUSES = {"queued", "running", "cancel_requested", "paused"}
TERMINAL_STATUSES = {
    "failed",
    "skipped",
    "succeeded",
    "succeeded_with_warnings",
    "canceled",
    "canceled_with_warnings",
}
RETRYABLE_STATUSES = {"failed", "paused", "canceled", "canceled_with_warnings", "succeeded_with_warnings"}
LANES = {"instagram", "youtube"}

STAGE_LABELS = {
    "queued": "排隊中",
    "running": "處理中",
    "validating_video": "驗證影片",
    "updating_metadata": "更新標題與描述",
    "setting_public": "設定為公開",
    "public_updated": "已設為公開",
    "removing_playlist_item": "移出 To-Post",
    "downloading": "從 Google Drive 下載影片",
    "validating": "驗證 Meta 影片規格",
    "uploading_r2": "上傳到 Cloudflare R2",
    "uploaded": "R2 上傳完成",
    "creating_container": "建立 Instagram container",
    "container_created": "Instagram container 已建立",
    "waiting_container": "等待 Instagram 處理影片",
    "publishing": "發布 Instagram Reel",
    "published": "Instagram 已發布",
    "moving_drive": "移入 Google Drive Published",
    "cleaning_r2": "清理 R2 暫存影片",
    "drive_move_failed": "Drive 搬移失敗",
    "r2_cleanup_failed": "R2 清理失敗",
    "completed": "已完成",
    "failed": "失敗",
    "paused": "等待確認後重試",
    "skipped": "已略過",
    "canceled": "已取消",
    "cancel_requested": "正在取消",
    "canceled_with_warnings": "已取消但清理有警告",
}

_UNSET = object()
_SECRET_KEY_MARKERS = (
    "access_token",
    "refresh_token",
    "client_secret",
    "client_id",
    "authorization",
    "credential",
    "secret_access_key",
    "oauth",
    "bearer",
    "token",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_dumps(value: Any) -> str:
    try:
        return json.dumps(value if value is not None else {}, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        return "{}"


def _json_loads(value: Any, default: Any = None) -> Any:
    if value in (None, ""):
        return {} if default is None else default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return {} if default is None else default


def _safe_error(value: Any) -> Optional[str]:
    if value in (None, ""):
        return None
    text = str(value).strip()
    lowered = text.casefold()
    if len(text) > 240 or any(marker in lowered for marker in _SECRET_KEY_MARKERS):
        return "外部服務處理失敗，請檢查設定後重試。"
    return text


def sanitize_payload(value: Any) -> Any:
    """Remove credential-shaped keys before anything reaches task storage."""

    if isinstance(value, dict):
        result = {}
        for key, child in value.items():
            normalized = str(key).casefold().replace("-", "_")
            if any(marker in normalized for marker in _SECRET_KEY_MARKERS):
                continue
            result[str(key)] = sanitize_payload(child)
        return result
    if isinstance(value, list):
        return [sanitize_payload(child) for child in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _short_code(identifier: str) -> str:
    return (identifier or "")[:8].upper()


def _folder_id(value: Any) -> str:
    text = str(value or "").strip()
    match = re.search(r"/folders/([A-Za-z0-9_-]+)", text)
    return match.group(1) if match else text


def _task_dict(row, *, public: bool = False, queue_position: Optional[int] = None) -> dict[str, Any]:
    if row is None:
        return {}
    result = dict(row)
    result["retryable"] = bool(result.get("retryable"))
    result["cancel_too_late"] = bool(result.get("cancel_too_late"))
    for key in ("payload_json", "checkpoint_json", "result_json"):
        if key in result:
            result[key.removesuffix("_json")] = _json_loads(result.pop(key))
    if queue_position is not None:
        result["queue_position"] = queue_position
    return result


def _batch_dict(row, *, public: bool = False) -> dict[str, Any]:
    if row is None:
        return {}
    result = dict(row)
    result["metadata"] = _json_loads(result.pop("metadata_json", "{}"))
    if public:
        result["batch_short_code"] = _short_code(result.get("id", ""))
    return result


class TaskRepository:
    def __init__(self, db: Database = database):
        self.db = db
        self.db.initialize()

    @staticmethod
    def _new_id(prefix: str) -> str:
        return f"{prefix}_{secrets.token_urlsafe(15)}"

    @staticmethod
    def _stage_meta(stage: str, stage_label: Optional[str], progress_percent: Any) -> tuple[str, str, float]:
        normalized_stage = stage or "queued"
        label = stage_label or STAGE_LABELS.get(normalized_stage, normalized_stage)
        try:
            progress = min(max(float(progress_percent if progress_percent is not None else 0), 0), 100)
        except (TypeError, ValueError):
            progress = 0
        return normalized_stage, label, progress

    @staticmethod
    def _event_key(task_id: str, event_type: str, attempt: Any, suffix: str = "") -> str:
        return f"task:{task_id}:{event_type}:attempt:{attempt}:{suffix or secrets.token_hex(5)}"

    @staticmethod
    def _insert_event(
        connection,
        *,
        task_id: Optional[str],
        batch_id: str,
        event_type: str,
        from_status: Optional[str],
        to_status: Optional[str],
        message: str = "",
        event_key: Optional[str] = None,
        created_at: Optional[str] = None,
    ) -> str:
        key = event_key or f"event:{secrets.token_urlsafe(18)}"
        connection.execute(
            """
            INSERT OR IGNORE INTO task_events
              (task_id,batch_id,event_type,from_status,to_status,message,created_at,event_key)
            VALUES (?,?,?,?,?,?,?,?)
            """,
            (task_id, batch_id, event_type, from_status, to_status, message, created_at or utc_now(), key),
        )
        return key

    @staticmethod
    def _insert_notification(
        connection,
        *,
        event_key: str,
        notification_type: str,
        severity: str,
        title: str,
        message: str,
        task_id: Optional[str] = None,
        batch_id: Optional[str] = None,
        created_at: Optional[str] = None,
    ) -> None:
        connection.execute(
            """
            INSERT OR IGNORE INTO notifications
              (event_key,type,severity,title,message,task_id,batch_id,created_at)
            VALUES (?,?,?,?,?,?,?,?)
            """,
            (
                event_key,
                notification_type,
                severity,
                title,
                message,
                task_id,
                batch_id,
                created_at or utc_now(),
            ),
        )

    @staticmethod
    def _batch_status(statuses: list[str]) -> str:
        if not statuses:
            return "completed"
        if any(status == "cancel_requested" for status in statuses):
            return "cancel_requested"
        if any(status == "running" for status in statuses):
            return "running"
        if any(status == "queued" for status in statuses):
            return "queued"
        if any(status == "paused" for status in statuses):
            return "paused"
        if any(status in {"canceled", "canceled_with_warnings"} for status in statuses):
            if any(status not in {"canceled", "canceled_with_warnings"} for status in statuses):
                return "partially_canceled"
            return "canceled"
        if any(status == "failed" for status in statuses):
            return "failed"
        if any(status == "succeeded_with_warnings" for status in statuses):
            return "completed_with_warnings"
        return "completed"

    @staticmethod
    def _is_terminal(status: str) -> bool:
        return status in TERMINAL_STATUSES

    def _recompute_batch(self, connection, batch_id: str, *, notify: bool = True) -> dict[str, Any]:
        batch_row = connection.execute("SELECT * FROM task_batches WHERE id = ?", (batch_id,)).fetchone()
        if batch_row is None:
            return {}
        task_rows = connection.execute(
            "SELECT status FROM tasks WHERE batch_id = ? ORDER BY sequence_in_batch", (batch_id,)
        ).fetchall()
        statuses = [str(row["status"]) for row in task_rows]
        previous_status = str(batch_row["status"])
        next_status = self._batch_status(statuses)
        now = utc_now()
        completed_at = now if statuses and all(self._is_terminal(status) for status in statuses) else None
        connection.execute(
            "UPDATE task_batches SET status = ?, updated_at = ?, completed_at = ? WHERE id = ?",
            (next_status, now, completed_at, batch_id),
        )

        if (
            notify
            and next_status != previous_status
            and next_status
            in {
                "completed",
                "completed_with_warnings",
                "canceled",
                "partially_canceled",
            }
        ):
            counts = {status: statuses.count(status) for status in TERMINAL_STATUSES}
            max_attempt = connection.execute(
                "SELECT COALESCE(MAX(attempt), 1) AS attempt FROM tasks WHERE batch_id = ?", (batch_id,)
            ).fetchone()["attempt"]
            event_key = f"batch:{batch_id}:terminal:{max_attempt}:{next_status}"
            if next_status == "partially_canceled":
                title = "批次部分取消"
                severity = "warning"
                message = f"批次完成，但有 {counts.get('canceled', 0) + counts.get('canceled_with_warnings', 0)} 支影片已取消。"
                notification_type = "batch_partially_canceled"
            elif next_status == "canceled":
                title = "批次已取消"
                severity = "info"
                message = f"批次中的 {len(statuses)} 支影片都已取消，已完成的外部操作不會回滾。"
                notification_type = "batch_canceled"
            elif next_status == "completed_with_warnings":
                title = "批次完成但需要注意"
                severity = "warning"
                message = f"批次完成，{counts.get('succeeded_with_warnings', 0)} 支影片有清理警告。"
                notification_type = "batch_completed_with_warnings"
            else:
                title = "批次已完成"
                severity = "success"
                message = f"批次中的 {len(statuses)} 支影片已處理完成。"
                notification_type = "batch_completed"
            self._insert_event(
                connection,
                task_id=None,
                batch_id=batch_id,
                event_type="batch_status",
                from_status=previous_status,
                to_status=next_status,
                message=message,
                event_key=f"batch-event:{event_key}",
            )
            self._insert_notification(
                connection,
                event_key=event_key,
                notification_type=notification_type,
                severity=severity,
                title=title,
                message=message,
                batch_id=batch_id,
            )
        return _batch_dict(connection.execute("SELECT * FROM task_batches WHERE id = ?", (batch_id,)).fetchone())

    def create_batch_and_tasks(
        self,
        batch: dict[str, Any],
        task_specs: Iterable[dict[str, Any]],
        *,
        batch_id: Optional[str] = None,
        legacy_job_id: Optional[str] = None,
        notify: bool = True,
    ) -> dict[str, Any]:
        """Insert one batch and every child task in a single transaction."""

        specs = list(task_specs)
        requested_legacy_id = legacy_job_id or batch.get("legacy_job_id")
        with self.db.transaction() as connection:
            if requested_legacy_id:
                existing = connection.execute(
                    "SELECT * FROM task_batches WHERE legacy_job_id = ?", (requested_legacy_id,)
                ).fetchone()
                if existing is not None:
                    existing_batch = _batch_dict(existing)
                    existing_tasks = self._tasks_for_batch_connection(connection, existing_batch["id"])
                    return {"batch": existing_batch, "tasks": existing_tasks, "created": False}

            now = utc_now()
            actual_batch_id = batch_id or self._new_id("batch")
            platform = str(batch.get("platform") or (specs[0].get("platform") if specs else "")).strip() or "mixed"
            operation = str(batch.get("operation") or (specs[0].get("operation") if specs else "")).strip()
            failure_policy = str(batch.get("failure_policy") or "continue")
            metadata = sanitize_payload(batch.get("metadata") or batch.get("metadata_json") or {})
            connection.execute(
                """
                INSERT INTO task_batches
                  (id,platform,operation,failure_policy,status,total_count,created_at,updated_at,legacy_job_id,metadata_json)
                VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    actual_batch_id,
                    platform,
                    operation,
                    failure_policy,
                    "queued" if specs else "completed",
                    len(specs),
                    now,
                    now,
                    requested_legacy_id,
                    _json_dumps(metadata),
                ),
            )

            next_sequences: dict[str, int] = {}
            tasks: list[dict[str, Any]] = []
            for index, spec in enumerate(specs, start=1):
                lane = str(spec.get("queue_lane") or spec.get("platform") or platform).strip()
                if lane not in LANES:
                    lane = "youtube" if platform == "youtube" else "instagram"
                if lane not in next_sequences:
                    row = connection.execute(
                        "SELECT COALESCE(MAX(queue_sequence), 0) AS sequence FROM tasks WHERE queue_lane = ?",
                        (lane,),
                    ).fetchone()
                    next_sequences[lane] = int(row["sequence"] or 0) + 1
                queue_sequence = next_sequences[lane]
                next_sequences[lane] += 1
                task_id = str(spec.get("id") or self._new_id("task"))
                status = str(spec.get("status") or "queued")
                stage, stage_label, progress = self._stage_meta(
                    str(spec.get("stage") or "queued"), spec.get("stage_label"), spec.get("progress_percent", 0)
                )
                if status == "skipped":
                    stage, stage_label, progress = "skipped", STAGE_LABELS["skipped"], 100
                if status == "paused":
                    stage, stage_label = "paused", STAGE_LABELS["paused"]
                task_now = str(spec.get("created_at") or now)
                finished_at = task_now if status in TERMINAL_STATUSES else None
                payload = sanitize_payload(spec.get("payload") or {})
                checkpoint = sanitize_payload(spec.get("checkpoint") or {})
                result = sanitize_payload(spec.get("result") or {})
                connection.execute(
                    """
                    INSERT INTO tasks
                      (id,batch_id,platform,operation,queue_lane,queue_sequence,sequence_in_batch,
                       video_id,video_title,thumbnail_url,status,stage,stage_label,progress_percent,
                       attempt,retryable,created_at,queued_at,updated_at,finished_at,cancel_too_late,
                       error,payload_json,checkpoint_json,result_json,legacy_item_sequence)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        task_id,
                        actual_batch_id,
                        str(spec.get("platform") or platform),
                        str(spec.get("operation") or operation),
                        lane,
                        queue_sequence,
                        int(spec.get("sequence_in_batch") or index),
                        str(spec.get("video_id") or "") or None,
                        str(spec.get("video_title") or "") or None,
                        str(spec.get("thumbnail_url") or "") or None,
                        status,
                        stage,
                        stage_label,
                        progress,
                        int(spec.get("attempt") or 1),
                        1 if bool(spec.get("retryable", status not in {"skipped", "succeeded"})) else 0,
                        task_now,
                        task_now if status == "queued" else None,
                        task_now,
                        finished_at,
                        1 if bool(spec.get("cancel_too_late")) else 0,
                        _safe_error(spec.get("error")),
                        _json_dumps(payload),
                        _json_dumps(checkpoint),
                        _json_dumps(result),
                        spec.get("legacy_item_sequence"),
                    ),
                )
                event_type = "task_created" if status == "queued" else "task_imported"
                self._insert_event(
                    connection,
                    task_id=task_id,
                    batch_id=actual_batch_id,
                    event_type=event_type,
                    from_status=None,
                    to_status=status,
                    message="已建立影片任務" if status == "queued" else "已匯入歷史影片任務",
                    event_key=f"task:{task_id}:created:{spec.get('attempt') or 1}",
                    created_at=task_now,
                )
                tasks.append(_task_dict(connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()))
            final_batch = self._recompute_batch(connection, actual_batch_id, notify=notify)
            return {"batch": final_batch, "tasks": tasks, "created": True}

    def _tasks_for_batch_connection(self, connection, batch_id: str) -> list[dict[str, Any]]:
        return [
            _task_dict(row)
            for row in connection.execute(
                "SELECT * FROM tasks WHERE batch_id = ? ORDER BY sequence_in_batch, id", (batch_id,)
            ).fetchall()
        ]

    def get_task_internal(self, task_id: str) -> Optional[dict[str, Any]]:
        with self.db.connection() as connection:
            row = connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            return _task_dict(row) if row else None

    def get_task(self, task_id: str) -> Optional[dict[str, Any]]:
        task = self.get_task_internal(task_id)
        return self.public_task(task) if task else None

    def get_batch_internal(self, batch_id: str) -> Optional[dict[str, Any]]:
        with self.db.connection() as connection:
            row = connection.execute("SELECT * FROM task_batches WHERE id = ?", (batch_id,)).fetchone()
            if row is None:
                return None
            batch = _batch_dict(row)
            batch["tasks"] = self._tasks_for_batch_connection(connection, batch_id)
            return batch

    def get_batch(self, batch_id: str) -> Optional[dict[str, Any]]:
        batch = self.get_batch_internal(batch_id)
        return self.public_batch(batch) if batch else None

    def _queue_position(self, connection, task: dict[str, Any]) -> Optional[int]:
        if task.get("status") not in {"queued", "running", "cancel_requested"}:
            return None
        row = connection.execute(
            """
            SELECT COUNT(*) AS count FROM tasks
            WHERE queue_lane = ? AND status IN ('queued','running','cancel_requested')
              AND (queue_sequence < ? OR (queue_sequence = ? AND id <= ?))
            """,
            (task["queue_lane"], task["queue_sequence"], task["queue_sequence"], task["id"]),
        ).fetchone()
        return int(row["count"] or 0)

    def public_task(self, task: Optional[dict[str, Any]], *, connection=None) -> Optional[dict[str, Any]]:
        if not task:
            return None
        if connection is None:
            with self.db.connection() as owned:
                return self.public_task(task, connection=owned)
        safe = {
            key: task.get(key)
            for key in (
                "id",
                "batch_id",
                "platform",
                "operation",
                "queue_lane",
                "queue_sequence",
                "sequence_in_batch",
                "video_id",
                "video_title",
                "thumbnail_url",
                "status",
                "stage",
                "stage_label",
                "progress_percent",
                "attempt",
                "retryable",
                "created_at",
                "queued_at",
                "started_at",
                "updated_at",
                "finished_at",
                "cancel_requested_at",
                "canceled_at",
                "cancel_scope",
                "cancel_reason",
                "cancel_too_late",
                "error",
            )
        }
        safe["queue_position"] = self._queue_position(connection, task)
        safe["batch_short_code"] = _short_code(str(task.get("batch_id") or ""))
        return safe

    def public_batch(self, batch: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
        if not batch:
            return None
        safe = {
            key: batch.get(key)
            for key in (
                "id",
                "platform",
                "operation",
                "failure_policy",
                "status",
                "total_count",
                "created_at",
                "updated_at",
                "completed_at",
                "legacy_job_id",
            )
        }
        safe["batch_short_code"] = _short_code(str(batch.get("id") or ""))
        safe["tasks"] = [self.public_task(task) for task in batch.get("tasks", [])]
        counts: dict[str, int] = dict(batch.get("counts") or {})
        for task in batch.get("tasks", []):
            counts[task.get("status", "unknown")] = counts.get(task.get("status", "unknown"), 0) + 1
        safe["counts"] = counts
        return safe

    def list_tasks(
        self,
        *,
        platform: Optional[str] = None,
        operation: Optional[str] = None,
        status: Optional[str] = None,
        batch_id: Optional[str] = None,
        sort: str = "submission",
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[dict[str, Any]], int]:
        clauses: list[str] = []
        values: list[Any] = []
        for field, value in (
            ("platform", platform),
            ("operation", operation),
            ("status", status),
            ("batch_id", batch_id),
        ):
            if value:
                clauses.append(f"{field} = ?")
                values.append(value)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        safe_offset = max(int(offset), 0)
        safe_limit = min(max(int(limit), 1), 100)
        order_by = (
            "updated_at DESC, id DESC"
            if sort == "updated_desc"
            else "created_at ASC, queue_sequence ASC, sequence_in_batch ASC, id ASC"
        )
        with self.db.connection() as connection:
            total = int(connection.execute(f"SELECT COUNT(*) AS count FROM tasks {where}", values).fetchone()["count"])
            rows = connection.execute(
                f"SELECT * FROM tasks {where} ORDER BY {order_by} LIMIT ? OFFSET ?",
                [*values, safe_limit, safe_offset],
            ).fetchall()
            public = []
            for row in rows:
                task = _task_dict(row)
                public.append(self.public_task(task, connection=connection))
            return public, total

    def list_batches(
        self, *, offset: int = 0, limit: int = 50, platform: Optional[str] = None
    ) -> tuple[list[dict[str, Any]], int]:
        clauses: list[str] = []
        values: list[Any] = []
        if platform:
            clauses.append("platform = ?")
            values.append(platform)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        safe_offset = max(int(offset), 0)
        safe_limit = min(max(int(limit), 1), 100)
        with self.db.connection() as connection:
            total = int(
                connection.execute(f"SELECT COUNT(*) AS count FROM task_batches {where}", values).fetchone()["count"]
            )
            rows = connection.execute(
                f"SELECT * FROM task_batches {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
                [*values, safe_limit, safe_offset],
            ).fetchall()
            batches = []
            for row in rows:
                batch = _batch_dict(row)
                count_rows = connection.execute(
                    "SELECT status, COUNT(*) AS count FROM tasks WHERE batch_id = ? GROUP BY status",
                    (batch["id"],),
                ).fetchall()
                batch["counts"] = {str(count_row["status"]): int(count_row["count"]) for count_row in count_rows}
                batch["tasks"] = []
                batches.append(self.public_batch(batch))
            return batches, total

    def update_task(
        self,
        task_id: str,
        *,
        status: Optional[str] = None,
        stage: Optional[str] = None,
        stage_label: Optional[str] = None,
        progress_percent: Any = None,
        checkpoint: Optional[dict[str, Any]] = None,
        result: Optional[dict[str, Any]] = None,
        error: Any = _UNSET,
        retryable: Optional[bool] = None,
        cancel_too_late: Optional[bool] = None,
        message: str = "",
        event_type: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        with self.db.transaction() as connection:
            current_row = connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if current_row is None:
                return None
            current = _task_dict(current_row)
            next_status = status or current["status"]
            next_stage = stage or current["stage"]
            next_stage, next_label, next_progress = self._stage_meta(
                next_stage,
                stage_label or (STAGE_LABELS.get(next_stage) if stage else current.get("stage_label")),
                progress_percent if progress_percent is not None else current.get("progress_percent"),
            )
            next_checkpoint = dict(current.get("checkpoint") or {})
            if checkpoint:
                next_checkpoint.update(sanitize_payload(checkpoint))
            next_result = dict(current.get("result") or {})
            if result:
                next_result.update(sanitize_payload(result))
            now = utc_now()
            finished_at = current.get("finished_at")
            if next_status in TERMINAL_STATUSES:
                finished_at = finished_at or now
            fields = [
                "status = ?",
                "stage = ?",
                "stage_label = ?",
                "progress_percent = ?",
                "updated_at = ?",
                "finished_at = ?",
                "checkpoint_json = ?",
                "result_json = ?",
            ]
            values: list[Any] = [
                next_status,
                next_stage,
                next_label,
                next_progress,
                now,
                finished_at,
                _json_dumps(next_checkpoint),
                _json_dumps(next_result),
            ]
            if error is not _UNSET:
                fields.append("error = ?")
                values.append(_safe_error(error))
            if retryable is not None:
                fields.append("retryable = ?")
                values.append(1 if retryable else 0)
            if cancel_too_late is not None:
                fields.append("cancel_too_late = ?")
                values.append(1 if cancel_too_late else 0)
            values.append(task_id)
            connection.execute(f"UPDATE tasks SET {', '.join(fields)} WHERE id = ?", values)

            changed_status = current["status"] != next_status
            changed_stage = current["stage"] != next_stage
            if changed_status or changed_stage or event_type:
                type_name = event_type or ("status_changed" if changed_status else "stage_changed")
                event_message = message or next_label
                self._insert_event(
                    connection,
                    task_id=task_id,
                    batch_id=current["batch_id"],
                    event_type=type_name,
                    from_status=current["status"],
                    to_status=next_status,
                    message=event_message,
                    event_key=self._event_key(task_id, type_name, current.get("attempt"), f"{now}:{next_stage}"),
                    created_at=now,
                )
            if changed_status:
                self._task_notifications(
                    connection,
                    current,
                    next_status,
                    error if error is not _UNSET else current.get("error"),
                    cancel_too_late,
                )
            self._recompute_batch(connection, current["batch_id"])
            row = connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            return _task_dict(row)

    def _task_notifications(
        self,
        connection,
        previous: dict[str, Any],
        status: str,
        error: Any,
        cancel_too_late: Optional[bool],
    ) -> None:
        task_id = previous["id"]
        batch_id = previous["batch_id"]
        attempt = previous.get("attempt", 1)
        if status == "failed":
            event_key = f"task:{task_id}:failed:attempt:{attempt}"
            self._insert_notification(
                connection,
                event_key=event_key,
                notification_type="task_failed",
                severity="error",
                title="影片任務失敗",
                message=_safe_error(error) or "影片任務失敗，請檢查後重試。",
                task_id=task_id,
                batch_id=batch_id,
            )
        elif status == "paused":
            event_key = f"task:{task_id}:paused:attempt:{attempt}"
            self._insert_notification(
                connection,
                event_key=event_key,
                notification_type="task_paused",
                severity="warning",
                title="影片任務已暫停",
                message=_safe_error(error) or "此影片任務已暫停，請確認後重試。",
                task_id=task_id,
                batch_id=batch_id,
            )
        elif status == "succeeded_with_warnings":
            event_key = f"task:{task_id}:warning:attempt:{attempt}"
            self._insert_notification(
                connection,
                event_key=event_key,
                notification_type="task_warning",
                severity="warning",
                title="影片任務完成但清理有警告",
                message=_safe_error(error) or "外部操作已完成，但後續清理需要重試。",
                task_id=task_id,
                batch_id=batch_id,
            )
        elif status == "canceled_with_warnings":
            event_key = f"task:{task_id}:canceled-warning:attempt:{attempt}"
            self._insert_notification(
                connection,
                event_key=event_key,
                notification_type="canceled_with_warnings",
                severity="warning",
                title="任務已取消但清理有警告",
                message=_safe_error(error) or "取消後的暫存清理失敗，請重試清理。",
                task_id=task_id,
                batch_id=batch_id,
            )
        if bool(cancel_too_late) or (
            status in TERMINAL_STATUSES and bool(previous.get("cancel_requested_at")) and status.startswith("succeeded")
        ):
            event_key = f"task:{task_id}:cancel-too-late:attempt:{attempt}"
            self._insert_notification(
                connection,
                event_key=event_key,
                notification_type="cancel_too_late",
                severity="warning",
                title="取消要求太晚，操作已完成",
                message="取消要求送達時外部操作已完成，系統不會回滾該操作。",
                task_id=task_id,
                batch_id=batch_id,
            )

    def claim_next(self, queue_lane: str) -> Optional[dict[str, Any]]:
        lane = queue_lane if queue_lane in LANES else "youtube"
        with self.db.transaction() as connection:
            row = connection.execute(
                """
                SELECT * FROM tasks
                WHERE queue_lane = ? AND status = 'queued' AND cancel_requested_at IS NULL
                ORDER BY queue_sequence ASC, id ASC LIMIT 1
                """,
                (lane,),
            ).fetchone()
            if row is None:
                return None
            task = _task_dict(row)
            # The condition is repeated in the UPDATE so a cancellation that
            # committed between a read and a write can never be claimed.
            now = utc_now()
            updated = connection.execute(
                """
                UPDATE tasks
                SET status='running', stage='running', stage_label=?, started_at=COALESCE(started_at,?),
                    updated_at=?, queued_at=COALESCE(queued_at,?)
                WHERE id=? AND status='queued' AND cancel_requested_at IS NULL
                """,
                (STAGE_LABELS["running"], now, now, now, task["id"]),
            )
            if updated.rowcount != 1:
                return None
            self._insert_event(
                connection,
                task_id=task["id"],
                batch_id=task["batch_id"],
                event_type="claimed",
                from_status="queued",
                to_status="running",
                message="Worker 已取得任務",
                event_key=f"task:{task['id']}:claimed:attempt:{task.get('attempt', 1)}:{now}",
                created_at=now,
            )
            self._recompute_batch(connection, task["batch_id"], notify=False)
            return _task_dict(connection.execute("SELECT * FROM tasks WHERE id = ?", (task["id"],)).fetchone())

    def claim_batch(self, queue_lane: str, *, limit: int = 50) -> list[dict[str, Any]]:
        """Claim the next contiguous batch in a lane as one worker unit.

        Instagram's Graph API can combine child requests, but doing so safely
        requires the worker to see the complete ordered group before it starts
        the first external call.  This method keeps the existing
        ``claim_next`` API for single-task consumers while allowing the
        Instagram lane to claim one contiguous submitted batch atomically.
        """

        lane = queue_lane if queue_lane in LANES else "youtube"
        safe_limit = min(max(int(limit), 1), 50)
        with self.db.transaction() as connection:
            rows = connection.execute(
                """
                SELECT * FROM tasks
                WHERE queue_lane = ? AND status = 'queued' AND cancel_requested_at IS NULL
                ORDER BY queue_sequence ASC, id ASC
                LIMIT ?
                """,
                (lane, safe_limit),
            ).fetchall()
            if not rows:
                return []
            first_batch_id = str(rows[0]["batch_id"])
            claim_rows = []
            for row in rows:
                if str(row["batch_id"]) != first_batch_id:
                    break
                claim_rows.append(row)
            if not claim_rows:
                return []

            now = utc_now()
            claimed_ids: list[str] = []
            for row in claim_rows:
                task_id = str(row["id"])
                updated = connection.execute(
                    """
                    UPDATE tasks
                    SET status='running', stage='running', stage_label=?, started_at=COALESCE(started_at,?),
                        updated_at=?, queued_at=COALESCE(queued_at,?)
                    WHERE id=? AND status='queued' AND cancel_requested_at IS NULL
                    """,
                    (STAGE_LABELS["running"], now, now, now, task_id),
                )
                if updated.rowcount != 1:
                    continue
                claimed_ids.append(task_id)
                self._insert_event(
                    connection,
                    task_id=task_id,
                    batch_id=first_batch_id,
                    event_type="claimed",
                    from_status="queued",
                    to_status="running",
                    message="Worker 已取得批次任務",
                    event_key=f"task:{task_id}:claimed:attempt:{row['attempt']}:{now}",
                    created_at=now,
                )
            if claimed_ids:
                self._recompute_batch(connection, first_batch_id, notify=False)
            return [
                _task_dict(connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone())
                for task_id in claimed_ids
            ]

    def request_cancel(
        self, task_id: str, *, scope: str = "task", reason: str = "使用者要求取消"
    ) -> Optional[dict[str, Any]]:
        with self.db.transaction() as connection:
            row = connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if row is None:
                return None
            current = _task_dict(row)
            if current["status"] in TERMINAL_STATUSES:
                return current
            now = utc_now()
            if current["status"] in {"queued", "paused"}:
                next_status = "canceled"
                fields = "status=?, stage=?, stage_label=?, progress_percent=?, updated_at=?, finished_at=?, canceled_at=?, cancel_requested_at=?, cancel_scope=?, cancel_reason=?"
                values = (
                    next_status,
                    "canceled",
                    STAGE_LABELS["canceled"],
                    current.get("progress_percent", 0),
                    now,
                    now,
                    now,
                    now,
                    scope,
                    _safe_error(reason),
                    task_id,
                )
            else:
                next_status = "cancel_requested"
                fields = "status=?, stage=?, stage_label=?, updated_at=?, cancel_requested_at=?, cancel_scope=?, cancel_reason=?"
                values = (
                    next_status,
                    "cancel_requested",
                    STAGE_LABELS["cancel_requested"],
                    now,
                    now,
                    scope,
                    _safe_error(reason),
                    task_id,
                )
            connection.execute(f"UPDATE tasks SET {fields} WHERE id = ?", values)
            self._insert_event(
                connection,
                task_id=task_id,
                batch_id=current["batch_id"],
                event_type="cancel_requested" if next_status == "cancel_requested" else "canceled",
                from_status=current["status"],
                to_status=next_status,
                message=_safe_error(reason) or "使用者要求取消",
                event_key=f"task:{task_id}:cancel:{current.get('attempt', 1)}:{now}",
                created_at=now,
            )
            self._recompute_batch(connection, current["batch_id"])
            return _task_dict(connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone())

    def finalize_canceled(
        self,
        task_id: str,
        *,
        warning: bool = False,
        error: Any = None,
        message: str = "任務已安全取消",
    ) -> Optional[dict[str, Any]]:
        """Finish a running cancellation without pretending an external rollback occurred."""

        with self.db.transaction() as connection:
            row = connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if row is None:
                return None
            current = _task_dict(row)
            now = utc_now()
            next_status = "canceled_with_warnings" if warning else "canceled"
            connection.execute(
                """
                UPDATE tasks SET status=?,stage=?,stage_label=?,updated_at=?,finished_at=?,canceled_at=?,
                  retryable=?,error=? WHERE id=?
                """,
                (
                    next_status,
                    "canceled_with_warnings" if warning else "canceled",
                    STAGE_LABELS["canceled_with_warnings"] if warning else STAGE_LABELS["canceled"],
                    now,
                    now,
                    now,
                    1,
                    _safe_error(error),
                    task_id,
                ),
            )
            self._insert_event(
                connection,
                task_id=task_id,
                batch_id=current["batch_id"],
                event_type="canceled_with_warnings" if warning else "canceled",
                from_status=current["status"],
                to_status=next_status,
                message=_safe_error(error) or message,
                event_key=f"task:{task_id}:finished-cancel:{current.get('attempt', 1)}:{now}",
                created_at=now,
            )
            if warning:
                self._insert_notification(
                    connection,
                    event_key=f"task:{task_id}:canceled-warning:attempt:{current.get('attempt', 1)}",
                    notification_type="canceled_with_warnings",
                    severity="warning",
                    title="任務已取消但清理有警告",
                    message=_safe_error(error) or "取消後的清理失敗，請重試清理。",
                    task_id=task_id,
                    batch_id=current["batch_id"],
                )
            self._recompute_batch(connection, current["batch_id"])
            return _task_dict(connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone())

    def cancel_batch(self, batch_id: str, *, reason: str = "使用者要求取消整個批次") -> dict[str, Any]:
        return self._cancel_where("batch_id = ?", (batch_id,), scope="batch", reason=reason)

    def cancel_all(self, *, reason: str = "使用者要求取消所有未完成任務") -> dict[str, Any]:
        with self.db.transaction() as connection:
            total = int(connection.execute("SELECT COUNT(*) AS count FROM tasks").fetchone()["count"])
            rows = connection.execute(
                "SELECT * FROM tasks WHERE status IN ('queued','running','paused','cancel_requested') ORDER BY queue_sequence"
            ).fetchall()
            immediate = 0
            requested = 0
            now = utc_now()
            touched_batches: set[str] = set()
            transitioned = 0
            for row in rows:
                current = _task_dict(row)
                touched_batches.add(current["batch_id"])
                if current["status"] == "cancel_requested":
                    # It is already in the requested state. Keep it in the
                    # response for the complete target-set semantics, but do
                    # not append another event or notification on a repeat.
                    requested += 1
                    continue
                if current["status"] in {"queued", "paused"}:
                    connection.execute(
                        """
                        UPDATE tasks SET status='canceled',stage='canceled',stage_label=?,updated_at=?,finished_at=?,
                          canceled_at=?,cancel_requested_at=?,cancel_scope='all',cancel_reason=? WHERE id=?
                        """,
                        (STAGE_LABELS["canceled"], now, now, now, now, _safe_error(reason), current["id"]),
                    )
                    immediate += 1
                    next_status = "canceled"
                else:
                    requested += 1
                    connection.execute(
                        """
                        UPDATE tasks SET status='cancel_requested',stage='cancel_requested',stage_label=?,
                          updated_at=?,cancel_requested_at=?,cancel_scope='all',cancel_reason=? WHERE id=?
                        """,
                        (STAGE_LABELS["cancel_requested"], now, now, _safe_error(reason), current["id"]),
                    )
                    next_status = "cancel_requested"
                transitioned += 1
                self._insert_event(
                    connection,
                    task_id=current["id"],
                    batch_id=current["batch_id"],
                    event_type="cancel_all",
                    from_status=current["status"],
                    to_status=next_status,
                    message=_safe_error(reason) or "取消所有未完成任務",
                    event_key=f"task:{current['id']}:cancel-all:{now}",
                    created_at=now,
                )
            for batch_id in touched_batches:
                self._recompute_batch(connection, batch_id)
            affected = len(rows)
            global_event = (
                f"cancel-all:{','.join(sorted(current['id'] for current in (_task_dict(row) for row in rows)))}"
            )
            if transitioned:
                self._insert_notification(
                    connection,
                    event_key=global_event,
                    notification_type="cancel_all",
                    severity="info",
                    title="已送出取消所有未完成任務",
                    message=f"已取消 {immediate} 支排隊／暫停任務，另有 {requested} 支正在安全停止。",
                )
            return {
                "requested_count": affected,
                "canceled_immediately_count": immediate,
                "cancel_requested_count": requested,
                "unaffected_count": max(total - affected, 0),
            }

    def _cancel_where(self, where: str, values: tuple[Any, ...], *, scope: str, reason: str) -> dict[str, Any]:
        with self.db.transaction() as connection:
            rows = connection.execute(
                f"SELECT * FROM tasks WHERE {where} AND status IN ('queued','running','paused','cancel_requested')",
                values,
            ).fetchall()
            immediate = 0
            requested = 0
            now = utc_now()
            batch_ids: set[str] = set()
            for row in rows:
                current = _task_dict(row)
                batch_ids.add(current["batch_id"])
                if current["status"] in {"queued", "paused"}:
                    connection.execute(
                        """
                        UPDATE tasks SET status='canceled',stage='canceled',stage_label=?,updated_at=?,finished_at=?,
                          canceled_at=?,cancel_requested_at=?,cancel_scope=?,cancel_reason=? WHERE id=?
                        """,
                        (STAGE_LABELS["canceled"], now, now, now, now, scope, _safe_error(reason), current["id"]),
                    )
                    immediate += 1
                    next_status = "canceled"
                else:
                    requested += 1
                    if current["status"] != "cancel_requested":
                        connection.execute(
                            """
                            UPDATE tasks SET status='cancel_requested',stage='cancel_requested',stage_label=?,updated_at=?,
                              cancel_requested_at=?,cancel_scope=?,cancel_reason=? WHERE id=?
                            """,
                            (STAGE_LABELS["cancel_requested"], now, now, scope, _safe_error(reason), current["id"]),
                        )
                    next_status = "cancel_requested"
                self._insert_event(
                    connection,
                    task_id=current["id"],
                    batch_id=current["batch_id"],
                    event_type="cancel_requested" if next_status == "cancel_requested" else "canceled",
                    from_status=current["status"],
                    to_status=next_status,
                    message=_safe_error(reason) or "使用者要求取消",
                    event_key=f"task:{current['id']}:cancel:{scope}:{now}",
                    created_at=now,
                )
            for batch_id in batch_ids:
                self._recompute_batch(connection, batch_id)
            return {
                "batch_id": values[0] if scope == "batch" and values else None,
                "requested_count": len(rows),
                "canceled_immediately_count": immediate,
                "cancel_requested_count": requested,
            }

    def _eligible_for_retry(self, task: dict[str, Any]) -> bool:
        status = task.get("status")
        if status not in RETRYABLE_STATUSES or not task.get("retryable", True):
            return False
        if status == "succeeded_with_warnings":
            checkpoint = task.get("checkpoint") or {}
            if not any(
                checkpoint.get(key) for key in ("drive_move_error", "r2_delete_error", "playlist_cleanup_error")
            ):
                return False
        if status == "succeeded" and task.get("cancel_too_late"):
            return False
        return True

    def retry_task(self, task_id: str) -> Optional[dict[str, Any]]:
        with self.db.transaction() as connection:
            row = connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if row is None:
                return None
            current = _task_dict(row)
            if not self._eligible_for_retry(current):
                raise ValueError("目前沒有可重試的未完成階段")
            now = utc_now()
            next_attempt = int(current.get("attempt") or 1) + 1
            max_sequence = connection.execute(
                "SELECT COALESCE(MAX(queue_sequence), 0) AS sequence FROM tasks WHERE queue_lane = ?",
                (current["queue_lane"],),
            ).fetchone()["sequence"]
            connection.execute(
                """
                UPDATE tasks SET status='queued',stage='queued',stage_label=?,progress_percent=0,attempt=?,
                  retryable=1,queue_sequence=?,queued_at=?,started_at=NULL,updated_at=?,finished_at=NULL,
                  cancel_requested_at=NULL,canceled_at=NULL,cancel_scope=NULL,cancel_reason=NULL,
                  cancel_too_late=0,error=NULL WHERE id=?
                """,
                (STAGE_LABELS["queued"], next_attempt, int(max_sequence) + 1, now, now, task_id),
            )
            self._insert_event(
                connection,
                task_id=task_id,
                batch_id=current["batch_id"],
                event_type="retried",
                from_status=current["status"],
                to_status="queued",
                message="已重新排入隊列",
                event_key=f"task:{task_id}:retry:attempt:{next_attempt}",
                created_at=now,
            )
            self._recompute_batch(connection, current["batch_id"], notify=False)
            return _task_dict(connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone())

    def retry_batch(self, batch_id: str) -> list[dict[str, Any]]:
        with self.db.transaction() as connection:
            rows = connection.execute(
                "SELECT * FROM tasks WHERE batch_id = ? ORDER BY sequence_in_batch ASC, id ASC", (batch_id,)
            ).fetchall()
            eligible = [task for task in (_task_dict(row) for row in rows) if self._eligible_for_retry(task)]
            if not eligible:
                raise ValueError("此批次目前沒有可重試的未完成任務")
            next_sequence = connection.execute(
                "SELECT COALESCE(MAX(queue_sequence), 0) AS sequence FROM tasks WHERE queue_lane = 'instagram'"
            ).fetchone()["sequence"]
            next_by_lane: dict[str, int] = {"instagram": int(next_sequence) + 1}
            for lane in ("youtube",):
                value = connection.execute(
                    "SELECT COALESCE(MAX(queue_sequence), 0) AS sequence FROM tasks WHERE queue_lane = ?", (lane,)
                ).fetchone()["sequence"]
                next_by_lane[lane] = int(value) + 1
            now = utc_now()
            for task in eligible:
                lane = task["queue_lane"]
                queue_sequence = next_by_lane.get(lane, 1)
                next_by_lane[lane] = queue_sequence + 1
                next_attempt = int(task.get("attempt") or 1) + 1
                connection.execute(
                    """
                    UPDATE tasks SET status='queued',stage='queued',stage_label=?,progress_percent=0,attempt=?,
                      retryable=1,queue_sequence=?,queued_at=?,started_at=NULL,updated_at=?,finished_at=NULL,
                      cancel_requested_at=NULL,canceled_at=NULL,cancel_scope=NULL,cancel_reason=NULL,
                      cancel_too_late=0,error=NULL WHERE id=?
                    """,
                    (STAGE_LABELS["queued"], next_attempt, queue_sequence, now, now, task["id"]),
                )
                self._insert_event(
                    connection,
                    task_id=task["id"],
                    batch_id=batch_id,
                    event_type="retried",
                    from_status=task["status"],
                    to_status="queued",
                    message="已重新排入隊列",
                    event_key=f"task:{task['id']}:retry:attempt:{next_attempt}",
                    created_at=now,
                )
            self._recompute_batch(connection, batch_id, notify=False)
            return self._tasks_for_batch_connection(connection, batch_id)

    def pause_remaining_tasks(self, batch_id: str, *, after_sequence: Optional[int] = None, reason: str) -> int:
        with self.db.transaction() as connection:
            clauses = ["batch_id = ?", "status = 'queued'"]
            values: list[Any] = [batch_id]
            if after_sequence is not None:
                clauses.append("sequence_in_batch > ?")
                values.append(after_sequence)
            rows = connection.execute(
                f"SELECT * FROM tasks WHERE {' AND '.join(clauses)} ORDER BY sequence_in_batch", values
            ).fetchall()
            now = utc_now()
            for row in rows:
                current = _task_dict(row)
                connection.execute(
                    "UPDATE tasks SET status='paused',stage='paused',stage_label=?,updated_at=?,error=? WHERE id=?",
                    (STAGE_LABELS["paused"], now, _safe_error(reason), current["id"]),
                )
                self._insert_event(
                    connection,
                    task_id=current["id"],
                    batch_id=batch_id,
                    event_type="paused_by_batch_failure",
                    from_status="queued",
                    to_status="paused",
                    message=_safe_error(reason) or "前一支影片失敗，後續任務已暫停",
                    event_key=f"task:{current['id']}:paused-by-failure:{current.get('attempt', 1)}",
                    created_at=now,
                )
                self._insert_notification(
                    connection,
                    event_key=f"task:{current['id']}:paused:attempt:{current.get('attempt', 1)}",
                    notification_type="task_paused",
                    severity="warning",
                    title="後續影片任務已暫停",
                    message=_safe_error(reason) or "前一支影片失敗，請確認後重試。",
                    task_id=current["id"],
                    batch_id=batch_id,
                )
            self._recompute_batch(connection, batch_id)
            return len(rows)

    def pause_or_cancel_claimed_tasks(
        self,
        batch_id: str,
        *,
        after_sequence: Optional[int] = None,
        reason: str,
    ) -> int:
        """Pause claimed siblings while honoring cancellation requests.

        Instagram tasks are claimed as one bounded worker unit.  A failure in
        an earlier child therefore has to release the later claimed children.
        A child that was canceled while the batch was running must become
        canceled, not paused, otherwise the user's cancellation is silently
        lost and the task becomes retryable again.
        """

        with self.db.transaction() as connection:
            clauses = ["batch_id = ?", "status IN ('running','cancel_requested')"]
            values: list[Any] = [batch_id]
            if after_sequence is not None:
                clauses.append("sequence_in_batch > ?")
                values.append(after_sequence)
            rows = connection.execute(
                f"SELECT * FROM tasks WHERE {' AND '.join(clauses)} ORDER BY sequence_in_batch", values
            ).fetchall()
            now = utc_now()
            for row in rows:
                current = _task_dict(row)
                canceled = current["status"] == "cancel_requested"
                next_status = "canceled" if canceled else "paused"
                next_stage = next_status
                connection.execute(
                    """
                    UPDATE tasks SET status=?,stage=?,stage_label=?,updated_at=?,finished_at=?,canceled_at=?,error=?
                    WHERE id=? AND status IN ('running','cancel_requested')
                    """,
                    (
                        next_status,
                        next_stage,
                        STAGE_LABELS[next_stage],
                        now,
                        now if canceled else None,
                        now if canceled else None,
                        None if canceled else _safe_error(reason),
                        current["id"],
                    ),
                )
                event_type = "canceled" if canceled else "paused_by_batch_failure"
                self._insert_event(
                    connection,
                    task_id=current["id"],
                    batch_id=batch_id,
                    event_type=event_type,
                    from_status=current["status"],
                    to_status=next_status,
                    message=current.get("cancel_reason") if canceled else (_safe_error(reason) or reason),
                    event_key=f"task:{current['id']}:{event_type}:attempt:{current.get('attempt', 1)}",
                    created_at=now,
                )
                if not canceled:
                    self._insert_notification(
                        connection,
                        event_key=f"task:{current['id']}:paused:attempt:{current.get('attempt', 1)}",
                        notification_type="task_paused",
                        severity="warning",
                        title="後續影片任務已暫停",
                        message=_safe_error(reason) or "前一支影片失敗，請確認後重試。",
                        task_id=current["id"],
                        batch_id=batch_id,
                    )
            self._recompute_batch(connection, batch_id)
            return len(rows)

    def recover_after_restart(self) -> int:
        """Turn interrupted workers into paused tasks and leave checkpoints intact."""

        with self.db.transaction() as connection:
            rows = connection.execute(
                "SELECT * FROM tasks WHERE status IN ('running','cancel_requested') ORDER BY updated_at"
            ).fetchall()
            now = utc_now()
            batch_ids: set[str] = set()
            for row in rows:
                current = _task_dict(row)
                batch_ids.add(current["batch_id"])
                message = "服務重新啟動，請確認 checkpoint 後重試；系統沒有自動重新發布。"
                connection.execute(
                    "UPDATE tasks SET status='paused',stage='paused',stage_label=?,updated_at=?,error=? WHERE id=?",
                    (STAGE_LABELS["paused"], now, message, current["id"]),
                )
                key = f"task:{current['id']}:service-restart:attempt:{current.get('attempt', 1)}"
                self._insert_event(
                    connection,
                    task_id=current["id"],
                    batch_id=current["batch_id"],
                    event_type="service_restart",
                    from_status=current["status"],
                    to_status="paused",
                    message=message,
                    event_key=f"event:{key}",
                    created_at=now,
                )
                self._insert_notification(
                    connection,
                    event_key=key,
                    notification_type="service_restart",
                    severity="warning",
                    title="服務重新啟動造成任務中斷",
                    message=message,
                    task_id=current["id"],
                    batch_id=current["batch_id"],
                )
            for batch_id in batch_ids:
                self._recompute_batch(connection, batch_id, notify=False)
            return len(rows)

    def pause_queued_without_credentials(
        self, *, message: str = "找不到持久化 Google credential，請重新登入後確認並重試。"
    ) -> int:
        with self.db.transaction() as connection:
            rows = connection.execute("SELECT * FROM tasks WHERE status = 'queued'").fetchall()
            now = utc_now()
            batch_ids: set[str] = set()
            for row in rows:
                current = _task_dict(row)
                batch_ids.add(current["batch_id"])
                connection.execute(
                    "UPDATE tasks SET status='paused',stage='paused',stage_label=?,updated_at=?,error=? WHERE id=?",
                    (STAGE_LABELS["paused"], now, _safe_error(message), current["id"]),
                )
                key = f"task:{current['id']}:credentials-unavailable:attempt:{current.get('attempt', 1)}"
                self._insert_event(
                    connection,
                    task_id=current["id"],
                    batch_id=current["batch_id"],
                    event_type="credentials_unavailable",
                    from_status="queued",
                    to_status="paused",
                    message=message,
                    event_key=f"event:{key}",
                    created_at=now,
                )
                self._insert_notification(
                    connection,
                    event_key=key,
                    notification_type="credentials_unavailable",
                    severity="error",
                    title="無法使用 Google credential",
                    message=message,
                    task_id=current["id"],
                    batch_id=current["batch_id"],
                )
            for batch_id in batch_ids:
                self._recompute_batch(connection, batch_id, notify=False)
            return len(rows)

    def activity_summary(self) -> dict[str, Any]:
        with self.db.connection() as connection:
            rows = connection.execute(
                "SELECT platform,status,COUNT(*) AS count FROM tasks GROUP BY platform,status"
            ).fetchall()
            counts = {
                "total": 0,
                "active": 0,
                "queued": 0,
                "running": 0,
                "cancel_requested": 0,
                "paused": 0,
                "failed": 0,
                "completed": 0,
                "canceled": 0,
            }
            by_platform: dict[str, dict[str, int]] = {}
            for row in rows:
                platform = str(row["platform"])
                status = str(row["status"])
                count = int(row["count"])
                counts["total"] += count
                counts[status] = counts.get(status, 0) + count
                if status in ACTIVE_STATUSES:
                    counts["active"] += count
                if status in {"succeeded", "succeeded_with_warnings", "skipped"}:
                    counts["completed"] += count
                if status == "canceled_with_warnings":
                    counts["canceled"] += count
                by_platform.setdefault(platform, {})[status] = count
            unread = int(
                connection.execute("SELECT COUNT(*) AS count FROM notifications WHERE read_at IS NULL").fetchone()[
                    "count"
                ]
            )
            batch_count = int(connection.execute("SELECT COUNT(*) AS count FROM task_batches").fetchone()["count"])
            return {
                "tasks": counts,
                "by_platform": by_platform,
                "batch_count": batch_count,
                "unread_notification_count": unread,
            }

    def find_instagram_record(
        self, source_folder_id: str, file_id: str, *, published_only: bool = False
    ) -> Optional[dict[str, Any]]:
        """Find active/published SQLite reservations for legacy de-duplication."""

        target_folder = _folder_id(source_folder_id)
        with self.db.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM tasks WHERE platform='instagram' AND video_id = ? ORDER BY created_at DESC",
                (file_id,),
            ).fetchall()
            for row in rows:
                task = _task_dict(row)
                payload = task.get("payload") or {}
                task_folder = _folder_id(payload.get("source_folder_id") or payload.get("folder"))
                checkpoint = task.get("checkpoint") or {}
                if checkpoint.get("history_released"):
                    continue
                has_media = bool(checkpoint.get("media_id"))
                is_published = has_media or task.get("status") in {"succeeded", "succeeded_with_warnings"}
                is_reserved = is_published or task.get("status") in {"queued", "running", "cancel_requested", "paused"}
                if (
                    task_folder != target_folder
                    or (published_only and not is_published)
                    or (not published_only and not is_reserved)
                ):
                    continue
                return {
                    "task_id": task["id"],
                    "batch_id": task["batch_id"],
                    "task_status": task["status"],
                    "item": {**payload, **checkpoint, "status": task["status"], "file_id": file_id},
                }
        return None

    def cancel_instagram_reservations(
        self,
        source_folder_id: str,
        file_ids: Iterable[str],
        *,
        exclude_batch_id: Optional[str] = None,
        reason: str = "使用者要求停止占用影片的舊 Instagram 工作",
    ) -> dict[str, Any]:
        """Cancel unfinished Instagram tasks that reserve the selected Drive files.

        Queued and paused tasks are canceled immediately. Running tasks retain
        cooperative cancellation semantics so an in-flight Meta operation is
        never silently released and published twice.
        """

        target_folder = _folder_id(source_folder_id)
        target_file_ids = {str(file_id).strip() for file_id in file_ids if str(file_id).strip()}
        if not target_folder or not target_file_ids:
            return {
                "requested_count": 0,
                "canceled_immediately_count": 0,
                "cancel_requested_count": 0,
                "task_ids": [],
                "batch_ids": [],
            }

        placeholders = ",".join("?" for _ in target_file_ids)
        values: list[Any] = [*sorted(target_file_ids)]
        batch_clause = ""
        if exclude_batch_id:
            batch_clause = " AND batch_id != ?"
            values.append(exclude_batch_id)
        with self.db.connection() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM tasks
                WHERE platform='instagram'
                  AND video_id IN ({placeholders})
                  AND status IN ('queued','running','paused','cancel_requested')
                  {batch_clause}
                ORDER BY created_at DESC, id DESC
                """,
                values,
            ).fetchall()

        matching_ids = []
        for row in rows:
            task = _task_dict(row)
            payload = task.get("payload") or {}
            task_folder = _folder_id(payload.get("source_folder_id") or payload.get("folder"))
            if task_folder == target_folder:
                matching_ids.append(task["id"])

        immediate = 0
        requested = 0
        batch_ids: set[str] = set()
        stopped_ids: list[str] = []
        for task_id in matching_ids:
            stopped = self.request_cancel(task_id, scope="blocking_instagram_job", reason=reason)
            if not stopped:
                continue
            stopped_ids.append(task_id)
            batch_ids.add(stopped["batch_id"])
            if stopped.get("status") == "canceled":
                immediate += 1
            elif stopped.get("status") == "cancel_requested":
                requested += 1

        return {
            "requested_count": len(stopped_ids),
            "canceled_immediately_count": immediate,
            "cancel_requested_count": requested,
            "task_ids": stopped_ids,
            "batch_ids": sorted(batch_ids),
        }

    def list_instagram_history(self) -> list[dict[str, Any]]:
        """Return safe published records for the existing Instagram history UI."""

        with self.db.connection() as connection:
            rows = connection.execute(
                """
                SELECT tasks.*, task_batches.legacy_job_id AS legacy_job_id
                FROM tasks
                JOIN task_batches ON task_batches.id = tasks.batch_id
                WHERE tasks.platform='instagram' AND tasks.status IN ('succeeded','succeeded_with_warnings')
                ORDER BY COALESCE(tasks.finished_at, tasks.updated_at) DESC
                """
            ).fetchall()
            history = []
            for row in rows:
                task = _task_dict(row)
                payload = task.get("payload") or {}
                checkpoint = task.get("checkpoint") or {}
                if checkpoint.get("history_released"):
                    continue
                history.append(
                    {
                        "record_id": f"{task['batch_id']}:{task.get('video_id') or task['id']}",
                        "job_id": task["batch_id"],
                        "batch_id": task["batch_id"],
                        "legacy_job_id": task.get("legacy_job_id"),
                        "created_at": task.get("created_at"),
                        "updated_at": task.get("updated_at"),
                        "published_at": checkpoint.get("published_at") or task.get("finished_at"),
                        "source_folder_id": _folder_id(payload.get("source_folder_id") or payload.get("folder")),
                        "published_folder_id": checkpoint.get("published_folder_id"),
                        "worksheet_name": None,
                        "team": payload.get("team"),
                        "share_to_feed": payload.get("share_to_feed", True),
                        "file_id": task.get("video_id"),
                        "file_name": task.get("video_title"),
                        "person": payload.get("person"),
                        "status": "published",
                        "stage": task.get("stage"),
                        "stage_label": task.get("stage_label"),
                        "media_id": checkpoint.get("media_id"),
                        "drive_move_error": checkpoint.get("drive_move_error"),
                        "drive_moved": bool(checkpoint.get("drive_moved")),
                        "drive_moved_at": checkpoint.get("drive_moved_at"),
                        "preflight": checkpoint.get("preflight") or {},
                    }
                )
            return history

    def release_instagram_history(self, batch_id: str, file_id: str) -> Optional[dict[str, Any]]:
        """Hide one SQLite history reservation while retaining its audit trail."""

        with self.db.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM tasks WHERE batch_id = ? AND platform='instagram' AND video_id = ?",
                (batch_id, file_id),
            ).fetchone()
            if row is None:
                return None
            task = _task_dict(row)
            if task.get("status") not in {"succeeded", "succeeded_with_warnings"}:
                return None
            checkpoint = dict(task.get("checkpoint") or {})
            checkpoint["history_released"] = True
            now = utc_now()
            connection.execute(
                "UPDATE tasks SET checkpoint_json=?,updated_at=? WHERE id=?",
                (_json_dumps(checkpoint), now, task["id"]),
            )
            self._insert_event(
                connection,
                task_id=task["id"],
                batch_id=batch_id,
                event_type="history_released",
                from_status=task["status"],
                to_status=task["status"],
                message="Instagram 歷史保留標記已移除",
                event_key=f"task:{task['id']}:history-released:{now}",
                created_at=now,
            )
            row = connection.execute("SELECT * FROM tasks WHERE id = ?", (task["id"],)).fetchone()
            task = _task_dict(row)
            payload = task.get("payload") or {}
            return {
                "record_id": f"{batch_id}:{file_id}",
                "job_id": batch_id,
                "batch_id": batch_id,
                "file_id": file_id,
                "file_name": task.get("video_title"),
                "media_id": checkpoint.get("media_id"),
                "source_folder_id": _folder_id(payload.get("source_folder_id") or payload.get("folder")),
                "published_folder_id": checkpoint.get("published_folder_id"),
                "drive_moved": bool(checkpoint.get("drive_moved")),
            }


def migrate_legacy_instagram_jobs(
    *,
    repository: Optional[TaskRepository] = None,
    legacy_path: str | Path = DATA_DIR / "instagram_publish_jobs.json",
) -> int:
    """Import the old JSON job store exactly once without creating notices.

    A legacy job id is stored in ``task_batches.legacy_job_id`` and every task
    id is derived from the job id plus the old sequence/file id.  Re-running
    startup is therefore safe even if the old JSON remains mounted forever.
    """

    repo = repository or task_repository
    path = Path(legacy_path)
    if not path.is_file():
        return 0
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    jobs = raw.get("jobs") if isinstance(raw, dict) else None
    if not isinstance(jobs, dict):
        return 0
    imported = 0
    for legacy_job_id, job in jobs.items():
        if not isinstance(job, dict) or not isinstance(job.get("items"), list):
            continue
        specs = []
        for index, item in enumerate(job.get("items", []), start=1):
            if not isinstance(item, dict):
                continue
            old_status = str(item.get("status") or "queued")
            if item.get("r2_delete_error") or item.get("drive_move_error"):
                status = "succeeded_with_warnings" if item.get("media_id") else "paused"
            elif old_status == "published" or item.get("media_id"):
                status = "succeeded"
            elif old_status == "skipped":
                status = "skipped"
            elif old_status == "failed":
                status = "failed"
            elif old_status == "paused":
                status = "paused"
            else:
                status = "paused"
            stage = str(item.get("stage") or ("completed" if status == "succeeded" else status))
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
            stable = hashlib.sha256(
                f"{legacy_job_id}:{item.get('sequence', index)}:{item.get('file_id', '')}".encode()
            ).hexdigest()
            specs.append(
                {
                    "id": f"legacy_task_{stable[:28]}",
                    "platform": "instagram",
                    "operation": "instagram.reels_publish",
                    "queue_lane": "instagram",
                    "sequence_in_batch": int(item.get("sequence") or index),
                    "video_id": item.get("file_id"),
                    "video_title": item.get("file_name"),
                    "status": status,
                    "stage": stage,
                    "stage_label": item.get("stage_label"),
                    "progress_percent": item.get("progress_percent", 100 if status in {"succeeded", "skipped"} else 0),
                    "retryable": status in {"failed", "paused", "succeeded_with_warnings"},
                    "error": item.get("error") or ("由舊工作資料匯入，請確認後重試。" if status == "paused" else None),
                    "payload": {
                        "file_id": item.get("file_id"),
                        "file_name": item.get("file_name"),
                        "person": item.get("person"),
                        "caption": item.get("caption"),
                        "source_folder_id": job.get("source_folder_id") or job.get("folder"),
                        "folder": job.get("folder"),
                        "published_folder_id": item.get("published_folder_id") or job.get("published_folder_id"),
                        "share_to_feed": job.get("share_to_feed", True),
                    },
                    "checkpoint": checkpoint,
                    "legacy_item_sequence": int(item.get("sequence") or index),
                }
            )
        if not specs:
            continue
        stable_batch = hashlib.sha256(str(legacy_job_id).encode()).hexdigest()
        batch = {
            "platform": "instagram",
            "operation": "instagram.reels_publish",
            "failure_policy": "pause_remaining_in_batch",
            "metadata": {
                "source": "legacy_json",
                "worksheet_name": job.get("worksheet_name"),
                "team": job.get("team"),
                "source_folder_id": job.get("source_folder_id") or job.get("folder"),
            },
        }
        result = repo.create_batch_and_tasks(
            batch,
            specs,
            batch_id=f"legacy_batch_{stable_batch[:28]}",
            legacy_job_id=str(legacy_job_id),
            notify=False,
        )
        if result.get("created"):
            imported += 1
    return imported


task_repository = TaskRepository()
