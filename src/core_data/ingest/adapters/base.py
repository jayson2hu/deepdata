from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from core_data.db.models import Source


@dataclass(frozen=True)
class Entry:
    url: str
    title: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)
    published_at: datetime | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class SourceAdapter(Protocol):
    @property
    def type(self) -> str:
        ...

    @property
    def label(self) -> str:
        ...

    @property
    def needs_page_fetch(self) -> bool:
        ...

    @property
    def config_schema(self) -> dict[str, Any]:
        ...

    def fetch_entries(self, source: Source) -> Iterable[Entry]:
        ...
