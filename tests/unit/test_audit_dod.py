from __future__ import annotations

from core_data.scripts.audit_dod import audit


def test_dod_audit_passes_static_contract_checks() -> None:
    items = audit()
    assert items
    assert all(item.passed for item in items), items
