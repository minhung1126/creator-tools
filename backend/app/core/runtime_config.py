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

from backend.app.core.config import normalize_youtube_slot, settings

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_DATA_DIR = _PROJECT_ROOT / "data"
_CONFIG_FILE = _DATA_DIR / "runtime_config.json"

# Only non-secret fields belong here. Tokens and secret keys must use credential_store.
_PERSISTABLE_FIELDS = {
    "default_spreadsheet_id",
    "default_playlist_id",
    "youtube_general_quota_limit",
    "youtube_quota_safety_buffer_units",
    "youtube_primary_general_quota_limit",
    "youtube_primary_quota_safety_buffer_units",
    "youtube_secondary_general_quota_limit",
    "youtube_secondary_quota_safety_buffer_units",
    "youtube_active_slot",
    "youtube_draft_video_config",
    "youtube_draft_shorts_config",
    "shared_team_person_filter",
}

class RuntimeConfig:
    """Thread-safe persistent configuration store backed by a JSON file."""

    def __init__(self, config_path: Path = _CONFIG_FILE):
        self._path = config_path
        self._lock = Lock()
        self._data: Dict[str, Any] = {}
        self._load()

    def _load(self):
        if not self._path.is_file():
            self._data = {}
            return
        try:
            with self._path.open("r", encoding="utf-8") as handle:
                saved = json.load(handle)
            if not isinstance(saved, dict):
                raise ValueError("runtime config root must be an object")
            self._data = {key: value for key, value in saved.items() if key in _PERSISTABLE_FIELDS}
            logger.info("Loaded runtime config from %s", self._path)
        except (json.JSONDecodeError, OSError, TypeError, ValueError) as exc:
            logger.warning("Failed to load runtime config: %s", type(exc).__name__)
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
            logger.error("Failed to save runtime config: %s", type(exc).__name__)

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

    def get_youtube_quota_settings(self, slot: str) -> tuple[int, int]:
        """Return the persisted-or-environment quota policy for one slot.

        The old generic keys remain a primary-slot fallback so an existing
        deployment can be upgraded without changing its effective quota on
        the first restart.
        """
        slot_name = normalize_youtube_slot(slot)
        slot_config = settings.youtube_oauth_slot(slot_name)
        limit_key = f"youtube_{slot_name}_general_quota_limit"
        buffer_key = f"youtube_{slot_name}_quota_safety_buffer_units"
        with self._lock:
            has_slot_limit = limit_key in self._data
            has_slot_buffer = buffer_key in self._data
            has_legacy_limit = "youtube_general_quota_limit" in self._data
            has_legacy_buffer = "youtube_quota_safety_buffer_units" in self._data

        if slot_name == "primary" and not has_slot_limit and has_legacy_limit:
            limit = self.get("youtube_general_quota_limit", slot_config.quota_limit)
        else:
            limit = self.get(limit_key, slot_config.quota_limit)
        if slot_name == "primary" and not has_slot_buffer and has_legacy_buffer:
            buffer = self.get("youtube_quota_safety_buffer_units", slot_config.safety_buffer_units)
        else:
            buffer = self.get(buffer_key, slot_config.safety_buffer_units)

        try:
            parsed_limit = max(int(limit), 1)
        except (TypeError, ValueError):
            parsed_limit = max(int(slot_config.quota_limit), 1)
        try:
            parsed_buffer = max(int(buffer), 0)
        except (TypeError, ValueError):
            parsed_buffer = max(int(slot_config.safety_buffer_units), 0)
        return parsed_limit, min(parsed_buffer, max(parsed_limit - 1, 0))

    def get_youtube_active_slot(self) -> str:
        value = self.get("youtube_active_slot", settings.youtube_default_slot)
        try:
            slot = normalize_youtube_slot(value)
        except ValueError:
            return settings.youtube_default_slot
        if settings.youtube_oauth_slot(slot).configured:
            return slot
        if settings.youtube_oauth_slot(settings.youtube_default_slot).configured:
            return settings.youtube_default_slot
        return slot

    def set_youtube_active_slot(self, slot: str) -> None:
        self.set("youtube_active_slot", normalize_youtube_slot(slot))


runtime_config = RuntimeConfig()
