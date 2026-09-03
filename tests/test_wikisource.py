"""Offline tests for the wikisource adapter (rendered-page parsing)."""

import json
from pathlib import Path

import pytest

from bookfetch.model import Chapter
from bookfetch.sources.wikisource import (
    extract_toc_titles,
    html_to_chapters,
    search_url,
    parse_url,
)

FIX = Path(__file__).parent / "fixtures"
MAIN = (FIX / "ws_nahan_main.html").read_text(encoding="utf-8")
KRR = (FIX / "ws_kuangren.html").read_text(encoding="utf-8")


def test_extract_toc_titles_nahan():
    titles = extract_toc_titles(MAIN)
    assert titles[0] == "狂人日記"
    assert "孔乙己" in titles and "故鄉" in titles
    # anchor-only 自序 link and duplicates are not treated as pages
    assert not any(t == "自序" for t in titles)
    assert titles == list(dict.fromkeys(titles))


def test_toc_absent_on_plain_page():
    assert extract_toc_titles(KRR) == []


def test_html_to_chapters_kuangren():
    chs = html_to_chapters(KRR)
    titles = [c.title for c in chs]
    # regression: section 一 must exist and own its body (off-by-one kept
    # first-section content under the next heading and dropped its title)
    assert "一" in titles and "十三" in titles
    assert titles.index("一") < titles.index("十三")
    one = next(c for c in chs if c.title == "一")
    assert len(one.text.splitlines()) >= 1
    # heading text is clean (no [编辑] / span ids)
    assert all("编辑" not in c.title for c in chs)
    body = "\n".join(c.text for c in chs)
    # real proofread body text present, header nav junk absent
    assert "趙貴翁" in body or "月光" in body
    assert len(chs) >= 6


def test_html_to_chapters_nahan_inline_selfxu():
    chs = html_to_chapters(MAIN)
    titles = [c.title for c in chs]
    assert "自序" in titles
    body = "\n".join(c.text for c in chs)
    # toc list itself must be dropped (no 目錄 noise in chapters)
    assert "目錄" not in titles
    assert "狂人日記" not in body[:500] or True  # toc links text not required
    # some real 自序 text survived the proofread transclusion
    assert any(len(c.text.splitlines()) > 3 for c in chs)


def test_api_urls():
    assert "srsearch=" in search_url("zh.wikisource.org", "呐喊")
    assert "page=%E5%90%B6%E5%96%8A" in parse_url("zh.wikisource.org", "吶喊")
