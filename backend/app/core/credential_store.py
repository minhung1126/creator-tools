"""Encrypted persistent storage for user-scoped Google OAuth credentials."""

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

from backend.app.core.config import normalize_youtube_slot, settings

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_DEFAULT_PATH = _PROJECT_ROOT / "data" / "credential_store.json"
_STORE_VERSION = 6


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def to_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _normalise_subject(value: Any) -> Optional[str]:
    subject = str(value or "").strip()
    if not subject or len(subject) > 256:
        return None
    return subject


def _require_subject(value: str) -> str:
    subject = _normalise_subject(value)
    if not subject:
        raise ValueError("owner_sub is required for credential storage")
    return subject


def _user_from_token(token_dict: Dict[str, Any]) -> Dict[str, Any]:
    user = token_dict.get("user")
    return dict(user) if isinstance(user, dict) else {}


def _subject_from_token(token_dict: Dict[str, Any]) -> Optional[str]:
    user = _user_from_token(token_dict)
    return _normalise_subject(user.get("sub") or user.get("id") or token_dict.get("sub"))


def _safe_public_user(user: Dict[str, Any]) -> Dict[str, str]:
    """Keep account metadata useful without reflecting arbitrary provider data."""
    return {field: str(user[field]) for field in ("email", "name", "picture") if user.get(field) is not None}


class CredentialStore:
    """Persist credentials under an authenticated user's OIDC subject."""

    def __init__(self, path: Path = _DEFAULT_PATH):
        self._path = path
        self._lock = RLock()
        key_material = settings.CREDENTIAL_ENCRYPTION_KEY
        digest = hashlib.sha256(key_material.encode("utf-8")).digest()
        self._fernet = Fernet(base64.urlsafe_b64encode(digest))
        self._data: Dict[str, Any] = {
            "version": _STORE_VERSION,
            "users": {},
        }
        self._load()

    def _load(self) -> None:
        with self._lock:
            if not self._path.is_file():
                return
            try:
                with self._path.open("r", encoding="utf-8") as handle:
                    loaded = json.load(handle)
                if not isinstance(loaded, dict):
                    return

                users = loaded.get("users")
                if isinstance(users, dict):
                    users = {
                        str(subject): records
                        for subject, records in users.items()
                        if isinstance(records, dict) and _normalise_subject(subject)
                    }
                    migrated = False
                    for records in users.values():
                        if "youtube" in records:
                            legacy = records.pop("youtube")
                            if "youtube_primary" not in records:
                                if isinstance(legacy, dict):
                                    legacy = dict(legacy)
                                    legacy.setdefault("slot", "primary")
                                records["youtube_primary"] = legacy
                            migrated = True
                        for slot in ("primary", "secondary"):
                            key = f"youtube_{slot}"
                            record = records.get(key)
                            if isinstance(record, dict) and record.get("slot") != slot:
                                record["slot"] = slot
                                migrated = True
                            if isinstance(record, dict):
                                encrypted = record.get("credentials_encrypted")
                                try:
                                    credentials = self._decrypt_json(encrypted)
                                except RuntimeError:
                                    credentials = None
                                if isinstance(credentials, dict) and "client_secret" in credentials:
                                    credentials.pop("client_secret", None)
                                    record["credentials_encrypted"] = self._encrypt(
                                        json.dumps(credentials, ensure_ascii=False)
                                    )
                                    migrated = True
                                if isinstance(credentials, dict) and not record.get("client_fingerprint"):
                                    client_id = str(credentials.get("client_id") or "").strip()
                                    if client_id:
                                        record["client_fingerprint"] = hashlib.sha256(client_id.encode("utf-8")).hexdigest()[:16]
                                        migrated = True
                    self._data = {
                        "version": _STORE_VERSION,
                        "users": users,
                    }
                    if migrated:
                        self._save()
            except (OSError, json.JSONDecodeError) as exc:
                logger.error("Failed to load credential store: %s", type(exc).__name__)

    def _save(self) -> None:
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

    def _find_record(self, key: str, owner_sub: str) -> Optional[Dict[str, Any]]:
        subject = _require_subject(owner_sub)
        user_records = self._data.get("users", {}).get(subject)
        record = user_records.get(key) if isinstance(user_records, dict) else None
        return record if isinstance(record, dict) else None

    @staticmethod
    def _same_account(first: Dict[str, Any], second: Dict[str, Any]) -> bool:
        first_subject = _subject_from_token(first)
        second_subject = _subject_from_token(second)
        if first_subject and second_subject:
            return first_subject == second_subject
        first_email = str(_user_from_token(first).get("email") or "").casefold()
        second_email = str(_user_from_token(second).get("email") or "").casefold()
        return bool(first_email and second_email and first_email == second_email)

    def _save_connection(
        self,
        key: str,
        token_dict: Dict[str, Any],
        owner_sub: str,
        *,
        slot: str | None = None,
    ) -> Dict[str, Any]:
        """Persist one OAuth connection separately from browser login sessions."""
        if not isinstance(token_dict, dict) or not token_dict.get("token"):
            raise ValueError("Google OAuth response did not contain an access token")

        subject = _require_subject(owner_sub)
        slot_name = normalize_youtube_slot(slot) if key == "youtube" else None
        storage_key = f"youtube_{slot_name}" if slot_name else key
        now = utc_now()
        with self._lock:
            users = self._data.setdefault("users", {})
            user_records = users.setdefault(subject, {})
            previous = user_records.get(storage_key)
            previous_credentials = (
                self._decrypt_json(previous.get("credentials_encrypted")) if isinstance(previous, dict) else None
            )
            # Client secrets are deployment configuration, never credential
            # data. Refresh code resolves the secret from the selected slot.
            credentials = {field: value for field, value in token_dict.items() if field != "client_secret"}
            user = _user_from_token(credentials)
            # Google may omit refresh_token when an already-authorized account
            # is connected again. Never replace a working refresh token with
            # None, and never copy one across different Google accounts.
            if (
                not credentials.get("refresh_token")
                and previous_credentials
                and self._same_account(credentials, previous_credentials)
            ):
                credentials["refresh_token"] = previous_credentials.get("refresh_token")

            scopes = credentials.get("scopes") if isinstance(credentials.get("scopes"), list) else []
            client_id = str(credentials.get("client_id") or "").strip()
            client_fingerprint = str(token_dict.get("client_fingerprint") or "").strip() or (
                hashlib.sha256(client_id.encode("utf-8")).hexdigest()[:16] if client_id else None
            )
            record = {
                "owner_sub": subject,
                "credential_sub": _subject_from_token(credentials),
                "credentials_encrypted": self._encrypt(json.dumps(credentials, ensure_ascii=False)),
                "user": _safe_public_user(user),
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
            if slot_name:
                record.update(
                    {
                        "slot": slot_name,
                        "client_fingerprint": client_fingerprint,
                        "channel_id": str(token_dict.get("channel_id") or "").strip() or None,
                        "channel_title": str(token_dict.get("channel_title") or "").strip() or None,
                    }
                )
            user_records[storage_key] = record
            self._save()
            return self._get_public(storage_key, subject) or {}

    def save_google_connection(self, token_dict: Dict[str, Any], owner_sub: str) -> Dict[str, Any]:
        """Persist the control-panel login/Sheets connection for one OIDC subject."""
        return self._save_connection("google", token_dict, owner_sub)

    def save_youtube_connection(
        self, token_dict: Dict[str, Any], owner_sub: str, slot: str = "primary"
    ) -> Dict[str, Any]:
        """Persist a YouTube connection under the logged-in user's OIDC subject."""
        return self._save_connection("youtube", token_dict, owner_sub, slot=slot)

    def _get_credentials(self, key: str, owner_sub: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            record = self._find_record(key, owner_sub)
            encrypted = record.get("credentials_encrypted") if isinstance(record, dict) else None
        return self._decrypt_json(encrypted)

    def get_google_credentials(self, owner_sub: str) -> Optional[Dict[str, Any]]:
        return self._get_credentials("google", owner_sub)

    def get_youtube_credentials(self, owner_sub: str, slot: str = "primary") -> Optional[Dict[str, Any]]:
        slot_name = normalize_youtube_slot(slot)
        return self._get_credentials(f"youtube_{slot_name}", owner_sub)

    def _get_public(self, key: str, owner_sub: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            record = self._find_record(key, owner_sub)
            if not isinstance(record, dict):
                return None
            public = {
                field: value
                for field, value in record.items()
                if field not in {"credentials_encrypted", "owner_sub", "credential_sub"}
            }
            if public.get("last_refresh_error"):
                public["last_refresh_error"] = "OAuth token refresh failed."
            return public

    def get_google_public(self, owner_sub: str) -> Optional[Dict[str, Any]]:
        return self._get_public("google", owner_sub)

    def get_youtube_public(self, owner_sub: str, slot: str = "primary") -> Optional[Dict[str, Any]]:
        slot_name = normalize_youtube_slot(slot)
        return self._get_public(f"youtube_{slot_name}", owner_sub)

    def get_youtube_slots_public(self, owner_sub: str) -> Dict[str, Dict[str, Any]]:
        return {
            slot: self.get_youtube_public(owner_sub, slot) or {}
            for slot in ("primary", "secondary")
        }

    def _mark_refresh_failed(
        self,
        key: str,
        message: str,
        *,
        owner_sub: str,
        requires_reauthorization: bool = False,
    ) -> None:
        with self._lock:
            record = self._find_record(key, owner_sub)
            if not isinstance(record, dict):
                return
            record["status"] = "reauthorization_required" if requires_reauthorization else "refresh_failed"
            record["last_refresh_error"] = (
                "Google OAuth refresh requires reauthorization."
                if requires_reauthorization
                else "OAuth token refresh failed."
            )
            record["last_refresh_failed_at"] = to_iso(utc_now())
            self._save()

    def mark_google_refresh_failed(
        self, message: str, *, owner_sub: str, requires_reauthorization: bool = False
    ) -> None:
        self._mark_refresh_failed(
            "google", message, owner_sub=owner_sub, requires_reauthorization=requires_reauthorization
        )

    def mark_youtube_refresh_failed(
        self,
        message: str,
        *,
        owner_sub: str,
        slot: str = "primary",
        requires_reauthorization: bool = False,
    ) -> None:
        self._mark_refresh_failed(
            f"youtube_{normalize_youtube_slot(slot)}",
            message,
            owner_sub=owner_sub,
            requires_reauthorization=requires_reauthorization,
        )

    def _clear(self, key: str, owner_sub: str) -> None:
        with self._lock:
            subject = _require_subject(owner_sub)
            user_records = self._data.get("users", {}).get(subject)
            if isinstance(user_records, dict):
                user_records[key] = None
                if not any(value for value in user_records.values()):
                    self._data["users"].pop(subject, None)
            self._save()

    def clear_google(self, owner_sub: str) -> None:
        self._clear("google", owner_sub)

    def clear_youtube(self, owner_sub: str, slot: str = "primary") -> None:
        self._clear(f"youtube_{normalize_youtube_slot(slot)}", owner_sub)


credential_store = CredentialStore()
