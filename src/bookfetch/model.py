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
class FetchResult:
    """Outcome of downloading a Book."""

    source: str
    id: str
    title: str
    out_path: str
    chars: int = 0
    lines: int = 0
    format: str = "txt"

    def to_dict(self) -> dict:
        return asdict(self)
