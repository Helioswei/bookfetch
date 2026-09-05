"""libgen source adapter — probe-first mirror chain (English/modern books).

libgen's mirrors churn constantly (parked domains, 502s, dead IPs), so this
source never hardcodes "the mirror": every search probes the candidate list
via the JSON API until one answers, caches the winner for 6h, and fails fast
with a clear error when none is alive. Books are binary files (epub/pdf/...)
and are saved byte-for-byte via FetchResult.raw — no text pipeline involved.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from ..model import Book, FetchResult
from ..util import FetchError, fetch, fetch_bytes, fetch_bytes_resumable
from .base import Source

_MIRRORS = [
    "libgen.is", "libgen.rs", "libgen.st", "libgen.li", "libgen.vg",
    "libgen.lc", "libgen.gs", "libgen.rocks", "libgen.ee",
]
_PROBE_TTL = 6 * 3600
_JSON_FIELDS = "id,title,author,year,language,extension,filesize,md5"


def _cache_dir() -> Path:
    base = os.environ.get("BOOKFETCH_CACHE") or Path.home() / ".cache" / "bookfetch"
    d = Path(base)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _alive_cache() -> Path:
    return _cache_dir() / "libgen_mirrors.json"


def probe_alive(timeout: float = 4.0) -> list[str]:
    """Mirrors whose json.php actually returns JSON right now."""
    alive: list[str] = []
    for m in _MIRRORS:
        try:
            body = fetch(f"https://{m}/json.php?fields=id&limit=1&q=test", timeout=timeout, retries=1)
            data = json.loads(body)
            if isinstance(data, list):  # parked/nginx pages are HTML, not JSON
                alive.append(m)
        except (FetchError, json.JSONDecodeError, ValueError):
            continue
        if alive:
            break
    return alive


def _mirrors() -> list[str]:
    """Alive mirrors, cached for 6h to keep searches snappy."""
    cache = _alive_cache()
    if cache.exists():
        try:
            data = json.loads(cache.read_text(encoding="utf-8"))
            if time.time() - data.get("ts", 0) < _PROBE_TTL:
                return data["alive"]
        except Exception:
            pass
    alive = probe_alive()
    try:
        cache.write_text(json.dumps({"ts": time.time(), "alive": alive}), encoding="utf-8")
    except OSError:
        pass
    return alive


class Libgen(Source):
    name = "libgen"
    label = "电子书库"

    def _first(self) -> str:
        alive = _mirrors()
        if not alive:
            # 2026-09 实测：libgen 官方全面迁移新版站（登录 + API keys + object 模型），
            # 老镜像域名（is/rs/st/lc 等）停放轮换、匿名 json.php/search.php 已停用——
            # 是源接口架构迁移，不是临时网络故障；适配新版 API 见 PRD P2（含备选
            # Anna's Archive 聚合）。探活保留：万一老镜像复活自动恢复，不手动判死。
            raise FetchError(
                "libgen：官方 2024 起迁移新版站（登录 + API keys），匿名搜索接口已停用，"
                "此源待适配（PRD P2）；英文现代书暂缺此源，公版英文书可走古登堡/维基文库"
            )
        return alive[0]

    def search(self, query: str) -> list[Book]:
        from urllib.parse import quote

        m = self._first()
        body = fetch(f"https://{m}/json.php?fields={_JSON_FIELDS}&limit=20&q={quote(query)}")
        try:
            rows = json.loads(body)
        except json.JSONDecodeError as e:
            raise FetchError(f"libgen json.php on {m} not JSON (parked/blocked?)") from e
        if not isinstance(rows, list):
            raise FetchError(f"libgen {m} returned unexpected payload")
        books: list[Book] = []
        for r in rows:
            md5 = str(r.get("md5", ""))
            if not md5:
                continue
            ext = str(r.get("extension", "bin"))
            size = r.get("filesize", "")
            try:
                size = f"{int(size) / 1e6:.1f}MB" if size else ""
            except (TypeError, ValueError):
                size = ""
            books.append(
                Book(
                    source=self.name,
                    id=md5,
                    title=str(r.get("title", "untitled")),
                    url=f"https://{m}/book/index.php?md5={md5}",
                    subtitle=" / ".join(
                        x for x in (str(r.get("author", "")), str(r.get("year", "")), size) if x
                    ),
                    format_hint=ext,
                    extra={"mirror": m, "extension": ext, "md5": md5},
                )
            )
        return books

    def fetch(self, book: Book, *, on_progress=None, on_checkpoint=None, resume_from=0) -> FetchResult:
        md5 = book.id.strip().lower()
        if not re_fullmatch_hex(md5):
            raise ValueError(f"libgen id must be a 32-char md5, got {book.id!r}")
        m = book.extra.get("mirror") or self._first()
        ext = book.extra.get("extension") or "bin"
        # B4 断点续传：大文件流式落盘 + Range 续传（中断残留 .part 是下次起点）
        from ..fetch_cache import partial_dir

        part = partial_dir() / f"{md5}.part"
        try:
            data = fetch_bytes_resumable(f"https://{m}/get.php?md5={md5}", part)
        except Exception:
            part.unlink(missing_ok=True)  # 挑战页/校验失败的残留丢弃，防续传串味
            raise
        head = data[:512].lstrip().lower()
        if head.startswith(b"<!doctype") or head.startswith(b"<html") or b"cloudflare" in head:
            part.unlink(missing_ok=True)
            raise FetchError(f"libgen {m} returned a page, not the file (CF challenge / dead link)")
        part.unlink(missing_ok=True)  # 成功：已进缓存区，清 scratch
        return FetchResult(
            source=self.name,
            id=md5,
            title=book.title or md5,
            format=ext,
            chars=len(data),
            raw=data,
        )


_HEX = "0123456789abcdef"


def re_fullmatch_hex(s: str) -> bool:
    return len(s) == 32 and all(c in _HEX for c in s)
