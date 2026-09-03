"""ctext.org source adapter (Chinese classics, punctuated full text)."""

from __future__ import annotations

import html
import re
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

from ..model import Book, FetchResult
from ..util import FetchError, fetch, sanitize_filename
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


class Ctext(Source):
    name = "ctext"

    def search(self, query: str) -> list[Book]:
        """Search ctext 書名檢索. Returns [] on network failure."""
        try:
            page = fetch(SEARCH_URL.format(q=quote(query)))
        except FetchError:
            return []
        return _parse_search_page(page)

    def fetch(self, book: Book, out_dir: str | Path = ".") -> FetchResult:
        """Download a full book: res page -> ordered chapters -> concatenated text."""
        rid = book.id
        if not rid.isdigit():
            raise ValueError(f"ctext id must be a res/chapter number, got: {book.id!r}")
        try:
            res_page = fetch(RES_URL.format(rid=rid))
        except FetchError:
            raise

        chapters = list(dict.fromkeys(_CHAPTER_RE.findall(res_page)))
        if not chapters:
            raise FetchError(f"ctext res page {rid} lists no text chapters")

        title = book.title or chapters[0][1].strip()
        lines: list[str] = []
        for cid, _anchor in chapters:
            try:
                page = fetch(CHAPTER_URL.format(cid=cid))
            except FetchError as e:
                raise FetchError(f"chapter {cid} failed: {e}") from e
            lines.extend(_parse_text_cells(page))

        if not lines:
            raise FetchError(f"no text extracted from chapters of res {rid}")

        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        fname = sanitize_filename(title) or rid
        out_path = out_dir / f"{fname}.txt"
        text = "\n".join(lines) + "\n"
        out_path.write_text(text, encoding="utf-8")
        return FetchResult(
            source=self.name,
            id=rid,
            title=title,
            out_path=str(out_path),
            chars=len(text),
            lines=len(lines),
            format="txt",
        )
