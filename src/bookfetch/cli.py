"""bookfetch CLI — JSON-first output for agents, --human for people."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from . import fetch_cache
from .model import Book, Chapter, FetchResult
from .sources import get_source, search_all, source_names
from .util import FetchError, sanitize_filename
from .util.epub import build_epub
from .util.simplify import to_simplified
from .util.splitters import split_headings

DESC = "Agent-friendly ebook finder: routes book queries to working sources."


def _human_search(obj: dict) -> None:
    for i, b in enumerate(obj["results"], 1):
        extra = f" [{b['subtitle']}]" if b.get("subtitle") else ""
        print(f"{i}. [{b['source']}] {b['title']} (id={b['id']}){extra}")
    if obj.get("errors"):
        for src, err in obj["errors"].items():
            print(f"   ! {src}: {err}", file=sys.stderr)


def _human_get(obj: dict) -> None:
    r = obj["result"]
    tag = "Cached, re-rendered: " if r.get("cached") else "Saved: "
    print(f"{tag}{r['out_path']}")
    extra = f" | {len(r['chapters'])} chapters" if r.get("chapters") else ""
    print(f"  {r['title']} | {r['lines']} paragraphs | {r['chars']} chars | {r['format']}{extra}")


def _ensure_chapters(fr: FetchResult) -> list[Chapter]:
    """Chapters from the source, or heading-split, or one whole-text chapter."""
    if fr.chapters:
        return list(fr.chapters)
    chs = split_headings(fr.content.splitlines())
    if chs:
        return chs
    return [Chapter(title=fr.title or fr.id, text=fr.content)]


def _render_get(src, fr: FetchResult, args) -> FetchResult:
    """Optional simplify -> render txt/epub under --out.

    `fr` is already fetched (network or cache). Binary sources (libgen etc.)
    return FetchResult.raw and are saved byte-for-byte; text-only flags
    (--simplify/--split/--format) reject them.
    """
    if fr.raw is not None:  # binary passthrough: save the original file
        if args.simplify or args.split or args.format != "txt":
            raise ValueError(f"源 {fr.source} 是二进制原文件（.{fr.format}），不支持 --simplify/--split/--format")
        fname = sanitize_filename(fr.title) or fr.id
        out_dir = Path(args.out)
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{fname}.{fr.format}"
        path.write_bytes(fr.raw)
        fr.out_path = str(path)
        return fr

    chapters = _ensure_chapters(fr)

    if args.simplify:
        chapters = [Chapter(title=to_simplified(c.title), text=to_simplified(c.text)) for c in chapters]
        fr.title = to_simplified(fr.title)

    fname = sanitize_filename(fr.title) or fr.id
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.format == "epub":
        path = build_epub(fr.title, chapters, out_dir / f"{fname}.epub")
        text_chars = sum(len(c.text) for c in chapters)
        n_lines = sum(len(c.text.splitlines()) for c in chapters)
    else:  # txt
        if args.split and len(chapters) > 1:
            parts = []
            for i, c in enumerate(chapters, 1):
                head = c.title or f"第{i}部分"
                parts.append(f"=== {head} ===\n{c.text}")
            text = "\n\n".join(parts) + "\n"
        elif args.simplify:
            text = "\n".join(c.text for c in chapters) + "\n"
        else:
            text = fr.content  # byte-identical to the fetched text
        path = out_dir / f"{fname}.txt"
        path.write_text(text, encoding="utf-8")
        text_chars = len(text)
        n_lines = len(text.splitlines())

    fr.out_path = str(path)
    fr.format = args.format
    fr.chars = text_chars
    fr.lines = n_lines
    return fr


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="bookfetch", description=DESC)
    p.add_argument("--version", action="version", version=f"bookfetch {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("search", help="search sources for a book")
    sp.add_argument("query", help="book title or keywords (Chinese OK)")
    sp.add_argument("--source", action="append", default=None, help="only search this source (repeatable)")
    sp.add_argument("--limit", type=int, default=20, help="max results (default 20)")
    sp.add_argument("--human", action="store_true", help="human-readable output")

    gp = sub.add_parser("get", help="download a book edition (id from search)")
    gp.add_argument("source", help="source name, e.g. ctext")
    gp.add_argument("id", help="edition id from search results")
    gp.add_argument("--title", default="", help="optional title override for the output filename")
    gp.add_argument("--force", action="store_true", help="re-fetch even if this edition is already cached")
    gp.add_argument("--out", default=".", help="output directory (default: current dir)")
    gp.add_argument(
        "--format",
        choices=["txt", "epub"],
        default="txt",
        help="output format (default: txt; epub needs no extra deps)",
    )
    gp.add_argument(
        "--split",
        action="store_true",
        help="insert '=== 章节 ===' separators into txt output (epub is always split)",
    )
    gp.add_argument(
        "--simplify",
        action="store_true",
        help="convert Traditional Chinese to Simplified (requires the [simp] extra: OpenCC)",
    )
    gp.add_argument("--human", action="store_true", help="human-readable output")

    args = p.parse_args(argv)
    try:
        if args.cmd == "search":
            results, errors = search_all(args.query, args.source, args.limit)
            obj = {
                "cmd": "search",
                "query": args.query,
                "results": [b.to_dict() for b in results],
                "count": len(results),
                "errors": errors,
            }
        else:  # get
            src = get_source(args.source)
            if src is None:
                raise ValueError(f"unknown source {args.source!r} (known: {', '.join(source_names())})")
            book = Book(source=args.source, id=args.id, title=args.title)
            cached = False
            fr = fetch_cache.load(args.source, args.id) if not args.force else None
            if fr is None:
                fr = src.fetch(book)
                fetch_cache.save(args.source, args.id, fr)
            else:
                cached = True
                fr.out_path = ""
            fr = _render_get(src, fr, args)
            d = fr.to_dict()
            d["cached"] = cached
            obj = {"cmd": "get", "result": d}

        if getattr(args, "human", False) and args.cmd == "search":
            _human_search(obj)
        elif getattr(args, "human", False) and args.cmd == "get":
            _human_get(obj)
        else:
            print(json.dumps(obj, ensure_ascii=False))
        return 0
    except (ValueError, FetchError) as e:
        print(json.dumps({"cmd": getattr(args, "cmd", None), "error": str(e)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())
