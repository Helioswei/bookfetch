"""Shared result models."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class Book:
    """One downloadable edition found by a source."""

    source: str
    id: str
    title: str
    url: str = ""
    subtitle: str = ""
    format_hint: str = "txt"
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Chapter:
    """A titled section of a fetched book (source pages, 《》 headings, ...)."""

    title: str
    text: str


@dataclass
class FetchResult:
    """Parsed content of a downloaded Book.

    Sources return content + optional chapter structure WITHOUT writing files;
    the CLI renders the requested format (txt/epub) and sets ``out_path``.
    ``content`` is the plain merged text: joining each chapter's ``text`` with
    ``"\\n"`` reproduces it exactly (chapters are ordered slices of lines), so
    format rendering never loses or reorders anything.
    """

    source: str
    id: str
    title: str
    out_path: str = ""
    chars: int = 0
    lines: int = 0
    format: str = "txt"
    content: str = ""
    chapters: list[Chapter] | None = None
    raw: bytes | None = None  # binary sources (libgen): file bytes, no text pipeline

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "id": self.id,
            "title": self.title,
            "out_path": self.out_path,
            "chars": self.chars,
            "lines": self.lines,
            "format": self.format,
            "chapters": [c.title for c in self.chapters] if self.chapters else None,
        }
