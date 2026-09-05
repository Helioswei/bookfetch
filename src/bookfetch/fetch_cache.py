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
