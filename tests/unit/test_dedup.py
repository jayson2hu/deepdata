from __future__ import annotations

from core_data.ingest.dedup import content_hash, hamming_distance, normalize_url, simhash, url_hash


def test_url_hash_ignores_tracking_params() -> None:
    left = "https://Example.com/Post/?utm_source=newsletter&id=1"
    right = "https://example.com/Post?id=1"
    assert normalize_url(left) == normalize_url(right)
    assert url_hash(left) == url_hash(right)


def test_content_hash_normalizes_whitespace_and_case() -> None:
    assert content_hash("Hello   World") == content_hash("hello world")


def test_simhash_near_texts_are_close() -> None:
    left = simhash("immutable raw data keeps downstream systems reproducible")
    right = simhash("immutable raw data keeps downstream systems very reproducible")
    assert hamming_distance(left, right) < 10
