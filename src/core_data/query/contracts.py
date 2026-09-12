from __future__ import annotations

from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class SourceRef(BaseModel):
    id: int | None
    name: str | None = None


class ContentRef(BaseModel):
    id: int
    canonical_url: str
    title: str | None
    lang: str | None
    source: SourceRef
    published_at: datetime | None
    status: str


class ContentOut(ContentRef):
    clean_text: str = Field(default="")


class Page(BaseModel, Generic[T]):  # noqa: UP046 - pydantic v2 generic model compatibility
    items: list[T]
    next_cursor: str | None = None
