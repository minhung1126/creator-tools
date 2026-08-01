from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

import boto3
import httpx


@dataclass
class R2Config:
    account_id: str
    access_key_id: str
    secret_access_key: str
    bucket_name: str
    public_base_url: str

    @property
    def endpoint_url(self):
        return f"https://{self.account_id}.r2.cloudflarestorage.com"


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


def upload_public_file(config: R2Config, local_path: Path, object_key: str, content_type: str):
    client = create_client(config)
    client.upload_file(
        str(local_path),
        config.bucket_name,
        object_key,
        ExtraArgs={"ContentType": content_type},
    )
    url = f"{config.public_base_url.rstrip('/')}/{quote(object_key, safe='/')}"
    with httpx.Client(timeout=30, follow_redirects=True) as http:
        with http.stream("GET", url, headers={"Range": "bytes=0-0"}) as response:
            if response.status_code not in (200, 206):
                raise RuntimeError(f"R2 公開網址驗證失敗：HTTP {response.status_code}")
            next(response.iter_bytes(chunk_size=1), b"")
    return url
