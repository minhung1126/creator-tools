"""Encrypted persistent storage for Google OAuth credentials."""

import base64
import hashlib
import json
import logging
import os
from datetime import datetime, timezone
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
        self._data: Dict[str, Any] = {"version": 3, "google": None}
        self._load()

    def _load(self):
        with self._lock:
            if not self._path.is_file():
                return
            try:
                with self._path.open("r", encoding="utf-8") as handle:
                    loaded = json.load(handle)
                if isinstance(loaded, dict):
                    # Version 3 retires the former Instagram and R2 records.
                    # Preserve only the Google credential when reading an older
                    # store; the next legitimate write removes retired fields.
                    self._data = {"version": 3, "google": loaded.get("google")}
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
            raise RuntimeError("無法解密已儲存的憑證。請確認 CREDENTIAL_ENCRYPTION_KEY 未變更，或重新連線。") from exc

    def _decrypt_json(self, value: Optional[str]) -> Optional[Dict[str, Any]]:
        if not value:
            return None
        try:
            payload = json.loads(self._decrypt(value))
        except (RuntimeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise RuntimeError("無法讀取已儲存的 OAuth 憑證。請重新連線。") from exc
        return payload if isinstance(payload, dict) else None

    @staticmethod
    def _expires_at_from_value(value: Any) -> Optional[str]:
        if not value:
            return None
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            return to_iso(value)
        if isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return to_iso(parsed)
            except ValueError:
                return None
        return None

    def save_google_connection(self, token_dict: Dict[str, Any]) -> Dict[str, Any]:
        """Persist Google OAuth credentials separately from short-lived login sessions."""
        if not isinstance(token_dict, dict) or not token_dict.get("token"):
            raise ValueError("Google OAuth response did not contain an access token")

        now = utc_now()
        with self._lock:
            previous = self._data.get("google")
            previous_credentials = (
                self._decrypt_json(previous.get("credentials_encrypted")) if isinstance(previous, dict) else None
            )
            credentials = dict(token_dict)
            user = credentials.get("user") if isinstance(credentials.get("user"), dict) else {}
            previous_user = (
                previous_credentials.get("user")
                if isinstance(previous_credentials, dict) and isinstance(previous_credentials.get("user"), dict)
                else {}
            )
            same_account = bool(
                user.get("email")
                and previous_user.get("email")
                and str(user["email"]).casefold() == str(previous_user["email"]).casefold()
            )
            # Google may omit refresh_token when an already-authorized account is
            # connected again. Never replace a working refresh token with None,
            # but never copy one across different Google accounts.
            if not credentials.get("refresh_token") and previous_credentials and same_account:
                credentials["refresh_token"] = previous_credentials.get("refresh_token")

            scopes = credentials.get("scopes") if isinstance(credentials.get("scopes"), list) else []
            self._data["google"] = {
                "credentials_encrypted": self._encrypt(json.dumps(credentials, ensure_ascii=False)),
                "user": user,
                "scopes": sorted({str(scope) for scope in scopes if str(scope).strip()}),
                "token_expires_at": self._expires_at_from_value(credentials.get("expiry")),
                "connected_at": (
                    previous.get("connected_at")
                    if isinstance(previous, dict) and previous.get("connected_at")
                    else to_iso(now)
                ),
                "last_refreshed_at": to_iso(now),
                "last_refresh_error": None,
                "status": "active",
            }
            self._save()
        return self.get_google_public() or {}

    def get_google_credentials(self) -> Optional[Dict[str, Any]]:
        with self._lock:
            record = self._data.get("google")
            encrypted = record.get("credentials_encrypted") if isinstance(record, dict) else None
        return self._decrypt_json(encrypted)

    def get_google_public(self) -> Optional[Dict[str, Any]]:
        with self._lock:
            record = self._data.get("google")
            if not isinstance(record, dict):
                return None
            return {key: value for key, value in record.items() if key != "credentials_encrypted"}

    def mark_google_refresh_failed(self, message: str, requires_reauthorization: bool = False) -> None:
        with self._lock:
            record = self._data.get("google")
            if not isinstance(record, dict):
                return
            record["status"] = "reauthorization_required" if requires_reauthorization else "refresh_failed"
            record["last_refresh_error"] = str(message)[:240]
            record["last_refresh_failed_at"] = to_iso(utc_now())
            self._save()

    def clear_google(self) -> None:
        with self._lock:
            self._data["google"] = None
            self._save()


credential_store = CredentialStore()
