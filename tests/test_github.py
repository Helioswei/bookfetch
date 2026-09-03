"""Offline tests for the github text-collection source (fixtures, no network)."""

import json
from pathlib import Path

from bookfetch.sources.github import (
    _paths_from_tree,
    _search_paths,
    _title_matches,
)

FIX = Path(__file__).parent / "fixtures"
CFG = {"repo": "mymmsc/books", "branch": "master", "note": "test"}


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
