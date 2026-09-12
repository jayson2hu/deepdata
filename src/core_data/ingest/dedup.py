from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from core_data.db.models import ContentItem

DROP_QUERY_PREFIXES = ("utm_",)
DROP_QUERY_NAMES = {"fbclid", "gclid", "mc_cid", "mc_eid"}
TOKEN_RE = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)


class DedupResult(StrEnum):
    NEW = "NEW"
    SAME_URL = "SAME_URL"
    DUPLICATE = "DUPLICATE"
    VARIANT = "VARIANT"


@dataclass(frozen=True)
class DedupDecision:
    result: DedupResult
    content_id: int | None
    reason: str


def normalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    scheme = (parts.scheme or "https").lower()
    netloc = parts.netloc.lower()
    path = parts.path or "/"
    if path != "/" and path.endswith("/"):
        path = path[:-1]
    query_items = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        lower_key = key.lower()
        if lower_key in DROP_QUERY_NAMES or lower_key.startswith(DROP_QUERY_PREFIXES):
            continue
        query_items.append((key, value))
    query = urlencode(sorted(query_items))
    return urlunsplit((scheme, netloc, path, query, ""))


def url_hash(url: str) -> str:
    return hashlib.sha1(normalize_url(url).encode("utf-8")).hexdigest()


def content_hash(text: str) -> str:
    normalized = " ".join(text.split()).strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def simhash(text: str) -> int:
    weights = [0] * 64
    tokens = TOKEN_RE.findall(text.lower())
    for token in tokens:
        digest = int(hashlib.blake2b(token.encode("utf-8"), digest_size=8).hexdigest(), 16)
        for bit in range(64):
            weights[bit] += 1 if digest & (1 << bit) else -1
    value = 0
    for bit, weight in enumerate(weights):
        if weight >= 0:
            value |= 1 << bit
    return value & ((1 << 63) - 1)


def hamming_distance(left: int, right: int) -> int:
    return (left ^ right).bit_count()


def classify(session: Session, url: str, text: str, simhash_threshold: int = 3) -> DedupDecision:
    u_hash = url_hash(url)
    c_hash = content_hash(text)
    s_hash = simhash(text)

    same_url = session.scalar(select(ContentItem).where(ContentItem.url_hash == u_hash))
    if same_url is not None:
        return DedupDecision(DedupResult.SAME_URL, same_url.id, "url_hash")

    duplicate = session.scalar(select(ContentItem).where(ContentItem.content_hash == c_hash))
    if duplicate is not None:
        return DedupDecision(DedupResult.DUPLICATE, duplicate.id, "content_hash")

    candidates = session.scalars(select(ContentItem).where(ContentItem.simhash.is_not(None))).all()
    for candidate in candidates:
        if (
            candidate.simhash is not None
            and hamming_distance(candidate.simhash, s_hash) <= simhash_threshold
        ):
            return DedupDecision(DedupResult.VARIANT, candidate.id, "simhash")

    return DedupDecision(DedupResult.NEW, None, "no_match")
