from __future__ import annotations

from sqlalchemy.orm import Session

from core_data.db.models import CrawlJob, Source
from core_data.ingest.adapters import get_adapter
from core_data.ingest.canonical import build_content_item, build_content_item_from_entry
from core_data.ingest.extractor import extract
from core_data.ingest.fetcher import fetch_page
from core_data.ingest.media import media_refs_from_entry
from core_data.ingest.raw_store import RawStore
from core_data.sources.health import mark_attempt, mark_failure, mark_success
from core_data.storage.object_store import ObjectStore


def crawl_source(
    session: Session,
    object_store: ObjectStore,
    source: Source,
    *,
    fetch_media: bool = False,
) -> dict[str, int]:
    adapter = get_adapter(source.type)
    job = CrawlJob(source_id=source.id, kind=adapter.type, status="running", stats={})
    session.add(job)
    session.flush()
    mark_attempt(session, source.id)
    stats = {"entries": 0, "raw": 0, "content": 0, "failed": 0, "media": 0, "trend": 0}
    raw_store = RawStore(session, object_store)
    try:
        for entry in adapter.fetch_entries(source):
            stats["entries"] += 1
            media_refs = []
            if fetch_media:
                media_refs = media_refs_from_entry(
                    object_store,
                    source_id=source.id,
                    raw_entry=entry.raw,
                )
                stats["media"] += len(media_refs)
            raw_entry = raw_store.append(
                source_id=source.id,
                crawl_job_id=job.id,
                url=entry.url,
                fetch_method=adapter.type,
                raw_entry=entry.raw,
                media=media_refs,
            )
            stats["raw"] += 1
            if not adapter.needs_page_fetch:
                item = build_content_item_from_entry(session, raw_entry, entry)
                if item.raw_document_id == raw_entry.id:
                    stats["content"] += 1
                    stats["trend"] += 1
                continue
            try:
                fetch = fetch_page(entry.url, render=bool(source.crawl_config.get("render")))
                raw_html = raw_store.append(
                    source_id=source.id,
                    crawl_job_id=job.id,
                    url=entry.url,
                    fetch_method=fetch.method,
                    http_status=fetch.status,
                    http_headers=fetch.headers,
                    raw_entry=entry.raw,
                    raw_html=fetch.html,
                    media=media_refs,
                    extra={"rss_raw_document_id": raw_entry.id},
                )
                stats["raw"] += 1
                extracted = extract(fetch.html, entry.url)
                if entry.title and not extracted.title:
                    extracted = extracted.__class__(
                        title=entry.title,
                        author=extracted.author or entry.extra.get("author"),
                        text=extracted.text,
                        published_at=extracted.published_at,
                        confidence=extracted.confidence,
                        lang=extracted.lang,
                    )
                item = build_content_item(session, object_store, raw_html, extracted)
                if item.raw_document_id == raw_html.id:
                    stats["content"] += 1
            except Exception as exc:  # keep failures as raw evidence
                stats["failed"] += 1
                raw_store.append(
                    source_id=source.id,
                    crawl_job_id=job.id,
                    url=entry.url,
                    fetch_method="error",
                    raw_entry=entry.raw,
                    extra={"error": str(exc), "rss_raw_document_id": raw_entry.id},
                )
                stats["raw"] += 1
        job.status = "succeeded"
        mark_success(session, source.id, empty=stats["entries"] == 0)
    except Exception as exc:
        job.status = "failed"
        job.error = str(exc)
        mark_failure(session, source.id, str(exc))
        raise
    finally:
        job.stats = stats
        session.flush()
    return stats
