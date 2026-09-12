from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "sqlite:///./.runtime/codepick_l0.db"
    redis_url: str = "redis://localhost:6379/0"
    object_store_backend: str = "file"
    object_store_path: str = ".runtime/object_store"
    s3_endpoint: str = "http://localhost:9000"
    s3_access_key: str = "minio"
    s3_secret_key: str = "minio123"
    s3_bucket: str = "codepick-raw"
    default_crawl_interval_min: int = 60
    fetch_timeout_sec: int = 30
    playwright_pool_size: int = 2
    source_max_concurrency: int = 2
    extract_confidence_min: float = 0.6
    respect_robots: bool = True
    retry_max_attempts: int = 3

    @property
    def object_store_root(self) -> Path:
        return Path(self.object_store_path)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
