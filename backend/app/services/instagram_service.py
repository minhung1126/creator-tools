import logging
import time
from typing import Any, Callable, Optional

import httpx

from backend.app.services.instagram_api_usage_service import instagram_api_usage_tracker

logger = logging.getLogger(__name__)


class InstagramBatchError(RuntimeError):
    """Compatibility error used by the legacy multi-task handler.

    The Instagram client no longer sends Graph batch requests. New worker
    execution processes exactly one Reel at a time through the single-item
    methods below.
    """

    def __init__(self, message: str, *, index: int, results: list[dict[str, Any]]) -> None:
        super().__init__(message)
        self.index = index
        self.results = results


class InstagramClient:
    def __init__(
        self,
        user_id: str,
        access_token: str,
        api_version: str = "v25.0",
        on_token_refresh: Optional[Callable[[], str]] = None,
    ):
        self.user_id = str(user_id)
        self.access_token = access_token
        self.base_url = f"https://graph.instagram.com/{api_version}"
        self._on_token_refresh = on_token_refresh

    @staticmethod
    def _is_token_error(response: httpx.Response, data: dict) -> bool:
        if response.status_code == 401:
            return True
        error = data.get("error") if isinstance(data, dict) else None
        return isinstance(error, dict) and str(error.get("code")) == "190"

    def _request_once(self, method: str, path: str, **kwargs):
        headers = {"Authorization": f"Bearer {self.access_token}"}
        headers.update(kwargs.pop("headers", {}))
        with httpx.Client(timeout=60, follow_redirects=True) as client:
            response = client.request(
                method,
                f"{self.base_url}/{path.lstrip('/')}",
                headers=headers,
                **kwargs,
            )
        try:
            data = response.json()
        except ValueError:
            data = {}
        try:
            instagram_api_usage_tracker.record_response(method, path, response, data)
        except Exception:  # Tracking must never turn a successful API call into a failure.
            logger.warning("Failed to record Instagram API usage", exc_info=True)
        if response.is_error or data.get("error"):
            error = data.get("error") or {}
            if isinstance(error, dict):
                message = error.get("message") or error.get("error_user_msg")
            else:
                message = str(error)
            error = data.get("error") or {}
            error_message = message or f"Instagram API HTTP {response.status_code}"
            error = RuntimeError(error_message)
            error.token_error = self._is_token_error(response, data)
            raise error
        return data

    def request(self, method: str, path: str, **kwargs):
        try:
            return self._request_once(method, path, **kwargs)
        except RuntimeError as exc:
            if not getattr(exc, "token_error", False) or not self._on_token_refresh:
                raise
            refreshed_token = self._on_token_refresh()
            if not refreshed_token:
                raise
            self.access_token = refreshed_token
            return self._request_once(method, path, **kwargs)

    def profile(self):
        # /me avoids trusting a separately supplied account ID during verification.
        return self.request("GET", "me", params={"fields": "id,username,account_type"})

    def get_content_publishing_limit(self) -> dict[str, int] | None:
        """Return the account's live rolling publishing capacity when available."""

        payload = self.request(
            "GET",
            f"{self.user_id}/content_publishing_limit",
            params={"fields": "quota_usage,config"},
        )
        records = payload.get("data") if isinstance(payload, dict) else None
        record = records[0] if isinstance(records, list) and records and isinstance(records[0], dict) else None
        if not record:
            return None
        config = record.get("config") if isinstance(record.get("config"), dict) else {}
        try:
            used = max(int(record.get("quota_usage") or 0), 0)
            total = max(int(config.get("quota_total") or 0), 0)
        except (TypeError, ValueError):
            return None
        if total <= 0:
            return None
        return {"used": used, "total": total, "remaining": max(total - used, 0)}

    def publish_reel(self, video_url: str, caption: str, share_to_feed: bool = True):
        creation_id = self.create_reel_container(video_url, caption, share_to_feed)
        self.wait_for_container(creation_id)
        return {"creation_id": creation_id, "media_id": self.publish_container(creation_id)}

    def create_reel_container(self, video_url: str, caption: str, share_to_feed: bool = True) -> str:
        container = self.request(
            "POST",
            f"{self.user_id}/media",
            data={
                "media_type": "REELS",
                "video_url": video_url,
                "caption": caption,
                "share_to_feed": "true" if share_to_feed else "false",
            },
        )
        return container["id"]

    def wait_for_container(self, creation_id: str, *, poll_interval: float = 5, max_polls: int = 120):
        for _ in range(max_polls):
            status = self.request(
                "GET",
                creation_id,
                params={"fields": "status_code,status"},
            )
            code = status.get("status_code")
            if code == "FINISHED":
                break
            if code in {"ERROR", "EXPIRED"}:
                raise RuntimeError(status.get("status") or f"Instagram container {code}")
            time.sleep(poll_interval)
        else:
            raise RuntimeError("等待 Instagram 處理影片逾時")

    def publish_container(self, creation_id: str) -> str:
        published = self.request(
            "POST",
            f"{self.user_id}/media_publish",
            data={"creation_id": creation_id},
        )
        return published.get("id")
