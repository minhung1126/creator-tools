"""Persistence and safe DTOs for the notification center."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from backend.app.core.database import Database, database


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _public(row) -> dict[str, Any]:
    # Keep this explicit: notifications must never become an accidental task
    # payload/checkpoint endpoint.
    return {
        "id": int(row["id"]),
        "event_key": row["event_key"],
        "type": row["type"],
        "severity": row["severity"],
        "title": row["title"],
        "message": row["message"],
        "task_id": row["task_id"],
        "batch_id": row["batch_id"],
        "created_at": row["created_at"],
        "read_at": row["read_at"],
    }


class NotificationRepository:
    def __init__(self, db: Database = database):
        self.db = db
        self.db.initialize()

    def list(self, *, unread_only: bool = False, offset: int = 0, limit: int = 50) -> tuple[list[dict[str, Any]], int]:
        clause = "WHERE read_at IS NULL" if unread_only else ""
        safe_offset = max(int(offset), 0)
        safe_limit = min(max(int(limit), 1), 100)
        with self.db.connection() as connection:
            total = int(connection.execute(f"SELECT COUNT(*) AS count FROM notifications {clause}").fetchone()["count"])
            rows = connection.execute(
                f"SELECT * FROM notifications {clause} ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
                (safe_limit, safe_offset),
            ).fetchall()
            return [_public(row) for row in rows], total

    def get(self, notification_id: int) -> Optional[dict[str, Any]]:
        with self.db.connection() as connection:
            row = connection.execute("SELECT * FROM notifications WHERE id = ?", (int(notification_id),)).fetchone()
            return _public(row) if row else None

    def mark_read(self, notification_id: int) -> Optional[dict[str, Any]]:
        with self.db.transaction() as connection:
            row = connection.execute("SELECT * FROM notifications WHERE id = ?", (int(notification_id),)).fetchone()
            if row is None:
                return None
            connection.execute(
                "UPDATE notifications SET read_at = COALESCE(read_at, ?) WHERE id = ?",
                (_now(), int(notification_id)),
            )
            row = connection.execute("SELECT * FROM notifications WHERE id = ?", (int(notification_id),)).fetchone()
            return _public(row)

    def mark_all_read(self) -> int:
        with self.db.transaction() as connection:
            result = connection.execute("UPDATE notifications SET read_at = ? WHERE read_at IS NULL", (_now(),))
            return int(result.rowcount or 0)

    def unread_count(self) -> int:
        with self.db.connection() as connection:
            return int(
                connection.execute("SELECT COUNT(*) AS count FROM notifications WHERE read_at IS NULL").fetchone()[
                    "count"
                ]
            )

    def create(
        self,
        *,
        event_key: str,
        notification_type: str,
        severity: str,
        title: str,
        message: str,
        task_id: Optional[str] = None,
        batch_id: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        with self.db.transaction() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO notifications
                  (event_key,type,severity,title,message,task_id,batch_id,created_at)
                VALUES (?,?,?,?,?,?,?,?)
                """,
                (event_key, notification_type, severity, title, message, task_id, batch_id, _now()),
            )
            row = connection.execute("SELECT * FROM notifications WHERE event_key = ?", (event_key,)).fetchone()
            return _public(row) if row else None


notification_repository = NotificationRepository()
