"""Project Gutenberg source adapter (English public-domain ebooks, 7万+).

Route: search page HTML -> /ebooks/<id> -> https://www.gutenberg.org/cache/epub/<id>/pg<id>.txt

The PG txt files are wrapped in license boilerplate:
  header: license + metadata up to  "*** START OF THE PROJECT GUTENBERG EBOOK ... ***"
  footer: "*** END OF THE PROJECT GUTENBERG EBOOK ... ***" + license text
``_strip_pg`` removes both so the user gets clean book text (the PG license
obligations apply at redistribution time and are the user's concern; the
tool-neutral stance is documented in README「源与合规」).

大陆直连实测 ~1.8s；无 GITenberg 的 per-book-repo 复杂度。英文书无繁简问题
(--simplify 遇英文原样)，单章/多章由 CLI 的 heading-split 兜底。
"""

from __future__ import annotations

import html
import re

from ..model import Book, FetchResult
from ..util import FetchError, fetch
from .base import Source

SEARCH_URL = "https://www.gutenberg.org/ebooks/search/?query={q}"
TXT_URL = "https://www.gutenberg.org/cache/epub/{eid}/pg{eid}.txt"

# Result list item (verified 2026-09-04 against live search HTML):
#   <li class="booklink"><a class="link" href="/ebooks/11" ...>
#     <span class="title">Alice's Adventures in Wonderland</span>
#     <span class="subtitle">Lewis Carroll</span> ...
_LI_RE = re.compile(r'<li class="booklink">(.*?)</li>', re.S)
_EID_RE = re.compile(r'href="/ebooks/(\d+)"')
_TITLE_RE = re.compile(r'<span class="title">(.*?)</span>', re.S)
_SUBTITLE_RE = re.compile(r'<span class="subtitle">(.*?)</span>', re.S)
_TAG_RE = re.compile(r"<[^>]+>")


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(_TAG_RE.sub("", s))).strip()


def _parse_search_page(page: str) -> list[Book]:
    """Parse the PG search results page into Book records."""
    books: list[Book] = []
    for li in _LI_RE.findall(page):
        m = _EID_RE.search(li)
        if not m:
            continue
        eid = m.group(1)
        t = _TITLE_RE.search(li)
        title = _clean(t.group(1)) if t else f"eBook #{eid}"
        if not title:
            continue
        author = ""
        st = _SUBTITLE_RE.search(li)
        if st:
            author = _clean(st.group(1))
        books.append(
            Book(
                source="gutenberg",
                id=eid,
                title=title,
                url=f"https://www.gutenberg.org/ebooks/{eid}",
                subtitle=author or "Project Gutenberg",
                format_hint="txt",
                extra={"author": author} if author else {},
            )
        )
    return books


_START_RE = re.compile(r"^\*{3}\s*START OF (?:THE|THIS) PROJECT GUTENBERG EBOOK", re.I | re.M)
_END_RE = re.compile(r"^\*{3}\s*END OF (?:THE|THIS) PROJECT GUTENBERG EBOOK", re.I | re.M)


def _strip_pg(text: str) -> str:
    """Cut the PG license header and footer, keeping only the book text.

    Robust to truncated input (a missing END marker keeps everything to EOF);
    returns the raw text unchanged when no START marker exists (never destroys
    content — the same invariant as the Chinese-classics splitters).
    """
    m = _START_RE.search(text)
    if not m:
        return text
    nl = text.find("\n", m.end())  # consume the whole marker line ("... EBOOK TITLE ***")
    body = text[nl + 1:] if nl >= 0 else text[m.end():]
    e = _END_RE.search(body)
    if e:
        body = body[: e.start()]
    return body


class Gutenberg(Source):
    name = "gutenberg"

    def search(self, query: str) -> list[Book]:
        page = fetch(SEARCH_URL.format(q=query.strip().replace(" ", "+")))
        return _parse_search_page(page)

    def fetch(self, book: Book) -> FetchResult:
        eid = book.id
        if not eid.isdigit():
            raise ValueError(f"gutenberg id must be an ebook number, got: {book.id!r}")
        text = fetch(TXT_URL.format(eid=eid))
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        content = _strip_pg(text).strip("\n")
        if not content:
            raise FetchError(f"gutenberg ebook {eid}: no book text after license strip")
        return FetchResult(
            source=self.name,
            id=eid,
            title=book.title or f"eBook #{eid}",
            chars=len(content),
            lines=len(content.splitlines()),
            format="txt",
            content=content,
            chapters=None,
        )
