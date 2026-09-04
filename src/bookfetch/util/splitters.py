"""Chapter splitting for Chinese classics text.

Text sources (a raw github txt, a ctext page) have no explicit chapter
structure. Real public-domain classics mark sections with standalone title
lines — most commonly 《書名》 wrappers (《論天干》《卷之三》), numbered 卷/章
headers, bare 序/跋/凡例 markers, and Chinese-numeral headers (一、天道).
``split_headings`` finds those lines and returns ordered Chapter slices of
the input; the original text is fully preserved (heading lines stay in the
body; renderers skip the duplicate).

``split_rendered`` inverts the render step: bookfetch-written txt files carry
``=== 标题 ===`` separator lines, so re-opening them restores exact chapters.

Both return [] when no structure is found, so callers fall back to a single
whole-text chapter — splitting must never destroy content.
"""

from __future__ import annotations

import re

from ..model import Chapter

# 1) 《論天干》-style standalone title lines (the dominant marker in classics)
_ANGLE_RE = re.compile(r"^《([^《》]{1,60})》$")
# 2) numbered volume/chapter headers: 卷一 / 第3卷 / 卷之十二 / 第廿四節
_NUM_RE = re.compile(
    r"^(?:第\s*[0-9一二三四五六七八九十百零〇]+\s*[卷章節节回篇部集]|"
    r"[卷章節节回篇部集]\s*(?:之\s*)?(?:[0-9一二三四五六七八九十百]+))$"
)
# 3) bare structural markers (序/跋/凡例/...) as standalone short lines
_BARE = {
    "卷首", "序", "自序", "原序", "跋", "後記", "后记", "凡例",
    "目錄", "目录", "附錄", "附录", "補遺", "补遗", "題記", "题记",
}
# 4) Chinese-numeral section headers: 一、天道 / 三、十二地支 / 七、论生克 ——
#    standalone lines starting with 一~百 + 、 and NO sentence punctuation in the
#    title (real sentences end with 。；：etc.). Title cap 16 chars keeps prose
#    like 「二、寅中火土长生…」 (long, punctuated) from matching.
_SEQ_RE = re.compile(r"^[一二三四五六七八九十百〇零]{1,3}[、.．]\S[^，。；：！？!?“”\"'（）()]{0,15}$")
_SENT_PUNCT = set("，。；：、！？!?；：,.;:")  # a real sentence never lacks these
# 5) bookfetch's own rendered marker: === 章节标题 ===
_MARK_RE = re.compile(r"^===\s*(.+?)\s*===$")


def _heading(line: str) -> str | None:
    s = line.strip()
    if not s or len(s) > 80:
        return None
    m = _ANGLE_RE.match(s)
    if m:
        return m.group(1).strip()
    if _NUM_RE.match(s):
        return s
    if _SEQ_RE.match(s):
        return s
    if s in _BARE:
        return s
    return None


def split_rendered(text: str) -> list[Chapter]:
    """Re-split a bookfetch-rendered txt (=== 标题 === separators).

    Exact inverse of the txt renderer: the marker line opens a chapter and is
    dropped from its text (render writes ``=== 标题 ===\\n{text}``, so the
    reader must not show the marker line as body content).
    Returns [] when no marker line exists (plain text → whole-text fallback).
    """
    lines = text.splitlines()
    marks = [i for i, ln in enumerate(lines) if _MARK_RE.match(ln)]
    if not marks:
        return []
    chapters: list[Chapter] = []
    for k, i in enumerate(marks):
        m = _MARK_RE.match(lines[i])
        assert m  # marks 由 _MARK_RE 命中而来
        title = m.group(1).strip()
        end = marks[k + 1] if k + 1 < len(marks) else len(lines)
        chapters.append(Chapter(title=title, text="\n".join(lines[i + 1:end]).strip()))
    return chapters


def split_headings(lines: list[str]) -> list[Chapter]:
    """Slice lines into chapters at standalone title lines.

    A heading line opens its chapter (it stays in the chapter text so the
    concatenation reproduces the input exactly); any leading lines before the
    first heading are folded into chapter one. Empty result = no structure.
    """
    heads: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        t = _heading(line)
        if t is not None:
            heads.append((i, t))
    if not heads:
        return []
    chapters: list[Chapter] = []
    for k, (idx, title) in enumerate(heads):
        end = heads[k + 1][0] if k + 1 < len(heads) else len(lines)
        text = "\n".join(lines[idx:end])
        chapters.append(Chapter(title=title, text=text))
    # fold preamble (lines before the first heading) into chapter one
    first = heads[0][0]
    if first > 0:
        chapters[0].text = "\n".join(lines[:first]) + "\n" + chapters[0].text
    return chapters
