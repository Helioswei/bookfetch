"""Offline tests for the github text-collection source (fixtures, no network)."""

import json
import time
from pathlib import Path

import pytest

from bookfetch.sources import github as gh
from bookfetch.sources.github import (
    _paths_from_tree,
    _search_paths,
    _title_matches,
)
from bookfetch.util import FetchError

FIX = Path(__file__).parent / "fixtures"
CFG = {"repo": "mymmsc/books", "branch": "master", "note": "test", "license": None}
CFG_TCM = {
    "repo": "xiaopangxia/TCM-Ancient-Books", "branch": "master",
    "note": "test", "license": None,
}


def test_tree_paths_parse():
    tree = json.loads((FIX / "gbooks_tree.json").read_text(encoding="utf-8"))
    paths = _paths_from_tree(tree)
    assert len(paths) == 26
    assert "国学/八字 - 渊海子平.txt" in paths


def test_title_matches():
    assert _title_matches("渊海子平", "国学/八字 - 渊海子平.txt")
    assert _title_matches("八字 - 渊海子平", "国学/八字 - 渊海子平.txt")
    assert not _title_matches("论语", "c/排序/冒泡排序.txt")
    assert not _title_matches("渊海子平", "asm/汇编语言指令大全.pdf")  # non-txt ignored
    assert _title_matches("BOOK", "python/Book.txt")  # case-insensitive
    assert not _title_matches("python", "python/Book.txt")  # folder not matched


def test_search_paths_builds_books():
    tree = json.loads((FIX / "gbooks_tree.json").read_text(encoding="utf-8"))
    books = _search_paths(_paths_from_tree(tree), CFG, "渊海子平")
    assert len(books) == 1
    b = books[0]
    assert b.source == "github"
    assert b.id == "mymmsc/books:国学/八字 - 渊海子平.txt"
    assert b.title == "八字 - 渊海子平"
    assert b.extra["repo"] == "mymmsc/books"
    assert "github.com" in b.url


# ---- M7: multi-repo + health probe -------------------------------------


def test_tcm_fixture_parses_and_searches():
    """xiaopangxia fixture (real 40-item capture) hits 本草纲目."""
    tree = json.loads((FIX / "xp_tree.json").read_text(encoding="utf-8"))
    paths = _paths_from_tree(tree)
    assert len(paths) == 40
    books = _search_paths(paths, CFG_TCM, "本草纲目")
    assert len(books) >= 1
    assert books[0].extra["repo"] == "xiaopangxia/TCM-Ancient-Books"
    assert books[0].id.endswith("013-本草纲目.txt")


def test_search_aggregates_across_repos(monkeypatch, tmp_path):
    """search() walks every curated repo and merges results."""
    monkeypatch.setenv("BOOKFETCH_CACHE", str(tmp_path))
    real_paths = gh._repo_paths

    def fake_paths(cfg):
        if cfg["repo"].endswith("mymmsc/books"):
            tree = json.loads((FIX / "gbooks_tree.json").read_text(encoding="utf-8"))
            return _paths_from_tree(tree)
        tree = json.loads((FIX / "xp_tree.json").read_text(encoding="utf-8"))
        return _paths_from_tree(tree)

    monkeypatch.setattr(gh, "_repo_paths", fake_paths)
    results = gh.GithubBooks().search("本草纲目")
    assert any(b.extra["repo"] == "xiaopangxia/TCM-Ancient-Books" for b in results)


def test_no_license_labeled_for_self_review():
    books = _search_paths(["013-本草纲目.txt"], CFG_TCM, "本草")
    assert "未声明" in books[0].extra["license"]


def _seed_cache(tmp_path, repo: str, *, paths, dead: bool, age_s: float):
    import os
    os.environ["BOOKFETCH_CACHE"] = str(tmp_path)
    cache = tmp_path / f"github_tree_{repo.replace('/', '_')}.json"
    cache.write_text(json.dumps({
        "ts": time.time() - age_s, "paths": paths, "dead": dead,
        "license": None,
    }), encoding="utf-8")
    return cache


def test_dead_cache_fails_fast_no_stale_fallback(tmp_path, monkeypatch):
    """A repo marked dead must raise, never silently serve the stale index."""
    monkeypatch.setenv("BOOKFETCH_CACHE", str(tmp_path))
    _seed_cache(tmp_path, "mymmsc/books", paths=["dead.txt"], dead=True, age_s=60)
    with pytest.raises(FetchError, match="失效"):
        gh._repo_paths({"repo": "mymmsc/books", "branch": "master"})


def test_stale_fallback_on_transient_api_error(tmp_path, monkeypatch):
    """Rate-limit/network failure keeps M2 stale fallback."""
    monkeypatch.setenv("BOOKFETCH_CACHE", str(tmp_path))
    _seed_cache(tmp_path, "mymmsc/books", paths=["老书.txt"], dead=False, age_s=8 * 86400)

    def boom(cfg):
        raise FetchError("rate limited")

    monkeypatch.setattr(gh, "_api_json", boom)
    out = gh._repo_paths({"repo": "mymmsc/books", "branch": "master"})
    assert out == ["老书.txt"]


def test_404_probe_marks_dead(tmp_path, monkeypatch):
    """404 on the repos API writes a dead marker and raises, no stale serve."""
    monkeypatch.setenv("BOOKFETCH_CACHE", str(tmp_path))
    _seed_cache(tmp_path, "xiaopangxia/TCM-Ancient-Books",
                paths=["旧索引.txt"], dead=False, age_s=8 * 86400)

    def dead404(cfg):
        raise gh.RepoDeadError("gone")

    monkeypatch.setattr(gh, "_api_json", dead404)
    with pytest.raises(FetchError, match="gone"):
        gh._repo_paths({"repo": "xiaopangxia/TCM-Ancient-Books", "branch": "master"})
    # dead marker persisted → next call fails fast even without network
    with pytest.raises(FetchError, match="失效"):
        gh._repo_paths({"repo": "xiaopangxia/TCM-Ancient-Books", "branch": "master"})
