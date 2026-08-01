import json
import logging
import time
from typing import Any, Callable, Optional
from urllib.parse import urlencode

import httpx

from backend.app.services.instagram_api_usage_service import instagram_api_usage_tracker

logger = logging.getLogger(__name__)


META_BATCH_LIMIT = 50


class InstagramBatchError(RuntimeError):
    """A child request in a Meta Graph API batch failed.

    ``results`` contains every child response in the same order as the input
    batch.  Keeping partial responses on the exception is important for
    publishing: a batch may create some containers before a later child
    fails, and those IDs must be checkpointed so a retry cannot duplicate the
    successful work.
    """

    def __init__(
        self,
        message: str,
        *,
        index: int,
        results: list[dict[str, Any]],
    ) -> None:
        super().__init__(message)
        self.index = index
        self.results = results


def _stringify_batch_value(value: Any) -> Any:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return value


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

    @staticmethod
    def _batch_error_message(data: Any, status_code: int | None = None) -> str:
        if isinstance(data, dict):
            error = data.get("error")
            if isinstance(error, dict):
                return str(error.get("message") or error.get("error_user_msg") or "Instagram API batch request failed")
            if error:
                return str(error)
        return f"Instagram API batch request failed: HTTP {status_code or 500}"

    @staticmethod
    def _batch_token_error(data: Any, status_code: int | None = None) -> bool:
        if status_code == 401:
            return True
        error = data.get("error") if isinstance(data, dict) else None
        return isinstance(error, dict) and str(error.get("code")) == "190"

    @staticmethod
    def _batch_relative_url(path: str, params: dict[str, Any] | None = None) -> str:
        relative_url = str(path or "").lstrip("/")
        if not relative_url or "://" in relative_url:
            raise ValueError("Instagram batch relative_url must be a relative Graph API path")
        values = {str(key): _stringify_batch_value(value) for key, value in (params or {}).items() if value is not None}
        if values:
            separator = "&" if "?" in relative_url else "?"
            relative_url = f"{relative_url}{separator}{urlencode(values, doseq=True)}"
        return relative_url

    @classmethod
    def _build_batch_entries(
        cls,
        requests: list[dict[str, Any]],
        *,
        preserve_order: bool,
    ) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        previous_name: str | None = None
        for index, request in enumerate(requests):
            method = str(request.get("method") or "GET").upper()
            name = str(request.get("name") or f"creator-tools-{index}")
            entry: dict[str, Any] = {
                "method": method,
                "relative_url": cls._batch_relative_url(request.get("path", ""), request.get("params")),
                "name": name,
            }
            body = request.get("body", request.get("data"))
            if body:
                body_values = {
                    str(key): _stringify_batch_value(value) for key, value in body.items() if value is not None
                }
                entry["body"] = urlencode(body_values, doseq=True)
            if preserve_order:
                if previous_name is not None:
                    entry["depends_on"] = previous_name
                previous_name = name
            elif request.get("depends_on"):
                entry["depends_on"] = request["depends_on"]
            entries.append(entry)
        return entries

    def _batch_request_once(
        self,
        requests: list[dict[str, Any]],
        *,
        preserve_order: bool,
    ) -> list[dict[str, Any]]:
        entries = self._build_batch_entries(requests, preserve_order=preserve_order)
        headers = {"Authorization": f"Bearer {self.access_token}"}
        payload = {
            "access_token": self.access_token,
            "batch": json.dumps(entries, ensure_ascii=False, separators=(",", ":")),
            "include_headers": "false",
        }
        with httpx.Client(timeout=60, follow_redirects=True) as client:
            response = client.request(
                "POST",
                self.base_url,
                headers=headers,
                data=payload,
            )
        try:
            outer_data = response.json()
        except ValueError:
            outer_data = None
        try:
            instagram_api_usage_tracker.record_response(
                "POST", "batch", response, outer_data if isinstance(outer_data, dict) else {}
            )
        except Exception:
            logger.warning("Failed to record Instagram batch API usage", exc_info=True)

        if response.is_error or isinstance(outer_data, dict) and outer_data.get("error"):
            error = RuntimeError(self._batch_error_message(outer_data, response.status_code))
            error.token_error = self._batch_token_error(outer_data, response.status_code)
            raise error
        if not isinstance(outer_data, list):
            raise RuntimeError("Instagram API batch response was not an array")

        results: list[dict[str, Any]] = []
        for index, raw_result in enumerate(outer_data):
            if not isinstance(raw_result, dict):
                data: Any = {}
                status_code = 500
            else:
                status_code = int(raw_result.get("code") or 500)
                raw_body = raw_result.get("body")
                try:
                    data = json.loads(raw_body) if isinstance(raw_body, str) else (raw_body or {})
                except (TypeError, json.JSONDecodeError):
                    data = {}
            error_payload = data.get("error") if isinstance(data, dict) else None
            ok = 200 <= status_code < 300 and not error_payload
            results.append(
                {
                    "ok": ok,
                    "status_code": status_code,
                    "data": data if isinstance(data, dict) else {},
                    "error": self._batch_error_message(data, status_code) if not ok else None,
                    "token_error": self._batch_token_error(data, status_code),
                    "index": index,
                }
            )
        if len(results) != len(requests):
            raise RuntimeError("Instagram API batch response count did not match the request count")
        return results

    def batch_request(
        self,
        requests: list[dict[str, Any]],
        *,
        preserve_order: bool = True,
    ) -> list[dict[str, Any]]:
        """Send Meta Graph API requests in ordered chunks of at most 50.

        The outer HTTP calls are sent sequentially when more than 50 child
        requests are supplied.  Within each batch, ``depends_on`` creates an
        ordered chain by default, while the returned list always follows the
        original input order.
        """

        request_list = list(requests)
        if not request_list:
            return []
        results: list[dict[str, Any]] = []
        for start in range(0, len(request_list), META_BATCH_LIMIT):
            chunk = request_list[start : start + META_BATCH_LIMIT]
            try:
                chunk_results = self._batch_request_once(chunk, preserve_order=preserve_order)
            except RuntimeError as exc:
                if not getattr(exc, "token_error", False) or not self._on_token_refresh:
                    raise
                refreshed_token = self._on_token_refresh()
                if not refreshed_token:
                    raise
                self.access_token = refreshed_token
                chunk_results = self._batch_request_once(chunk, preserve_order=preserve_order)
            for result in chunk_results:
                result["index"] = start + int(result.get("index", 0))
            results.extend(chunk_results)
            # A failed child in an ordered batch is the ordering barrier for
            # every later chunk as well.  Do not send side-effecting requests
            # after that failure; callers can checkpoint the successful prefix
            # and retry the failed suffix safely.
            if preserve_order and any(not result.get("ok") for result in chunk_results):
                break
        return results

    def _request_from_batch_spec(self, request: dict[str, Any]) -> dict[str, Any]:
        """Execute one child request using the normal client path.

        High-level Instagram operations are independent child requests.  If
        Meta rejects one child in an otherwise valid batch, retrying only that
        child keeps the successful responses useful without repeating their
        side effects.
        """

        kwargs: dict[str, Any] = {}
        if request.get("params"):
            kwargs["params"] = request["params"]
        body = request.get("body", request.get("data"))
        if body is not None:
            kwargs["data"] = {
                str(key): _stringify_batch_value(value) for key, value in body.items() if value is not None
            }
        return self.request(
            str(request.get("method") or "GET").upper(),
            str(request.get("path") or ""),
            **kwargs,
        )

    def _independent_batch_data(self, requests: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Run independent children without artificial ``depends_on`` links.

        The Graph batch response keeps the input order, so the caller still
        gets deterministic ID/status mapping.  ``depends_on`` is reserved for
        low-level callers whose later request actually consumes an earlier
        request's result; using it for separate Reel operations can prevent
        later children from running when the first child has a transient
        failure.  A failed child is retried individually once so one bad child
        does not discard successful work from the same batch.
        """

        results = self.batch_request(requests, preserve_order=False)
        resolved: list[dict[str, Any]] = []
        first_failure: int | None = None
        for index, (request, result) in enumerate(zip(requests, results)):
            if result.get("ok"):
                resolved.append(result)
                continue
            try:
                data = self._request_from_batch_spec(request)
            except Exception as exc:
                if first_failure is None:
                    first_failure = index
                resolved.append(
                    {
                        "ok": False,
                        "status_code": getattr(exc, "status_code", 500),
                        "data": {},
                        "error": str(exc) or result.get("error") or "Instagram API batch child request failed",
                        "token_error": bool(getattr(exc, "token_error", False)),
                        "index": index,
                    }
                )
            else:
                resolved.append(
                    {
                        "ok": True,
                        "status_code": 200,
                        "data": data,
                        "error": None,
                        "token_error": False,
                        "index": index,
                    }
                )

        if first_failure is not None:
            failed = resolved[first_failure]
            raise InstagramBatchError(
                failed.get("error") or "Instagram API batch child request failed",
                index=first_failure,
                results=resolved,
            )
        return [result["data"] for result in resolved]

    def _strict_batch_data(
        self,
        requests: list[dict[str, Any]],
        *,
        preserve_order: bool = True,
    ) -> list[dict[str, Any]]:
        results = self.batch_request(requests, preserve_order=preserve_order)
        for result in results:
            if not result["ok"]:
                raise InstagramBatchError(
                    result["error"] or "Instagram API batch child request failed",
                    index=int(result["index"]),
                    results=results,
                )
        return [result["data"] for result in results]

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

    def create_reel_containers(self, reels: list[dict[str, Any]]) -> list[str]:
        """Create multiple Reel containers in input order with one batch call."""

        if not reels:
            return []
        if len(reels) == 1:
            return [
                self.create_reel_container(
                    str(reels[0]["video_url"]),
                    str(reels[0].get("caption") or ""),
                    bool(reels[0].get("share_to_feed", True)),
                )
            ]
        requests = [
            {
                "method": "POST",
                "path": f"{self.user_id}/media",
                "data": {
                    "media_type": "REELS",
                    "video_url": reel["video_url"],
                    "caption": reel.get("caption") or "",
                    "share_to_feed": bool(reel.get("share_to_feed", True)),
                },
            }
            for reel in reels
        ]
        return [str(data["id"]) for data in self._independent_batch_data(requests)]

    def get_container_statuses(self, creation_ids: list[str]) -> list[dict[str, Any]]:
        """Fetch container statuses in the same order as ``creation_ids``."""

        if not creation_ids:
            return []
        if len(creation_ids) == 1:
            return [self.request("GET", creation_ids[0], params={"fields": "status_code,status"})]
        requests = [
            {
                "method": "GET",
                "path": creation_id,
                "params": {"fields": "status_code,status"},
            }
            for creation_id in creation_ids
        ]
        return self._independent_batch_data(requests)

    def publish_containers(self, creation_ids: list[str]) -> list[str]:
        """Publish multiple ready containers in input order with one batch call."""

        if not creation_ids:
            return []
        if len(creation_ids) == 1:
            return [self.publish_container(creation_ids[0])]
        requests = [
            {
                "method": "POST",
                "path": f"{self.user_id}/media_publish",
                "data": {"creation_id": creation_id},
            }
            for creation_id in creation_ids
        ]
        return [str(data.get("id") or "") for data in self._independent_batch_data(requests)]

    def wait_for_containers(
        self,
        creation_ids: list[str],
        *,
        poll_interval: float = 5,
        max_polls: int = 120,
    ) -> list[dict[str, Any]]:
        """Poll multiple containers using one ordered batch per poll cycle."""

        if not creation_ids:
            return []
        if len(creation_ids) == 1:
            self.wait_for_container(creation_ids[0], poll_interval=poll_interval, max_polls=max_polls)
            return [{"status_code": "FINISHED", "status": "Finished"}]

        pending = list(creation_ids)
        final: dict[str, dict[str, Any]] = {}
        for _ in range(max_polls):
            statuses = self.get_container_statuses(pending)
            next_pending: list[str] = []
            for creation_id, status in zip(pending, statuses):
                code = status.get("status_code")
                if code == "FINISHED":
                    final[creation_id] = status
                elif code in {"ERROR", "EXPIRED"}:
                    raise RuntimeError(status.get("status") or f"Instagram container {code}")
                else:
                    next_pending.append(creation_id)
            if not next_pending:
                return [final[creation_id] for creation_id in creation_ids]
            pending = next_pending
            time.sleep(poll_interval)
        raise RuntimeError("等待 Instagram 處理影片逾時")

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
