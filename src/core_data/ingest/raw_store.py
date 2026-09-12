from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from core_data.db.models import RawDocument
from core_data.storage.object_store import ObjectStore, raw_html_key, sha256_bytes


class RawStore:
    """Append-only repository for immutable raw documents.

    This class intentionally exposes no update/delete methods.
    """

    def __init__(self, session: Session, object_store: ObjectStore) -> None:
        self.session = session
        self.object_store = object_store

    def append(
        self,
        *,
        source_id: int,
        crawl_job_id: int | None,
        url: str,
        fetch_method: str,
        http_status: int | None = None,
        http_headers: dict[str, Any] | None = None,
        raw_entry: dict[str, Any] | None = None,
        raw_html: bytes | None = None,
        media: list[dict[str, Any]] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> RawDocument:
        raw_html_ref: str | None = None
        raw_html_sha256: str | None = None
        if raw_html is not None:
            raw_html_sha256 = sha256_bytes(raw_html)
            key = raw_html_key(source_id, raw_html_sha256)
            raw_html_ref = self.object_store.put_bytes(key, raw_html, "text/html; charset=utf-8")

        raw = RawDocument(
            source_id=source_id,
            crawl_job_id=crawl_job_id,
            url=url,
            fetch_method=fetch_method,
            http_status=http_status,
            http_headers=http_headers,
            raw_entry=raw_entry,
            raw_html_ref=raw_html_ref,
            raw_html_sha256=raw_html_sha256,
            media_refs=media or [],
            extra=extra or {},
        )
        self.session.add(raw)
        self.session.flush()
        return raw
