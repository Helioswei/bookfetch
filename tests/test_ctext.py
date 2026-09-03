"""Offline parser tests using captured real ctext pages (no network)."""

from pathlib import Path

from bookfetch.sources.ctext import (
    _parse_search_page,
    _parse_text_cells,
    _CHAPTER_RE,
)

FIX = Path(__file__).parent / "fixtures"


def test_search_page_parses_yuanhai():
    page = (FIX / "searchbooks.html").read_text(encoding="utf-8")
    books = _parse_search_page(page)
    # Real capture: 3 records, 2 of them wiki text editions of 淵海子平
    assert len(books) >= 2
    assert all(b.source == "ctext" for b in books)
    titles = {b.title for b in books}
    assert "淵海子平" in titles
    ids = {b.id for b in books}
    assert "727782" in ids and "6995577" in ids
    # Author metadata present on the representative edition
    by_id = {b.id: b for b in books}
    assert "徐子平" in by_id["727782"].extra.get("author", "")
    assert any("維基文字版" in b.subtitle for b in books)


def test_res_page_lists_ordered_chapters():
    page = (FIX / "res_book.html").read_text(encoding="utf-8")
    chapters = list(dict.fromkeys(_CHAPTER_RE.findall(page)))
    ids = [c[0] for c in chapters]
    assert ids == ["296619", "524726", "901791"]
    assert all("淵海子平" in c[1] for c in chapters)


def test_chapter_page_extracts_text_cells():
    page = (FIX / "chapter_296619_head.html").read_text(encoding="utf-8")
    lines = _parse_text_cells(page)
    assert lines, "no text cells parsed"
    # numbering cells must be excluded: no line is a bare number
    assert not any(l.isdigit() for l in lines)
    # real captured content sanity
    joined = "\n".join(lines)
    assert "淵海子平" in joined or "五干屬陽" in joined or "基礎" in joined
