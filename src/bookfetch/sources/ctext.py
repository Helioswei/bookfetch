"""ctext.org source adapter (Chinese classics, punctuated full text)."""

from __future__ import annotations

import html
import re
from urllib.parse import parse_qs, quote, urlparse

from ..model import Book, Chapter, FetchResult
from ..util import CancelledError, FetchError, fetch
from ..util.splitters import split_headings
from .base import Source

SEARCH_URL = "https://ctext.org/searchbooks.pl?if=gb&searchu={q}"
RES_URL = "https://ctext.org/wiki.pl?if=gb&res={rid}"
CHAPTER_URL = "https://ctext.org/wiki.pl?if=gb&chapter={cid}"

# A paragraph row is: <tr class="result" id="pN">
#   <td class="ctext" style="width: 60px;" ...>N <a onclick=showDic>...</td>   <- line number
#   <td class="ctext">正文…</td>                                                 <- the text
_TD_RE = re.compile(r'<td class="ctext"([^>]*)>(.*?)</td>', re.S)
_NUM_CELL = re.compile(r"width:\s*60px")
_ANCHOR_RE = re.compile(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', re.S)
_AUTHOR_RE = re.compile(r'<span style="font-weight: bold;">(.*?)</span>', re.S)
_CHAPTER_RE = re.compile(r'href="[^"]*chapter=(\d+)"[^>]*>(.*?)</a>', re.S)

_TAG_RE = re.compile(r"<[^>]+>")


def _strip_tags(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(_TAG_RE.sub("", s))).strip()


def _parse_search_page(page: str) -> list[Book]:
    """Parse a ctext 書名檢索 result page into Book records."""
    books: list[Book] = []
    for li in re.split(r"<li", page)[1:]:
        m = _ANCHOR_RE.search(li)
        if not m:
            continue
        href = html.unescape(m.group(1))
        title = _strip_tags(m.group(2))
        if "wiki.pl" not in href or "res=" not in href:
            continue  # only wiki text editions are downloadable in V1
        rid = parse_qs(urlparse(href).query).get("res", [""])[0]
        if not rid:
            continue
        author = ""
        am = _AUTHOR_RE.search(li)
        if am:
            author = _strip_tags(am.group(1))
            # "（宋）徐子平" -> "徐子平" (drop the era wrapper)
            author = re.sub(r"^[（(][^）)]*[）)]", "", author).strip()
        note = ""
        # note text sits after the bold author span (usually after a <br>),
        # up to the end of the <li> record
        if am:
            tail = li[am.end() :]
            end = tail.find("</li>")
            if end >= 0:
                tail = tail[:end]
            note = _strip_tags(tail)
        books.append(
            Book(
                source="ctext",
                id=rid,
                title=title,
                url=href,
                subtitle=note,
                format_hint="txt",
                extra={"author": author} if author else {},
            )
        )
    return books


def _parse_text_cells(page: str) -> list[str]:
    """Extract paragraph text from a ctext wiki text page (td.ctext cells)."""
    lines: list[str] = []
    for attrs, body in _TD_RE.findall(page):
        if _NUM_CELL.search(attrs or ""):
            continue  # line-number cell
        txt = _strip_tags(body)
        if txt:
            lines.append(txt)
    return lines


def _chapter_title(anchor: str, idx: int) -> str:
    """Wiki-page anchor text, or a neutral ordinal for unnamed pages
    (most wiki pages of one book share the book title as anchor)."""
    t = _strip_tags(anchor)
    return t or f"第{idx}部分"


class Ctext(Source):
    name = "ctext"
    label = "中文古籍"

    def search(self, query: str) -> list[Book]:
        """Search ctext 書名檢索. Network errors propagate to the CLI errors dict."""
        page = fetch(SEARCH_URL.format(q=quote(query)))
        return _parse_search_page(page)

    def fetch(self, book: Book, *, on_progress=None, on_checkpoint=None, resume_from=0) -> FetchResult:
        """Fetch a whole book: res page -> ordered wiki pages -> chapters.

        Each wiki page becomes one or more chapters: standalone 《》/卷
        heading lines split it into titled sections; a page without such
        structure stays one chapter named by its anchor.
        """
        rid = book.id
        if not rid.isdigit():
            raise ValueError(f"ctext id must be a res/chapter number, got: {book.id!r}")

        res_page = fetch(RES_URL.format(rid=rid))
        anchors = list(dict.fromkeys(_CHAPTER_RE.findall(res_page)))
        if not anchors:
            raise FetchError(f"ctext res page {rid} lists no text chapters")

        title = book.title or _strip_tags(anchors[0][1])
        chapters: list[Chapter] = []
        all_lines: list[str] = []
        for idx, (cid, anchor) in enumerate(anchors, 1):
            if on_progress and not on_progress(idx - 1, len(anchors)):
                raise CancelledError()
            try:
                page = fetch(CHAPTER_URL.format(cid=cid))
            except FetchError as e:
                raise FetchError(f"chapter {cid} failed: {e}") from e
            lines = _parse_text_cells(page)
            if not lines:
                continue
            all_lines.extend(lines)
            page_chs = split_headings(lines)
            if page_chs:
                chapters.extend(page_chs)
            else:
                chapters.append(Chapter(title=_chapter_title(anchor, idx), text="\n".join(lines)))

        if not all_lines:
            raise FetchError(f"no text extracted from chapters of res {rid}")

        content = "\n".join(c.text for c in chapters) + "\n"
        return FetchResult(
            source=self.name,
            id=rid,
            title=title,
            chars=len(content),
            lines=len(all_lines),
            format="txt",
            content=content,
            chapters=chapters,
        )
