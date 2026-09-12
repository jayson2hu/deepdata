from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Protocol


class ObjectStore(Protocol):
    def put_bytes(self, key: str, data: bytes, content_type: str) -> str: ...

    def get_bytes(self, key: str) -> bytes: ...

    def exists(self, key: str) -> bool: ...


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def raw_html_key(source_id: int, digest: str) -> str:
    return f"raw/{source_id}/{digest}.html"


def clean_text_key(source_id: int, digest: str) -> str:
    return f"clean/{source_id}/{digest}.txt"


def media_key(source_id: int, digest: str, extension: str = "bin") -> str:
    safe_ext = extension.strip(".").lower() or "bin"
    return f"media/{source_id}/{digest}.{safe_ext}"


class FileObjectStore:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def put_bytes(self, key: str, data: bytes, content_type: str) -> str:
        del content_type
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(data)
        return key

    def get_bytes(self, key: str) -> bytes:
        return (self.root / key).read_bytes()

    def exists(self, key: str) -> bool:
        return (self.root / key).exists()


class S3ObjectStore:
    def __init__(
        self,
        *,
        bucket: str,
        endpoint_url: str | None,
        access_key: str,
        secret_key: str,
    ) -> None:
        try:
            import boto3
        except ModuleNotFoundError as exc:  # pragma: no cover - optional dependency path
            raise RuntimeError("boto3 is required for S3 object storage") from exc
        self.bucket = bucket
        self.client: Any = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )

    def put_bytes(self, key: str, data: bytes, content_type: str) -> str:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)
        return key

    def get_bytes(self, key: str) -> bytes:
        response = self.client.get_object(Bucket=self.bucket, Key=key)
        return bytes(response["Body"].read())

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
        except Exception:  # boto3 raises service-specific ClientError
            return False
        return True
