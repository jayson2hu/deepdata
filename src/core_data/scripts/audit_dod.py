from __future__ import annotations

import inspect
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from core_data.db.models import (
    ContentItem,
    ContentVersion,
    CrawlJob,
    RawDocument,
    Source,
    SourceHealth,
)
from core_data.events.outbox import emit
from core_data.ingest.raw_store import RawStore
from core_data.query.contracts import ContentOut


@dataclass(frozen=True)
class AuditItem:
    name: str
    passed: bool
    evidence: str


L0_TABLES = {
    "sources": Source,
    "source_health": SourceHealth,
    "crawl_jobs": CrawlJob,
    "raw_documents": RawDocument,
    "content_items": ContentItem,
    "content_versions": ContentVersion,
}

STABLE_FIELDS = {
    "id",
    "canonical_url",
    "title",
    "clean_text",
    "lang",
    "source",
    "published_at",
    "status",
}


def audit() -> list[AuditItem]:
    items = [
        _audit_raw_store_append_only(),
        _audit_owned_tables(),
        _audit_content_contract_fields(),
        _audit_event_contract(),
        _audit_no_upper_layer_imports(),
        _audit_delivery_files(),
        _audit_external_dod_entrypoint(),
    ]
    return items


def _audit_raw_store_append_only() -> AuditItem:
    forbidden = [name for name in ("update", "delete") if hasattr(RawStore, name)]
    return AuditItem(
        "RawStore append-only API",
        not forbidden,
        "no update/delete methods" if not forbidden else f"forbidden methods: {forbidden}",
    )


def _audit_owned_tables() -> AuditItem:
    table_names = {model.__tablename__ for model in L0_TABLES.values()}
    missing = set(L0_TABLES) - table_names
    return AuditItem(
        "L0 owned table models",
        not missing,
        f"tables={sorted(table_names)}",
    )


def _audit_content_contract_fields() -> AuditItem:
    fields = set(ContentOut.model_fields)
    missing = STABLE_FIELDS - fields
    return AuditItem(
        "L1 stable content fields",
        not missing,
        f"fields={sorted(fields)}",
    )


def _audit_event_contract() -> AuditItem:
    signature = inspect.signature(emit)
    parameters = set(signature.parameters)
    expected = {"session", "topic", "payload", "idempotency_key"}
    return AuditItem(
        "Transactional outbox emit signature",
        expected.issubset(parameters),
        f"parameters={sorted(parameters)}",
    )


def _audit_no_upper_layer_imports() -> AuditItem:
    root = Path(__file__).resolve().parents[1]
    forbidden = {"app_l1", "app_l2", "app_l3", "l1", "l2", "l3"}
    hits: list[str] = []
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for name in forbidden:
            if f"import {name}" in text or f"from {name}" in text:
                hits.append(f"{path}:{name}")
    return AuditItem(
        "No upper-layer imports",
        not hits,
        "FORBIDDEN_IMPORTS []" if not hits else ", ".join(hits),
    )


def _audit_delivery_files() -> AuditItem:
    repo = Path(__file__).resolve().parents[3]
    required = [
        repo / "README.md",
        repo / "Makefile",
        repo / "deploy" / "docker-compose.yml",
        repo / "db" / "alembic" / "versions" / "0001_l0_initial.py",
        repo / "tests" / "fixtures" / "rss" / "normal.xml",
    ]
    missing = [str(path) for path in required if not path.exists()]
    return AuditItem(
        "Delivery artifacts",
        not missing,
        "all required artifacts present" if not missing else f"missing={missing}",
    )


def _audit_external_dod_entrypoint() -> AuditItem:
    repo = Path(__file__).resolve().parents[3]
    required = {
        repo / "src" / "core_data" / "scripts" / "external_dod.py": [
            "DATABASE_URL must point at PostgreSQL",
            "OBJECT_STORE_BACKEND must be s3",
            "_verify_redis_relay",
            "run_soak",
        ],
        repo / "Makefile": ["external-dod", "core_data.scripts.external_dod"],
        repo / "README.md": [
            "make external-dod",
            "PostgreSQL+pgvector",
            "Redis relay",
            "24 小时 soak",
        ],
    }
    missing: list[str] = []
    for path, snippets in required.items():
        if not path.exists():
            missing.append(str(path))
            continue
        text = path.read_text(encoding="utf-8")
        for snippet in snippets:
            if snippet not in text:
                missing.append(f"{path.name}:{snippet}")
    return AuditItem(
        "External DoD verifier entrypoint",
        not missing,
        "external DoD verifier documented and wired"
        if not missing
        else f"missing={missing}",
    )


def main() -> None:
    items = audit()
    report = {
        "passed": all(item.passed for item in items),
        "items": [asdict(item) for item in items],
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
