"""`bookfetch serve` — stdlib-only HTTP layer over the N2 core.

Static frontend + JSON API. The exact same frontend later runs inside the
pywebview desktop shell (js_api bridge), so this server is just one of two
transports; it also stays useful as a developer/preview mode.
"""

from __future__ import annotations

import json
import mimetypes
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import n2core

_STATIC = Path(__file__).parent / "static"
_PORT_DEFAULT = 8756


def _send_json(handler: BaseHTTPRequestHandler, code: int, obj) -> None:
    body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


def _read_json_body(handler: BaseHTTPRequestHandler) -> dict:
    try:
        n = int(handler.headers.get("Content-Length", 0))
        if n > 0:
            return json.loads(handler.rfile.read(n).decode("utf-8"))
    except Exception:
        pass
    return {}


class _Handler(BaseHTTPRequestHandler):
    server_version = "bookfetch-serve"
    protocol_version = "HTTP/1.1"

    # -- helpers -----------------------------------------------------

    def _static_file(self, rel: str) -> None:
        p = (_STATIC / rel).resolve()
        if _STATIC.resolve() not in p.parents or not p.is_file():
            self.send_error(404)
            return
        data = p.read_bytes()
        ctype, _ = mimetypes.guess_type(p.name)
        self.send_response(200)
        self.send_header("Content-Type", ctype or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def _api(self, name: str) -> None:
        params = _read_json_body(self)
        if self.command == "GET":  # allow GET /api/<name>?k=v for quick tests
            from urllib.parse import parse_qs, urlparse

            qs = parse_qs(urlparse(self.path).query)
            for k, v in qs.items():
                params.setdefault(k, v[0])
        try:
            _send_json(self, 200, n2core.api_call(name, params))
        except Exception as e:
            _send_json(self, 400, {"error": f"{type(e).__name__}: {e}"})

    # -- routes ------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            self._static_file("index.html")
        elif path.startswith("/static/"):
            self._static_file(path.removeprefix("/static/"))
        elif path.startswith("/api/"):
            self._api(path.removeprefix("/api/"))
        else:
            self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802
        if self.path.startswith("/api/"):
            self._api(self.path.removeprefix("/api/"))
        else:
            self.send_error(404)

    def log_message(self, format: str, *args) -> None:  # noqa: A002 — silence per-request logs
        pass


def serve(port: int = _PORT_DEFAULT, open_browser: bool = True) -> None:
    """Run the stdlib HTTP server until Ctrl-C."""
    httpd = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"
    print(f"bookfetch serve → {url}  (Ctrl-C 停止)", flush=True)
    if open_browser:
        threading.Timer(0.3, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")
