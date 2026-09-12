from __future__ import annotations

from pathlib import Path

from core_data.config import Settings
from core_data.storage.factory import build_object_store
from core_data.storage.object_store import FileObjectStore


def test_build_object_store_defaults_to_file(tmp_path: Path) -> None:
    settings = Settings(object_store_backend="file", object_store_path=str(tmp_path))
    store = build_object_store(settings)
    assert isinstance(store, FileObjectStore)
