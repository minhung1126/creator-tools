"""Atomic persistence for Instagram publish jobs."""

import json
import os
import re
import secrets
from pathlib import Path
from threading import RLock
from typing import Any, Optional

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_DEFAULT_PATH = _PROJECT_ROOT / "data" / "instagram_publish_jobs.json"
_RESERVED_ITEM_STATUSES = {"queued", "uploaded", "container_created"}


def _folder_id(value: Any) -> str:
    value = str(value or "").strip()
    match = re.search(r"/folders/([A-Za-z0-9_-]+)", value)
    return match.group(1) if match else value


def _job_folder_id(job: dict[str, Any]) -> str:
    return _folder_id(job.get("source_folder_id") or job.get("folder"))


def _record_matches(job: dict[str, Any], source_folder_id: str, file_id: str) -> bool:
    return _job_folder_id(job) == _folder_id(source_folder_id) and any(
        item.get("file_id") == file_id for item in job.get("items", [])
    )


def _item_is_publish_record(item: dict[str, Any]) -> bool:
    return item.get("status") == "published" or bool(item.get("media_id"))


def _item_is_reserved(item: dict[str, Any]) -> bool:
    return _item_is_publish_record(item) or item.get("status") in _RESERVED_ITEM_STATUSES


class InstagramPublishStore:
    def __init__(self, path: Path = _DEFAULT_PATH):
        self._path = path
        self._lock = RLock()

    def _read(self) -> dict[str, Any]:
        if not self._path.is_file():
            return {"version": 1, "jobs": {}}
        try:
            with self._path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            return data if isinstance(data, dict) and isinstance(data.get("jobs"), dict) else {"version": 1, "jobs": {}}
        except (OSError, json.JSONDecodeError):
            return {"version": 1, "jobs": {}}

    def _write(self, data: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self._path.with_name(f".{self._path.name}.{os.getpid()}.tmp")
        with temp_path.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
        os.replace(temp_path, self._path)

    @staticmethod
    def _find_file_record_in_data(
        data: dict[str, Any],
        source_folder_id: str,
        file_id: str,
        *,
        published_only: bool = False,
    ) -> Optional[dict[str, Any]]:
        for job_id, job in data.get("jobs", {}).items():
            if not isinstance(job, dict) or not _record_matches(job, source_folder_id, file_id):
                continue
            for item in job.get("items", []):
                if item.get("file_id") != file_id:
                    continue
                if published_only and not _item_is_publish_record(item):
                    continue
                if not published_only and not _item_is_reserved(item):
                    continue
                return {
                    "job_id": job_id,
                    "job_status": job.get("status"),
                    "item": json.loads(json.dumps(item, ensure_ascii=False)),
                }
        return None

    def find_file_record(self, source_folder_id: str, file_id: str) -> Optional[dict[str, Any]]:
        """Find a published or in-progress record for a Drive file."""
        with self._lock:
            return self._find_file_record_in_data(self._read(), source_folder_id, file_id)

    def find_published_record(self, source_folder_id: str, file_id: str) -> Optional[dict[str, Any]]:
        """Find a record that has already obtained an Instagram media id."""
        with self._lock:
            return self._find_file_record_in_data(
                self._read(), source_folder_id, file_id, published_only=True
            )

    @staticmethod
    def _mark_duplicate(item: dict[str, Any], record: dict[str, Any]) -> None:
        existing_item = record.get("item") or {}
        already_published = _item_is_publish_record(existing_item)
        item.update(
            status="skipped",
            error=(
                "此影片已發布過，為避免重複上傳已略過。"
                if already_published
                else "此影片已有未完成的發布工作，請回到原工作重試。"
            ),
            duplicate_of_job_id=record.get("job_id"),
            duplicate_media_id=existing_item.get("media_id"),
            stage="skipped",
            stage_label="已略過",
            progress_percent=100,
        )

    def create(self, job: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            data = self._read()
            job_id = secrets.token_urlsafe(18)
            job["id"] = job_id
            source_folder_id = _job_folder_id(job)
            seen_file_ids: set[str] = set()
            for item in job.get("items", []):
                file_id = str(item.get("file_id") or "")
                if not file_id or item.get("status") != "queued":
                    continue
                if file_id in seen_file_ids:
                    self._mark_duplicate(
                        item,
                        {
                            "job_id": job_id,
                            "item": {"status": "queued"},
                        },
                    )
                    item["error"] = "同一支影片在本次工作中重複指定，已略過。"
                    continue
                seen_file_ids.add(file_id)
                existing = self._find_file_record_in_data(data, source_folder_id, file_id)
                if existing:
                    self._mark_duplicate(item, existing)
            data["jobs"][job_id] = job
            self._write(data)
            return json.loads(json.dumps(job, ensure_ascii=False))

    def get(self, job_id: str) -> Optional[dict[str, Any]]:
        with self._lock:
            job = self._read()["jobs"].get(job_id)
            return json.loads(json.dumps(job, ensure_ascii=False)) if isinstance(job, dict) else None

    def save(self, job: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            data = self._read()
            data["jobs"][job["id"]] = job
            self._write(data)
            return json.loads(json.dumps(job, ensure_ascii=False))


instagram_publish_store = InstagramPublishStore()
