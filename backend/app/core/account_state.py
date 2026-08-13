"""Account-scoped settings and work-state helpers."""

from __future__ import annotations

from typing import Any

from backend.app.core.account_state_store import (
    ACCOUNT_SETTING_KEYS,
    MISSING,
    WORK_STATE_KEYS,
    account_state_store,
)
from backend.app.core.config import normalize_youtube_slot, settings


def _owner(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def ensure_account(owner_sub: str) -> str:
    subject = _owner(owner_sub)
    if not subject:
        raise ValueError("account subject is required")
    account_state_store.ensure_account(subject)
    return subject


def get_account_setting(owner_sub: str, key: str, default: Any = "") -> Any:
    if key not in ACCOUNT_SETTING_KEYS:
        raise ValueError(f"Unsupported account setting: {key}")
    subject = ensure_account(owner_sub)
    value = account_state_store.get_setting(subject, key, MISSING)
    return default if value is MISSING else value


def set_account_setting(owner_sub: str, key: str, value: Any) -> None:
    if key not in ACCOUNT_SETTING_KEYS:
        raise ValueError(f"Unsupported account setting: {key}")
    subject = ensure_account(owner_sub)
    account_state_store.set_setting(subject, key, value)


def update_account_settings(owner_sub: str, values: dict[str, Any]) -> None:
    subject = ensure_account(owner_sub)
    for key, value in values.items():
        if key in ACCOUNT_SETTING_KEYS and value is not None:
            account_state_store.set_setting(subject, key, value)


def get_account_active_slot(owner_sub: str) -> str:
    subject = ensure_account(owner_sub)
    value = get_account_setting(subject, "youtube_active_slot", settings.youtube_default_slot)
    try:
        slot = normalize_youtube_slot(value)
    except ValueError:
        slot = settings.youtube_default_slot
    if settings.youtube_oauth_slot(slot).configured:
        return slot
    if settings.youtube_oauth_slot(settings.youtube_default_slot).configured:
        return settings.youtube_default_slot
    return slot


def set_account_active_slot(owner_sub: str, slot: str) -> str:
    normalized = normalize_youtube_slot(slot)
    set_account_setting(owner_sub, "youtube_active_slot", normalized)
    return normalized


def get_account_work_state(owner_sub: str) -> dict[str, Any]:
    subject = ensure_account(owner_sub)
    return account_state_store.get_work_state(subject)


def update_account_work_state(owner_sub: str, key: str, value: dict[str, Any]) -> dict[str, Any]:
    if key not in WORK_STATE_KEYS:
        raise ValueError(f"Unsupported work state: {key}")
    subject = ensure_account(owner_sub)
    return account_state_store.set_work_state(subject, key, value)


__all__ = [
    "ensure_account",
    "get_account_active_slot",
    "get_account_setting",
    "get_account_work_state",
    "set_account_active_slot",
    "set_account_setting",
    "update_account_settings",
    "update_account_work_state",
]
