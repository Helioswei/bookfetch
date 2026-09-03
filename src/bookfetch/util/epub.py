"""Zero-dependency EPUB2 writer (zipfile + hand-built XHTML/OPF/NCX).

EPUB is a zip with a stored ``mimetype`` first entry plus container.xml /
content.opf / toc.ncx / XHTML chapters. Everything here is stdlib, so the
core zero-dependency promise holds for --format epub.

Rendering rules:
- each Chapter becomes one XHTML file with an <h1> title;
- a body paragraph identical to the chapter's own title line (the original
  《論X》 marker kept in the text by splitters) is skipped as a duplicate;
- XML 1.0-illegal control characters are stripped.
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

from ..model import Chapter

_XML_ILLEGAL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]")

XHTML_NS = 'xmlns="http://www.w3.org/1999/xhtml"'

_TEMPLATE_CHAPTER = """<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html {ns}>
<head><meta charset="utf-8"/><title>{title}</title></head>
<body>
<h1>{title}</h1>
{paras}
</body>
</html>
"""

_OPF = """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="BookId" version="2.0">
<metadata xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:opf="http://www.idpf.org/2007/opf">
<dc:identifier id="BookId">{book_id}</dc:identifier>
<dc:title>{title}</dc:title>
<dc:creator>{creator}</dc:creator>
<dc:language>zh</dc:language>
<meta name="generator" content="{creator}"/>
</metadata>
<manifest>
{item_entries}
<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
</manifest>
<spine toc="ncx">
{spine_entries}
</spine>
</package>
"""

_NCX = """<?xml version="1.0" encoding="utf-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
<head>
<meta name="dtb:uid" content="{book_id}"/>
<meta name="dtb:depth" content="1"/>
<meta name="dtb:totalPageCount" content="0"/>
<meta name="dtb:maxPageNumber" content="0"/>
</head>
<docTitle><text>{title}</text></docTitle>
<navMap>
{nav_points}
</navMap>
</ncx>
"""

_CONTAINER = """<?xml version="1.0" encoding="utf-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
<rootfiles>
<rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
</rootfiles>
</container>
"""

_MIMETYPE = b"application/epub+zip"


def _clean(s: str) -> str:
    return _XML_ILLEGAL.sub("", s)


def _chapter_xhtml(ch: Chapter, idx: int) -> str:
    title = _clean(ch.title) or f"第{idx}章"
    paras = []
    for line in ch.text.splitlines():
        s = _clean(line).strip()
        if not s:
            continue
        if s == _clean(ch.title) or s == f"《{_clean(ch.title)}》":
            continue  # duplicate of the <h1>
        paras.append(f"<p>{escape(s)}</p>")
    body = "\n".join(paras)
    return _TEMPLATE_CHAPTER.format(ns=XHTML_NS, title=escape(title), paras=body)


def build_epub(
    title: str,
    chapters: list[Chapter],
    out_path: str | Path,
    creator: str = "bookfetch",
    book_id: str = "",
) -> Path:
    """Write a valid EPUB2 file for chapters. Returns the output path."""
    out_path = Path(out_path)
    chapters = [c for c in chapters if c.text.strip()] or chapters[:1]
    book_id = book_id or f"bookfetch:{_clean(title)[:60]}"
    book_id = _clean(book_id)

    files: list[tuple[str, bytes, int]] = []
    item_entries: list[str] = []
    spine_entries: list[str] = []
    nav_points: list[str] = []

    for i, ch in enumerate(chapters, 1):
        fname = f"chap_{i:04d}.xhtml"
        files.append((f"OEBPS/{fname}", _chapter_xhtml(ch, i).encode("utf-8"), zipfile.ZIP_DEFLATED))
        item_entries.append(
            f'<item id="chap{i}" href="{fname}" media-type="application/xhtml+xml"/>'
        )
        spine_entries.append(f'<itemref idref="chap{i}"/>')
        nav_points.append(
            f'<navPoint id="np{i}" playOrder="{i}">'
            f'<navLabel><text>{escape(_clean(ch.title) or f"第{i}章")}</text></navLabel>'
            f'<content src="{fname}"/></navPoint>'
        )

    opf = _OPF.format(
        book_id=escape(book_id),
        title=escape(_clean(title)),
        creator=escape(creator),
        item_entries="\n".join(item_entries),
        spine_entries="\n".join(spine_entries),
    )
    ncx = _NCX.format(
        book_id=escape(book_id),
        title=escape(_clean(title)),
        nav_points="\n".join(nav_points),
    )
    files.append(("OEBPS/content.opf", opf.encode("utf-8"), zipfile.ZIP_DEFLATED))
    files.append(("OEBPS/toc.ncx", ncx.encode("utf-8"), zipfile.ZIP_DEFLATED))
    files.append(("META-INF/container.xml", _CONTAINER.encode("utf-8"), zipfile.ZIP_DEFLATED))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_path, "w") as zf:
        # mimetype must be first and uncompressed per the EPUB spec
        zf.writestr(zipfile.ZipInfo("mimetype"), _MIMETYPE, compress_type=zipfile.ZIP_STORED)
        for name, data, ctype in files:
            zi = zipfile.ZipInfo(name)
            zi.date_time = (1980, 1, 1, 0, 0, 0)  # deterministic builds
            zf.writestr(zi, data, compress_type=ctype)
    return out_path
