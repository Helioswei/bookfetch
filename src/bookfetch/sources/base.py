"""Source adapter interface."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..model import Book, FetchResult


class Source(ABC):
    """One book source (ctext, github, ...). Implementations must be stateless
    except for util's built-in rate limiting."""

    name: str = "base"
    label: str = "未知书源"  # user-facing Chinese label (D1 decision A)

    @abstractmethod
    def search(self, query: str) -> list[Book]:
        """Return editions matching query. Never raises for network issues —
        callers surface errors via the errors dict instead."""

    @abstractmethod
    def fetch(self, book: Book, *, on_progress=None, on_checkpoint=None, resume_from=0) -> FetchResult:
        """Fetch and parse one edition into content + optional chapter
        structure. Never writes files — the CLI renders txt/epub.

        Multi-request sources (chapter-at-a-time: biquge/ctext/wikisource)
        MUST call on_progress(done, total) before each chapter and abort with
        util.CancelledError when it returns False (user cancelled).
        Single-request sources accept and ignore the hook.
        """
