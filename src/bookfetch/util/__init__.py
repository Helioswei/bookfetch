"""Network + text utilities (stdlib only)."""

from __future__ import annotations

import time
import urllib.error
import urllib.request

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

# Polite per-host pacing: some sources (ctext) block clients that hammer them.
_MIN_INTERVAL = 2.0
_last_request: dict[str, float] = {}
_max_retries = 3


class FetchError(Exception):
    """Raised when a source page cannot be fetched after retries."""


def _pace(host: str) -> None:
    now = time.monotonic()
    last = _last_request.get(host, 0.0)
    wait = _MIN_INTERVAL - (now - last)
    if wait > 0:
        time.sleep(wait)
    _last_request[host] = time.monotonic()


def fetch(url: str, *, timeout: float = 30.0, retries: int = _max_retries) -> str:
    """GET a URL and return decoded text. Retries with backoff on failure."""
    from urllib.parse import urlparse

    host = urlparse(url).netloc
    last_err: Exception | None = None
    for attempt in range(retries):
        _pace(host)
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = resp.read()
            return decode_bytes(data)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as e:
            last_err = e
            if attempt < retries - 1:
                time.sleep(3.0 * (attempt + 1))  # 3s, 6s backoff
    raise FetchError(f"GET {url} failed after {retries} tries: {last_err}")


def decode_bytes(data: bytes) -> str:
    """Decode bytes trying encodings most common in our sources."""
    for enc in ("utf-8", "gb18030", "big5"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def sanitize_filename(name: str) -> str:
    """Make a filesystem-safe name from a book title."""
    out = []
    for ch in name:
        if ch.isalnum() or ch in " ._-()（）【】":
            out.append(ch)
        else:
            out.append("_")
    s = "".join(out).strip(" ._")
    return s or "untitled"
