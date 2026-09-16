from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname

import httpx


@dataclass(frozen=True)
class FetchResult:
    html: bytes
    status: int
    headers: dict[str, str]
    method: str


def fetch_page(url: str, render: bool = False, timeout_sec: int = 30) -> FetchResult:
    if render:
        return _fetch_with_playwright(url, timeout_sec)
    parsed = urlparse(url)
    if parsed.scheme == "file":
        data = _file_url_to_path(url).read_bytes()
        return FetchResult(data, 200, {}, "file")
    response = httpx.get(url, timeout=timeout_sec, follow_redirects=True)
    return FetchResult(
        bytes(response.content),
        response.status_code,
        dict(response.headers),
        "httpx",
    )


def _fetch_with_playwright(url: str, timeout_sec: int) -> FetchResult:
    try:
        from playwright.sync_api import sync_playwright
    except ModuleNotFoundError as exc:  # pragma: no cover - optional runtime path
        raise RuntimeError("Playwright is required for rendered fetches") from exc

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, wait_until="networkidle", timeout=timeout_sec * 1000)
        html = page.content().encode("utf-8")
        browser.close()
    return FetchResult(html, 200, {}, "playwright")


def _file_url_to_path(url: str) -> Path:
    parsed = urlparse(url)
    if parsed.netloc and parsed.netloc.endswith(":"):
        return Path(url2pathname(f"{parsed.netloc}{parsed.path}"))
    if parsed.netloc and parsed.netloc != "localhost":
        if os.name == "nt":
            return Path(url2pathname(f"//{parsed.netloc}{parsed.path}"))
        return Path(url2pathname(f"/{parsed.netloc}{parsed.path}"))
    return Path(url2pathname(parsed.path))
