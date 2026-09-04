"""HTTP serve layer tests — the transport the browser UI and the desktop shell share.

The desktop shell (gui_app) points its window at a localhost ThreadingHTTPServer
running the exact same _Handler, so this file covers both forms. All API calls
used here are local-only (no network).
"""

import json
import threading
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from bookfetch.server import _Handler

_httpd: ThreadingHTTPServer | None = None
_base = ""


def setup_module():
    global _httpd, _base
    _httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    _base = f"http://127.0.0.1:{_httpd.server_address[1]}"
    threading.Thread(target=_httpd.serve_forever, daemon=True).start()


def teardown_module():
    if _httpd:
        _httpd.shutdown()


def _api(name: str, params: dict | None = None):
    req = Request(
        f"{_base}/api/{name}",
        data=json.dumps(params or {}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urlopen(req) as r:
        return json.loads(r.read().decode("utf-8"))


def _get(path: str) -> tuple[int, bytes]:
    try:
        with urlopen(f"{_base}{path}") as r:
            return r.status, r.read()
    except HTTPError as e:
        return e.code, b""


def test_index_served():
    status, body = _get("/")
    assert status == 200
    assert b"bookfetch" in body


def test_assets_served_from_document_root():
    """Frontend references assets relatively (vendor/, style.css, app.js) — the
    same URLs a file:// page resolves — so the server must serve them at /<name>."""
    for path in ("/style.css", "/app.js", "/vendor/pico.min.css"):
        status, body = _get(path)
        assert status == 200, path
        assert len(body) > 500, path


def test_api_library_and_sources_local():
    lib = _api("library")
    assert lib["library"].endswith("Books")
    srcs = _api("sources")
    assert len(srcs["sources"]) >= 6


def test_api_unknown_name_returns_400():
    status, _ = _get("/api/nope")
    assert status == 400


def test_unknown_path_404():
    status, _ = _get("/no/such/file.txt")
    assert status == 404
