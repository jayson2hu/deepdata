from __future__ import annotations

from core_data.config import Settings
from core_data.storage.object_store import FileObjectStore, ObjectStore, S3ObjectStore


def build_object_store(settings: Settings) -> ObjectStore:
    if settings.object_store_backend == "s3":
        return S3ObjectStore(
            bucket=settings.s3_bucket,
            endpoint_url=settings.s3_endpoint,
            access_key=settings.s3_access_key,
            secret_key=settings.s3_secret_key,
        )
    return FileObjectStore(settings.object_store_root)
