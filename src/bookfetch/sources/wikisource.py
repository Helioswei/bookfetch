"""zh/en.wikisource.org adapter (public-domain texts, incl. ProofreadPage
scanned editions whose body only exists in the rendered HTML).

MediaWiki JSON API is used for search and for action=parse (rendered HTML)
because many books transclude their text from scanned pages (<pages> tags)
which raw wikitext does not contain. Container books (吶喊 = TOC + story
pages) are expanded: TOC page links become chapters fetched in order; inline
sections on the container page (自序...) stay as chapters too.
"""

from __future__ import annotations

import html as html_mod
import json
import re
from html.parser import HTMLParser
from urllib.parse import quote, unquote

from ..model import Book, Chapter, FetchResult
from ..util import CancelledError, FetchError, fetch
from .base import Source

API = "https://{host}/w/api.php"
PAGE_URL = "https://{host}/wiki/{title}"

_UA_PARAMS = "&format=json&utf8=1"

# Junk subtrees to skip in rendered pages: nav headers, edit links, footers.
_JUNK_CLASS = (
    "mw-editsection", "headerContainer", "navbox", "noprint", "printfooter",
    "catlinks", "sisterproject", "mw-empty-elt", "ws-noexport", "license",
    "references", "mw-indicators", "error", "mw-revision",
)

_TAG_RE = re.compile(r"<[^>]+>")


def _strip_tags(s: str) -> str:
    return re.sub(r"\s+", " ", html_mod.unescape(_TAG_RE.sub("", s))).strip()


def search_url(host: str, query: str, limit: int = 20) -> str:
    q = quote(query)
    return (
        f"{API.format(host=host)}?action=query&list=search&srnamespace=0"
        f"&srlimit={limit}&srsearch={q}{_UA_PARAMS}"
    )


def parse_url(host: str, title: str) -> str:
    t = quote(title.replace(" ", "_"), safe="")
    return f"{API.format(host=host)}?action=parse&page={t}&prop=text|displaytitle&redirects=1{_UA_PARAMS}"


def _search_json(page: str, host: str, source_name: str) -> list[Book]:
    books: list[Book] = []
    data = json.loads(page)
    for item in data.get("query", {}).get("search", []):
        title = item.get("title", "")
        if not title:
            continue
        books.append(
            Book(
                source=source_name,
                id=title,
                title=title,
                url=PAGE_URL.format(host=host, title=quote(title.replace(" ", "_"), safe="")),
                subtitle=_strip_tags(item.get("snippet", ""))[:120],
                format_hint="txt",
                extra={"lang": host.split(".")[0], "pageid": item.get("pageid")},
            )
        )
    return books


def extract_toc_titles(html: str) -> list[str]:
    """Ordered subpage titles from a 目錄/目录/TOC heading's link list."""
    m = re.search(r'<h2[^>]*>(?:(?!</h2>).)*?目[錄录]</h2>', html, re.S)
    if not m:
        return []
    region = html[m.end():]
    nxt = re.search(r"<h[23][^>]*>", region)
    if nxt:
        region = region[: nxt.start()]
    titles: list[str] = []
    for href, text in re.findall(r'<a[^>]+href="(/wiki/[^"]+)"[^>]*>(.*?)</a>', region, re.S):
        label = _strip_tags(text)
        if not label or label.startswith("#"):
            continue
        title = unquote(href[len("/wiki/"):]).replace("_", " ")
        titles.append(title)
    # drop duplicate labels keep first occurrence order stable
    seen: set[str] = set()
    out: list[str] = []
    for t in titles:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


class _PageParser(HTMLParser):
    """Rendered page -> chapters split at h2/h3/h4 headings.

    Each chapter accumulates block lines (<p>/<li>, <br> = line break).
    The 目錄 heading and everything until the next heading is dropped;
    junk-class subtrees (edit links, nav tables, licences) are skipped.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.chapters: list[Chapter] = []
        self._title = ""
        self._lines: list[str] = []
        self._block: list[str] = []
        self._skip = 0
        self._in_toc = False
        self._in_heading = False
        self._heading = ""
        self._stack: list[str] = []  # element classes for skip bookkeeping

    def _push(self, attrs):
        cls = dict(attrs).get("class", "")
        self._stack.append(cls)
        if any(j in cls for j in _JUNK_CLASS):
            self._skip += 1

    def _pop(self):
        cls = self._stack.pop() if self._stack else ""
        if any(j in cls for j in _JUNK_CLASS) and self._skip > 0:
            self._skip -= 1

    def handle_starttag(self, tag, attrs):
        self._push(attrs)
        if tag in ("h2", "h3", "h4"):
            if self._in_toc:
                self._in_toc = False
            self._in_heading = True
            self._heading = ""
        elif tag in ("p", "li") and not self._skip and not self._in_toc:
            self._block = []

    def handle_startendtag(self, tag, attrs):
        if tag == "br" and not self._skip and not self._in_toc and not self._in_heading:
            self._block.append("\n")

    def handle_endtag(self, tag):
        if tag in ("h2", "h3", "h4") and self._in_heading:
            self._in_heading = False
            heading = self._heading.strip()
            if heading == "目錄":
                self._in_toc = True
                self._title = ""
                self._lines = []
            else:
                # finalize the chapter that just ended (its title was set by
                # the previous heading); then open the new one
                if self._title or self._lines:
                    self.chapters.append(Chapter(title=self._title, text="\n".join(self._lines)))
                self._title = heading
                self._lines = []
        elif tag in ("p", "li") and not self._skip and not self._in_toc:
            line = "".join(self._block).strip()
            if line:
                self._lines.append(line)
            self._block = []
        self._pop()

    def handle_data(self, data):
        if self._in_heading:
            self._heading += data
        elif not self._skip and not self._in_toc:
            self._block.append(data)


def html_to_chapters(page_html: str) -> list[Chapter]:
    """Split one rendered page into chapters; may be empty if unstructured."""
    p = _PageParser()
    p.feed(page_html)
    if p._title or p._lines:  # trailing content of the last chapter
        p.chapters.append(Chapter(title=p._title, text="\n".join(p._lines)))
    return p.chapters


def _parse_payload(resp: str) -> str:
    data = json.loads(resp)
    parse = data.get("parse")
    if not parse:
        raise FetchError(f"wikisource parse failed: {list(data.keys())}")
    return parse["text"]["*"]


class Wikisource(Source):
    """MediaWiki-based public-domain source (zh by default, en available)."""

    name: str = ""

    def __init__(self, lang: str = "zh"):
        self.lang = lang
        self.host = "zh.wikisource.org" if lang == "zh" else f"{lang}.wikisource.org"
        self.name = "wikisource" if lang == "zh" else f"wikisource-{lang}"
        self.label = "中文公版" if lang == "zh" else "英文公版"

    def search(self, query: str) -> list[Book]:
        return _search_json(fetch(search_url(self.host, query)), self.host, self.name)

    def fetch(self, book: Book, *, on_progress=None) -> FetchResult:
        title = book.id
        main_html = _parse_payload(fetch(parse_url(self.host, title)))
        toc = extract_toc_titles(main_html)
        chapters: list[Chapter] = []
        for ch in html_to_chapters(main_html):
            if ch.title or ch.text.strip():
                chapters.append(ch)
        for i, page_title in enumerate(toc):
            if on_progress and not on_progress(i, len(toc)):
                raise CancelledError()
            sub_html = _parse_payload(fetch(parse_url(self.host, page_title)))
            sub_chs = html_to_chapters(sub_html)
            if not sub_chs:
                continue
            if len(sub_chs) == 1 and not sub_chs[0].title:
                sub_chs[0].title = page_title
            elif len(sub_chs) > 1:
                # prefix ambiguous section headings with the page name
                for c in sub_chs:
                    c.title = f"{page_title}·{c.title}" if c.title else page_title
            chapters.extend(sub_chs)

        if not chapters:
            raise FetchError(f"no content parsed from {self.name} page {title!r}")
        content = "\n".join(c.text for c in chapters) + "\n"
        return FetchResult(
            source=self.name,
            id=title,
            title=book.title or title,
            chars=len(content),
            lines=len(content.splitlines()),
            format="txt",
            content=content,
            chapters=chapters,
        )
