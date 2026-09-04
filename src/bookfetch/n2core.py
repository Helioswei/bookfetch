"""N2 backend core — shared by `bookfetch serve` (HTTP) and the pywebview app.

All functions are plain dict/JSON-able Python so the same calls serve both
transport layers. State lives in:

- library dir:  $BOOKFETCH_LIBRARY or ~/Books   (the "书架", D2 decision)
- fetch cache:  ~/.cache/bookfetch/fetched/     (N1, reuse)
- progress:     ~/.config/bookfetch/progress.json

Downloads run on background threads; the UI polls task_status(id).
Every shelf-path parameter is a *relative* path inside the library dir, so a
client can never touch files outside the library.
"""

from __future__ import annotations

import json
import os
import re
import threading
import zipfile
from argparse import Namespace
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import fetch_cache
from .cli import _ensure_chapters, _render_get
from .model import Book, Chapter, FetchResult
from .sources import get_source, source_names
from .util.epub import build_epub

_CFG_DIR = Path(os.environ.get("BOOKFETCH_CONFIG", "~/.config/bookfetch")).expanduser()
_PROGRESS = _CFG_DIR / "progress.json"
_LOCK = threading.Lock()
_TASKS: dict[str, _Job] = {}
_TASK_ID = 0


def library_dir() -> Path:
    p = Path(os.environ.get("BOOKFETCH_LIBRARY", "~/Books")).expanduser()
    p.mkdir(parents=True, exist_ok=True)
    return p


def library_rel(path: Path) -> str:
    """Absolute library path -> library-relative string ('' if outside)."""
    try:
        return str(path.resolve().relative_to(library_dir().resolve()))
    except ValueError:
        return ""


def _resolve(rel: str) -> Path:
    """Library-relative string -> safe absolute path (rejects escapes)."""
    root = library_dir().resolve()
    p = (root / rel).resolve()
    if p != root and root not in p.parents:
        raise ValueError("path escapes library dir")
    return p


# ---------------------------------------------------------------- search ---

def search(query: str, sources: list[str] | None = None, limit: int = 30) -> dict:
    """Search across sources in parallel (GUI: a slow/dead source must not
    stall the whole grid; CLI keeps its own serial search_all)."""
    names = sources or source_names()
    out: list[dict] = []
    errors: dict[str, str] = {}

    def _one(n: str) -> None:
        src = get_source(n)
        if src is None:
            errors[n] = "unknown source"
            return
        try:
            for b in src.search(query):
                out.append(b.to_dict())
        except Exception as e:  # noqa: BLE001 — per-source failures are reported, not fatal
            errors[n] = f"{type(e).__name__}: {e}"

    threads = [threading.Thread(target=_one, args=(n,), daemon=True) for n in names]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)  # hard cap; a hung source is reported as an error
    # join() returning early leaves stragglers; mark them if still alive
    for n, t in zip(names, threads):
        if t.is_alive() and n not in errors:
            errors[n] = "TimeoutError: source did not respond in 20s"
    out.sort(key=lambda d: d.get("title", ""))
    return {
        "query": query,
        "count": len(out),
        "errors": errors,
        "results": out[:limit],
        "sources": names,
    }


# --------------------------------------------------------------- download ---

@dataclass
class _Job:
    id: str
    source: str
    book_id: str
    title: str
    fmt: str
    status: str = "running"   # running | done | error
    out_rel: str = ""
    message: str = ""


def _run_job(job: _Job) -> None:
    try:
        src = get_source(job.source)
        if src is None:
            raise ValueError(f"unknown source {job.source!r}")
        book = Book(source=job.source, id=job.book_id, title=job.title)
        fr = fetch_cache.load(job.source, job.book_id)
        if fr is None:
            fr = src.fetch(book)
            fetch_cache.save(job.source, job.book_id, fr)
        if fr.raw is not None:
            # binary passthrough: _render_get saves the original .epub/.pdf
            # as-is when args.format == "txt" (the CLI default convention)
            fmt = "txt"
            simp = split = False
        else:
            fmt = job.fmt if job.fmt in ("txt", "epub") else "txt"
            simp = split = False
        ns = Namespace(out=str(library_dir()), format=fmt, simplify=simp, split=split)
        fr = _render_get(src, fr, ns)
        job.out_rel = library_rel(Path(fr.out_path))
        job.status = "done"
        job.message = f"{fr.chars:,} chars · {len(_ensure_chapters(fr))} chapters"
    except Exception as e:  # surface any failure to the UI
        job.status = "error"
        job.message = f"{type(e).__name__}: {e}"


def download(source: str, id: str, title: str = "", fmt: str = "txt") -> dict:
    global _TASK_ID
    with _LOCK:
        _TASK_ID += 1
        job = _Job(id=f"t{_TASK_ID}", source=source, book_id=id, title=title, fmt=fmt)
        _TASKS[job.id] = job  # same object the worker thread updates
        threading.Thread(target=_run_job, args=(job,), daemon=True).start()
        return {"task_id": job.id}


def task_status(task_id: str) -> dict:
    with _LOCK:
        job = _TASKS.get(task_id)
    if job is None:
        return {"task_id": task_id, "status": "unknown"}
    return {
        "task_id": task_id,
        "status": job.status,
        "message": job.message,
        "out_rel": job.out_rel,
    }


# ------------------------------------------------------------------ shelf ---

_TXT_EXT = (".txt",)
_EPUB_EXT = (".epub",)


def shelf() -> dict:
    """Scan the library dir for books: [{rel, title, format, size_kb}]."""
    root = library_dir()
    books = []
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.name.startswith("."):
            continue
        if p.suffix.lower() in _TXT_EXT + _EPUB_EXT:
            rel = library_rel(p)
            books.append(
                {
                    "rel": rel,
                    "title": p.stem,
                    "format": p.suffix.lower().lstrip("."),
                    "size_kb": max(1, p.stat().st_size // 1024),
                }
            )
    return {"library": str(root), "books": books}


# ------------------------------------------------------------------ read ---

_TAG_RE = re.compile(r"<[^>]+>")
_EPUB_SPINE: dict[str, list[str]] = {}  # rel -> ordered xhtml member names


def _epub_chapters(path: Path) -> list[Chapter]:
    """Generic epub -> [Chapter] (any producer, spine order when present)."""
    key = str(path)
    names = _EPUB_SPINE.get(key)
    if names is None:
        with zipfile.ZipFile(path) as z:
            names = [n for n in z.namelist() if n.lower().endswith((".xhtml", ".html"))]
            try:
                opf = [n for n in z.namelist() if n.endswith(".opf")][0]
                xml = z.read(opf).decode("utf-8", "replace")
                order = re.findall(r'idref="([^"]+)"', xml)
                if order:
                    idmap = dict(
                        re.findall(r'<item\b[^>]*\bid="([^"]+)"[^>]*href="([^"]+)"', xml)
                    ) or dict(
                        re.findall(r'<item\b[^>]*href="([^"]+)"[^>]*\bid="([^"]+)"', xml)
                    )
                    hrefs = [idmap.get(r, r) for r in order]
                    # hrefs are relative to the OPF dir
                    base = str(Path(opf).parent)
                    full = []
                    for h in hrefs:
                        cand = f"{base}/{h}".strip("/")
                        if cand in names:
                            full.append(cand)
                        elif h in names:
                            full.append(h)
                    if full:
                        names = full
            except Exception:
                names = sorted(names)
        _EPUB_SPINE[key] = names
    chapters: list[Chapter] = []
    with zipfile.ZipFile(path) as z:
        for n in names:
            raw = z.read(n).decode("utf-8", "replace")
            body = re.search(r"<body[^>]*>(.*?)</body>", raw, re.S)
            text = _TAG_RE.sub("", body.group(1) if body else raw)
            text = re.sub(r"\n{3,}", "\n\n", text.replace("\r", "")).strip()
            if not text:
                continue
            tm = re.search(r"<h[1-3][^>]*>(.*?)</h[1-3]>", raw, re.S)
            title = re.sub(r"<[^>]+>", "", tm.group(1)).strip() if tm else f"{n}"
            # drop the heading line from the body text (the reader renders the
            # title itself; producers keep the heading inside the chapter)
            if text.startswith(title):
                text = text[len(title):].lstrip("\n")
            chapters.append(Chapter(title=title, text=text))
    return chapters


@dataclass
class _OpenBook:
    chapters: list[Chapter]
    format: str


_OPEN_CACHE: dict[str, _OpenBook] = {}
_OPEN_CACHE_META: dict[str, tuple[int, int]] = {}


def _open(path: Path) -> _OpenBook:
    """Read + split a book file once, cached by (rel, mtime, size)."""
    st = path.stat()
    key = str(path)
    meta = _OPEN_CACHE_META.get(key)
    if meta == (st.st_mtime_ns, st.st_size) and key in _OPEN_CACHE:
        return _OPEN_CACHE[key]
    if path.suffix.lower() == ".epub":
        ob = _OpenBook(chapters=_epub_chapters(path), format="epub")
    else:
        text = path.read_text(encoding="utf-8", errors="replace")
        chapters = _ensure_chapters(
            FetchResult(source="shelf", id=key, title=path.stem, content=text)
        )
        ob = _OpenBook(chapters=chapters, format="txt")
    _OPEN_CACHE[key] = ob
    _OPEN_CACHE_META[key] = (st.st_mtime_ns, st.st_size)
    return ob


def open_book(rel: str) -> dict:
    """Chapter index for the reader: {title, format, chapters:[{i,title}]}."""
    p = _resolve(rel)
    ob = _open(p)
    return {
        "rel": rel,
        "title": p.stem,
        "format": ob.format,
        "chapters": [{"i": i, "title": c.title or f"第{i+1}部分"} for i, c in enumerate(ob.chapters)],
    }


def chapter(rel: str, idx: int) -> dict:
    ob = _open(_resolve(rel))
    if idx < 0 or idx >= len(ob.chapters):
        raise ValueError(f"chapter index out of range: {idx}")
    c = ob.chapters[idx]
    return {"rel": rel, "i": idx, "title": c.title, "text": c.text}


def _load_progress() -> dict:
    if not _PROGRESS.exists():
        return {}
    try:
        return json.loads(_PROGRESS.read_text(encoding="utf-8"))
    except Exception:
        return {}


def progress_get(rel: str) -> dict:
    return {"rel": rel, "progress": _load_progress().get(rel, {})}


def progress_set(rel: str, chapter_idx: int, pct: int = 0) -> dict:
    """Save reading position: chapter index + pct (0..1000 scroll fraction)."""
    with _LOCK:
        d = _load_progress()
        d[rel] = {"chapter": int(chapter_idx), "pct": int(pct)}
        _PROGRESS.parent.mkdir(parents=True, exist_ok=True)
        _PROGRESS.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"ok": True}


# ---------------------------------------------------------------- dispatch ---

def api_call(name: str, params: dict) -> dict:
    """Named dispatch so HTTP and pywebview share one entry point."""
    if name == "search":
        return search(params.get("query", ""), params.get("sources"))
    if name == "download":
        return download(params.get("source", ""), params.get("id", ""), params.get("title", ""), params.get("fmt", "txt"))
    if name == "task_status":
        return task_status(params.get("task_id", ""))
    if name == "shelf":
        return shelf()
    if name == "open_book":
        return open_book(params.get("rel", ""))
    if name == "chapter":
        return chapter(params.get("rel", ""), int(params.get("idx", 0)))
    if name == "progress_get":
        return progress_get(params.get("rel", ""))
    if name == "progress_set":
        return progress_set(params.get("rel", ""), int(params.get("chapter", 0)), int(params.get("pct", 0)))
    if name == "library":
        return {"library": str(library_dir())}
    if name == "sources":
        return {"sources": source_names()}
    raise ValueError(f"unknown api: {name}")


BUILTIN_API = {
    "search", "download", "task_status", "shelf", "open_book",
    "chapter", "progress_get", "progress_set", "library", "sources",
}
