"""N2 desktop shell — pywebview window over the shared web frontend.

Three forms, one core:
  CLI          cli.py            (search/get/serve…)
  Browser UI   server.py         (bookfetch serve)
  Desktop App  gui_app.py        (this module — bookfetch gui)

The window loads the SAME frontend from a localhost HTTP server (not file://):
pywebview's js_api bridge proved unreliable on file:// pages (bridge never
injected on macOS 6.x, and WebKit forbids fetch() on file:// origins — every
API call dies with "The string did not match the expected pattern"). Pointing
the shell at 127.0.0.1 makes the frontend use its plain http transport, which
is byte-for-byte the path already exercised by `bookfetch serve`. All
search/download/render logic lives in n2core + cli._render_get regardless of
which of the three forms is running.
"""

from __future__ import annotations

import threading
from http.server import ThreadingHTTPServer

from . import n2core
from .server import _Handler

_WIDTH, _HEIGHT = 1080, 780
_MIN_W, _MIN_H = 860, 600


def run(debug: bool = False) -> int:
    """Open the desktop window. Blocks until the window is closed."""
    try:
        import webview
    except ImportError:
        print(
            "桌面 App 需要 GUI 依赖：uv sync --extra gui  或  pip install 'bookfetch[gui]'",
            file=__import__("sys").stderr,
        )
        return 2

    n2core.library_dir().mkdir(parents=True, exist_ok=True)  # shelf root exists
    from .logging_setup import setup_logging

    setup_logging(n2core.config_dir())  # idempotent; CLI main also calls it
    n2core.apply_proxy()  # idempotent; persisted proxy from the settings panel

    # localhost-only server on a random free port; frontend talks to it over
    # plain http (same code path as `bookfetch serve`, fully exercised).
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    webview.create_window(
        "bookfetch",
        f"http://127.0.0.1:{port}/",
        width=_WIDTH,
        height=_HEIGHT,
        min_size=(_MIN_W, _MIN_H),
    )
    webview.start(debug=debug)  # blocks until the window closes
    httpd.shutdown()
    return 0


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="bookfetch gui", description="桌面阅读 App（pywebview 壳）")
    ap.add_argument("--debug", action="store_true", help="打开 WebView 开发者工具")
    args = ap.parse_args(argv)
    return run(debug=args.debug)


if __name__ == "__main__":
    raise SystemExit(main())
