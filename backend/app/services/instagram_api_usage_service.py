"""Track Meta's Instagram API usage headers and local request counts.

Unlike YouTube Data API, Instagram does not expose a fixed daily units quota
for this integration. Meta reports rolling app usage in the ``x-app-usage``
response header instead. The tracker keeps the latest values from that header
and a small local request summary so the dashboard can show both signals.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Mapping

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_DATA_DIR = _PROJECT_ROOT / "data"
_USAGE_FILE = _DATA_DIR / "instagram_api_usage.json"
_USAGE_HEADER = "https://developers.facebook.com/docs/graph-api/overview/rate-limiting/"


class InstagramApiUsageTracker:
    """Thread-safe JSON-backed tracker for Instagram Graph API responses."""

    def __init__(self, path: Path = _USAGE_FILE):
        self._path = path
        self._lock = Lock()

    @staticmethod
    def _today() -> str:
        return datetime.now(timezone.utc).date().isoformat()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _endpoint_label(method: str, path: str) -> str:
        method_name = str(method or "GET").upper()
        normalized_path = str(path or "").split("?", 1)[0].strip("/")
        if normalized_path == "me":
            return f"{method_name} profile"
        if method_name == "POST" and normalized_path.endswith("/media"):
            return "POST create media container"
        if method_name == "POST" and normalized_path.endswith("/media_publish"):
            return "POST publish media"
        if method_name == "GET":
            return "GET media container status"
        return f"{method_name} Instagram API"

    @staticmethod
    def _coerce_percent(value: Any) -> float | None:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        if number != number:  # NaN
            return None
        return round(max(0.0, min(number, 100.0)), 2)

    @classmethod
    def parse_usage_header(cls, value: Any) -> dict[str, float] | None:
        """Normalize Meta's header variants into three display metrics."""

        if not value:
            return None
        payload = value
        if isinstance(value, str):
            try:
                payload = json.loads(value)
            except (TypeError, json.JSONDecodeError):
                return None
        if not isinstance(payload, Mapping):
            return None

        aliases = {
            "call_volume": ("call_volume", "call_count"),
            "cpu_time": ("cpu_time", "total_cputime"),
            "total_time": ("total_time",),
        }
        parsed: dict[str, float] = {}
        for field, names in aliases.items():
            for name in names:
                if name in payload:
                    number = cls._coerce_percent(payload[name])
                    if number is not None:
                        parsed[field] = number
                        break
        return parsed or None

    @staticmethod
    def _empty_data(today: str) -> dict[str, Any]:
        return {
            "request_date": today,
            "requests_today": 0,
            "total_requests": 0,
            "methods": {},
            "last_meta_usage": None,
            "last_meta_usage_at": None,
            "last_error": None,
            "updated_at": None,
        }

    def _load_unlocked(self) -> dict[str, Any]:
        today = self._today()
        if not self._path.is_file():
            return self._empty_data(today)

        try:
            with self._path.open("r", encoding="utf-8") as file:
                data = json.load(file)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Failed to load Instagram API usage: %s", exc)
            return self._empty_data(today)

        if not isinstance(data, dict):
            return self._empty_data(today)
        data.setdefault("request_date", today)
        data.setdefault("requests_today", 0)
        data.setdefault("total_requests", 0)
        if not isinstance(data.get("methods"), dict):
            data["methods"] = {}
        data.setdefault("last_meta_usage", None)
        data.setdefault("last_meta_usage_at", None)
        data.setdefault("last_error", None)
        data.setdefault("updated_at", None)
        if data.get("request_date") != today:
            data["request_date"] = today
            data["requests_today"] = 0
            data["methods"] = {}
        if not isinstance(data.get("last_meta_usage"), dict):
            data["last_meta_usage"] = None
        return data

    def _save_unlocked(self, data: dict[str, Any]) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path = self._path.with_suffix(".tmp")
            with temporary_path.open("w", encoding="utf-8") as file:
                json.dump(data, file, ensure_ascii=False, indent=2)
            temporary_path.replace(self._path)
        except OSError as exc:
            logger.error("Failed to persist Instagram API usage: %s", exc)

    def record_response(
        self,
        method: str,
        path: str,
        response: Any,
        response_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Record one Graph API response without allowing tracking to fail the request."""

        headers = getattr(response, "headers", {}) or {}
        raw_usage = headers.get("x-app-usage") or headers.get("X-App-Usage")
        meta_usage = self.parse_usage_header(raw_usage)
        if response_data is None:
            try:
                response_data = response.json()
            except (AttributeError, ValueError):
                response_data = {}
        response_data = response_data if isinstance(response_data, dict) else {}
        error = response_data.get("error")
        status_code = getattr(response, "status_code", None)
        endpoint = self._endpoint_label(method, path)
        now = self._now()

        with self._lock:
            data = self._load_unlocked()
            data["requests_today"] = int(data.get("requests_today", 0)) + 1
            data["total_requests"] = int(data.get("total_requests", 0)) + 1
            method_data = data["methods"].setdefault(endpoint, {"calls": 0})
            method_data["calls"] = int(method_data.get("calls", 0)) + 1
            if meta_usage is not None:
                data["last_meta_usage"] = meta_usage
                data["last_meta_usage_at"] = now
            if isinstance(error, Mapping) or (isinstance(status_code, int) and status_code >= 400):
                error_payload = error if isinstance(error, Mapping) else {}
                message = str(error_payload.get("message") or error_payload.get("error_user_msg") or "")
                data["last_error"] = {
                    "endpoint": endpoint,
                    "status_code": status_code,
                    "code": error_payload.get("code"),
                    "error_subcode": error_payload.get("error_subcode"),
                    "message": message[:200],
                    "at": now,
                }
            data["updated_at"] = now
            self._save_unlocked(data)
            return self._format_usage(data)

    def get_usage(self) -> dict[str, Any]:
        with self._lock:
            return self._format_usage(self._load_unlocked())

    def _format_usage(self, data: dict[str, Any]) -> dict[str, Any]:
        meta_usage = data.get("last_meta_usage") or {}
        methods = data.get("methods") if isinstance(data.get("methods"), dict) else {}
        values = [value for value in meta_usage.values() if isinstance(value, (int, float))]
        usage_percent = round(max(values), 2) if values else None
        return {
            "request_date": data.get("request_date", self._today()),
            "requests_today": int(data.get("requests_today", 0)),
            "total_requests": int(data.get("total_requests", 0)),
            "methods": [
                {"endpoint": endpoint, **values}
                for endpoint, values in sorted(methods.items())
                if isinstance(values, dict)
            ],
            "meta_usage": {
                "available": bool(meta_usage),
                "call_volume": meta_usage.get("call_volume"),
                "cpu_time": meta_usage.get("cpu_time"),
                "total_time": meta_usage.get("total_time"),
                "usage_percent": usage_percent,
                "remaining_percent": max(100 - usage_percent, 0) if usage_percent is not None else None,
                "observed_at": data.get("last_meta_usage_at"),
            },
            "usage_percent": usage_percent,
            "remaining_percent": max(100 - usage_percent, 0) if usage_percent is not None else None,
            "updated_at": data.get("updated_at"),
            "last_error": data.get("last_error"),
            "has_fixed_quota": False,
            "is_estimate": False,
            "calculation_basis": "Meta x-app-usage response header",
            "quota_source_url": _USAGE_HEADER,
            "note": (
                "Instagram API 沒有 YouTube 那種固定 daily units 配額；這裡顯示 Meta 回應的 "
                "x-app-usage 滾動使用率，以及本系統實際送出的請求數。剩餘百分比是目前最高欄位的估算，"
                "不代表固定每日配額。"
            ),
        }


instagram_api_usage_tracker = InstagramApiUsageTracker()
