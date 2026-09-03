"""Offline tests for the zero-dependency EPUB writer."""

import re
import zipfile
import xml.etree.ElementTree as ET

from bookfetch.model import Chapter
from bookfetch.util.epub import build_epub


def test_epub_structure(tmp_path):
    out = build_epub(
        "淵海子平",
        [Chapter("論天干", "甲木參天，脫胎要火。\n乙木花草。"), Chapter("論地支", "子丑合土。")],
        tmp_path / "book.epub",
    )
    assert out.exists()
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
        # mimetype first + stored; container/opf/ncx/chapters present
        assert names[0] == "mimetype"
        assert zf.getinfo("mimetype").compress_type == zipfile.ZIP_STORED
        assert zf.read("mimetype") == b"application/epub+zip"
        for required in ("META-INF/container.xml", "OEBPS/content.opf", "OEBPS/toc.ncx"):
            assert required in names
        assert "OEBPS/chap_0001.xhtml" in names
        assert "OEBPS/chap_0002.xhtml" in names

        # every xml file is well-formed
        for n in names:
            if n.endswith((".xml", ".opf", ".ncx", ".xhtml")):
                ET.fromstring(zf.read(n))

        # opf spine references chapters in order
        opf = zf.read("OEBPS/content.opf").decode("utf-8")
        assert opf.index('id="chap1"') < opf.index('id="chap2"')
        assert '<dc:title>淵海子平</dc:title>' in opf

        # ncx nav lists both titles
        ncx = zf.read("OEBPS/toc.ncx").decode("utf-8")
        assert "<text>論天干</text>" in ncx
        assert "<text>論地支</text>" in ncx

        # xhtml contains the body text and well-formed tags
        xh = zf.read("OEBPS/chap_0001.xhtml").decode("utf-8")
        assert "<h1>論天干</h1>" in xh
        assert "甲木參天，脫胎要火。" in xh
        assert len(re.findall(r"<p>", xh)) == 2


def test_epub_skips_duplicate_heading_paragraph(tmp_path):
    # the 《論X》 marker line stays in chapter text for lossless txt; epub
    # rendering must not repeat it right under the <h1>
    out = build_epub("書", [Chapter("論天干", "《論天干》\n甲木參天。")], tmp_path / "b.epub")
    with zipfile.ZipFile(out) as zf:
        xh = zf.read("OEBPS/chap_0001.xhtml").decode("utf-8")
        assert "<h1>論天干</h1>" in xh
        assert "<p>《論天干》</p>" not in xh
        assert "甲木參天。" in xh


def test_epub_escapes_xml_specials(tmp_path):
    out = build_epub("A&B <書>", [Chapter("章 & <節>", "5 < 6 && 7 > 3")], tmp_path / "b.epub")
    with zipfile.ZipFile(out) as zf:
        ET.fromstring(zf.read("OEBPS/content.opf"))
        xh = zf.read("OEBPS/chap_0001.xhtml").decode("utf-8")
        ET.fromstring(xh)  # well-formed despite specials
        assert "5 &lt; 6 &amp;&amp; 7 &gt; 3" in xh
