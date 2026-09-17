from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from core_data.db.models import Base, ContentItem, CrawlJob, OutboxEvent, Source, SourceHealth
from core_data.scripts import dashboard


@pytest.fixture
def dashboard_database(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'dashboard.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(dashboard, "engine", engine)
    monkeypatch.setattr(dashboard, "SessionLocal", maker)
    monkeypatch.setattr(
        dashboard, "_scheduler_status", lambda: {"running": False, "last_tick": None}
    )
    yield maker
    engine.dispose()


@pytest.fixture
def dashboard_server(dashboard_database):
    servers = []

    def start(*, read_only=True):
        server = dashboard.DashboardServer(("127.0.0.1", 0), read_only=read_only)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        servers.append((server, thread))
        return f"http://127.0.0.1:{server.server_port}"

    yield start
    for server, thread in servers:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def seed_dashboard(maker):
    now = datetime.now(UTC)
    with maker.begin() as session:
        source = Source(
            name="开发工具来源 " + "LongSourceName" * 8,
            feed_url="https://example.test/feed.xml",
            type="rss",
            enabled=True,
            crawl_config={},
        )
        session.add(source)
        session.flush()
        session.add(
            SourceHealth(
                source_id=source.id,
                status="failed",
                fail_count=2,
                last_attempt_at=now,
                note="HTTP 429: retry later",
            )
        )
        session.add(
            ContentItem(
                canonical_url="https://example.test/article",
                url_hash="a" * 40,
                title="真实入库的工程更新",
                source_id=source.id,
                current_version=3,
                lang="en",
                status="WAIT_FILTER",
            )
        )
        session.add(
            ContentItem(
                canonical_url="javascript:alert('not allowed')",
                url_hash="b" * 40,
                title="不安全来源链接",
                source_id=source.id,
                current_version=1,
                status="WAIT_FILTER",
            )
        )
        session.add(
            CrawlJob(
                source_id=source.id,
                kind="rss",
                status="failed",
                error="HTTP 429: retry later",
                stats={},
                started_at=now,
            )
        )
        session.add(
            OutboxEvent(
                topic="content.ingested",
                payload={"content_id": 1, "content_version": 3},
                idempotency_key="dashboard-event-1",
            )
        )
        session.add(
            OutboxEvent(
                topic="content.ingested",
                payload={"content_id": 2, "content_version": 1},
                idempotency_key="dashboard-event-2",
                published_at=now,
            )
        )


def test_empty_event_denominator_is_unknown_not_full_delivery(dashboard_database):
    result = dashboard._status()
    assert result["counts"]["outbox_events"] == 0
    assert result["counts"]["delivery_rate"] is None
    assert result["source_health"] == {}
    assert result["failed_jobs"] == []
    assert result["pending_events"] == []


def test_operator_snapshot_exposes_versions_health_failures_and_pending(dashboard_database):
    seed_dashboard(dashboard_database)
    result = dashboard._status()
    assert result["counts"]["delivery_rate"] == 50.0
    assert result["counts"]["failed_jobs"] == 1
    assert result["source_health"] == {"failed": 1}
    assert result["sources"][0]["health_note"] == "HTTP 429: retry later"
    assert result["sources"][0]["last_ok_at"] is None
    assert result["pending_events"][0]["content_version"] == 3
    assert result["failed_jobs"][0]["error"] == "HTTP 429: retry later"
    article = next(item for item in result["recent_content"] if item["id"] == 1)
    assert article["current_version"] == 3
    assert article["published_at"] is None
    assert datetime.fromisoformat(result["generated_at"]).tzinfo is not None


@pytest.mark.parametrize("path", ["/api/sources", "/api/sources/toggle", "/api/crawl"])
def test_read_only_rejects_mutations_before_dispatch(dashboard_server, monkeypatch, path):
    def forbidden(_body):
        raise AssertionError("mutation was dispatched from a read-only server")

    monkeypatch.setattr(dashboard, "_create_source", forbidden)
    monkeypatch.setattr(dashboard, "_toggle_source", forbidden)
    monkeypatch.setattr(dashboard, "_run_crawl", forbidden)
    base = dashboard_server()
    request = Request(base + path, data=b"not even valid JSON", method="POST")
    with pytest.raises(HTTPError) as error:
        urlopen(request, timeout=5)
    assert error.value.code == 403
    assert json.loads(error.value.read())["code"] == "read_only"
    with urlopen(base + "/api/status", timeout=5) as response:
        result = json.load(response)
    assert result["read_only"] is True
    assert result["counts"]["sources"] == 0


def test_development_management_mode_preserves_source_creation(
    dashboard_server, dashboard_database
):
    base = dashboard_server(read_only=False)
    request = Request(
        base + "/api/sources",
        data=json.dumps({"name": "Development source", "type": "rss"}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urlopen(request, timeout=5) as response:
        assert response.status == 201
    with dashboard_database() as session:
        assert session.scalar(select(Source.name)) == "Development source"
    with urlopen(base + "/api/status", timeout=5) as response:
        assert json.load(response)["read_only"] is False


def test_read_only_preparation_never_creates_schema(dashboard_database, monkeypatch):
    def forbidden(_engine):
        raise AssertionError("read-only startup attempted to create tables")

    monkeypatch.setattr(dashboard, "create_all", forbidden)
    before = inspect(dashboard.engine).get_table_names()
    dashboard._prepare_database(read_only=True)
    assert inspect(dashboard.engine).get_table_names() == before


def test_read_only_preparation_rejects_missing_file_without_creating_it(tmp_path, monkeypatch):
    path = tmp_path / "missing.db"
    monkeypatch.setattr(dashboard, "engine", create_engine(f"sqlite:///{path}"))
    with pytest.raises(ValueError, match="已存在"):
        dashboard._prepare_database(read_only=True)
    assert not path.exists()


def test_read_only_preparation_reports_missing_tables_without_migrating(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'empty.db'}")
    with engine.connect():
        pass
    monkeypatch.setattr(dashboard, "engine", engine)
    with pytest.raises(ValueError, match="缺少 L0 表"):
        dashboard._prepare_database(read_only=True)
    assert inspect(engine).get_table_names() == []
    engine.dispose()


def test_status_storage_failure_returns_retryable_service_error(dashboard_server, monkeypatch):
    def unavailable(**_kwargs):
        raise OperationalError("secret connection details", {}, Exception("db unavailable"))

    monkeypatch.setattr(dashboard, "_status", unavailable)
    with pytest.raises(HTTPError) as error:
        urlopen(dashboard_server() + "/api/status", timeout=5)
    assert error.value.code == 503
    payload = json.loads(error.value.read())
    assert payload["code"] == "storage_unavailable"
    assert "secret" not in payload["error"]


@pytest.mark.integration
@pytest.mark.parametrize("width", [390, 1280])
def test_browser_read_only_safety_mobile_layout_and_stale_refresh(
    dashboard_server, dashboard_database, monkeypatch, tmp_path, width
):
    from playwright.sync_api import expect, sync_playwright

    seed_dashboard(dashboard_database)
    base = dashboard_server()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=os.getenv("PLAYWRIGHT_CHROMIUM_EXECUTABLE") or None
        )
        page = browser.new_page(viewport={"width": width, "height": 900})
        page.goto(base)
        expect(page.get_by_text("真实入库的工程更新", exact=True)).to_be_visible()
        expect(page.locator("#modeLabel")).to_have_text("只读预览")
        expect(page.get_by_role("button", name="新增来源")).not_to_be_visible()
        assert page.locator("button[data-act]").count() == 0
        assert page.locator('a[href^="javascript:"]').count() == 0
        link = page.get_by_role("link", name="真实入库的工程更新")
        expect(link).to_have_attribute("rel", "noopener noreferrer")
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.screenshot(path=str(tmp_path / f"dashboard-{width}.png"), full_page=True)

        def unavailable(**_kwargs):
            raise OperationalError("forced refresh failure", {}, Exception("unavailable"))

        monkeypatch.setattr(dashboard, "_status", unavailable)
        page.get_by_role("button", name="刷新数据").click()
        expect(page.locator("#freshness")).to_contain_text("数据可能已过期")
        expect(page.get_by_text("真实入库的工程更新", exact=True)).to_be_visible()
        expect(page.locator("#stamp")).to_contain_text("最近成功读取")
        browser.close()
