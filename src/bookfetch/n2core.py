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

import hashlib
import json
import logging
import os
import re
import subprocess
import sys
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
from .util import CancelledError, FetchError, HumanVerificationError, sanitize_filename
from .util.epub import build_epub
from .util.simplify import to_simplified, to_traditional
from .util.splitters import split_rendered
from .util.translator import (
    split_reader_paras,
    trans_direction,
    translate_available,
    translate_paragraphs,
)

logger = logging.getLogger("bookfetch")

_CFG_DIR = Path(os.environ.get("BOOKFETCH_CONFIG", "~/.config/bookfetch")).expanduser()
_PROGRESS = _CFG_DIR / "progress.json"
_TR_CACHE_DIR = Path(
    os.environ.get("BOOKFETCH_CACHE", "~/.cache/bookfetch")
).expanduser() / "translations"
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
    status: str = "queued"    # queued | running | done | error | cancelled
    out_rel: str = ""
    message: str = ""
    cancel: bool = False
    done: int = 0     # progress: chapters fetched so far (multi-chapter sources)
    total: int = 0


# ═══════ CLI/UI 边界（2026-09-05 少爷拍板，勿破）═══════════════════════════
# 本文件 = UI 后端（serve 浏览器 / gui 桌面壳共用）：任务系统、并发队列、
# 逐章断点续传、边下边读 .part 全部是 UI 用户的体验机制，**只作用于本模块
# 的 download() 后台任务**。CLI `bookfetch get`（cli.py main get 分支）是
# 独立同步直连：src.fetch(book) 一步到底，不经 download()/_run_job()/本队列，
# 因此 agent 脚本并发跑多个 CLI 进程互不排队、无上限、不产生 .part。
# 防回归锁 = tests/test_cli_ui_boundary.py（哨兵断言 CLI 路径零触碰本任务系统）。
# 给 CLI get 引入队列/断点/任何 UI 语义前，先确认那条边界仍成立。
# ══════════════════════════════════════════════════════════════════════════
# 并发队列（B4 落地，2026-09-05）：UI 下载并发上限 3，超出排队（queued）。
# 多书多源可并行，但不再无上限叠线程打爆单源/带宽。
_SLOTS = threading.Semaphore(3)


def _run_job(job: _Job) -> None:
    try:
        _SLOTS.acquire()
        try:
            if job.cancel:
                raise CancelledError()
            job.status = "running"
            _run_job_inner(job)
        finally:
            _SLOTS.release()
    except CancelledError:
        job.status = "cancelled"
        job.message = "已取消"
        logger.info("download job %s cancelled by user", job.id)
    except Exception as e:  # surface any failure to the UI
        job.status = "error"
        logger.exception("download job %s (%s %s) failed", job.id, job.source, job.book_id)
        job.message = friendly(e)


def _run_job_inner(job: _Job) -> None:
    src = get_source(job.source)
    if src is None:
        raise ValueError(f"unknown source {job.source!r}")
    book = Book(source=job.source, id=job.book_id, title=job.title)
    fr = fetch_cache.load(job.source, job.book_id)
    part = meta_path = None
    if fr is None:
        part, resume_from = _partial_state(book)
        meta_path = library_dir() / f"{_partial_fname(book)}.txt.part.meta"
        if resume_from == 0 and part is not None and part.exists():
            # 从头下载但 .part 有残留（meta 损坏/版本不匹配被清）：先清空重下，
            # 否则 on_checkpoint 会把新内容 append 进旧半成品 → 混版/章节重复
            part.unlink(missing_ok=True)
            if meta_path is not None:
                meta_path.unlink(missing_ok=True)

        def on_progress(done: int, total: int) -> bool:
            job.done, job.total = done, total
            return not job.cancel

        def on_checkpoint(index: int, c: Chapter) -> None:
            # B4 边下边读：每成功一章 → 更新 meta（续传点）+ 增量追加库内 .part
            # meta 存完整任务元信息（source/id/title/fmt）——书架「继续下载」靠它
            # 还原 download() 参数（resume_partial）；旧版只有 source+index 也能续传，
            # 但缺 id 无法从书架一键恢复（需按书名搜索找回，见 resume_partial）。
            if part is None:
                return
            meta_path.write_text(
                json.dumps(
                    {
                        "source": job.source,
                        "id": job.book_id,
                        "title": job.title,
                        "fmt": job.fmt,
                        "index": index,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            head = f"=== {c.title} ===\n{c.text}"
            with part.open("a", encoding="utf-8") as fh:
                if part.stat().st_size == 0:
                    fh.write(head)
                else:
                    fh.write("\n\n" + head)
            job.done = index + 1

        job.message = "抓取中…"
        fr = src.fetch(book, on_progress=on_progress, on_checkpoint=on_checkpoint, resume_from=resume_from)
        if resume_from > 0 and part is not None and part.exists():
            # 续传：.part 已含 prior + 本次新增（checkpoint 全程 append）→ 直接还原全量
            prior = split_rendered(part.read_text(encoding="utf-8"))
            if prior:
                fr.chapters = prior
                fr.content = "\n\n".join(c.text for c in prior)
                fr.chars = len(fr.content)
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
    if part is not None:  # 完成：清 B4 边读/断点残留（正式书已入库）
        part.unlink(missing_ok=True)
        if meta_path is not None:
            meta_path.unlink(missing_ok=True)
    job.status = "done"
    job.message = f"{fr.chars:,} chars · {len(_ensure_chapters(fr))} chapters"


def _partial_fname(book: Book) -> str:
    """B4 库内边读/断点文件基名 —— 与正式渲染同名规则（sanitize 书名）。"""
    return sanitize_filename(book.title) or f"{book.source}-{book.id}"


def _partial_state(book: Book) -> tuple[Path, int]:
    """B4 断点状态：(库内 .part 候选路径, resume_from toc 索引)。

    .part 路径始终返回——首次下载也由 on_checkpoint 创建（边下边读起点）；
    resume_from 仅当 meta 有效（source 匹配 + 整数索引）且 .part 在位才 >0；
    meta 损坏/孤儿 → 清掉从头下，防误续。
    """
    fname = _partial_fname(book)
    part = library_dir() / f"{fname}.txt.part"
    meta = library_dir() / f"{fname}.txt.part.meta"
    if not part.exists():
        meta.unlink(missing_ok=True)  # .part 被清（手动/完成）→ meta 一并作废
        return part, 0
    if meta.exists():
        try:
            m = json.loads(meta.read_text(encoding="utf-8"))
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
            return part, int(m["index"]) + 1
        meta.unlink(missing_ok=True)  # 损坏/孤儿/版本不匹配：清掉，避免误续
    return part, 0


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
    if job.done > 0:
        # B4 边下边读：库内已下 .part 存在 → 前端「打开已读」入口
        # （不限 running：cancelled 后 .part 保留，重试任务轮询即见；done 时已清理自然消失）
        part, _ = _partial_state(Book(source=job.source, id=job.book_id, title=job.title))
        if part.exists():
            out["partial_rel"] = library_rel(part)
    return out


def cancel(task_id: str) -> dict:
    """Ask a job to stop (cooperative, next chapter boundary / queue slot)."""
    with _LOCK:
        job = _TASKS.get(task_id)
    if job is None:
        return {"task_id": task_id, "ok": False, "message": "任务不存在"}
    if job.status in ("queued", "running"):
        job.cancel = True
        return {"task_id": task_id, "ok": True, "message": "取消中…"}
    zh = {"done": "已完成", "error": "失败", "cancelled": "已取消"}.get(job.status, job.status)
    return {"task_id": task_id, "ok": False, "message": f"任务已{zh}"}


def resume_partial(rel: str) -> dict:
    """书架「继续下载」：把未完成半成品（.txt.part）重新投入下载队列，自动断点续传。

    任务元信息存 .part.meta（source/id/title/fmt/index，B4c+扩展）；本函数把 meta
    还原成 download() 参数——download 内部 _partial_state 命中 meta 即从
    index+1 续传，完成时 .part/meta 清理、正式书条目接管进度（a91ccf1）。
    应用重启后任务列表（_TASKS 内存态）已清，这是半成品的唯一恢复入口。

    旧版 meta 只有 {"source","index"}（缺 id）→ 自动按书名在该源内搜索，找回
    唯一同名条目续传（防误配：书名必须完全一致）；找不到 → ValueError 中文引导。
    """
    p = _resolve(rel)
    if not p.is_file() or not p.name.endswith(_PART_SUFFIX):
        raise ValueError("不是未完成下载条目（.part）")
    meta_path = library_dir() / f"{p.name}.meta"
    book_title = p.name[: -len(_PART_SUFFIX)]  # 书名 = 文件名去 .txt.part（与正式书同源命名）
    src = None
    b_id = None
    fmt = None
    if meta_path.exists():
        try:
            m = json.loads(meta_path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            m = None
        if isinstance(m, dict) and isinstance(m.get("source"), str):
            src = m["source"]
            b_id = m.get("id")
            if not isinstance(b_id, str) or not b_id:
                b_id = None
            fmt = m.get("fmt")
            if not isinstance(fmt, str) or not fmt:
                fmt = None
    if not src:
        raise ValueError(
            f"「{book_title}」的半成品缺少断点信息——请到搜索页搜索该书重新下载，"
            "已下章节会被续写复用"
        )
    if b_id is None:
        # 旧版 meta 无 id：按书名在该源内搜索找回（书名必须完全一致才续，防误配错书；
        # 同名多命中 = 可能不同转载版本，绝不自动挑——引导手动选）
        try:
            r = search(book_title, [src])
        except Exception as e:  # noqa: BLE001 — 网络失败等一律转中文引导
            raise ValueError(f"自动找回源条目失败：{friendly(e)}") from None
        hits = [b for b in r.get("results", []) if b.get("title") == book_title]
        if not hits:
            raise ValueError(
                f"在源「{src}」找不到与「{book_title}」完全同名的条目——"
                "请到搜索页搜索该书手动下载"
            )
        if len(hits) > 1:
            raise ValueError(
                f"「{book_title}」在源「{src}」有 {len(hits)} 个同名条目（可能是不同"
                "版本/转载）——请到搜索页手动选择与半成品一致的那本下载；"
                "选对版本后会自动从断点继续，已下章节不重抓"
            )
        b_id = hits[0]["id"]
    job = download(src, b_id, title=book_title, fmt=fmt or "txt")
    return {"task_id": job["task_id"], "title": book_title, "fmt": fmt or "txt"}


# ------------------------------------------------------------------ shelf ---

_TXT_EXT = (".txt",)
_EPUB_EXT = (".epub",)
_PART_SUFFIX = ".txt.part"  # B4c 边下边读/断点半成品（库内 <书名>.txt.part）


def shelf() -> dict:
    """Scan the library dir for books, each with reading progress:
    [{rel, title, format, size_kb, progress:{chapter,pct}|None}].

    未完成下载（B4c 边下边读的 .txt.part）也列出：partial=True + 已下章数，
    点击直接读半成品；下载完成后 .part 消失、正式书条目接管同一进度 key。
    同名正式书已存在时跳过 .part（完成路径本会删，残留不双列）。
    """
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
        elif p.name.endswith(_PART_SUFFIX):
            # 未完成下载的半成品：书架可见可读（书名.txt.part）
            title = p.name[: -len(_PART_SUFFIX)]  # 书名（正式书同源命名）
            if (root / f"{title}.txt").exists():
                continue  # 正式书已入库 → .part 是残留（正常完成路径会删）
            rel = library_rel(p)
            try:
                nch = len(_open(p).chapters)
            except Exception:
                nch = None
            books.append(
                {
                    "rel": rel,
                    "title": title,
                    "format": "txt",
                    "size_kb": max(1, p.stat().st_size // 1024),
                    "chapters": nch,
                    "partial": True,
                    "progress": prog.get(_progress_key(rel)) or None,
                }
            )
    return {"library": str(root), "books": books}


# ------------------------------------------------------- shelf 管理（删/导/开）---

def delete_book(rel: str) -> dict:
    """书架删除书：删库内文件 + 清阅读进度 + 级联 .txt.part/.meta（无回收站，前端须二次确认）。

    半成品条目（书名.txt.part）删除后，其进度条目（归一的正式书名 key，B4c）一并清。
    """
    p = _resolve(rel)
    if not p.is_file():
        raise ValueError(f"「{rel}」在书库中不存在")
    is_partial = p.name.endswith(_PART_SUFFIX)
    if not (is_partial or p.suffix.lower() in _TXT_EXT + _EPUB_EXT):
        raise ValueError("只支持删除 .txt/.epub 书籍或 .txt.part 半成品")
    gone = [p.name]
    p.unlink()
    if is_partial:
        m = p.parent / f"{p.name}.meta"
        if m.exists():
            m.unlink()
            gone.append(m.name)
    else:
        # 正式书伴生残留的半成品（同名正式书在时 shelf 不列，但文件可能还在）
        for suffix in (_PART_SUFFIX, _PART_SUFFIX + ".meta"):
            c = p.parent / f"{p.stem}{suffix}"
            if c.exists():
                c.unlink()
                gone.append(c.name)
    key = _progress_key(library_rel(p))
    with _LOCK:
        d = _load_progress()
        if key in d:
            del d[key]
            _PROGRESS.parent.mkdir(parents=True, exist_ok=True)
            _PROGRESS.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"ok": True, "deleted": gone}


def import_book(name: str, data_b64: str) -> dict:
    """导入用户本地书（txt/epub）：base64 → 写书库上架。

    重名不覆盖——自动加序号（名.txt → 名(1).txt）后返回实际 rel。
    """
    import base64

    name = Path(name or "").name  # 只取文件名（去路径防目录穿越）
    if not name.lower().endswith((".txt", ".epub")):
        raise ValueError("只支持导入 .txt / .epub 文件")
    try:
        raw = base64.b64decode(data_b64, validate=True)
    except Exception:
        raise ValueError("导入数据损坏（base64 解码失败）——请重试") from None
    if not raw:
        raise ValueError("文件为空——请选择有效的书籍文件")
    root = library_dir()
    root.mkdir(parents=True, exist_ok=True)
    stem, ext = os.path.splitext(name)
    cand = root / name
    n = 1
    while cand.exists():
        cand = root / f"{stem}({n}){ext}"
        n += 1
    cand.write_bytes(raw)
    return {"ok": True, "rel": library_rel(cand), "title": cand.stem}


def open_library() -> dict:
    """在系统文件管理器打开书库目录（Finder / 资源管理器 / xdg-open）。"""
    root = library_dir()
    if not root.exists():
        raise ValueError(f"书库目录不存在：{root}")
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", str(root)])
        elif sys.platform.startswith("win"):
            subprocess.Popen(["explorer", str(root)])
        else:
            subprocess.Popen(["xdg-open", str(root)])
    except OSError as e:
        raise ValueError(f"无法打开书库目录：{e}") from None
    return {"ok": True}


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
    translate = 平台翻译可用性（非 macOS False → 前端藏「译」钮，A3 收尾）。
    """
    p = _resolve(rel)
    ob = _open(p)
    titles = [c.title or f"第{i+1}部分" for i, c in enumerate(ob.chapters)]
    if simp:
        titles = [_conv(ob, t) for t in titles]
    # .part 半成品：书名去掉 .txt.part 双后缀（书名.txt.part → 书名）
    btitle = p.name[: -len(_PART_SUFFIX)] if p.name.endswith(_PART_SUFFIX) else p.stem
    return {
        "rel": rel,
        "title": btitle,
        "format": ob.format,
        "base": ob.base,
        "translate": translate_available(),
        "chapters": [{"i": i, "title": t} for i, t in enumerate(titles)],
    }


def chapter(rel: str, idx: int, simp: bool = False) -> dict:
    ob = _open(_resolve(rel))
    if idx < 0 or idx >= len(ob.chapters):
        raise ValueError(f"chapter index out of range: {idx}")
    c = ob.chapters[idx]
    if simp:
        text = _conv(ob, c.text)
        title = _conv(ob, c.title or "")
    else:
        text = c.text
        title = c.title or ""
    full = title + "\n" + text
    return {
        "rel": rel,
        "i": idx,
        "title": title,
        "text": text,
        "dir": trans_direction(full),  # N3 双向：方向唯一判定在此（前端不自算）
    }


def translate(rel: str, idx: int) -> dict:
    """N3 双向整章翻译：按阅读器切段规则对齐段落，逐段系统翻译，结果缓存。

    方向 = trans_direction(章全文)（含较多拉丁词 → en2zh，否则 zh2en）；
    返回 {dir, trs: [译文|null...]}，trs 长度 = 前端渲染段落数（正文去标题后）。
    缓存 key = sha1(rel|idx|direction|原文全文)——方向与文本共同决定缓存。
    桥缺失/语言包未装 → ValueError（中文引导文案）。
    """
    ob = _open(_resolve(rel))
    if idx < 0 or idx >= len(ob.chapters):
        raise ValueError(f"chapter index out of range: {idx}")
    c = ob.chapters[idx]
    title = c.title or ""
    direction = trans_direction(title + "\n" + c.text)
    paras = split_reader_paras(c.text, title)
    if not paras:
        return {"rel": rel, "i": idx, "dir": direction, "trs": []}

    key = hashlib.sha1(
        f"{rel}|{idx}|{direction}|{c.text}".encode("utf-8")
    ).hexdigest()
    cache_file = _TR_CACHE_DIR / f"{key}.json"
    try:
        if cache_file.exists():
            trs = json.loads(cache_file.read_text(encoding="utf-8"))
            if isinstance(trs, list) and len(trs) == len(paras):
                return {"rel": rel, "i": idx, "dir": direction, "trs": trs}
    except Exception:
        pass  # 缓存损坏 = miss 重翻

    trs = translate_paragraphs(paras, direction=direction)
    if len(trs) != len(paras):
        raise ValueError("翻译段落数与原文不一致，请重试")
    try:
        _TR_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(
            json.dumps(trs, ensure_ascii=False), encoding="utf-8"
        )
    except Exception:
        pass  # 缓存写失败不影响本次返回
    return {"rel": rel, "i": idx, "dir": direction, "trs": trs}


def open_activator() -> dict:
    """拉起「翻译语言包准备器」（SwiftUI，用户点一下完成下载+安装）。

    首次翻译遇 notInstalled 时前端调用；激活器是独立 .app，由 LaunchServices
    open 拉起（自带 UI 会话，才有语言包下载权限——pywebview 会话没有）。
    """
    from .util.translator import find_activator

    p = find_activator()
    try:
        subprocess.Popen(["open", str(p)])  # detach，激活器独立进程
    except OSError as e:
        raise ValueError(f"无法打开翻译语言包准备器：{e}") from None
    return {"ok": True, "activator": str(p)}


def _load_progress() -> dict:
    if not _PROGRESS.exists():
        return {}
    try:
        return json.loads(_PROGRESS.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _progress_key(rel: str) -> str:
    """B4c 进度 key 归一：半成品 .part 的阅读进度记到正式书名上。

    .part 读（书名.txt.part）与下载完成后的正式书（书名.txt）共享同一
    key —— 下载完成书架换正式条目时进度无缝继承，不从头。
    """
    return rel[: -len(".part")] if rel.endswith(".part") else rel


def progress_get(rel: str) -> dict:
    return {"rel": rel, "progress": _load_progress().get(_progress_key(rel), {})}


def progress_set(rel: str, chapter_idx: int, pct: int = 0) -> dict:
    """Save reading position: chapter index + pct (0..1000 scroll fraction)."""
    with _LOCK:
        d = _load_progress()
        d[_progress_key(rel)] = {"chapter": int(chapter_idx), "pct": int(pct)}
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
    if name == "resume_partial":
        return resume_partial(params.get("rel", ""))
    if name == "delete_book":
        return delete_book(params.get("rel", ""))
    if name == "import_book":
        return import_book(params.get("name", ""), params.get("data", ""))
    if name == "open_library":
        return open_library()
    if name == "shelf":
        return shelf()
    if name == "open_book":
        return open_book(params.get("rel", ""), bool(params.get("simp", False)))
    if name == "chapter":
        return chapter(params.get("rel", ""), int(params.get("idx", 0)), bool(params.get("simp", False)))
    if name == "translate":
        return translate(params.get("rel", ""), int(params.get("idx", 0)))
    if name == "open_activator":
        return open_activator()
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
    "search", "download", "cancel", "resume_partial", "delete_book", "import_book",
    "open_library", "task_status", "shelf", "open_book",
    "chapter", "translate", "open_activator", "progress_get", "progress_set",
    "library", "sources", "settings_get", "settings_set",
}
