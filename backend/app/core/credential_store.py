"""Encrypted persistent storage for Instagram and R2 credentials."""

import base64
import hashlib
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Dict, Optional

from cryptography.fernet import Fernet, InvalidToken

from backend.app.core.config import settings

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_DEFAULT_PATH = _PROJECT_ROOT / "data" / "credential_store.json"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def to_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


class CredentialStore:
    def __init__(self, path: Path = _DEFAULT_PATH):
        self._path = path
        self._lock = RLock()
        key_material = settings.CREDENTIAL_ENCRYPTION_KEY or settings.SECRET_KEY
        digest = hashlib.sha256(key_material.encode("utf-8")).digest()
        self._fernet = Fernet(base64.urlsafe_b64encode(digest))
        self._data: Dict[str, Any] = {"version": 1, "instagram": None, "secrets": {}}
        self._load()

    def _load(self):
        with self._lock:
            if not self._path.is_file():
                return
            try:
                with self._path.open("r", encoding="utf-8") as handle:
                    loaded = json.load(handle)
                if isinstance(loaded, dict):
                    self._data.update(loaded)
                    self._data.setdefault("secrets", {})
            except (OSError, json.JSONDecodeError) as exc:
                logger.error("Failed to load credential store: %s", exc)

    def _save(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # Keep the replace atomic and avoid a shared ``.tmp`` name when more
        # than one process writes the store during a deployment.
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

    def _encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode("utf-8")).decode("ascii")

    def _decrypt(self, value: str) -> str:
        try:
            return self._fernet.decrypt(value.encode("ascii")).decode("utf-8")
        except (InvalidToken, ValueError) as exc:
            raise RuntimeError(
                "無法解密已儲存的憑證。請確認 CREDENTIAL_ENCRYPTION_KEY 未變更，或重新連線。"
            ) from exc

    def save_instagram_connection(
        self,
        *,
        access_token: str,
        user_id: str,
        username: str,
        account_type: str,
        granted_scopes: list[str],
        expires_in: Optional[int],
        permissions_verified: bool,
    ) -> Dict[str, Any]:
        now = utc_now()
        expires_at = now + timedelta(seconds=int(expires_in)) if expires_in else None
        record = {
            "access_token_encrypted": self._encrypt(access_token),
            "instagram_user_id": str(user_id),
            "username": username or "",
            "account_type": account_type or "",
            "granted_scopes": sorted(set(granted_scopes)),
            "permissions_verified": bool(permissions_verified),
            "token_expires_at": to_iso(expires_at) if expires_at else None,
            "connected_at": to_iso(now),
            "last_verified_at": to_iso(now),
        }
        with self._lock:
            self._data["instagram"] = record
            self._save()
        return self.get_instagram_public() or {}

    def get_instagram_public(self) -> Optional[Dict[str, Any]]:
        with self._lock:
            record = self._data.get("instagram")
            if not isinstance(record, dict):
                return None
            return {key: value for key, value in record.items() if key != "access_token_encrypted"}

    def get_instagram_token(self) -> Optional[str]:
        with self._lock:
            record = self._data.get("instagram")
            encrypted = record.get("access_token_encrypted") if isinstance(record, dict) else None
        return self._decrypt(encrypted) if encrypted else None

    def update_instagram_token(self, access_token: str, expires_in: Optional[int]) -> Dict[str, Any]:
        now = utc_now()
        expires_at = now + timedelta(seconds=int(expires_in)) if expires_in else None
        with self._lock:
            record = self._data.get("instagram")
            if not isinstance(record, dict):
                raise RuntimeError("Instagram 尚未連線")
            record["access_token_encrypted"] = self._encrypt(access_token)
            record["token_expires_at"] = to_iso(expires_at) if expires_at else record.get("token_expires_at")
            record["last_verified_at"] = to_iso(now)
            self._save()
        return self.get_instagram_public() or {}

    def update_instagram_profile(self, username: str, account_type: str):
        with self._lock:
            record = self._data.get("instagram")
            if not isinstance(record, dict):
                return
            record["username"] = username or record.get("username", "")
            record["account_type"] = account_type or record.get("account_type", "")
            record["last_verified_at"] = to_iso(utc_now())
            self._save()

    def clear_instagram(self):
        with self._lock:
            self._data["instagram"] = None
            self._save()

    def set_secret(self, name: str, value: str):
        with self._lock:
            secrets = self._data.setdefault("secrets", {})
            secrets[name] = self._encrypt(value)
            self._save()

    def get_secret(self, name: str) -> str:
        with self._lock:
            encrypted = self._data.get("secrets", {}).get(name)
        return self._decrypt(encrypted) if encrypted else ""

    def has_secret(self, name: str) -> bool:
        with self._lock:
            return bool(self._data.get("secrets", {}).get(name))


credential_store = CredentialStore()
