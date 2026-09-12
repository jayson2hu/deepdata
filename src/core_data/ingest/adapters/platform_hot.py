from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

import httpx

from core_data.db.models import Source
from core_data.ingest.adapters.base import Entry


def _pick_text(item: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = item.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def parse_hot_json(payload: dict[str, Any], *, platform: str) -> list[Entry]:
    raw_items = payload.get("data", payload)
    if isinstance(raw_items, dict):
        raw_items = raw_items.get("list") or raw_items.get("cards") or raw_items.get("items") or []
    if not isinstance(raw_items, list):
        raise ValueError(f"{platform} hot payload must contain a list")
    entries: list[Entry] = []
    for idx, raw in enumerate(raw_items, start=1):
        if not isinstance(raw, dict):
            continue
        title = _pick_text(raw, "title", "word", "query", "name", "display_query")
        url = _pick_text(raw, "url", "link", "target_url", "mobileUrl") or (
            f"https://example.invalid/{platform}/{idx}"
        )
        heat = _pick_text(raw, "heat", "hot", "hotValue", "score", "metrics")
        rank = int(raw.get("rank") or raw.get("index") or idx)
        extra = {
            "rank": rank,
            "heat": heat,
            "platform": platform,
            "tags": raw.get("tags") or [],
        }
        entries.append(
            Entry(
                url=url,
                title=title,
                raw=raw,
                extra={key: value for key, value in extra.items() if value not in (None, "")},
            )
        )
    return entries


@dataclass(frozen=True)
class JsonHotAdapter:
    type: str
    label: str
    default_url: str
    needs_page_fetch: bool = False
    config_schema: dict[str, Any] = field(
        default_factory=lambda: {
            "api_url": {"type": "url", "required": False},
            "top_n": {"type": "int", "default": 30},
            "cookie": {"type": "string", "required": False},
            "interval_min": {"type": "int", "default": 60},
        }
    )

    def fetch_entries(self, source: Source) -> Iterable[Entry]:
        cfg = source.crawl_config or {}
        api_url = str(cfg.get("api_url") or self.default_url)
        headers = {"User-Agent": "CodePick-L0/0.1"}
        cookie = str(cfg.get("cookie") or "").strip()
        if cookie:
            headers["Cookie"] = cookie
        response = httpx.get(api_url, timeout=30, follow_redirects=True, headers=headers)
        response.raise_for_status()
        limit = max(1, min(int(cfg.get("top_n") or 30), 100))
        return parse_hot_json(response.json(), platform=self.type)[:limit]


@dataclass(frozen=True)
class NotImplementedHotAdapter:
    type: str
    label: str
    needs_page_fetch: bool = False
    config_schema: dict[str, Any] = field(
        default_factory=lambda: {
            "api_url": {"type": "url", "required": True},
            "cookie": {"type": "string", "required": False},
            "interval_min": {"type": "int", "default": 60},
        }
    )

    def fetch_entries(self, source: Source) -> Iterable[Entry]:
        raise NotImplementedError(f"{self.type} requires an authorized API/cookie integration")


def built_in_platform_adapters() -> list[JsonHotAdapter | NotImplementedHotAdapter]:
    return [
        JsonHotAdapter("baidu_hot", "Baidu Hot", "https://top.baidu.com/api/board?platform=wise"),
        JsonHotAdapter("zhihu_hot", "Zhihu Hot", "https://www.zhihu.com/api/v3/feed/topstory/hot-lists/total"),
        JsonHotAdapter("weibo_hot", "Weibo Hot", "https://weibo.com/ajax/side/hotSearch"),
        NotImplementedHotAdapter("douyin_hot", "Douyin Hot"),
        NotImplementedHotAdapter("xiaohongshu", "Xiaohongshu"),
    ]
