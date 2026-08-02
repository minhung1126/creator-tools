import logging
import random
import time
from copy import deepcopy
from threading import Lock
from typing import Any, Callable, Optional

import httpx

from backend.app.core.config import settings
from backend.app.core.instagram_limiter import InstagramLimiter, instagram_limiter
from backend.app.services.instagram_api_usage_service import instagram_api_usage_tracker
from backend.app.services.instagram_errors import InstagramApiError

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
    _cache_lock = Lock()
    _cache: dict[tuple[str, str, str], tuple[float, Any]] = {}

    def __init__(
        self,
        user_id: str,
        access_token: str,
        api_version: str = "v25.0",
        on_token_refresh: Optional[Callable[[], str]] = None,
        limiter: Optional[InstagramLimiter] = None,
    ):
        self.user_id = str(user_id)
        self.access_token = access_token
        self.base_url = f"https://graph.instagram.com/{api_version}"
        self._on_token_refresh = on_token_refresh
        self.limiter = limiter or instagram_limiter

    @staticmethod
    def _is_token_error(response: httpx.Response, data: dict) -> bool:
        if response.status_code == 401:
            return True
        error = data.get("error") if isinstance(data, dict) else None
        return isinstance(error, dict) and str(error.get("code")) == "190"

    def _request_once(self, method: str, path: str, **kwargs):
        endpoint = str(path or "").split("?", 1)[0].strip("/")
        self.limiter.assert_request_allowed(method=method, endpoint=endpoint)
        headers = {"Authorization": f"Bearer {self.access_token}"}
        headers.update(kwargs.pop("headers", {}))
        try:
            with httpx.Client(timeout=60, follow_redirects=True) as client:
                response = client.request(
                    method,
                    f"{self.base_url}/{path.lstrip('/')}",
                    headers=headers,
                    **kwargs,
                )
        except httpx.TimeoutException as exc:
            raise InstagramApiError.timeout(method=method, endpoint=endpoint) from exc
        except httpx.RequestError as exc:
            raise InstagramApiError.transport(method=method, endpoint=endpoint) from exc
        try:
            data = response.json()
        except ValueError:
            data = {}
        raw_usage = (getattr(response, "headers", {}) or {}).get("x-app-usage")
        if raw_usage is None:
            raw_usage = (getattr(response, "headers", {}) or {}).get("X-App-Usage")
        meta_usage = instagram_api_usage_tracker.parse_usage_header(raw_usage)
        try:
            instagram_api_usage_tracker.record_response(method, path, response, data)
        except Exception:  # Tracking must never turn a successful API call into a failure.
            logger.warning("Failed to record Instagram API usage", exc_info=True)
        try:
            self.limiter.observe_usage(meta_usage)
        except Exception:
            logger.warning("Failed to record Instagram limiter usage", exc_info=True)
        if response.is_error or data.get("error"):
            error = InstagramApiError.from_response(
                response,
                data,
                method=method,
                endpoint=endpoint,
                x_app_usage=meta_usage,
            )
            if error.rate_limited:
                try:
                    state = self.limiter.record_rate_limit(error, endpoint=endpoint, usage=meta_usage)
                    if not error.estimated_recovery_at:
                        error.estimated_recovery_at = state.get("estimated_recovery_at")
                except Exception:
                    logger.warning("Failed to persist Instagram limiter cooldown", exc_info=True)
            raise error
        try:
            self.limiter.record_success(endpoint=endpoint)
        except Exception:
            logger.warning("Failed to persist Instagram limiter success", exc_info=True)
        return data

    def request(self, method: str, path: str, **kwargs):
        try:
            return self._request_once(method, path, **kwargs)
        except InstagramApiError as exc:
            if not exc.token_error or not self._on_token_refresh:
                raise
            refreshed_token = self._on_token_refresh()
            if not refreshed_token:
                raise
            self.access_token = refreshed_token
            return self._request_once(method, path, **kwargs)

    def _cached(self, name: str, loader: Callable[[], Any], ttl_seconds: float) -> Any:
        ttl = max(float(ttl_seconds), 0)
        key = (self.user_id, self.access_token, name)
        now = time.monotonic()
        with self._cache_lock:
            cached = self._cache.get(key)
            if cached and now - cached[0] < ttl:
                return deepcopy(cached[1])
        value = loader()
        with self._cache_lock:
            self._cache[key] = (now, deepcopy(value))
        return value

    @classmethod
    def clear_cache(cls) -> None:
        with cls._cache_lock:
            cls._cache.clear()

    def profile(self):
        # /me avoids trusting a separately supplied account ID during verification.
        return self._cached(
            "profile",
            lambda: self.request("GET", "me", params={"fields": "id,username,account_type"}),
            settings.INSTAGRAM_METADATA_CACHE_SECONDS,
        )

    def get_content_publishing_limit(self) -> dict[str, int] | None:
        """Return the account's live rolling publishing capacity when available."""

        def load() -> dict[str, int] | None:
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

        result = self._cached(
            "content_publishing_limit",
            load,
            settings.INSTAGRAM_PUBLISHING_LIMIT_CACHE_SECONDS,
        )
        if result:
            try:
                instagram_api_usage_tracker.record_publishing_limit(result)
            except Exception:
                logger.warning("Failed to record Instagram publishing capacity", exc_info=True)
        return result

    def publish_reel(self, video_url: str, caption: str, share_to_feed: bool = True):
        creation_id = self.create_reel_container(video_url, caption, share_to_feed)
        self.wait_for_container(creation_id)
        return {"creation_id": creation_id, "media_id": self.publish_container(creation_id)}

    def create_reel_container(self, video_url: str, caption: str, share_to_feed: bool = True) -> str:
        self.limiter.assert_can_start_task(endpoint=f"{self.user_id}/media")
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

    def wait_for_container(
        self,
        creation_id: str,
        *,
        poll_interval: float | None = None,
        max_polls: int | None = None,
        max_poll_interval: float | None = None,
    ):
        initial_interval = max(
            float(settings.INSTAGRAM_CONTAINER_INITIAL_POLL_SECONDS if poll_interval is None else poll_interval), 0.1
        )
        upper_interval = max(
            float(settings.INSTAGRAM_CONTAINER_MAX_POLL_SECONDS if max_poll_interval is None else max_poll_interval),
            initial_interval,
        )
        poll_limit = max(int(settings.INSTAGRAM_CONTAINER_MAX_POLLS if max_polls is None else max_polls), 1)
        delay = initial_interval
        for poll_number in range(poll_limit):
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
            usage = instagram_api_usage_tracker.get_usage()
            usage_percent = usage.get("usage_percent")
            if usage_percent is not None and usage_percent >= float(settings.INSTAGRAM_USAGE_SOFT_THRESHOLD):
                delay = min(upper_interval, max(delay, initial_interval * 1.5))
            if usage_percent is not None and usage_percent >= float(settings.INSTAGRAM_USAGE_HARD_THRESHOLD):
                delay = max(delay, upper_interval * 0.75)
            if poll_number < poll_limit - 1:
                jitter = random.uniform(0, max(float(settings.INSTAGRAM_CONTAINER_POLL_JITTER_SECONDS), 0))
                time.sleep(min(upper_interval, delay + jitter))
                delay = min(upper_interval, delay * 1.5)
        else:
            raise RuntimeError("等待 Instagram 處理影片逾時")

    def publish_container(self, creation_id: str) -> str:
        published = self.request(
            "POST",
            f"{self.user_id}/media_publish",
            data={"creation_id": creation_id},
        )
        media_id = published.get("id") if isinstance(published, dict) else None
        if not media_id:
            raise RuntimeError("Instagram 未回傳 media_id")
        # A successful publish changes the rolling account capacity.  Do not
        # let the short-lived quota cache authorize the next Reel with stale
        # remaining capacity.
        with self._cache_lock:
            self._cache.pop((self.user_id, self.access_token, "content_publishing_limit"), None)
        return str(media_id)
