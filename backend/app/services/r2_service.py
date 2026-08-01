import ipaddress
import re
import socket
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urlparse

import boto3
import httpx


@dataclass
class R2Config:
    account_id: str
    access_key_id: str
    secret_access_key: str
    bucket_name: str
    public_base_url: str

    def __post_init__(self):
        validate_public_base_url(self.public_base_url)
        if not re.fullmatch(r"[A-Za-z0-9-]+", self.account_id):
            raise ValueError("R2 Account ID 格式無效")

    @property
    def endpoint_url(self):
        return f"https://{self.account_id}.r2.cloudflarestorage.com"


def validate_public_base_url(value: str) -> str:
    parsed = urlparse((value or "").strip())
    if parsed.scheme.lower() != "https":
        raise ValueError("R2 公開網址必須使用 HTTPS")
    if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("R2 公開網址格式無效")
    hostname = parsed.hostname.rstrip(".").lower()
    if hostname in {"localhost", "localhost.localdomain"} or hostname.endswith(".localhost"):
        raise ValueError("R2 公開網址不得指向 localhost")
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(hostname, parsed.port or 443, type=socket.SOCK_STREAM)}
    except OSError as exc:
        raise ValueError("R2 公開網址無法解析") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise ValueError("R2 公開網址不得指向 private 或 loopback IP")
    return parsed._replace(scheme="https", netloc=parsed.netloc, path=parsed.path.rstrip("/")).geturl().rstrip("/")


def create_client(config: R2Config):
    return boto3.client(
        "s3",
        endpoint_url=config.endpoint_url,
        region_name="auto",
        aws_access_key_id=config.access_key_id,
        aws_secret_access_key=config.secret_access_key,
    )


def test_r2_connection(config: R2Config):
    client = create_client(config)
    client.head_bucket(Bucket=config.bucket_name)
    return {
        "ok": True,
        "bucket_name": config.bucket_name,
        "public_base_url": config.public_base_url.rstrip("/"),
    }


def ensure_lifecycle(config: R2Config, days: int = 3):
    if not 1 <= days <= 7:
        raise ValueError("R2 lifecycle 天數必須介於 1 到 7 天")
    create_client(config).put_bucket_lifecycle_configuration(
        Bucket=config.bucket_name,
        LifecycleConfiguration={
            "Rules": [{
                "ID": "creator-tools-temporary-reels",
                "Status": "Enabled",
                "Filter": {"Prefix": "instagram-reels/"},
                "Expiration": {"Days": days},
            }]
        },
    )


def upload_public_file(config: R2Config, local_path: Path, object_key: str, content_type: str):
    client = create_client(config)
    client.upload_file(
        str(local_path),
        config.bucket_name,
        object_key,
        ExtraArgs={"ContentType": content_type},
    )
    url = f"{validate_public_base_url(config.public_base_url)}/{quote(object_key, safe='/')}"
    with httpx.Client(timeout=30, follow_redirects=True) as http:
        with http.stream("GET", url, headers={"Range": "bytes=0-0"}) as response:
            if response.status_code not in (200, 206):
                raise RuntimeError(f"R2 公開網址驗證失敗：HTTP {response.status_code}")
            next(response.iter_bytes(chunk_size=1), b"")
    return url
