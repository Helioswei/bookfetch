"""Offline parser tests for the Project Gutenberg source (real captures)."""

from pathlib import Path

from bookfetch.sources.gutenberg import _parse_search_page, _strip_pg

FIX = Path(__file__).parent / "fixtures"


def test_search_page_parses_alice():
    page = (FIX / "pg_search_alice.html").read_text(encoding="utf-8")
    books = _parse_search_page(page)
    assert books, "real capture should contain results"
    assert all(b.source == "gutenberg" for b in books)
    ids = {b.id for b in books}
    assert "11" in ids  # Alice's Adventures in Wonderland (canonical PG #11)
    by_id = {b.id: b for b in books}
    assert by_id["11"].title == "Alice's Adventures in Wonderland"
    assert by_id["11"].subtitle == "Lewis Carroll"
    assert by_id["11"].url == "https://www.gutenberg.org/ebooks/11"


def test_strip_pg_removes_license_keep_text():
    raw = (FIX / "pg11_sample.txt").read_text(encoding="utf-8")
    out = _strip_pg(raw)
    assert "START OF THE PROJECT GUTENBERG EBOOK" not in out
    assert "END OF THE PROJECT GUTENBERG EBOOK" not in out
    # license header text is gone
    assert "This eBook is for the use of anyone" not in out
    # license tail (after END marker) is gone
    assert "Professor Michael S. Hart was the originator" not in out
    # book content between the markers survives
    assert "THE MILLENNIUM FULCRUM EDITION 3.0" in out


def test_strip_pg_no_start_returns_unchanged():
    # invariant: never destroy content when markers are absent
    assert _strip_pg("plain text without markers\n") == "plain text without markers\n"
    assert _strip_pg("") == ""
