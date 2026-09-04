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
import logging
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
from .sources import get_source, source_catalog, source_names
from .util import CancelledError, FetchError, HumanVerificationError
from .util.epub import build_epub
from .util.simplify import to_simplified, to_traditional
from .util.splitters import split_rendered

logger = logging.getLogger("bookfetch")

_CFG_DIR = Path(os.environ.get("BOOKFETCH_CONFIG", "~/.config/bookfetch")).expanduser()
_PROGRESS = _CFG_DIR / "progress.json"
_LOCK = threading.Lock()
_TASKS: dict[str, _Job] = {}
_TASK_ID = 0


def config_dir() -> Path:
    """Config dir (progress.json, bookfetch.log live here)."""
    return _CFG_DIR


def load_settings() -> dict:
    """settings.json in the config dir; missing/corrupt -> {}."""
    try:
        return json.loads((config_dir() / "settings.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_settings(s: dict) -> None:
    d = config_dir()
    d.mkdir(parents=True, exist_ok=True)
    (d / "settings.json").write_text(
        json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def settings_get() -> dict:
    """Proxy config for the settings panel (D1 addendum)."""
    p = load_settings().get("proxy") or {}
    return {"proxy": {"mode": p.get("mode", "system"), "url": p.get("url", "")}}


def settings_set(proxy: dict) -> dict:
    """Persist proxy settings and apply them to the next request."""
    mode = proxy.get("mode", "system")
    url = str(proxy.get("url", "")).strip()
    if mode not in ("system", "manual", "none"):
        raise ValueError(f"invalid proxy mode: {mode!r}")
    if mode == "manual" and not url:
        raise ValueError("manual proxy mode requires a proxy url")
    s = load_settings()
    s["proxy"] = {"mode": mode, "url": url}
    save_settings(s)
    apply_proxy()
    return {"ok": True, "proxy": {"mode": mode, "url": url}}


def apply_proxy() -> None:
    """Push the persisted proxy settings into util (startup + after save)."""
    from .util import set_proxy

    p = load_settings().get("proxy") or {}
    mode = p.get("mode", "system")
    if mode == "manual" and p.get("url"):
        set_proxy("manual", str(p["url"]))
    elif mode == "none":
        set_proxy("none")
    else:
        set_proxy("system")


def friendly(exc: BaseException) -> str:
    """Map an internal exception to a short user-facing Chinese message.

    Full technical detail goes to the log file (logging_setup) — end users and
    the search-meta line get this friendly line instead (D1 decision 3).
    """
    if isinstance(exc, HumanVerificationError):
        return "源站要求人机验证（反爬拦截）——当前网络出口被源站标记；换个网络或代理节点后重试"
    if isinstance(exc, FetchError):
        return "网络请求失败（已自动重试仍不通）——请检查网络或稍后重试"
    if isinstance(exc, (UnicodeEncodeError, UnicodeDecodeError, ValueError, json.JSONDecodeError)):
        return f"内容解析异常——该源返回了无法处理的数据，可能已改版（{type(exc).__name__}）"
    return f"{type(exc).__name__}: {exc}"


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
            logger.warning("search source %s failed: %s", n, e, exc_info=True)
            errors[n] = friendly(e)

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
    status: str = "running"   # running | done | error | cancelled
    out_rel: str = ""
    message: str = ""
    cancel: bool = False
    done: int = 0     # progress: chapters fetched so far (multi-chapter sources)
    total: int = 0


def _run_job(job: _Job) -> None:
    try:
        src = get_source(job.source)
        if src is None:
            raise ValueError(f"unknown source {job.source!r}")
        book = Book(source=job.source, id=job.book_id, title=job.title)
        fr = fetch_cache.load(job.source, job.book_id)
        if fr is None:
            def on_progress(done: int, total: int) -> bool:
                job.done, job.total = done, total
                return not job.cancel

            job.message = "抓取中…"
            fr = src.fetch(book, on_progress=on_progress)
            fetch_cache.save(job.source, job.book_id, fr)
        if fr.raw is not None:
            # binary passthrough: _render_get saves the original .epub/.pdf
            # as-is when args.format == "txt" (the CLI default convention)
            fmt = "txt"
            simp = split = False
        else:
            fmt = job.fmt if job.fmt in ("txt", "epub") else "txt"
            simp = split = False
        job.message = "整理成书…"
        ns = Namespace(out=str(library_dir()), format=fmt, simplify=simp, split=split)
        fr = _render_get(src, fr, ns)
        job.out_rel = library_rel(Path(fr.out_path))
        job.status = "done"
        job.message = f"{fr.chars:,} chars · {len(_ensure_chapters(fr))} chapters"
    except CancelledError:
        job.status = "cancelled"
        job.message = "已取消"
        logger.info("download job %s cancelled by user", job.id)
    except Exception as e:  # surface any failure to the UI
        job.status = "error"
        logger.exception("download job %s (%s %s) failed", job.id, job.source, job.book_id)
        job.message = friendly(e)


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
    out: dict[str, object] = {
        "task_id": task_id,
        "status": job.status,
        "message": job.message,
        "out_rel": job.out_rel,
        "fmt": job.fmt,
    }
    if job.status == "running" and job.total:
        out["progress"] = {"done": job.done, "total": job.total}
    return out


def cancel(task_id: str) -> dict:
    """Ask a running job to stop at the next chapter boundary (cooperative)."""
    with _LOCK:
        job = _TASKS.get(task_id)
    if job is None:
        return {"task_id": task_id, "ok": False, "message": "任务不存在"}
    if job.status != "running":
        zh = {"done": "已完成", "error": "失败", "cancelled": "已取消"}.get(job.status, job.status)
        return {"task_id": task_id, "ok": False, "message": f"任务已{zh}"}
    job.cancel = True
    return {"task_id": task_id, "ok": True, "message": "取消中…"}


# ------------------------------------------------------------------ shelf ---

_TXT_EXT = (".txt",)
_EPUB_EXT = (".epub",)


def shelf() -> dict:
    """Scan the library dir for books, each with reading progress:
    [{rel, title, format, size_kb, progress:{chapter,pct}|None}]."""
    root = library_dir()
    books = []
    prog = _load_progress()
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.name.startswith("."):
            continue
        if p.suffix.lower() in _TXT_EXT + _EPUB_EXT:
            rel = library_rel(p)
            try:
                nch = len(_open(p).chapters)
            except Exception:
                nch = None  # 坏文件：不给章数，前端回退"第 N 章"不带 %
            books.append(
                {
                    "rel": rel,
                    "title": p.stem,
                    "format": p.suffix.lower().lstrip("."),
                    "size_kb": max(1, p.stat().st_size // 1024),
                    "chapters": nch,
                    "progress": prog.get(rel) or None,
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
    base: str | None = None  # 'trad'|'simp' 文本基准简繁（OpenCC 探测）；无 OpenCC → None


_OPEN_CACHE: dict[str, _OpenBook] = {}
_OPEN_CACHE_META: dict[str, tuple[int, int]] = {}


def _chg(a: str, b: str) -> int:
    """粗略字符差异数（含长度差）——基准检测只需比较 t2s/s2t 谁改得多。"""
    return abs(len(a) - len(b)) + sum(1 for x, y in zip(a, b) if x != y)


def _detect_base(ob: _OpenBook) -> str | None:
    """Detect the text's baseline script: 'simp'/'trad' by comparing how many
    chars each direction changes. 双向投票：简体文本 s2t 改变量 ≫ t2s，
    繁体反之。单向 t2s 探测会把简体周易误判为繁体——"乾"(qián) 是合法简体，
    却会被 t2s 词典转"干"，造成 t2s 改动数虚高（2026-09-05 实测反馈：
    点简/繁只有"乾→干"，正是 base 判错 + 乾 误转叠加）。
    None when OpenCC is unavailable (optional extra missing)."""
    try:
        for c in ob.chapters[:2]:
            probe = (c.text or "")[:800]
            if probe.strip():
                st = _chg(probe, to_simplified(probe))  # 繁→简 改动
                ts = _chg(probe, to_traditional(probe))  # 简→繁 改动
                return "simp" if ts >= st else "trad"
    except ValueError:
        pass
    return None


def _conv(ob: _OpenBook, text: str) -> str:
    """Convert away from the book's baseline script: 繁书→简 (t2s) / 简书→繁 (s2t)."""
    return to_traditional(text) if ob.base == "simp" else to_simplified(text)


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
        chapters = split_rendered(text)  # bookfetch 自产 === 分隔 txt 精确还原
        if not chapters:
            chapters = _ensure_chapters(
                FetchResult(source="shelf", id=key, title=path.stem, content=text)
            )
        ob = _OpenBook(chapters=chapters, format="txt")
    ob.base = _detect_base(ob)
    _OPEN_CACHE[key] = ob
    _OPEN_CACHE_META[key] = (st.st_mtime_ns, st.st_size)
    return ob


def open_book(rel: str, simp: bool = False) -> dict:
    """Chapter index for the reader: {title, format, chapters:[{i,title}], base}.

    simp=True 把目录标题转成与基准相反的语言（繁书→简 t2s / 简书→繁 s2t），
    正文由 chapter API 转。base 供前端决定切换按钮初始态。
    """
    p = _resolve(rel)
    ob = _open(p)
    titles = [c.title or f"第{i+1}部分" for i, c in enumerate(ob.chapters)]
    if simp:
        titles = [_conv(ob, t) for t in titles]
    return {
        "rel": rel,
        "title": p.stem,
        "format": ob.format,
        "base": ob.base,
        "chapters": [{"i": i, "title": t} for i, t in enumerate(titles)],
    }


def chapter(rel: str, idx: int, simp: bool = False) -> dict:
    ob = _open(_resolve(rel))
    if idx < 0 or idx >= len(ob.chapters):
        raise ValueError(f"chapter index out of range: {idx}")
    c = ob.chapters[idx]
    if simp:
        return {"rel": rel, "i": idx, "title": _conv(ob, c.title or ""), "text": _conv(ob, c.text)}
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
    if name == "cancel":
        return cancel(params.get("task_id", ""))
    if name == "shelf":
        return shelf()
    if name == "open_book":
        return open_book(params.get("rel", ""), bool(params.get("simp", False)))
    if name == "chapter":
        return chapter(params.get("rel", ""), int(params.get("idx", 0)), bool(params.get("simp", False)))
    if name == "progress_get":
        return progress_get(params.get("rel", ""))
    if name == "progress_set":
        return progress_set(params.get("rel", ""), int(params.get("chapter", 0)), int(params.get("pct", 0)))
    if name == "library":
        return {"library": str(library_dir())}
    if name == "sources":
        return {"sources": source_catalog()}
    if name == "settings_get":
        return settings_get()
    if name == "settings_set":
        return settings_set(params.get("proxy") or {})
    raise ValueError(f"unknown api: {name}")


BUILTIN_API = {
    "search", "download", "cancel", "task_status", "shelf", "open_book",
    "chapter", "progress_get", "progress_set", "library", "sources",
    "settings_get", "settings_set",
}
