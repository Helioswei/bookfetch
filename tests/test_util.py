"""Unit tests for shared utilities."""

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from bookfetch.util import decode_bytes, fetch_bytes_resumable, looks_like_challenge, sanitize_filename


def test_decode_utf8():
    assert decode_bytes("淵海子平".encode("utf-8")) == "淵海子平"


def test_decode_gb18030_fallback():
    raw = "渊海子平".encode("gb18030")
    assert decode_bytes(raw) == "渊海子平"


def test_sanitize_filename():
    # ？* map to _ then get stripped from the tail; inner ： becomes _
    assert sanitize_filename("淵海子平：論天干？*") == "淵海子平_論天干"
    assert sanitize_filename("a/b\\c:d") == "a_b_c_d"
    assert sanitize_filename("   ") == "untitled"


def test_looks_like_challenge_detects_antibot_pages():
    """Anti-bot pages must be detected (never silent) — D1 addendum."""
    samples = [
        "<html><head><title>Please confirm that you are human!</title>敬請輸入認證圖案</head></html>",
        "<html><title>Just a moment...</title><script>cf-challenge</script></html>",
        '<html><body><div id="challenge-platform">…</div></body></html>',
        "<html><title>Attention Required! | Cloudflare</title></html>",
    ]
    for s in samples:
        assert looks_like_challenge(s), s[:50]


def test_looks_like_challenge_ignores_normal_pages():
    """Ordinary book text / list pages must never be misclassified."""
    normal = [
        "<html><body><li>道德經正文內容，長篇古籍文字</li></body></html>",
        "Alice's Adventures in Wonderland\nChapter I\nDown the Rabbit-Hole",
        "<html><body>书籍列表页面的正常内容，无验证字样</body></html>",
    ]
    for s in normal:
        assert not looks_like_challenge(s), s[:50]


# ---------------------------------------------------------------------------
# B4: fetch_bytes_resumable — HTTP Range 断点续传（本地真 server 验证）
# ---------------------------------------------------------------------------

_PAYLOAD = bytes(range(256)) * 8  # 2048B


class _RangeHandler(BaseHTTPRequestHandler):
    seen_ranges: list[str] = []
    supports_range = True

    def do_GET(self):  # noqa: N802 (BaseHTTPRequestHandler API)
        rng = self.headers.get("Range")
        self.seen_ranges.append(rng or "")
        body = _PAYLOAD
        if self.supports_range and rng and rng.startswith("bytes="):
            start = int(rng[6:].split("-")[0])
            if start >= len(body):
                self.send_response(416)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            chunk = body[start:]
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{len(body)-1}/{len(body)}")
        else:  # 服务器忽略 Range：整文件 200
            chunk = body
            self.send_response(200)
        self.send_header("Content-Length", str(len(chunk)))
        self.end_headers()
        self.wfile.write(chunk)

    def log_message(self, format, *args):  # noqa: A002 — silence
        pass


def _serve():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _RangeHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    _RangeHandler.seen_ranges = []
    return srv


def test_resumable_resumes_from_partial(monkeypatch, tmp_path):
    """dest 已有部分内容 → 带 Range 续传，成品完整。"""
    import bookfetch.util as util

    monkeypatch.setattr(util, "_pace", lambda host: None)
    srv = _serve()
    try:
        dest = tmp_path / "book.part"
        dest.write_bytes(_PAYLOAD[:500])  # 上次中断的残留
        got = fetch_bytes_resumable(f"http://127.0.0.1:{srv.server_address[1]}/f", dest)
        assert _RangeHandler.seen_ranges == ["bytes=500-"]
        assert got == _PAYLOAD
        assert dest.read_bytes() == _PAYLOAD
    finally:
        srv.shutdown()


def test_resumable_rewrites_when_server_ignores_range(monkeypatch, tmp_path):
    """服务器返 200 全量（无 Range 支持）→ 从零重写，不残留杂糅。"""
    import bookfetch.util as util

    monkeypatch.setattr(util, "_pace", lambda host: None)
    srv = _serve()
    try:
        _RangeHandler.supports_range = False
        dest = tmp_path / "book.part"
        dest.write_bytes(b"garbage-stale-partial")
        got = fetch_bytes_resumable(f"http://127.0.0.1:{srv.server_address[1]}/f", dest)
        assert got == _PAYLOAD
        assert dest.read_bytes() == _PAYLOAD  # 200 分支整文件覆盖
    finally:
        _RangeHandler.supports_range = True
        srv.shutdown()


def test_resumable_fresh_download(monkeypatch, tmp_path):
    """无残留 → 普通全量下载。"""
    import bookfetch.util as util

    monkeypatch.setattr(util, "_pace", lambda host: None)
    srv = _serve()
    try:
        dest = tmp_path / "book.part"
        got = fetch_bytes_resumable(f"http://127.0.0.1:{srv.server_address[1]}/f", dest)
        assert _RangeHandler.seen_ranges == [""]
        assert got == _PAYLOAD
    finally:
        srv.shutdown()
