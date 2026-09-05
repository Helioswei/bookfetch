"""biquge.tw (笔趣阁镜像) — 中文现代网文/小说镜像源 (M8, 2026-09-04 定案).

工具中立立场 (yt-dlp 模式): bookfetch 是路由下载工具, 不存储/重新分发内容,
义务在使用方; README「源与合规」对此源有红字免责. 本站为程序自动索引的
转载镜像 (页脚自述), 版权期内内容请使用方自审 —— 2025 年北京高院终审
判决「笔趣阁」商标无效, 为盗版网文平台代名词 (游民星空 2026-06 报道).

站情 (2026-09-04 实测): 大陆直连 ~1s; 搜索 /search.php?keyword=; 书目录
/book/<id>/ 全章节静态完整; 正文容器 <div id="chaptercontent"> 段落式
<p> 包裹, 无 JS 渲染; 繁体文本 (用户 --simplify 转简); CRLF 换行.

路由: search(关键词) → result-card 列表; fetch(书) → 目录页逐章抓正文.
"""

from __future__ import annotations

import html as html_mod
import re
from urllib.parse import quote

from ..model import Book, Chapter, FetchResult
from ..util import CancelledError, fetch
from .base import Source

_SEARCH_URL = "https://www.biquge.tw/search.php?keyword={q}"
_TOC_URL = "https://www.biquge.tw/book/{book_id}/"
_CHAPTER_URL = "https://www.biquge.tw/book/{book_id}/{cid}.html"
_BOOK_URL = "https://www.biquge.tw/book/{book_id}.html"
_LICENSE_NOTE = "转载镜像(程序自动索引), 版权期内内容使用前自审"

_CARD_RE = re.compile(r'<div class="result-card"(.*?)(?=<div class="result-card"|</ul>|<!-- |$)', re.S)
_HREF_RE = re.compile(r'href="/book/(\d+)\.html"')
_TITLE_RE = re.compile(r'class="book-title"[^>]*>(.*?)</a>', re.S)
_AUTHOR_RE = re.compile(r'class="author"[^>]*>(.*?)</span>', re.S)
_STATUS_RE = re.compile(r'class="badge[^"]*"[^>]*>(.*?)</span>', re.S)
_INTRO_RE = re.compile(r'class="book-intro"[^>]*>(.*?)</div>', re.S)
_TOC_RE = re.compile(r'href="(/book/\d+/(\d+)\.html)"[^>]*>(.*?)</a>', re.S)
_H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.S)
_CONTENT_RE = re.compile(r'<div[^>]+id="chaptercontent"[^>]*>(.*?)</div>', re.S)
_PAGE_NOISE = re.compile(r"\s*（\s*\d+\s*/\s*\d+\s*）\s*$")


def _clean_title(s: str) -> str:
    t = html_mod.unescape(re.sub(r"<[^>]+>", "", s)).strip()
    return _PAGE_NOISE.sub("", t).strip()


def _parse_search(html: str) -> list[dict]:
    """result-card 列表 → [{book_id, title, author, status, intro}]."""
    out: list[dict] = []
    for card in _CARD_RE.findall(html):
        m = _HREF_RE.search(card)
        if not m:
            continue
        t = _TITLE_RE.search(card)
        author = _AUTHOR_RE.search(card)
        status = _STATUS_RE.search(card)
        intro = _INTRO_RE.search(card)
        out.append({
            "book_id": m.group(1),
            "title": _clean_title(t.group(1)) if t else "",
            "author": _clean_title(author.group(1)) if author else "",
            "status": _clean_title(status.group(1)) if status else "",
            "intro": re.sub(r"\s+", " ", _clean_title(intro.group(1)))[:120] if intro else "",
        })
    return out


def _parse_toc(html: str, book_id: str) -> list[tuple[str, str]]:
    """目录页 → [(cid, title)] 保持页序. 只收该书自己的章节链接."""
    out = []
    for full, cid, title in _TOC_RE.findall(html):
        if f"/book/{book_id}/" not in full:
            continue
        t = _clean_title(title)
        if t and (cid, t) not in out:
            out.append((cid, t))
    return out


def _parse_chapter(html: str) -> tuple[str, str]:
    """章节页 → (title, plain text). 空壳页返回 ("", "")."""
    m = _CONTENT_RE.search(html)
    if not m:
        return "", ""
    raw = m.group(1)
    # 段落式: </p> 为段界; 兜底 <br> 为行界
    raw = raw.replace("</p>", "\n").replace("<br/>", "\n").replace("<br>", "\n")
    text = re.sub(r"<[^>]+>", "", raw)
    text = html_mod.unescape(text)
    text = text.replace("\r", "").replace("\u3000", " ")
    lines = [re.sub(r"^\s+|\s+$", "", ln) for ln in text.splitlines()]
    text = "\n".join(ln for ln in lines if ln.strip()).strip()
    mh = _H1_RE.search(html)
    title = _clean_title(mh.group(1)) if mh else ""
    return title, text


class Biquge(Source):
    name = "biquge"
    label = "网络小说"

    def search(self, query: str) -> list[Book]:
        html = fetch(_SEARCH_URL.format(q=quote(query)))
        books = []
        for r in _parse_search(html):
            books.append(Book(
                source=self.name,
                id=r["book_id"],
                title=r["title"],
                url=_BOOK_URL.format(book_id=r["book_id"]),
                subtitle=f"{r['author']} · {r['status']}".strip(" ·"),
                format_hint="txt",
                extra={
                    "author": r["author"],
                    "status": r["status"],
                    "intro": r["intro"],
                    "license": _LICENSE_NOTE,
                },
            ))
        return books

    def fetch(self, book: Book, *, on_progress=None, on_checkpoint=None, resume_from=0) -> FetchResult:
        """整本下载: 目录页 → 逐章正文 (每章一请求, 全局限速 2s/请求).
        1361 章的书 ≈ 45 分钟; 空壳章节跳过不中断.

        B4 断点续传/边下边读：on_checkpoint(index, Chapter) 每成功章回调一次
        （调用方持久化 + 增量写库）；resume_from = 跳过前 N 个 toc 条目
        （续传起点 = 上次最后成功章之后，空壳章不计数不回调）。
        """
        book_id = book.id.strip()
        if not book_id.isdigit():
            raise ValueError(f"biquge id must be the numeric book id, got {book.id!r}")
        toc_html = fetch(_TOC_URL.format(book_id=book_id))
        toc = _parse_toc(toc_html, book_id)
        if not toc:
            raise ValueError(f"目录页无章节 (书 {book_id} 不存在或已下架?)")
        chapters: list[Chapter] = []
        skipped = 0
        for i in range(resume_from, len(toc)):
            cid, toc_title = toc[i]
            if on_progress and not on_progress(i, len(toc)):
                raise CancelledError()
            html = fetch(_CHAPTER_URL.format(book_id=book_id, cid=cid))
            ctitle, ctext = _parse_chapter(html)
            if not ctext:
                skipped += 1
                continue
            c = Chapter(title=ctitle or toc_title, text=ctext)
            chapters.append(c)
            if on_checkpoint:
                on_checkpoint(i, c)
        content = "\n\n".join(c.text for c in chapters)
        title = book.title or f"biquge-{book_id}"
        return FetchResult(
            source=self.name,
            id=book.id,
            title=title,
            chars=len(content),
            lines=content.count("\n") + 1 if content else 0,
            format="txt",
            content=content,
            chapters=chapters,
        )
