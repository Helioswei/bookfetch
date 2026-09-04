"""GitHub-hosted public-domain Chinese classic text collections.

Design: each curated repo's blob list is fetched once via the git trees API
and cached on disk for 7 days (unauthenticated GitHub API quota is 60/hr —
this keeps usage at ~2 calls per repo per week: one repos-API health probe
+ one trees-API index refresh). Searches match filenames locally; downloads
go straight to raw.githubusercontent.com (not rate-limited the same way).

M7 multi-repo + health probe (2026-09-04):
- curated list is config-driven; each entry carries a measured license state.
- a repo that 404s on the repos API is marked dead in the cache and every
  search fails fast with RepoDeadError (no silent stale fallback — a dead
  source must surface in the registry errors dict, never quietly serve a
  7-day-old index). Transient API failures (rate limit / network) still fall
  back to stale cache, preserving the M2 semantics.
- dead markers expire after _CACHE_TTL, so a revived repo is re-probed.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote

from ..model import Book, FetchResult
from ..util import FetchError, fetch
from ..util.splitters import split_headings
from .base import Source

# Curated repo list — deliberately small and reviewed. license values are the
# measured spdx_id (None = no license file found; repo content may still be
# public-domain text, but transcription/compilation rights are unverified →
# README「源与合规」labels these "使用前自审").
_REPOS: list[dict] = [
    {
        "repo": "mymmsc/books",
        "branch": "master",
        "note": "综合资料库，含《国学/八字 - 渊海子平.txt》等公版古籍文本",
        "license": None,  # 实测 2026-09-04: repos API spdx_id = None, ★2641
    },
    {
        "repo": "xiaopangxia/TCM-Ancient-Books",
        "branch": "master",
        "note": "中医药古籍文本 ~700 本（神农本草经/本草纲目…，平铺 txt）",
        "license": None,  # 实测 2026-09-04: repos API spdx_id = None, ★1411
    },
]

_TREE_URL = "https://api.github.com/repos/{repo}/git/trees/HEAD?recursive=1"
_META_URL = "https://api.github.com/repos/{repo}"
_RAW_URL = "https://raw.githubusercontent.com/{repo}/{branch}/{path}"
_BLOB_URL = "https://github.com/{repo}/blob/{branch}/{path}"
_CACHE_TTL = 7 * 24 * 3600
_UA = "bookfetch/0.4 (https://github.com/Helioswei/bookfetch)"


class RepoDeadError(FetchError):
    """The repo is gone (404/410): deleted, made private, or renamed."""


def _cache_dir() -> Path:
    base = os.environ.get("BOOKFETCH_CACHE") or Path.home() / ".cache" / "bookfetch"
    d = Path(base)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cache_file(cfg: dict) -> Path:
    return _cache_dir() / f"github_tree_{cfg['repo'].replace('/', '_')}.json"


def _read_cache(cache: Path) -> dict | None:
    try:
        data = json.loads(cache.read_text(encoding="utf-8"))
        if isinstance(data.get("paths"), list):
            return data
    except Exception:
        pass
    return None


def _write_cache(cache: Path, *, ts: float, paths: list[str], dead: bool,
                 license_spdx: str | None) -> None:
    cache.write_text(json.dumps({
        "ts": ts, "paths": paths, "dead": dead, "license": license_spdx,
    }), encoding="utf-8")


def _api_json(url: str) -> dict:
    """GET JSON from api.github.com with a browser-ish UA."""
    req = urllib.request.Request(url, headers={
        "User-Agent": _UA, "Accept": "application/vnd.github+json",
    })
    try:
        with urllib.request.urlopen(req, timeout=25.0) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code in (404, 410):
            raise RepoDeadError(
                f"github repo {url.rsplit('/', 1)[-1]!r} 不存在（HTTP {e.code}）"
                "—— 可能被删除/转私有/改名")
        raise FetchError(f"github api HTTP {e.code}: {url}")
    except Exception as e:  # network / timeout / bad json
        raise FetchError(f"github api 请求失败: {url} ({e})") from e


def _paths_from_tree(tree: dict) -> list[str]:
    return [t["path"] for t in tree.get("tree", []) if t.get("type") == "blob"]


def _title_matches(query: str, path: str) -> bool:
    """Loose filename match: query contained in basename or vice versa."""
    if not path.lower().endswith(".txt"):
        return False
    base = path.rsplit("/", 1)[-1][:-4].strip()
    q = query.strip()
    if not q or not base:
        return False
    return q.lower() in base.lower() or base.lower() in q.lower()


def _license_label(cfg: dict) -> str:
    """Human label for the repo's measured license state."""
    spdx = cfg.get("license")
    if spdx:
        return spdx
    return "未声明(权利状态不明，使用前自审)"


def _search_paths(paths: list[str], cfg: dict, query: str) -> list[Book]:
    books: list[Book] = []
    repo = cfg["repo"]
    branch = cfg["branch"]
    for path in paths:
        if not _title_matches(query, path):
            continue
        base = path.rsplit("/", 1)[-1][:-4].strip()
        folder = path.rsplit("/", 1)[0] if "/" in path else ""
        books.append(
            Book(
                source="github",
                id=f"{repo}:{path}",
                title=base,
                url=_BLOB_URL.format(repo=repo, branch=branch, path=quote(path, safe="/")),
                subtitle=cfg.get("note", ""),
                format_hint="txt",
                extra={
                    "repo": repo,
                    "folder": folder,
                    "license": _license_label(cfg),
                },
            )
        )
    return books


def _repo_paths(cfg: dict) -> list[str]:
    """Blob paths for a repo.

    - fresh cache (alive) → cached paths (0 network calls)
    - fresh cache (dead) → fail fast: RepoDeadError (no stale fallback)
    - stale/absent cache → probe repos API (liveness + license + default
      branch), then refresh the trees index; on 404 mark dead and raise;
      on transient API trouble fall back to stale paths when present.
    """
    repo = cfg["repo"]
    cache = _cache_file(cfg)
    data = _read_cache(cache)
    now = time.time()
    if data and now - data.get("ts", 0) < _CACHE_TTL:
        if data.get("dead"):
            raise RepoDeadError(f"github repo {repo!r} 已标记失效（404），缓存期不重试")
        return data["paths"]
    stale: list[str] | None = data["paths"] if data else None
    try:
        meta = _api_json(_META_URL.format(repo=repo))
        tree = _api_json(_TREE_URL.format(repo=repo))
        paths = _paths_from_tree(tree)
        spdx = (meta.get("license") or {}).get("spdx_id")
        cfg["branch"] = meta.get("default_branch") or cfg.get("branch", "master")
        cfg["license"] = spdx  # keep measured state in sync for this process
        _write_cache(cache, ts=now, paths=paths, dead=False, license_spdx=spdx)
        return paths
    except RepoDeadError:
        _write_cache(cache, ts=now, paths=stale or [], dead=True, license_spdx=None)
        raise
    except FetchError:
        if stale is not None:
            return stale  # rate limit / network hiccup: M2 stale fallback
        raise


class GithubBooks(Source):
    name = "github"

    def search(self, query: str) -> list[Book]:
        books: list[Book] = []
        for cfg in _REPOS:
            paths = _repo_paths(cfg)  # RepoDeadError/FetchError → registry errors
            books.extend(_search_paths(paths, cfg, query))
        return books

    def fetch(self, book: Book) -> FetchResult:
        """Fetch one raw txt file; chapter structure comes from headings."""
        repo, sep, path = book.id.partition(":")
        if not sep or not repo or not path:
            raise ValueError("github id must look like 'owner/repo:path/to/book.txt'")
        cfg = next((c for c in _REPOS if c["repo"] == repo), None)
        if cfg is None:
            raise ValueError(f"repo {repo!r} not in curated list: {[c['repo'] for c in _REPOS]}")
        raw_url = _RAW_URL.format(
            repo=repo, branch=cfg["branch"], path=quote(path, safe="/")
        )
        text = fetch(raw_url)  # decode handles UTF-8 / GB18030 / Big5
        title = book.title or path.rsplit("/", 1)[-1][:-4] or repo
        lines = text.splitlines()
        chapters = split_headings(lines)
        if chapters:
            content = "\n".join(c.text for c in chapters)
        else:
            chapters = None
            content = text
        return FetchResult(
            source=self.name,
            id=book.id,
            title=title,
            chars=len(content),
            lines=len(lines),
            format="txt",
            content=content,
            chapters=chapters,
        )
