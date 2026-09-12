from __future__ import annotations

from typing import Any

from core_data.ingest.adapters.base import SourceAdapter
from core_data.ingest.adapters.github_trending import GithubTrendingAdapter
from core_data.ingest.adapters.html_list import HtmlListAdapter
from core_data.ingest.adapters.platform_hot import built_in_platform_adapters
from core_data.ingest.adapters.rss import RssAdapter

_REGISTRY: dict[str, SourceAdapter] = {}


def register(adapter: SourceAdapter) -> None:
    _REGISTRY[adapter.type] = adapter


def get_adapter(type_: str | None) -> SourceAdapter:
    key = type_ or "rss"
    if key == "article":
        key = "rss"
    try:
        return _REGISTRY[key]
    except KeyError as exc:
        raise ValueError(f"unknown source type: {key}") from exc


def list_types() -> list[dict[str, Any]]:
    return [
        {
            "type": adapter.type,
            "label": adapter.label,
            "needs_page_fetch": adapter.needs_page_fetch,
            "config_schema": adapter.config_schema,
        }
        for adapter in _REGISTRY.values()
    ]


register(RssAdapter())
register(HtmlListAdapter())
register(GithubTrendingAdapter())
for _adapter in built_in_platform_adapters():
    register(_adapter)
