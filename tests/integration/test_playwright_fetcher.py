from __future__ import annotations

from pathlib import Path

import pytest

from core_data.ingest.fetcher import fetch_page


@pytest.mark.integration
def test_playwright_rendered_file_fixture() -> None:
    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "html" / "js_rendered.html"
    result = fetch_page(fixture.as_uri(), render=True)

    assert result.method == "playwright"
    assert result.status == 200
    assert b"Playwright rendered content proves browser fetching works" in result.html
