"""Atomic persistence for Instagram publish jobs."""

import json
import os
import secrets
from pathlib import Path
from threading import RLock
from typing import Any, Optional

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_DEFAULT_PATH = _PROJECT_ROOT / "data" / "instagram_publish_jobs.json"


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

    def create(self, job: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            data = self._read()
            job_id = secrets.token_urlsafe(18)
            job["id"] = job_id
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
