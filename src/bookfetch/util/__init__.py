"""Network + text utilities.

Fetch layer rides on curl_cffi (MIT) with Chrome TLS-fingerprint impersonation:
plain urllib advertises a Python/OpenSSL TLS fingerprint no matter what
User-Agent header you send, which Cloudflare-class systems flag probabilistically
(this was the likeliest cause of the intermittent biquge/ctext blocks). Also
implements per-host circuit breaking (B) and no-blind-retry on 403 (C).

Public API (used by sources/n2core, stable):
  fetch / fetch_bytes / fetch_bytes_resumable / set_proxy
  FetchError / HumanVerificationError / CancelledError
  looks_like_challenge / decode_bytes / sanitize_filename / _pace
  set_pacing / set_host_interval / pace_interval
"""

from __future__ import annotations

import logging
import sys
import threading
import time
import urllib.request
from pathlib import Path

from curl_cffi import requests as _creq

_log = logging.getLogger("bookfetch")

# Browser impersonation target: curl_cffi maps "chrome" to a recent Chrome
# build and sends matching TLS/HTTP2 fingerprints plus its header set
# (User-Agent, sec-ch-ua, sec-fetch-*, ...). Do NOT add a manual User-Agent —
# that would desync header from fingerprint again.
_IMPERSONATE = "chrome"
_HEADERS = {"Accept-Language": "zh-CN,zh;q=0.9"}

# Polite per-host pacing: some sources (ctext/biquge) block clients that hammer
# them. 2026-11 防封加固：间隔随机化（默认 2–4s，固定节拍易被识别）、每 host
# 一把锁（多线程同 host 严格串行，不再并发抢跑）、每 ~100 次请求长休一次
# （30–60s，长篇连续下载最易被标记）。优先级：set_pacing 全局覆盖（CLI --delay）
# > set_host_interval 源级设置（Source.min_interval）> 默认。
_MIN_INTERVAL = 2.0          # 默认间隔下限（秒）
_MAX_INTERVAL = 4.0          # 默认间隔上限（秒）
_REST_EVERY = 100            # 每 host 每 N 次请求长休一次（≈ N 章）；0 = 关闭
_REST_RANGE = (30.0, 60.0)   # 长休时长（秒）
_last_request: dict[str, float] = {}
_req_count: dict[str, int] = {}
_host_interval: dict[str, tuple[float, float]] = {}
_override_interval: tuple[float, float] | None = None
_pace_locks: dict[str, threading.Lock] = {}
_pace_locks_guard = threading.Lock()


def _norm_interval(lo: float, hi: float | None) -> tuple[float, float]:
    lo = float(lo)
    hi = lo if hi is None else float(hi)
    if lo < 0 or hi < lo:
        raise ValueError(f"invalid pacing interval: {lo}-{hi}")
    return lo, hi


def set_pacing(lo: float | None = None, hi: float | None = None) -> None:
    """Process-wide request interval override (CLI ``--delay``); None = clear.

    ``hi`` omitted -> fixed interval ``lo``. Wins over per-source settings.
    """
    global _override_interval
    _override_interval = None if lo is None else _norm_interval(lo, hi)


def set_host_interval(host: str, lo: float, hi: float | None = None) -> None:
    """Per-host (per-source) interval, e.g. from ``Source.min_interval``."""
    _host_interval[host] = _norm_interval(lo, hi)


def pace_interval(host: str) -> tuple[float, float]:
    """Effective (min, max) seconds between two requests to ``host``."""
    if _override_interval is not None:
        return _override_interval
    return _host_interval.get(host, (_MIN_INTERVAL, _MAX_INTERVAL))


def _pace_lock(host: str) -> threading.Lock:
    with _pace_locks_guard:
        lk = _pace_locks.get(host)
        if lk is None:
            lk = _pace_locks[host] = threading.Lock()
        return lk

# ---- runtime proxy (D1: settings panel) ---------------------------------
# mode "system" = follow env vars + macOS system proxy (probed & passed
# explicitly so libcurl never re-reads env behind our back);
# mode "manual" = route everything through url; mode "none" = direct only.
_PROXY_MODE = "system"
_PROXY_URL = ""


def set_proxy(mode: str = "system", url: str = "") -> None:
    """Switch the process-wide proxy behaviour. Applies to the next request.

    mode: "system" (default: env + macOS system proxy), "manual" (route all
    HTTP(S) through ``url``), or "none" (direct connection).
    """
    global _PROXY_MODE, _PROXY_URL
    if mode not in ("system", "manual", "none"):
        raise ValueError(f"invalid proxy mode: {mode!r}")
    if mode == "manual" and not url:
        raise ValueError("manual proxy mode requires a proxy url")
    _PROXY_MODE, _PROXY_URL = mode, url


def _proxy_for(url: str) -> dict[str, str]:
    """Proxies dict for a single request.

    libcurl reads http(s)_proxy env vars unless CURLOPT_PROXY is explicitly
    set — an empty-string value means "no proxy" and *overrides* env. We always
    pass an explicit dict so behaviour is deterministic:
      * loopback hosts always bypass (local test servers must never ride the
        user's Clash/proxy),
      * "manual" -> the configured url,
      * "none"   -> empty-string values (true direct),
      * "system" -> env first, then macOS system proxy (scutil) as the
        PyInstaller fallback (same resolution as before, now explicit).
    """
    host = (url.split("://", 1)[1].split("/", 1)[0].split(":", 1)[0] if "://" in url else "")
    if host in ("localhost", "127.0.0.1", "::1"):
        return {"http": "", "https": ""}
    if _PROXY_MODE == "manual":
        return {"http": _PROXY_URL, "https": _PROXY_URL}
    if _PROXY_MODE == "none":
        return {"http": "", "https": ""}
    # system
    proxies = urllib.request.getproxies()  # env (lowercase only, urllib-safe)
    if not (proxies.get("http") or proxies.get("https")):
        sys_proxy = _macos_system_proxy()
        if sys_proxy:
            proxies = sys_proxy
    _log.info("proxy mode=system resolved: %s", proxies or "直连")
    return {
        "http": proxies.get("http") or "",
        "https": proxies.get("https") or "",
    }


def _macos_system_proxy() -> dict:
    """Parse `scutil --proxy` for the HTTP(S) proxy (127.0.0.1:port).

    Avoids depending on _scproxy, which PyInstaller cannot bundle (it is a
    statically-linked builtin extension). Returns {} when no proxy is enabled.
    """
    import subprocess

    try:
        out = subprocess.run(
            ["scutil", "--proxy"],
            capture_output=True,
            text=True,
            timeout=3,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    fields: dict[str, str] = {}
    for line in out.splitlines():
        line = line.strip().rstrip(",")
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        fields[key.strip()] = val.strip()
    if fields.get("HTTPEnable") != "1":
        return {}
    host = fields.get("HTTPProxy")
    port = fields.get("HTTPPort")
    if not host or not port:
        return {}
    # SOCKS/HTTP 混合端口（Clash 等）：https 走同一代理（HTTPSProxy 单独设置时除外）
    https_host = fields.get("HTTPSProxy") or host
    https_port = fields.get("HTTPSPort") or port
    return {
        "http": f"http://{host}:{port}",
        "https": f"http://{https_host}:{https_port}",
    }


# ---- circuit breaker (B) ------------------------------------------------
# Per-host: N consecutive source-side failures (challenge, 403, 429, network
# error) open the breaker for a cooldown window; requests during the window
# fail fast with a clear message instead of burning 9s of blind retries.
# A success closes it. Shared state is locked — the GUI server fans out
# concurrent searches across sources and threads.
_BREAK_FAILS = 3
_BREAK_WINDOW = 300.0  # seconds a source stays open after tripping
_breaker: dict[str, dict] = {}  # host -> {"fails": int, "open_until": float}
_breaker_lock = threading.Lock()


def _breaker_open(host: str) -> float:
    """Seconds until the breaker closes; 0.0 = closed.

    Only entries with an armed ``open_until`` count as open; a host merely
    accumulating failures (open_until == 0) is still closed and keeps its
    failure count across calls.
    """
    with _breaker_lock:
        st = _breaker.get(host)
        if not st or st["open_until"] <= 0:
            return 0.0
        left = st["open_until"] - time.monotonic()
        if left <= 0:
            _breaker.pop(host, None)
            return 0.0
        return left


def _breaker_fail(host: str) -> None:
    with _breaker_lock:
        st = _breaker.setdefault(host, {"fails": 0, "open_until": 0.0})
        st["fails"] += 1
        if st["fails"] >= _BREAK_FAILS:
            st["open_until"] = time.monotonic() + _BREAK_WINDOW
            st["fails"] = 0
            _log.warning("circuit breaker OPEN for %s (%ss)", host, _BREAK_WINDOW)


def _breaker_ok(host: str) -> None:
    with _breaker_lock:
        _breaker.pop(host, None)


# ---- errors -------------------------------------------------------------

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
    """Wait until ``host`` may be hit again (thread-safe, randomized).

    The per-host lock is held across the sleep, so concurrent threads hitting
    the same host are strictly serialized and each keeps the full interval.
    """
    import random

    with _pace_lock(host):
        lo, hi = pace_interval(host)
        interval = random.uniform(lo, hi) if hi > lo else lo
        n = _req_count.get(host, 0) + 1
        _req_count[host] = n
        if _REST_EVERY and n % _REST_EVERY == 0:
            rest = random.uniform(*_REST_RANGE)
            _log.info("pacing: %s reached %d requests, resting %.0fs", host, n, rest)
            interval = max(interval, rest)
        last = _last_request.get(host)
        wait = interval - (time.monotonic() - last) if last is not None else 0.0
        if wait > 0:
            time.sleep(wait)
        _last_request[host] = time.monotonic()


def _host_of(url: str) -> str:
    from urllib.parse import urlparse

    return urlparse(url).netloc


def _sleep_backoff(attempt: int, *, base: float = 3.0) -> None:
    """Exponential backoff with jitter (attempt 0 -> ~3s, 1 -> ~6s, ...)."""
    import random

    time.sleep(base * (attempt + 1) * (0.8 + 0.4 * random.random()))


def _do_get(url: str, *, timeout: float, headers: dict | None = None,
            stream: bool = False):
    """One curl_cffi GET (impersonated). Callers own retry/error policy."""
    return _creq.get(
        url,
        impersonate=_IMPERSONATE,
        headers={**_HEADERS, **(headers or {})},
        proxies=_proxy_for(url),
        timeout=timeout,
        stream=stream,
    )


def fetch(url: str, *, timeout: float = 30.0, retries: int = _max_retries) -> str:
    """GET a URL and return decoded text. Retries with backoff on failure.

    Anti-bot pages (ctext CAPTCHA, Cloudflare interstitial) raise
    HumanVerificationError instead of silently parsing to nothing.
    """
    return decode_bytes(fetch_bytes(url, timeout=timeout, retries=retries))


def fetch_bytes(url: str, *, timeout: float = 30.0, retries: int = _max_retries) -> bytes:
    """GET a URL and return raw bytes. Retries with backoff on failure.

    429 (rate limit) gets a long, Retry-After-aware backoff: sources like
    Wikimedia throttle anonymous bursts and recover in tens of seconds.
    403 is never blind-retried (C): a 403 from the same exit IP is a block,
    not a hiccup — report it; the circuit breaker (B) then cools the source
    down instead of letting every concurrent search re-hit it.
    """
    host = _host_of(url)
    left = _breaker_open(host)
    if left > 0:
        raise FetchError(
            f"源站 {host} 暂时不可用（连续失败触发放问保护），约 {int(left)} 秒后自动恢复"
        )

    last_err: Exception | None = None
    for attempt in range(retries + 1):  # +1 spare for the 429 long-wait path
        _pace(host)
        try:
            resp = _do_get(url, timeout=timeout)
        except _creq.errors.RequestsError as e:
            last_err = e
            _breaker_fail(host)
            if attempt < retries:
                _sleep_backoff(attempt)
            continue

        code = resp.status_code
        if code == 200:
            body = resp.content
            if looks_like_challenge(decode_bytes(body[:65536])):
                _breaker_fail(host)
                raise HumanVerificationError(f"GET {url} 返回人机验证页（源站反爬拦截）")
            _breaker_ok(host)
            return body

        if code == 403:
            body = resp.content
            _breaker_fail(host)
            if looks_like_challenge(decode_bytes(body[:65536])):
                raise HumanVerificationError(f"GET {url} 被源站人机验证拦截（HTTP 403）")
            # C: non-challenge 403 = exit blocked; retrying is pointless.
            raise FetchError(f"GET {url} 被源站拒绝（HTTP 403）")

        if code == 429:
            wait = 10.0
            try:
                wait = max(wait, float(resp.headers.get("Retry-After", 10)))
            except (TypeError, ValueError):
                pass
            _breaker_fail(host)
            time.sleep(wait)
            continue  # rate limit: wait long, then give it another go

        # Other 4xx/5xx: transient server-side → backoff and retry.
        last_err = FetchError(f"GET {url} HTTP {code}")
        _breaker_fail(host)
        if attempt < retries:
            _sleep_backoff(attempt)
    raise FetchError(f"GET {url} 失败（已重试 {retries} 次）：{last_err}")


def fetch_bytes_resumable(url: str, dest: Path, *, timeout: float = 60.0,
                          retries: int = _max_retries) -> bytes:
    """Stream a GET to ``dest``, resuming from a previously written partial.

    B4 断点续传（2026-09-05）：dest 已有内容时带 ``Range: bytes=N-`` 续传
    （服务器忽略 Range 返回 200 时整文件重写，稳）；完成后 dest 即完整文件。
    网络错/超时重试间不删 dest —— 残留即下次续传的起点；只有 403 挑战页
    （重试无用）直接抛 HumanVerificationError，不落盘。返回完整 bytes。
    """
    host = _host_of(url)
    left = _breaker_open(host)
    if left > 0:
        raise FetchError(
            f"源站 {host} 暂时不可用（连续失败触发放问保护），约 {int(left)} 秒后自动恢复"
        )

    last_err: Exception | None = None
    for attempt in range(retries + 1):
        _pace(host)
        have = dest.stat().st_size if dest.exists() else 0
        headers = {}
        if have > 0:
            headers["Range"] = f"bytes={have}-"
        try:
            resp = _do_get(url, timeout=timeout, headers=headers, stream=True)
        except _creq.errors.RequestsError as e:
            last_err = e
            _breaker_fail(host)
            if attempt < retries:
                _sleep_backoff(attempt)
            continue

        code = resp.status_code
        if code == 416 and have > 0:
            # 已完整（Range 起点 ≥ 文件尾）：残留即成品
            resp.close()
            _breaker_ok(host)
            return dest.read_bytes()
        if code in (200, 206):
            if code == 200:
                have = 0  # server ignored Range → rewrite from scratch
            try:
                with dest.open("ab" if have > 0 else "wb") as fh:
                    for chunk in resp.iter_content():  # curl buffers internally; no chunk_size
                        if chunk:
                            fh.write(chunk)
            finally:
                resp.close()
            _breaker_ok(host)
            return dest.read_bytes()
        # HTTP errors from the source itself
        resp.close()
        body_head = decode_bytes(resp.content[:65536])
        if code == 403 and looks_like_challenge(body_head):
            _breaker_fail(host)
            raise HumanVerificationError(f"GET {url} 被源站人机验证拦截（HTTP 403）")
        if code == 429:
            wait = 10.0
            try:
                wait = max(wait, float(resp.headers.get("Retry-After", 10)))
            except (TypeError, ValueError):
                pass
            _breaker_fail(host)
            time.sleep(wait)
            continue
        last_err = FetchError(f"GET {url} HTTP {code}")
        _breaker_fail(host)
        if attempt < retries:
            _sleep_backoff(attempt)
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
