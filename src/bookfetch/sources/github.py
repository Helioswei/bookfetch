"""GitHub-hosted public-domain Chinese classic text collections.

Design: each curated repo's blob list is fetched once via the git trees API
and cached on disk for 7 days (unauthenticated GitHub API quota is 60/hr —
this keeps usage at ~2 calls per repo per week). Searches match filenames
locally; downloads go straight to raw.githubusercontent.com (not rate-limited
the same way).

The curated repo list is deliberately small and reviewed: only public-domain
text collections.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from urllib.parse import quote

from ..model import Book, FetchResult
from ..util import FetchError, fetch
from ..util.splitters import split_headings
from .base import Source

_REPOS: list[dict] = [
    {
        "repo": "mymmsc/books",
        "branch": "master",
        "note": "综合资料库，含《国学/八字 - 渊海子平.txt》等公版古籍文本",
    },
]

_TREE_URL = "https://api.github.com/repos/{repo}/git/trees/HEAD?recursive=1"
_RAW_URL = "https://raw.githubusercontent.com/{repo}/{branch}/{path}"
_BLOB_URL = "https://github.com/{repo}/blob/{branch}/{path}"
_CACHE_TTL = 7 * 24 * 3600


def _cache_dir() -> Path:
    base = os.environ.get("BOOKFETCH_CACHE") or Path.home() / ".cache" / "bookfetch"
    d = Path(base)
    d.mkdir(parents=True, exist_ok=True)
    return d


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
                extra={"repo": repo, "folder": folder},
            )
        )
    return books


def _repo_paths(cfg: dict) -> list[str]:
    """Blob paths for a repo, refreshed from the trees API at most every TTL.
    Falls back to a stale cache when the API is rate-limited or down."""
    repo = cfg["repo"]
    cache = _cache_dir() / f"github_tree_{repo.replace('/', '_')}.json"
    stale: list[str] | None = None
    if cache.exists():
        try:
            data = json.loads(cache.read_text(encoding="utf-8"))
            if time.time() - data.get("ts", 0) < _CACHE_TTL:
                return data["paths"]
            stale = data["paths"]
        except Exception:
            stale = None
    try:
        tree = json.loads(fetch(_TREE_URL.format(repo=repo)))
        paths = _paths_from_tree(tree)
        cache.write_text(json.dumps({"ts": time.time(), "paths": paths}), encoding="utf-8")
        return paths
    except FetchError:
        if stale is not None:
            return stale
        raise


class GithubBooks(Source):
    name = "github"

    def search(self, query: str) -> list[Book]:
        books: list[Book] = []
        for cfg in _REPOS:
            try:
                paths = _repo_paths(cfg)
            except FetchError:
                raise  # surfaced via registry errors dict
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
