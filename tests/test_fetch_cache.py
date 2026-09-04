"""Offline tests for the N1 fetch cache (yt-dlp archive style)."""

import json

from bookfetch import fetch_cache
from bookfetch.model import Chapter, FetchResult
from bookfetch.cli import main


def _txt_result() -> FetchResult:
    return FetchResult(
        source="gutenberg", id="11", title="Alice",
        chars=120, lines=3, format="txt",
        content="line1\nline2\nline3",
        chapters=[Chapter("CH1", "line1\nline2"), Chapter("CH2", "line3")],
    )


def _raw_result() -> FetchResult:
    return FetchResult(
        source="libgen", id="abc123", title="Modern Book",
        chars=0, lines=0, format="epub", content="", chapters=None,
        raw=b"\x50\x4b binary epub bytes",
    )


def test_roundtrip_text(tmp_path, monkeypatch):
    monkeypatch.setenv("BOOKFETCH_CACHE", str(tmp_path))
    fr = _txt_result()
    fetch_cache.save("gutenberg", "11", fr)
    got = fetch_cache.load("gutenberg", "11")
    assert got is not None
    assert got.title == "Alice"
    assert got.content == "line1\nline2\nline3"
    assert got.chapters and got.chapters[0].title == "CH1"
    assert got.chapters[1].text == "line3"
    assert got.raw is None


def test_roundtrip_raw(tmp_path, monkeypatch):
    monkeypatch.setenv("BOOKFETCH_CACHE", str(tmp_path))
    fetch_cache.save("libgen", "abc123", _raw_result())
    got = fetch_cache.load("libgen", "abc123")
    assert got is not None and got.raw == b"\x50\x4b binary epub bytes"
    assert got.format == "epub"


def test_key_isolation(tmp_path, monkeypatch):
    monkeypatch.setenv("BOOKFETCH_CACHE", str(tmp_path))
    fetch_cache.save("gutenberg", "11", _txt_result())
    assert fetch_cache.load("gutenberg", "12") is None   # different id
    assert fetch_cache.load("ctext", "11") is None       # different source


def test_corrupt_cache_is_a_miss(tmp_path, monkeypatch):
    monkeypatch.setenv("BOOKFETCH_CACHE", str(tmp_path))
    p = fetch_cache.cache_path("gutenberg", "11")
    p.write_text("{not valid json", encoding="utf-8")
    assert fetch_cache.load("gutenberg", "11") is None


def test_clear(tmp_path, monkeypatch):
    monkeypatch.setenv("BOOKFETCH_CACHE", str(tmp_path))
    fetch_cache.save("gutenberg", "11", _txt_result())
    fetch_cache.clear("gutenberg", "11")
    assert fetch_cache.load("gutenberg", "11") is None


class _FakeSrc:
    """Counts fetch() calls; returns a tiny deterministic book."""

    def __init__(self):
        self.calls = 0

    def fetch(self, book):
        self.calls += 1
        return FetchResult(
            source=book.source, id=book.id, title="假书",
            chars=10, lines=2, format="txt",
            content="第一行\n第二行",
            chapters=[Chapter("第一节", "第一行\n第二行")],
        )


def test_get_second_run_is_cached(tmp_path, monkeypatch):
    """yt-dlp archive behavior: 2nd get of the same edition skips network."""
    monkeypatch.setenv("BOOKFETCH_CACHE", str(tmp_path))
    out = tmp_path / "out"
    fake = _FakeSrc()
    monkeypatch.setattr("bookfetch.cli.get_source", lambda name: fake)

    assert main(["get", "fake", "42", "--out", str(out)]) == 0
    assert fake.calls == 1
    f1 = out / "假书.txt"
    assert f1.exists()

    assert main(["get", "fake", "42", "--out", str(out)]) == 0
    assert fake.calls == 1, "second get must not hit the source again"
    assert f1.exists()  # re-rendered from cache into the same path

    # --force re-fetches
    assert main(["get", "fake", "42", "--out", str(out), "--force"]) == 0
    assert fake.calls == 2


def test_get_different_format_also_cached(tmp_path, monkeypatch):
    """txt cached once → epub request served from cache, no network."""
    monkeypatch.setenv("BOOKFETCH_CACHE", str(tmp_path))
    out = tmp_path / "out"
    fake = _FakeSrc()
    monkeypatch.setattr("bookfetch.cli.get_source", lambda name: fake)

    assert main(["get", "fake", "42", "--out", str(out)]) == 0
    assert fake.calls == 1
    assert main(["get", "fake", "42", "--out", str(out), "--format", "epub"]) == 0
    assert fake.calls == 1
    assert (out / "假书.epub").exists()
