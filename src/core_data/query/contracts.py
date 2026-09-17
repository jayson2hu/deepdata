from __future__ import annotations

from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class SourceRef(BaseModel):
    id: int | None
    name: str | None = None
    kind: str | None = None
    home_url: str | None = None
    feed_url: str | None = None
    etiquette: dict[str, object] = Field(default_factory=dict)


class ContentRef(BaseModel):
    id: int
    current_version: int
    content_hash: str | None
    canonical_url: str
    title: str | None
    lang: str | None
    source: SourceRef
    published_at: datetime | None
    status: str
    fetched_at: datetime


class ContentOut(ContentRef):
    clean_text: str = Field(default="")


class Page(BaseModel, Generic[T]):  # noqa: UP046 - pydantic v2 generic model compatibility
    items: list[T]
    next_cursor: str | None = None
