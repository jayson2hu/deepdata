from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname

import httpx

from core_data.storage.object_store import ObjectStore, media_key, sha256_bytes


@dataclass(frozen=True)
class MediaAsset:
    url: str
    ref: str
    sha256: str
    content_type: str
    size: int


def fetch_media_bytes(url: str, timeout_sec: int = 30) -> tuple[bytes, str]:
    parsed = urlparse(url)
    if parsed.scheme == "file":
        path = _file_url_to_path(url)
        data = path.read_bytes()
        return data, _guess_content_type(parsed.path)
    response = httpx.get(url, timeout=timeout_sec, follow_redirects=True)
    response.raise_for_status()
    return bytes(response.content), response.headers.get("content-type", "application/octet-stream")


def store_media(
    object_store: ObjectStore,
    *,
    source_id: int,
    url: str,
    data: bytes,
    content_type: str,
) -> MediaAsset:
    digest = sha256_bytes(data)
    extension = _extension_from_content_type(content_type) or Path(urlparse(url).path).suffix.strip(
        "."
    )
    key = media_key(source_id, digest, extension or "bin")
    ref = object_store.put_bytes(key, data, content_type)
    return MediaAsset(url=url, ref=ref, sha256=digest, content_type=content_type, size=len(data))


def fetch_and_store_media(
    object_store: ObjectStore,
    *,
    source_id: int,
    url: str,
    timeout_sec: int = 30,
) -> MediaAsset:
    data, content_type = fetch_media_bytes(url, timeout_sec)
    return store_media(
        object_store,
        source_id=source_id,
        url=url,
        data=data,
        content_type=content_type,
    )


def media_refs_from_entry(
    object_store: ObjectStore,
    *,
    source_id: int,
    raw_entry: dict[str, object],
    timeout_sec: int = 30,
) -> list[dict[str, object]]:
    urls: list[str] = []
    enclosures = _list_value(raw_entry.get("enclosures"))
    media_items = _list_value(raw_entry.get("media_content"))
    for enclosure in enclosures:
        if isinstance(enclosure, dict) and isinstance(enclosure.get("href"), str):
            urls.append(enclosure["href"])
    for media in media_items:
        if isinstance(media, dict) and isinstance(media.get("url"), str):
            urls.append(media["url"])

    refs: list[dict[str, object]] = []
    for url in dict.fromkeys(urls):
        asset = fetch_and_store_media(
            object_store, source_id=source_id, url=url, timeout_sec=timeout_sec
        )
        refs.append(asset.__dict__)
    return refs


def _extension_from_content_type(content_type: str) -> str | None:
    content_type = content_type.split(";")[0].strip().lower()
    return {
        "image/jpeg": "jpg",
        "image/png": "png",
        "image/webp": "webp",
        "image/gif": "gif",
        "audio/mpeg": "mp3",
        "audio/mp4": "m4a",
        "audio/ogg": "ogg",
    }.get(content_type)


def _guess_content_type(path: str) -> str:
    suffix = Path(path).suffix.lower()
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
        ".mp3": "audio/mpeg",
        ".m4a": "audio/mp4",
        ".ogg": "audio/ogg",
    }.get(suffix, "application/octet-stream")


def _list_value(value: object) -> Iterable[object]:
    return value if isinstance(value, list) else []


def _file_url_to_path(url: str) -> Path:
    parsed = urlparse(url)
    if parsed.netloc and parsed.netloc.endswith(":"):
        return Path(url2pathname(f"{parsed.netloc}{parsed.path}"))
    return Path(url2pathname(parsed.path))
