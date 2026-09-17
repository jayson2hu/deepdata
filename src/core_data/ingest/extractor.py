from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser

import trafilatura

TAIL_MARKERS = (
    "\nTags:\nWritten by\nRelated posts",
    "\nRelated posts\n",
)


def _trim_site_tail(text: str) -> str:
    lowered = text.casefold()
    positions = [lowered.find(marker.casefold()) for marker in TAIL_MARKERS]
    valid_positions = [position for position in positions if position >= 0]
    return text[: min(valid_positions)].rstrip() if valid_positions else text



@dataclass(frozen=True)
class Extracted:
    title: str | None
    author: str | None
    text: str
    published_at: datetime | None
    confidence: float
    lang: str | None = None


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip = False
        self._title = False
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag in {"script", "style", "nav", "footer", "header"}:
            self._skip = True
        if tag == "title":
            self._title = True

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "nav", "footer", "header"}:
            self._skip = False
        if tag == "title":
            self._title = False

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if not text:
            return
        if self._title:
            self.title_parts.append(text)
        elif not self._skip:
            self.text_parts.append(text)


def extract(html: bytes, url: str) -> Extracted:
    parser = _TextExtractor()
    parser.feed(html.decode("utf-8", errors="replace"))
    title = " ".join(parser.title_parts).strip() or None
    document = trafilatura.extract(
        html,
        url=url,
        include_comments=False,
        include_tables=False,
        favor_precision=True,
    )
    document = _trim_site_tail(document) if document else None
    fallback = " ".join(parser.text_parts)
    text = re.sub(r"\s+", " ", document if document else fallback).strip()
    confidence = min(1.0, len(text) / 500.0) if text else 0.0
    lang = "zh" if re.search(r"[\u4e00-\u9fff]", text) else "en"
    return Extracted(
        title=title,
        author=None,
        text=text,
        published_at=None,
        confidence=confidence,
        lang=lang,
    )
