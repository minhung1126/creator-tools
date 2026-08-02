"""SQLite infrastructure for the durable activity center.

The production deployment intentionally uses one Uvicorn process, but task
handlers still run in background threads.  This module therefore never shares
connections between threads or operations.  SQLite's WAL journal lets the
HTTP request path and the two worker lanes make progress concurrently while
the short transactions in the repositories provide the required claim and
enqueue atomicity.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from typing import Iterator

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = PROJECT_ROOT / "data"
DATABASE_PATH = DATA_DIR / "creator_tools.db"
SCHEMA_VERSION = 3


class Database:
    """Small per-operation SQLite connection manager."""

    def __init__(self, path: str | Path = DATABASE_PATH, *, busy_timeout_ms: int = 30_000):
        self.path = Path(path)
        self.busy_timeout_ms = int(busy_timeout_ms)
        self._schema_lock = RLock()

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(
            str(self.path),
            timeout=max(self.busy_timeout_ms / 1000, 1),
            isolation_level=None,
            check_same_thread=False,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA busy_timeout = {self.busy_timeout_ms}")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def transaction(self, *, immediate: bool = True) -> Iterator[sqlite3.Connection]:
        """Yield a connection with an explicit transaction.

        ``BEGIN IMMEDIATE`` is used for state transitions so a worker claim or
        cancellation cannot race another writer after reading a task.
        """

        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        """Apply schema migrations using ``PRAGMA user_version``."""

        with self._schema_lock:
            with self.connection() as connection:
                version = int(connection.execute("PRAGMA user_version").fetchone()[0])
                if version < 1:
                    self._migration_1(connection)
                    connection.execute("PRAGMA user_version = 1")
                    version = 1
                if version < 2:
                    self._migration_2(connection)
                    connection.execute("PRAGMA user_version = 2")
                    version = 2
                if version < 3:
                    self._migration_3(connection)
                    connection.execute("PRAGMA user_version = 3")
                    version = 3
                if version < SCHEMA_VERSION:
                    raise RuntimeError(f"Unsupported creator_tools.db schema version {version}")

    @staticmethod
    def _migration_1(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS task_batches (
                id TEXT PRIMARY KEY,
                platform TEXT NOT NULL,
                operation TEXT NOT NULL,
                failure_policy TEXT NOT NULL,
                status TEXT NOT NULL,
                total_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                completed_at TEXT,
                legacy_job_id TEXT UNIQUE,
                metadata_json TEXT NOT NULL DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                batch_id TEXT NOT NULL REFERENCES task_batches(id) ON DELETE CASCADE,
                platform TEXT NOT NULL,
                operation TEXT NOT NULL,
                queue_lane TEXT NOT NULL,
                queue_sequence INTEGER NOT NULL,
                sequence_in_batch INTEGER NOT NULL,
                video_id TEXT,
                video_title TEXT,
                thumbnail_url TEXT,
                status TEXT NOT NULL,
                stage TEXT NOT NULL,
                stage_label TEXT NOT NULL,
                progress_percent REAL NOT NULL DEFAULT 0,
                attempt INTEGER NOT NULL DEFAULT 1,
                retryable INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                queued_at TEXT,
                started_at TEXT,
                updated_at TEXT NOT NULL,
                finished_at TEXT,
                cancel_requested_at TEXT,
                canceled_at TEXT,
                cancel_scope TEXT,
                cancel_reason TEXT,
                cancel_too_late INTEGER NOT NULL DEFAULT 0,
                error TEXT,
                payload_json TEXT NOT NULL DEFAULT '{}',
                checkpoint_json TEXT NOT NULL DEFAULT '{}',
                result_json TEXT NOT NULL DEFAULT '{}',
                legacy_item_sequence INTEGER
            );

            CREATE TABLE IF NOT EXISTS task_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT REFERENCES tasks(id) ON DELETE CASCADE,
                batch_id TEXT NOT NULL REFERENCES task_batches(id) ON DELETE CASCADE,
                event_type TEXT NOT NULL,
                from_status TEXT,
                to_status TEXT,
                message TEXT,
                created_at TEXT NOT NULL,
                event_key TEXT NOT NULL UNIQUE
            );

            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_key TEXT NOT NULL UNIQUE,
                type TEXT NOT NULL,
                severity TEXT NOT NULL,
                title TEXT NOT NULL,
                message TEXT NOT NULL,
                task_id TEXT REFERENCES tasks(id) ON DELETE CASCADE,
                batch_id TEXT REFERENCES task_batches(id) ON DELETE CASCADE,
                created_at TEXT NOT NULL,
                read_at TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_tasks_lane_status_sequence
                ON tasks(queue_lane, status, queue_sequence, id);
            CREATE INDEX IF NOT EXISTS idx_tasks_batch_sequence
                ON tasks(batch_id, sequence_in_batch);
            CREATE INDEX IF NOT EXISTS idx_tasks_status_updated
                ON tasks(status, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_notifications_unread
                ON notifications(read_at, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_events_task_created
                ON task_events(task_id, created_at DESC);
            """
        )

    @staticmethod
    def _migration_2(connection: sqlite3.Connection) -> None:
        columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(tasks)").fetchall()}
        if "next_attempt_at" not in columns:
            connection.execute("ALTER TABLE tasks ADD COLUMN next_attempt_at TEXT")
        connection.executescript(
            """
            CREATE INDEX IF NOT EXISTS idx_tasks_lane_due
                ON tasks(queue_lane, status, next_attempt_at, queue_sequence, id);

            CREATE TABLE IF NOT EXISTS instagram_limiter (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                cooldown_until TEXT,
                last_reason TEXT,
                last_http_status INTEGER,
                last_meta_code INTEGER,
                last_error_subcode INTEGER,
                last_fbtrace_id TEXT,
                last_endpoint TEXT,
                last_retry_after TEXT,
                estimated_recovery_at TEXT,
                consecutive_failures INTEGER NOT NULL DEFAULT 0,
                recent_success_at TEXT,
                last_failure_at TEXT,
                last_success_endpoint TEXT,
                last_app_usage_json TEXT,
                updated_at TEXT
            );

            INSERT OR IGNORE INTO instagram_limiter (id) VALUES (1);
            """
        )

    @staticmethod
    def _migration_3(connection: sqlite3.Connection) -> None:
        """Persist the YouTube quota ledger separately from task history.

        This is intentionally a new migration.  The Instagram migration above
        is part of the existing dirty worktree and must remain reproducible for
        installations that are upgrading from schema version 2.
        """

        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS youtube_quota_daily (
                quota_date TEXT NOT NULL,
                bucket TEXT NOT NULL,
                configured_limit INTEGER NOT NULL,
                estimated_used_units INTEGER NOT NULL DEFAULT 0,
                state TEXT NOT NULL DEFAULT 'normal',
                blocked_reason TEXT,
                blocked_until TEXT,
                confirmed_exhausted_at TEXT,
                last_http_status INTEGER,
                last_error_reason TEXT,
                last_error_method TEXT,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (quota_date, bucket)
            );

            CREATE TABLE IF NOT EXISTS youtube_quota_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_key TEXT NOT NULL UNIQUE,
                quota_date TEXT NOT NULL,
                bucket TEXT NOT NULL,
                method TEXT NOT NULL,
                documented_cost INTEGER NOT NULL,
                outcome TEXT NOT NULL,
                http_status INTEGER,
                error_reason TEXT,
                task_id TEXT,
                batch_id TEXT,
                operation TEXT,
                created_at TEXT NOT NULL,
                completed_at TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_youtube_quota_events_date_bucket
                ON youtube_quota_events(quota_date, bucket, created_at);
            CREATE INDEX IF NOT EXISTS idx_youtube_quota_events_task
                ON youtube_quota_events(task_id, created_at);
            """
        )


database = Database()
database.initialize()
