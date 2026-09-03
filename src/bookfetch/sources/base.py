"""Source adapter interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from ..model import Book, FetchResult


class Source(ABC):
    """One book source (ctext, github, ...). Implementations must be stateless
    except for util's built-in rate limiting."""

    name: str = "base"

    @abstractmethod
    def search(self, query: str) -> list[Book]:
        """Return editions matching query. Never raises for network issues —
        callers surface errors via the errors dict instead."""

    @abstractmethod
    def fetch(self, book: Book, out_dir: str | Path = ".") -> FetchResult:
        """Download the book edition and write it under out_dir."""
