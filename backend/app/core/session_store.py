"""Encrypted, server-side Google sessions.

Only the random session id is sent to the browser. OAuth credentials and the
associated user profile remain encrypted in ``data/sessions.json``.
"""

import base64
import hashlib
import json
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Optional

from cryptography.fernet import Fernet, InvalidToken

from backend.app.core.config import settings

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_DEFAULT_PATH = _PROJECT_ROOT / "data" / "sessions.json"
SESSION_MAX_AGE = 7 * 24 * 60 * 60


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SessionStore:
    def __init__(self, path: Path = _DEFAULT_PATH):
        self._path = path
        self._lock = RLock()
        key_material = settings.CREDENTIAL_ENCRYPTION_KEY or settings.SECRET_KEY
        digest = hashlib.sha256(key_material.encode("utf-8")).digest()
        self._fernet = Fernet(base64.urlsafe_b64encode(digest))
        self._data: dict[str, Any] = {"version": 1, "sessions": {}}
        self._load()

    def _load(self) -> None:
        with self._lock:
            if not self._path.is_file():
                return
            try:
                with self._path.open("r", encoding="utf-8") as handle:
                    loaded = json.load(handle)
                if isinstance(loaded, dict):
                    sessions = loaded.get("sessions")
                    self._data["sessions"] = sessions if isinstance(sessions, dict) else {}
            except (OSError, json.JSONDecodeError) as exc:
                logger.error("Failed to load server session store: %s", type(exc).__name__)

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._path.with_name(f".{self._path.name}.{os.getpid()}.tmp")
        with tmp_path.open("w", encoding="utf-8") as handle:
            json.dump(self._data, handle, ensure_ascii=False, indent=2)
        try:
            os.chmod(tmp_path, 0o600)
        except OSError:
            pass
        os.replace(tmp_path, self._path)
        try:
            os.chmod(self._path, 0o600)
        except OSError:
            pass

    def _purge_expired(self) -> None:
        now = _now()
        expired = []
        for session_id, record in self._data["sessions"].items():
            if not isinstance(record, dict):
                expired.append(session_id)
                continue
            try:
                expires_at = datetime.fromisoformat(record["expires_at"])
            except (KeyError, TypeError, ValueError):
                expired.append(session_id)
                continue
            if expires_at <= now:
                expired.append(session_id)
        for session_id in expired:
            self._data["sessions"].pop(session_id, None)
        if expired:
            self._save()

    def create(self, data: dict[str, Any], max_age: int = SESSION_MAX_AGE) -> str:
        session_id = secrets.token_urlsafe(32)
        record = {
            "expires_at": (_now() + timedelta(seconds=max_age)).isoformat(),
            "data": self._fernet.encrypt(json.dumps(data, ensure_ascii=False).encode("utf-8")).decode("ascii"),
        }
        with self._lock:
            self._purge_expired()
            self._data["sessions"][session_id] = record
            self._save()
        return session_id

    def get(self, session_id: str) -> Optional[dict[str, Any]]:
        if not session_id or len(session_id) > 200:
            return None
        with self._lock:
            self._purge_expired()
            record = self._data["sessions"].get(session_id)
            if not isinstance(record, dict):
                return None
            encrypted = record.get("data")
            if not isinstance(encrypted, str):
                return None
            try:
                payload = self._fernet.decrypt(encrypted.encode("ascii"))
                data = json.loads(payload.decode("utf-8"))
            except (InvalidToken, ValueError, json.JSONDecodeError) as exc:
                logger.error("Failed to decrypt server session: %s", type(exc).__name__)
                return None
            return data if isinstance(data, dict) else None

    def update(self, session_id: str, data: dict[str, Any]) -> bool:
        with self._lock:
            self._purge_expired()
            record = self._data["sessions"].get(session_id)
            if not isinstance(record, dict):
                return False
            record["data"] = self._fernet.encrypt(json.dumps(data, ensure_ascii=False).encode("utf-8")).decode("ascii")
            self._save()
            return True

    def delete(self, session_id: str) -> None:
        if not session_id:
            return
        with self._lock:
            self._data["sessions"].pop(session_id, None)
            self._save()


session_store = SessionStore()
