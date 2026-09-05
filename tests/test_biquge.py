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


# ----------------------------------------------------------- B4 fetch 循环策略 ---

def test_fetch_checkpoint_skips_shells_and_resumes(monkeypatch):
    """B4：成功章逐章 on_checkpoint(index, chapter)；空壳章跳过不回调不计数；
    resume_from 从指定 toc 条目续抓（不重抓已成功章、不产生重复）。"""
    import bookfetch.sources.biquge as bq
    from bookfetch.model import Book
    from bookfetch.sources.biquge import Biquge

    # 6 章目录，第 2 章（102）是空壳
    toc = [(str(101 + i), f"第{i + 1}章") for i in range(6)]
    seen_urls = []

    def fake_parse_chapter(html):
        cid = html.strip()  # 简化：html 直接携带 cid
        if cid == "102":  # 空壳防盗章
            return ("", "")
        return (f"第{cid}章", f"正文-{cid}")

    monkeypatch.setattr(bq, "_parse_toc", lambda html, book_id: toc)
    monkeypatch.setattr(bq, "_parse_chapter", fake_parse_chapter)
    monkeypatch.setattr(bq, "fetch", lambda url: (seen_urls.append(url) or url.rsplit("/", 1)[-1].split(".")[0]))

    src = Biquge()
    book = Book(source="biquge", id="50045", title="测试书")

    # ① 从头抓：checkpoint 只收到成功章（102 不在），chapters 无空壳
    checkpoints = []
    fr = src.fetch(book, on_checkpoint=lambda i, c: checkpoints.append((i, c.title)))
    assert [i for i, _ in checkpoints] == [0, 2, 3, 4, 5], checkpoints
    assert [c.title for c in (fr.chapters or [])] == ["第101章", "第103章", "第104章", "第105章", "第106章"]
    assert len(seen_urls) == 1 + 6  # toc 页 + 6 个条目全请求（空壳 102 也消耗一次请求）

    # ② 续传：resume_from=3 → 只抓 toc[3:]（104 起），不重抓已成功章
    seen_urls.clear()
    fr2 = src.fetch(book, resume_from=3)
    assert [c.title for c in (fr2.chapters or [])] == ["第104章", "第105章", "第106章"]
    assert len(seen_urls) == 1 + 3  # toc 页 + 3 个条目

    # ③ cancel：on_progress 返 False → CancelledError 冒泡
    import pytest
    from bookfetch.util import CancelledError

    with pytest.raises(CancelledError):
        src.fetch(book, on_progress=lambda done, total: False)
