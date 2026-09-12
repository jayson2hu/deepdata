from __future__ import annotations

import pytest

from core_data.scripts.external_dod import _redact_url


def test_redact_url_hides_credentials() -> None:
    assert (
        _redact_url("postgresql+psycopg://codepick:dev@localhost:5432/codepick")
        == "postgresql+psycopg://***@localhost:5432/codepick"
    )


def test_external_dod_rejects_local_sqlite(monkeypatch: pytest.MonkeyPatch) -> None:
    from core_data.scripts import external_dod

    monkeypatch.setattr(
        external_dod,
        "get_settings",
        lambda: type(
            "Settings",
            (),
            {
                "database_url": "sqlite:///./.runtime/codepick_l0.db",
                "object_store_backend": "file",
            },
        )(),
    )

    with pytest.raises(SystemExit, match="DATABASE_URL must point at PostgreSQL"):
        external_dod.main([])
