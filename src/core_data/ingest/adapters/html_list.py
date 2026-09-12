from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin

import httpx
from lxml import html

from core_data.db.models import Source
from core_data.ingest.adapters.base import Entry
from core_data.ingest.fetcher import fetch_page


@dataclass(frozen=True)
class HtmlListConfig:
    list_url: str
    selector: str
    selector_type: str = "css"
    link_attr: str = "href"
    base_url: str | None = None
    limit: int = 30


def _config(raw: dict[str, Any]) -> HtmlListConfig:
    list_url = str(raw.get("list_url") or "").strip()
    selector = str(raw.get("selector") or raw.get("item_selector") or "").strip()
    if not list_url:
        raise ValueError("html_list requires crawl_config.list_url")
    if not selector:
        raise ValueError("html_list requires crawl_config.selector")
    selector_type = str(raw.get("selector_type") or "css").strip().lower()
    if selector_type not in {"css", "xpath"}:
        raise ValueError("html_list selector_type must be css or xpath")
    limit = int(raw.get("limit") or 30)
    return HtmlListConfig(
        list_url=list_url,
        selector=selector,
        selector_type=selector_type,
        link_attr=str(raw.get("link_attr") or "href"),
        base_url=str(raw.get("base_url") or list_url),
        limit=max(1, min(limit, 200)),
    )


def parse_list(payload: bytes, config: HtmlListConfig) -> list[Entry]:
    doc = html.fromstring(payload)
    if config.selector_type == "xpath":
        nodes = doc.xpath(config.selector)
    else:
        nodes = doc.cssselect(config.selector)
    entries: list[Entry] = []
    for rank, node in enumerate(nodes[: config.limit], start=1):
        href: str | None
        title: str | None
        if isinstance(node, str):
            title = node.strip()
            href = title
        else:
            title = " ".join(node.text_content().split()) or None
            href = node.get(config.link_attr) or node.get("href")
        if not href:
            continue
        url = urljoin(config.base_url or config.list_url, str(href))
        entries.append(
            Entry(
                url=url,
                title=title,
                raw={"url": url, "title": title, "rank": rank},
                extra={"rank": rank, "platform": "html_list"},
            )
        )
    return entries


@dataclass(frozen=True)
class HtmlListAdapter:
    type: str = "html_list"
    label: str = "HTML list"
    needs_page_fetch: bool = True
    config_schema: dict[str, Any] = field(
        default_factory=lambda: {
            "list_url": {"type": "url", "required": True},
            "selector": {"type": "string", "required": True},
            "selector_type": {"type": "enum", "options": ["css", "xpath"], "default": "css"},
            "link_attr": {"type": "string", "default": "href"},
            "base_url": {"type": "url", "required": False},
            "limit": {"type": "int", "default": 30},
            "interval_min": {"type": "int", "default": 60},
            "render": {"type": "bool", "default": False},
        }
    )

    def fetch_entries(self, source: Source) -> Iterable[Entry]:
        cfg = _config(source.crawl_config or {})
        if bool((source.crawl_config or {}).get("render")):
            payload = fetch_page(cfg.list_url, render=True).html
        else:
            response = httpx.get(
                cfg.list_url,
                timeout=30,
                follow_redirects=True,
                headers={"User-Agent": "CodePick-L0/0.1"},
            )
            response.raise_for_status()
            payload = bytes(response.content)
        return parse_list(payload, cfg)
