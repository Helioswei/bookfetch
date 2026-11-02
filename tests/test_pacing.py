"""防封节奏（2026-11）：每 host 锁、随机间隔、每 ~100 次长休、源级/CLI 覆盖。

time.sleep / random 全部 mock，测试不真睡。
"""

from __future__ import annotations

import argparse
import threading
import time

import pytest

from bookfetch import util


@pytest.fixture(autouse=True)
def clean_pacing(monkeypatch):
    monkeypatch.setattr(util, "_last_request", {})
    monkeypatch.setattr(util, "_req_count", {})
    monkeypatch.setattr(util, "_host_interval", {})
    monkeypatch.setattr(util, "_override_interval", None)
    monkeypatch.setattr(util, "_pace_locks", {})
    yield


def _fake_clock(monkeypatch):
    """可控时钟：sleep 推进 monotonic，记录每次 sleep。"""
    now = [1000.0]
    sleeps = []

    def sleep(s):
        sleeps.append(s)
        now[0] += s

    monkeypatch.setattr(time, "monotonic", lambda: now[0])
    monkeypatch.setattr(time, "sleep", sleep)
    return now, sleeps


def test_default_interval_is_2_to_4():
    assert util.pace_interval("example.org") == (2.0, 4.0)


def test_first_request_no_wait_then_random_interval_in_bounds(monkeypatch):
    now, sleeps = _fake_clock(monkeypatch)
    util._pace("h")
    assert sleeps == []
    for _ in range(30):
        util._pace("h")
    assert len(sleeps) == 30
    assert all(2.0 <= s <= 4.0 for s in sleeps)
    assert len({round(s, 6) for s in sleeps}) > 1  # 随机，不是固定节拍


def test_elapsed_time_counts_toward_interval(monkeypatch):
    now, sleeps = _fake_clock(monkeypatch)
    util.set_pacing(3)
    util._pace("h")
    now[0] += 2.5  # 解析耗时
    util._pace("h")
    assert sleeps == [pytest.approx(0.5)]


def test_rest_every_100_requests(monkeypatch):
    now, sleeps = _fake_clock(monkeypatch)
    util.set_pacing(0)
    for _ in range(250):
        util._pace("h")
    long_ = [s for s in sleeps if s >= 30]
    assert len(long_) == 2  # 第 100、200 次
    assert all(30 <= s <= 60 for s in long_)


def test_hosts_are_independent(monkeypatch):
    now, sleeps = _fake_clock(monkeypatch)
    util._pace("a")
    util._pace("b")
    assert sleeps == []


def test_override_beats_host_beats_default():
    util.set_host_interval("x", 5, 6)
    assert util.pace_interval("x") == (5.0, 6.0)
    assert util.pace_interval("y") == (2.0, 4.0)
    util.set_pacing(1, 1.5)
    assert util.pace_interval("x") == (1.0, 1.5)
    util.set_pacing(3)
    assert util.pace_interval("y") == (3.0, 3.0)
    util.set_pacing(None)
    assert util.pace_interval("x") == (5.0, 6.0)


@pytest.mark.parametrize("lo,hi", [(-1, None), (3, 2)])
def test_invalid_interval_rejected(lo, hi):
    with pytest.raises(ValueError):
        util.set_pacing(lo, hi)


def test_same_host_threads_are_serialized(monkeypatch):
    """锁跨 sleep 持有：并发线程同 host 严格串行，不会同时“睡醒”抢跑。"""
    util.set_pacing(0.05)
    stamps = []
    lk = threading.Lock()

    def worker():
        util._pace("same")
        with lk:
            stamps.append(time.monotonic())

    ts = [threading.Thread(target=worker) for _ in range(4)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(5)
    stamps.sort()
    gaps = [b - a for a, b in zip(stamps, stamps[1:])]
    assert len(stamps) == 4
    assert all(g >= 0.04 for g in gaps), gaps


def test_apply_source_pacing(monkeypatch):
    from bookfetch.sources import apply_source_pacing

    class S:
        min_interval = 3.0
        hosts = ("a.example", "b.example")

    apply_source_pacing(S())
    assert util.pace_interval("a.example") == (3.0, 6.0)
    assert util.pace_interval("b.example") == (3.0, 6.0)

    class T:
        min_interval = (5, 8)
        hosts = ("c.example",)

    apply_source_pacing(T())
    assert util.pace_interval("c.example") == (5.0, 8.0)

    class U:  # 未设置 → 不改动
        min_interval = None
        hosts = ("d.example",)

    apply_source_pacing(U())
    assert util.pace_interval("d.example") == (2.0, 4.0)


def test_builtin_sources_keep_default_strategy():
    """本次只加能力，不改任何源的策略：内置源均未设置 min_interval。"""
    from bookfetch.sources import _REGISTRY

    assert all(getattr(s, "min_interval", None) is None for s in _REGISTRY.values())


@pytest.mark.parametrize("v,exp", [("3", (3.0, 3.0)), ("2-4", (2.0, 4.0)), ("0", (0.0, 0.0)), ("1.5-2.5", (1.5, 2.5))])
def test_parse_delay_ok(v, exp):
    from bookfetch.cli import _parse_delay

    assert _parse_delay(v) == exp


@pytest.mark.parametrize("v", ["abc", "4-2", "-1", "1-x"])
def test_parse_delay_bad(v):
    from bookfetch.cli import _parse_delay

    with pytest.raises(argparse.ArgumentTypeError):
        _parse_delay(v)


def test_cli_delay_flag_sets_and_clears_override(tmp_path, monkeypatch):
    import bookfetch.cli as cli_mod
    from bookfetch.model import FetchResult

    monkeypatch.setenv("BOOKFETCH_CACHE", str(tmp_path / "cache"))
    seen = []

    class Src:
        def fetch(self, book, **kw):
            seen.append(util.pace_interval("any.host"))
            return FetchResult(source="f", id=book.id, title="节奏书", chars=1, lines=1, format="txt", content="x")

    monkeypatch.setattr("bookfetch.cli.get_source", lambda name: Src())
    out = str(tmp_path / "out")
    assert cli_mod.main(["get", "f", "1", "--out", out, "--delay", "5-7"]) == 0
    assert cli_mod.main(["get", "f", "2", "--out", out]) == 0
    assert seen == [(5.0, 7.0), (2.0, 4.0)]
