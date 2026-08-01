import time

import httpx


class InstagramClient:
    def __init__(self, user_id: str, access_token: str, api_version: str = "v25.0"):
        self.user_id = str(user_id)
        self.access_token = access_token
        self.base_url = f"https://graph.instagram.com/{api_version}"

    def request(self, method: str, path: str, **kwargs):
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
        if response.is_error or data.get("error"):
            error = data.get("error") or {}
            if isinstance(error, dict):
                message = error.get("message") or error.get("error_user_msg")
            else:
                message = str(error)
            raise RuntimeError(message or f"Instagram API HTTP {response.status_code}")
        return data

    def profile(self):
        # /me avoids trusting a separately supplied account ID during verification.
        return self.request("GET", "me", params={"fields": "id,username,account_type"})

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

    def wait_for_container(self, creation_id: str):
        for _ in range(120):
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
            time.sleep(5)
        else:
            raise RuntimeError("等待 Instagram 處理影片逾時")

    def publish_container(self, creation_id: str) -> str:
        published = self.request(
            "POST",
            f"{self.user_id}/media_publish",
            data={"creation_id": creation_id},
        )
        return published.get("id")
