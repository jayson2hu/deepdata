from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from core_data.db.models import ContentItem, ContentVersion, RawDocument
from core_data.events.outbox import emit
from core_data.ingest.adapters.base import Entry
from core_data.ingest.dedup import (
    DedupResult,
    classify,
    content_hash,
    normalize_url,
    simhash,
    url_hash,
)
from core_data.ingest.extractor import Extracted
from core_data.storage.object_store import ObjectStore, clean_text_key, sha256_bytes

WAIT_FILTER = "WAIT_FILTER"
TREND = "TREND"


def build_content_item(
    session: Session,
    object_store: ObjectStore,
    raw: RawDocument,
    extracted: Extracted,
) -> ContentItem:
    if not extracted.text.strip():
        raise ValueError("cannot build content item from empty text")
    if raw.source_id is None:
        raise ValueError("raw document must have source_id")

    digest = sha256_bytes(extracted.text.encode("utf-8"))
    clean_ref = object_store.put_bytes(
        clean_text_key(raw.source_id, digest), extracted.text.encode("utf-8"), "text/plain"
    )
    c_hash = content_hash(extracted.text)
    decision = classify(session, raw.url, extracted.text)

    if decision.result == DedupResult.SAME_URL and decision.content_id is not None:
        item = session.get(ContentItem, decision.content_id)
        if item is None:
            raise LookupError(decision.content_id)
        if item.content_hash != c_hash:
            item.current_version += 1
            item.content_hash = c_hash
            item.simhash = simhash(extracted.text)
            item.title = extracted.title or item.title
            item.clean_text_ref = clean_ref
            item.raw_document_id = raw.id
            item.updated_at = datetime.now(UTC)
            session.add(
                ContentVersion(
                    content_id=item.id,
                    version=item.current_version,
                    raw_document_id=raw.id,
                    clean_text_ref=clean_ref,
                    content_hash=c_hash,
                    diff_summary="content_hash changed",
                )
            )
            session.flush()
        return item

    if (
        decision.result in {DedupResult.DUPLICATE, DedupResult.VARIANT}
        and decision.content_id is not None
    ):
        representative = session.get(ContentItem, decision.content_id)
        if representative is None:
            raise LookupError(decision.content_id)
        representative.meta = {
            **(representative.meta or {}),
            "variants": [
                *((representative.meta or {}).get("variants", [])),
                {"raw_document_id": raw.id, "url": raw.url, "reason": decision.reason},
            ],
        }
        return representative

    item = ContentItem(
        canonical_url=normalize_url(raw.url),
        url_hash=url_hash(raw.url),
        content_hash=c_hash,
        simhash=simhash(extracted.text),
        title=extracted.title,
        author=extracted.author,
        clean_text_ref=clean_ref,
        lang=extracted.lang,
        source_id=raw.source_id,
        published_at=extracted.published_at,
        raw_document_id=raw.id,
        status=WAIT_FILTER,
        meta={"extract_confidence": extracted.confidence},
    )
    session.add(item)
    session.flush()
    session.add(
        ContentVersion(
            content_id=item.id,
            version=1,
            raw_document_id=raw.id,
            clean_text_ref=clean_ref,
            content_hash=c_hash,
            diff_summary="initial version",
        )
    )
    emit(
        session,
        "content.ingested",
        {"content_id": item.id, "lang": item.lang},
        f"content.ingested:{item.id}",
    )
    session.flush()
    return item


def build_content_item_from_entry(
    session: Session,
    raw: RawDocument,
    entry: Entry,
    *,
    status: str = TREND,
) -> ContentItem:
    if raw.source_id is None:
        raise ValueError("raw document must have source_id")
    text = " ".join(part for part in (entry.title, entry.extra.get("description")) if part).strip()
    if not text:
        text = entry.url
    c_hash = content_hash(text)
    decision = classify(session, entry.url, text)

    if decision.result == DedupResult.SAME_URL and decision.content_id is not None:
        item = session.get(ContentItem, decision.content_id)
        if item is None:
            raise LookupError(decision.content_id)
        item.meta = {**(item.meta or {}), **entry.extra}
        item.raw_document_id = raw.id
        item.updated_at = datetime.now(UTC)
        session.flush()
        return item

    if (
        decision.result in {DedupResult.DUPLICATE, DedupResult.VARIANT}
        and decision.content_id is not None
    ):
        representative = session.get(ContentItem, decision.content_id)
        if representative is None:
            raise LookupError(decision.content_id)
        representative.meta = {
            **(representative.meta or {}),
            "variants": [
                *((representative.meta or {}).get("variants", [])),
                {"raw_document_id": raw.id, "url": entry.url, "reason": decision.reason},
            ],
        }
        session.flush()
        return representative

    item = ContentItem(
        canonical_url=normalize_url(entry.url),
        url_hash=url_hash(entry.url),
        content_hash=c_hash,
        simhash=simhash(text),
        title=entry.title,
        lang=None,
        source_id=raw.source_id,
        published_at=entry.published_at,
        raw_document_id=raw.id,
        status=status,
        meta=entry.extra,
    )
    session.add(item)
    session.flush()
    emit(
        session,
        "content.ingested",
        {"content_id": item.id, "lang": item.lang},
        f"content.ingested:{item.id}",
    )
    session.flush()
    return item


def rebuild_canonical(session: Session, object_store: ObjectStore, content_id: int) -> ContentItem:
    old = session.get(ContentItem, content_id)
    if old is None or old.raw_document_id is None:
        raise LookupError(content_id)
    raw = session.get(RawDocument, old.raw_document_id)
    if raw is None or raw.raw_html_ref is None:
        raise LookupError(f"raw for content {content_id}")
    from core_data.ingest.extractor import extract

    extracted = extract(object_store.get_bytes(raw.raw_html_ref), raw.url)
    old.content_hash = content_hash(extracted.text)
    old.simhash = simhash(extracted.text)
    old.title = extracted.title
    old.lang = extracted.lang
    old.clean_text_ref = object_store.put_bytes(
        clean_text_key(raw.source_id or 0, sha256_bytes(extracted.text.encode("utf-8"))),
        extracted.text.encode("utf-8"),
        "text/plain",
    )
    session.flush()
    return old


def lineage(session: Session, content_id: int) -> dict[str, object]:
    item = session.get(ContentItem, content_id)
    if item is None:
        raise LookupError(content_id)
    raw = session.get(RawDocument, item.raw_document_id) if item.raw_document_id else None
    return {
        "content_id": item.id,
        "raw_document_id": raw.id if raw else None,
        "crawl_job_id": raw.crawl_job_id if raw else None,
        "source_id": item.source_id,
    }


def list_reprocess_targets(session: Session, source_id: int | None = None) -> list[ContentItem]:
    stmt = select(ContentItem)
    if source_id is not None:
        stmt = stmt.where(ContentItem.source_id == source_id)
    return list(session.scalars(stmt.order_by(ContentItem.id)).all())
