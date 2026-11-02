"""N1 fetch cache — yt-dlp --download-archive style dedup for bookfetch.

Keyed by (source, id): once a book's *fetched content* is cached, a later
`get` of the same edition skips the network entirely and re-renders locally
(txt/epub both served from cache — format conversion is local anyway, so
"downloaded once" means any format is free afterwards).

Storage layout under $BOOKFETCH_CACHE/fetched/ (default
~/.cache/bookfetch/fetched/):

    <sha1(source|id)>.json   — FetchResult content + chapters + meta
    <sha1(source|id)>.bin    — raw bytes for binary sources (libgen etc.)

Corrupt/absent files simply count as "not cached" → next get re-fetches.
`--force` on the CLI overwrites the cache entry.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

from .model import Chapter, FetchResult

_CACHE_SUBDIR = "fetched"
_SCHEMA = 1


def _cache_dir() -> Path:
    base = os.environ.get("BOOKFETCH_CACHE") or Path.home() / ".cache" / "bookfetch"
    d = Path(base) / _CACHE_SUBDIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def partial_dir() -> Path:
    """Scratch area for interrupted single-file downloads (B4 resume).

    fetch_bytes_resumable keeps a ``.part`` file here between attempts;
    a completed download is stored as the real cache entry and the
    .part is removed.
    """
    base = os.environ.get("BOOKFETCH_CACHE") or Path.home() / ".cache" / "bookfetch"
    d = Path(base) / "partial"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _key(source: str, id_: str) -> str:
    return hashlib.sha1(f"{source}|{id_}".encode("utf-8")).hexdigest()[:24]


def cache_path(source: str, id_: str) -> Path:
    """Public handle for the cache entry (tests, diagnostics)."""
    return _cache_dir() / f"{_key(source, id_)}.json"


def load(source: str, id_: str) -> FetchResult | None:
    """Cached FetchResult for (source, id), or None (miss / corrupt)."""
    p = _cache_dir() / f"{_key(source, id_)}.json"
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        if d.get("schema") != _SCHEMA or d.get("source") != source or d.get("id") != id_:
            return None
        chapters = None
        if d.get("chapters"):
            chapters = [Chapter(title=c.get("title", ""), text=c.get("text", "")) for c in d["chapters"]]
        raw = None
        if d.get("has_raw"):
            raw = p.with_suffix(".bin").read_bytes()
        return FetchResult(
            source=source,
            id=id_,
            title=d.get("title", ""),
            chars=d.get("chars", 0),
            lines=d.get("lines", 0),
            format=d.get("format", "txt"),
            content=d.get("content", ""),
            chapters=chapters,
            raw=raw,
        )
    except Exception:
        return None


def save(source: str, id_: str, fr: FetchResult) -> Path:
    """Persist a FetchResult; binary sources keep their raw bytes in a .bin."""
    p = _cache_dir() / f"{_key(source, id_)}.json"
    payload = {
        "schema": _SCHEMA,
        "source": source,
        "id": id_,
        "title": fr.title,
        "chars": fr.chars,
        "lines": fr.lines,
        "format": fr.format,
        "content": fr.content,
        "chapters": [{"title": c.title, "text": c.text} for c in fr.chapters]
        if fr.chapters
        else None,
        "has_raw": fr.raw is not None,
        "saved_ts": time.time(),
    }
    if fr.raw is not None:
        p.with_suffix(".bin").write_bytes(fr.raw)
    p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return p


def clear(source: str, id_: str) -> None:
    """Remove a cache entry (--force refreshes by overwriting; this is for tests)."""
    p = _cache_dir() / f"{_key(source, id_)}.json"
    p.unlink(missing_ok=True)
    p.with_suffix(".bin").unlink(missing_ok=True)


# ---------------------------------------------------------- B4 checkpoint ---
# 逐章断点续传 / 边下边读的唯一实现（桌面 n2core 下载任务与 CLI `get` 共用，
# 2026-11 起 CLI 与桌面行为一致）。落盘布局（与历史桌面版完全兼容）：
#
#     <dir>/<书名>.txt.part        已下章节，=== 标题 === 分隔增量追加（边下边读）
#     <dir>/<书名>.txt.part.meta   续传点 {"source","id","title","fmt","index"}
#
# <dir> = 桌面书库目录 / CLI 的 --out 目录。index = 最后一个成功章的 toc 索引，
# 续传从 index+1 开始；源 fetch 通过 on_checkpoint(index, Chapter) 回调推进。


def partial_fname(book) -> str:
    """断点文件基名 —— 与正式渲染同名规则（sanitize 书名），无书名退回 source-id。"""
    from .util import sanitize_filename

    title = (book.title or "").strip()
    # sanitize_filename 对空串返回 "untitled"（永不为空）→ 原 `or` 兜底失效，
    # 无书名的多本书会共用 untitled.txt.part、互相清掉断点。无书名直接用 source-id。
    return sanitize_filename(title) if title else f"{book.source}-{book.id}"


class Checkpoint:
    """One book's chapter-level checkpoint (.part + .part.meta) in ``directory``."""

    def __init__(self, directory: Path, book, fmt: str = "txt"):
        self.book = book
        self.fmt = fmt
        fname = partial_fname(book)
        self.part = Path(directory) / f"{fname}.txt.part"
        self.meta = Path(directory) / f"{fname}.txt.part.meta"

    def resume_index(self) -> int:
        """续传起点（toc 索引）；0 = 从头。

        仅当 meta 有效（source 匹配 + 整数索引 + id 匹配）且 .part 在位才 >0；
        .part 不在 → meta 作废；meta 损坏/孤儿/版本不匹配 → 清掉，防误续。
        """
        book = self.book
        if not self.part.exists():
            self.meta.unlink(missing_ok=True)
            return 0
        if self.meta.exists():
            try:
                m = json.loads(self.meta.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                m = None
            m_id = m.get("id") if isinstance(m, dict) else None
            if (
                isinstance(m, dict)
                and m.get("source") == book.source
                and isinstance(m.get("index"), int)
                # meta 带 id 时精确绑定任务（防同源同名不同版本误续——biquge 转载版
                # 同名多条目实测）；旧 meta 无 id 退化 source+书名 匹配（存量兼容）
                and (m_id is None or m_id == book.id)
            ):
                return int(m["index"]) + 1
            self.meta.unlink(missing_ok=True)
        return 0

    def prepare(self) -> int:
        """开始下载前调用：返回 resume_from；从头下载时清掉残留 .part。

        从头下载但 .part 有残留（meta 损坏/版本不匹配被清）必须先清空，
        否则 on_checkpoint 会把新内容 append 进旧半成品 → 混版/章节重复。
        """
        resume_from = self.resume_index()
        if resume_from == 0 and self.part.exists():
            self.clear()
        return resume_from

    def write(self, index: int, chapter: Chapter) -> None:
        """on_checkpoint 实现：更新 meta 续传点 + 增量追加 .part。"""
        self.part.parent.mkdir(parents=True, exist_ok=True)
        book = self.book
        self.meta.write_text(
            json.dumps(
                {
                    "source": book.source,
                    "id": book.id,
                    "title": book.title,
                    "fmt": self.fmt,
                    "index": index,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        head = f"=== {chapter.title} ===\n{chapter.text}"
        with self.part.open("a", encoding="utf-8") as fh:
            if self.part.stat().st_size == 0:
                fh.write(head)
            else:
                fh.write("\n\n" + head)

    def merge(self, fr: FetchResult, resume_from: int) -> FetchResult:
        """续传完成：.part 已含 prior + 本次新增（全程 append）→ 还原全量章节。"""
        if resume_from > 0 and self.part.exists():
            from .util.splitters import split_rendered

            prior = split_rendered(self.part.read_text(encoding="utf-8"))
            if prior:
                fr.chapters = prior
                fr.content = "\n\n".join(c.text for c in prior)
                fr.chars = len(fr.content)
        return fr

    def clear(self) -> None:
        """完成（正式书已落盘）或从头重下：清断点残留。"""
        self.part.unlink(missing_ok=True)
        self.meta.unlink(missing_ok=True)
