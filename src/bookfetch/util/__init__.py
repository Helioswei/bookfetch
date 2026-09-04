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


class HumanVerificationError(FetchError):
    """The source answered with an anti-bot / human-verification page
    (Cloudflare challenge, ctext-style CAPTCHA, …). Raised instead of a
    silent empty parse so failures are never quiet (D1 addendum)."""


class CancelledError(Exception):
    """Raised inside a source fetch loop when the user cancelled the job
    (checked cooperatively at chapter boundaries via the on_progress hook)."""


# Anti-bot markers seen in the wild (lowercased, matched against the head of
# the page).  ctext: "Please confirm that you are human! 敬請輸入認證圖案";
# Cloudflare: "Just a moment...", cf-challenge, challenge-platform.
_CHALLENGE_MARKS = (
    "please confirm that you are human",
    "just a moment",
    "cf-challenge",
    "challenge-platform",
    "checking your browser",
    "attention required",
    "認證圖案",
    "验证图案",
    "verify you are human",
)


def looks_like_challenge(text: str) -> bool:
    """True if the page looks like an anti-bot verification page.

    Checked only on the head (challenge pages are small) with distinctive
    markers, so normal book text / small pages are never misclassified.
    """
    head = text[:8192].lower()
    return any(m in head for m in _CHALLENGE_MARKS)


def _pace(host: str) -> None:
    now = time.monotonic()
    last = _last_request.get(host, 0.0)
    wait = _MIN_INTERVAL - (now - last)
    if wait > 0:
        time.sleep(wait)
    _last_request[host] = time.monotonic()


def fetch(url: str, *, timeout: float = 30.0, retries: int = _max_retries) -> str:
    """GET a URL and return decoded text. Retries with backoff on failure.

    A 200 human-verification page (ctext CAPTCHA, Cloudflare interstitial)
    raises HumanVerificationError instead of silently parsing to nothing.
    """
    text = decode_bytes(fetch_bytes(url, timeout=timeout, retries=retries))
    if looks_like_challenge(text):
        raise HumanVerificationError(f"GET {url} 返回人机验证页（源站反爬拦截）")
    return text


def fetch_bytes(url: str, *, timeout: float = 30.0, retries: int = _max_retries) -> bytes:
    """GET a URL and return raw bytes. Retries with backoff on failure.

    429 (rate limit) gets a long, Retry-After-aware backoff: sources like
    Wikimedia throttle anonymous bursts and recover in tens of seconds.
    """
    from urllib.parse import urlparse

    host = urlparse(url).netloc
    last_err: Exception | None = None
    for attempt in range(retries + 1):  # +1 spare for the 429 long-wait path
        _pace(host)
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code == 403 and looks_like_challenge(
                decode_bytes(e.read(65536))
            ):
                # Cloudflare "Just a moment..." style block: retrying is
                # pointless (same exit IP → same challenge). Report clearly.
                raise HumanVerificationError(f"GET {url} 被源站人机验证拦截（HTTP 403）")
            if e.code == 429:
                wait = 10.0
                try:
                    wait = max(wait, float(e.headers.get("Retry-After", 10)))
                except (TypeError, ValueError):
                    pass
                time.sleep(wait)
                continue  # rate limit: wait long, then give it another go
            if attempt < retries:
                time.sleep(3.0 * (attempt + 1))  # 3s, 6s backoff
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last_err = e
            if attempt < retries:
                time.sleep(3.0 * (attempt + 1))
    raise FetchError(f"GET {url} 失败（已重试 {retries} 次）：{last_err}")


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
