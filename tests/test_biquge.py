"""Offline parser tests for the biquge source (real 2026-09-04 captures)."""

from pathlib import Path

from bookfetch.sources.biquge import _parse_chapter, _parse_search, _parse_toc

FIX = Path(__file__).parent / "fixtures"


def test_parse_search_cards():
    html = (FIX / "bq_search.html").read_text(encoding="utf-8")
    cards = _parse_search(html)
    assert len(cards) >= 2
    top = cards[0]
    assert top["book_id"] == "50045"
    assert top["title"] == "詭秘之主"
    assert "烏賊" in top["author"]          # 作者(繁体原文保留)
    assert top["status"]                     # 完結/連載
    assert top["intro"]                      # 简介


def test_parse_toc_order_and_titles():
    html = (FIX / "bq_toc.html").read_text(encoding="utf-8")
    toc = _parse_toc(html, "50045")
    assert len(toc) >= 20
    cid0, t0 = toc[0]
    assert cid0 == "33397038"
    assert t0 == "第一章 绯红"
    # 页数尾注"（1 / 1）"已被清掉 (书名自带括号如"（第一更…）"保留)
    assert not any(t.endswith("（1 / 1）") or t.endswith("(1/1)") for _, t in toc)
    # 不混入别书链接
    assert all(cid.isdigit() for cid, _ in toc)


def test_parse_chapter_body():
    html = (FIX / "bq_chapter.html").read_text(encoding="utf-8")
    title, text = _parse_chapter(html)
    assert title == "第一章 绯红"
    assert len(text) > 500
    assert text.startswith("痛！")           # 段首无残留标签/空白
    assert "周明瑞" in text                  # 正文在
    assert "<" not in text                   # 无 HTML 残留
    assert "\r" not in text                  # CRLF 已清洗
    assert "笔趣阁" not in text[:50]         # 正文头无站名噪音


def test_parse_chapter_empty_shell():
    title, text = _parse_chapter("<html><body>no content div</body></html>")
    assert (title, text) == ("", "")
