"""bookfetch CLI — JSON-first output for agents, --human for people."""

from __future__ import annotations

import argparse
import json
import sys

from . import __version__
from .model import Book, FetchResult
from .sources import get_source, search_all, source_names
from .util import FetchError

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
    print(f"Saved: {r['out_path']}")
    print(f"  {r['title']} | {r['lines']} paragraphs | {r['chars']} chars | {r['format']}")


def _simplify_result(fr: FetchResult) -> FetchResult:
    """Rewrite a downloaded txt to Simplified Chinese (filename included)."""
    from pathlib import Path

    from .util import sanitize_filename
    from .util.simplify import to_simplified

    path = Path(fr.out_path)
    text = to_simplified(path.read_text(encoding="utf-8"))
    fname = sanitize_filename(to_simplified(fr.title)) or fr.id
    new_path = path.parent / f"{fname}.txt"
    new_path.write_text(text, encoding="utf-8")
    if new_path != path:
        path.unlink(missing_ok=True)
    return FetchResult(
        source=fr.source,
        id=fr.id,
        title=to_simplified(fr.title),
        out_path=str(new_path),
        chars=len(text),
        lines=len(text.splitlines()),
        format="txt",
    )


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
    gp.add_argument("--out", default=".", help="output directory (default: current dir)")
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
            fr = src.fetch(book, out_dir=args.out)
            if args.simplify:
                fr = _simplify_result(fr)
            obj = {"cmd": "get", "result": fr.to_dict()}

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
