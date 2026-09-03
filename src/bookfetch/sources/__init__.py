"""Source registry."""

from __future__ import annotations

from ..model import Book
from .base import Source
from .ctext import Ctext

_REGISTRY: dict[str, Source] = {}


def _register(src: Source) -> Source:
    _REGISTRY[src.name] = src
    return src


_register(Ctext())


def get_source(name: str) -> Source | None:
    return _REGISTRY.get(name)


def source_names() -> list[str]:
    return list(_REGISTRY)


def search_all(query: str, names: list[str] | None = None, limit: int = 20):
    """Search across sources. Returns (results, errors_by_source)."""
    names = names or source_names()
    results: list[Book] = []
    errors: dict[str, str] = {}
    for n in names:
        src = _REGISTRY.get(n)
        if src is None:
            errors[n] = f"unknown source (known: {', '.join(source_names())})"
            continue
        try:
            results.extend(src.search(query))
        except Exception as e:  # source failure must not kill the whole search
            errors[n] = f"{type(e).__name__}: {e}"
    return results[:limit], errors
