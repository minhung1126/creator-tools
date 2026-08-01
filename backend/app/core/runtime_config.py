"""
Runtime Configuration Persistence

Manages user-modifiable, non-secret settings that persist across server restarts.
Sensitive values are stored separately by credential_store.py.
"""

import json
import logging
from pathlib import Path
from threading import Lock
from typing import Any, Dict

from backend.app.core.config import settings

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_DATA_DIR = _PROJECT_ROOT / "data"
_CONFIG_FILE = _DATA_DIR / "runtime_config.json"

# Only non-secret fields belong here. Tokens and secret keys must use credential_store.
_PERSISTABLE_FIELDS = {
    "default_spreadsheet_id",
    "default_playlist_id",
    "youtube_draft_video_config",
    "youtube_draft_shorts_config",
    "instagram_drive_folder_id",
    "instagram_spreadsheet_id",
    "r2_account_id",
    "r2_access_key_id",
    "r2_bucket_name",
    "r2_public_base_url",
}

# Removed legacy secrets are discarded during load instead of being copied forward.
_LEGACY_SECRET_FIELDS = {"meta_app_secret", "meta_access_token", "instagram_access_token", "r2_secret_access_key"}


class RuntimeConfig:
    """Thread-safe persistent configuration store backed by a JSON file."""

    def __init__(self, config_path: Path = _CONFIG_FILE):
        self._path = config_path
        self._lock = Lock()
        self._data: Dict[str, Any] = {}
        self._migrate_legacy_config()
        self._load()

    def _migrate_legacy_config(self):
        legacy_root_config = _PROJECT_ROOT / "runtime_config.json"
        if not self._path.exists() and legacy_root_config.is_file():
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                import shutil

                shutil.move(str(legacy_root_config), str(self._path))
                logger.info("Migrated legacy runtime_config.json to %s", self._path)
            except Exception as exc:
                logger.warning("Failed to migrate legacy runtime config: %s", exc)

    def _load(self):
        if not self._path.is_file():
            self._data = {}
            return
        try:
            with self._path.open("r", encoding="utf-8") as handle:
                saved = json.load(handle)
            self._data = {key: value for key, value in saved.items() if key in _PERSISTABLE_FIELDS}
            if any(key in saved for key in _LEGACY_SECRET_FIELDS):
                logger.warning("Discarded legacy plaintext secret fields from runtime_config.json")
                self._save()
            logger.info("Loaded runtime config from %s", self._path)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load runtime config: %s", exc)
            self._data = {}

    def _save(self):
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self._path.with_suffix(".tmp")
            with tmp_path.open("w", encoding="utf-8") as handle:
                json.dump(self._data, handle, ensure_ascii=False, indent=2)
            tmp_path.replace(self._path)
            logger.info("Saved runtime config to %s", self._path)
        except OSError as exc:
            logger.error("Failed to save runtime config: %s", exc)

    def get(self, key: str, default: Any = "") -> Any:
        with self._lock:
            if key in self._data and self._data[key] not in (None, ""):
                return self._data[key]
        env_value = getattr(settings, key.upper(), "")
        return env_value if env_value not in (None, "") else default

    def set(self, key: str, value: Any):
        if key not in _PERSISTABLE_FIELDS:
            logger.warning("Attempted to persist non-persistable field: %s", key)
            return
        with self._lock:
            self._data[key] = value
            self._save()

    def update(self, data: Dict[str, Any]):
        with self._lock:
            for key, value in data.items():
                if key in _PERSISTABLE_FIELDS and value is not None:
                    self._data[key] = value
            self._save()

    def get_all(self) -> Dict[str, Any]:
        return {field: self.get(field) for field in _PERSISTABLE_FIELDS}


runtime_config = RuntimeConfig()
