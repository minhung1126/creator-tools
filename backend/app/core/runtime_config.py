"""
Runtime Configuration Persistence

Manages user-modifiable settings that persist across server restarts.
On startup, values from .env are used as defaults, then overlaid with
any values saved in runtime_config.json.
"""

import json
import logging
import os
from pathlib import Path
from threading import Lock
from typing import Any, Dict, Optional

from backend.app.core.config import settings

logger = logging.getLogger(__name__)

# Resolve config file path relative to project root
_CONFIG_DIR = Path(__file__).resolve().parent.parent.parent.parent  # creator-tools/
_CONFIG_FILE = _CONFIG_DIR / "runtime_config.json"

# Fields that can be persisted via the Settings UI
_PERSISTABLE_FIELDS = {
    "default_spreadsheet_id",
    "default_playlist_id",
    "default_drive_folder_id",
    "meta_app_id",
    "meta_app_secret",
    "meta_access_token",
}


class RuntimeConfig:
    """Thread-safe persistent configuration store backed by a JSON file."""

    def __init__(self, config_path: Path = _CONFIG_FILE):
        self._path = config_path
        self._lock = Lock()
        self._data: Dict[str, str] = {}
        self._load()

    def _load(self):
        """Load saved config from JSON file, falling back to .env defaults."""
        if self._path.exists():
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                self._data = {k: v for k, v in saved.items() if k in _PERSISTABLE_FIELDS}
                logger.info("Loaded runtime config from %s", self._path)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Failed to load runtime config: %s", e)
                self._data = {}
        else:
            self._data = {}

    def _save(self):
        """Atomically save current config to JSON file."""
        try:
            tmp_path = self._path.with_suffix(".tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
            tmp_path.replace(self._path)
            logger.info("Saved runtime config to %s", self._path)
        except OSError as e:
            logger.error("Failed to save runtime config: %s", e)

    def get(self, key: str, default: str = "") -> str:
        """Get a config value. Priority: runtime_config.json > .env > default."""
        with self._lock:
            if key in self._data and self._data[key]:
                return self._data[key]
        # Fall back to .env value from Settings
        env_value = getattr(settings, key.upper(), "")
        return env_value or default

    def set(self, key: str, value: str):
        """Set and persist a config value."""
        if key not in _PERSISTABLE_FIELDS:
            logger.warning("Attempted to persist non-persistable field: %s", key)
            return
        with self._lock:
            self._data[key] = value
            self._save()

    def update(self, data: Dict[str, Any]):
        """Bulk update and persist multiple config values."""
        with self._lock:
            for key, value in data.items():
                if key in _PERSISTABLE_FIELDS and value is not None:
                    self._data[key] = str(value)
            self._save()

    def get_all(self) -> Dict[str, str]:
        """Get all persistable config values (merged with .env defaults)."""
        result = {}
        for field in _PERSISTABLE_FIELDS:
            result[field] = self.get(field)
        return result


# Singleton instance
runtime_config = RuntimeConfig()
