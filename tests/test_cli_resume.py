"""CLI `get` 逐章断点续传（2026-11：命令行与桌面保持一致）。

同一实现 fetch_cache.Checkpoint：每成功一章追加 --out/<书名>.txt.part +
.part.meta 续传点；中断后重跑同一条 get 从 index+1 继续；完成后清残留。
全部 mock，无网络。
"""

from __future__ import annotations

import json

import pytest

from bookfetch.model import Chapter, FetchResult
from bookfetch.util import FetchError


class _ChapSrc:
    """N 章的假源：fail_at=k → 第 k 章（0 起）抛 FetchError 模拟中断。"""

    def __init__(self, n=5, fail_at=None):
        self.n = n
        self.fail_at = fail_at
        self.resume_calls = []

    def fetch(self, book, *, on_progress=None, on_checkpoint=None, resume_from=0):
        self.resume_calls.append(resume_from)
        chs = []
        for i in range(resume_from, self.n):
            if self.fail_at is not None and i == self.fail_at:
                raise FetchError("模拟网络中断")
            c = Chapter(f"第{i + 1}章", f"正文{i + 1}")
            chs.append(c)
            if on_checkpoint:
                on_checkpoint(i, c)
        content = "\n".join(c.text for c in chs)
        return FetchResult(
            source=book.source, id=book.id, title="续传书",
            chars=len(content), lines=len(chs), format="txt",
            content=content, chapters=chs,
        )


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("BOOKFETCH_CACHE", str(tmp_path / "cache"))
    return tmp_path / "out"


def _run(cli_mod, out, *extra):
    return cli_mod.main(["get", "fake", "7", "--title", "续传书", "--out", str(out), *extra])


def test_cli_get_resumes_after_interrupt(env, monkeypatch, capsys):
    import bookfetch.cli as cli_mod

    out = env
    src = _ChapSrc(n=5, fail_at=3)
    monkeypatch.setattr("bookfetch.cli.get_source", lambda name: src)

    # 第一次：第 4 章（index 3）中断 → 非 0 退出，断点保留
    assert _run(cli_mod, out) != 0
    part, meta = out / "续传书.txt.part", out / "续传书.txt.part.meta"
    assert part.exists() and meta.exists()
    m = json.loads(meta.read_text(encoding="utf-8"))
    assert m["index"] == 2 and m["source"] == "fake" and m["id"] == "7"
    assert "正文3" in part.read_text(encoding="utf-8")
    capsys.readouterr()

    # 第二次：同一命令自动从 index 3 续传
    src.fail_at = None
    assert _run(cli_mod, out) == 0
    assert src.resume_calls == [0, 3]
    res = json.loads(capsys.readouterr().out)["result"]
    assert res["resumed_from"] == 3
    text = (out / "续传书.txt").read_text(encoding="utf-8")
    for i in range(1, 6):
        assert f"正文{i}" in text
    assert text.count("正文1") == 1  # 不重复
    assert not part.exists() and not meta.exists()


def test_cli_get_force_discards_partial(env, monkeypatch, capsys):
    import bookfetch.cli as cli_mod

    out = env
    src = _ChapSrc(n=4, fail_at=2)
    monkeypatch.setattr("bookfetch.cli.get_source", lambda name: src)
    assert _run(cli_mod, out) != 0
    assert (out / "续传书.txt.part").exists()
    capsys.readouterr()

    src.fail_at = None
    assert _run(cli_mod, out, "--force") == 0
    assert src.resume_calls == [0, 0]  # --force 从头下
    res = json.loads(capsys.readouterr().out)["result"]
    assert "resumed_from" not in res
    text = (out / "续传书.txt").read_text(encoding="utf-8")
    assert text.count("正文1") == 1
    assert not (out / "续传书.txt.part").exists()


def test_cli_get_cached_skips_checkpoint(env, monkeypatch, capsys):
    import bookfetch.cli as cli_mod

    out = env
    src = _ChapSrc(n=2)
    monkeypatch.setattr("bookfetch.cli.get_source", lambda name: src)
    assert _run(cli_mod, out) == 0
    capsys.readouterr()
    assert _run(cli_mod, out) == 0
    assert src.resume_calls == [0]  # 第二次走缓存，不再请求源
    assert json.loads(capsys.readouterr().out)["result"]["cached"] is True


def test_ctext_resume_skips_done_pages_and_checkpoints(monkeypatch):
    from bookfetch.model import Book
    from bookfetch.sources import ctext as ct

    res = "".join(f'<a href="wiki.pl?if=gb&chapter={c}">某書</a>' for c in (11, 22, 33))

    def page(n):
        return f'<tr><td class="ctext" style="width: 60px;">1</td><td class="ctext">第{n}頁正文</td></tr>'

    fetched = []

    def fake_fetch(url, *a, **kw):
        fetched.append(url)
        if "res=" in url:
            return res
        cid = url.rsplit("=", 1)[1]
        return page({"11": 1, "22": 2, "33": 3}[cid])

    monkeypatch.setattr(ct, "fetch", fake_fetch)
    cps = []
    fr = ct.Ctext().fetch(
        Book(source="ctext", id="999", title="某書"),
        on_checkpoint=lambda i, c: cps.append((i, c.text)),
        resume_from=1,
    )
    assert not any("chapter=11" in u for u in fetched)  # 已下页跳过
    assert [i for i, _ in cps] == [1, 2]
    assert "第2頁正文" in cps[0][1] and "第3頁正文" in cps[1][1]
    assert len(fr.chapters) == 2


def test_ctext_resume_past_end_returns_empty_not_error(monkeypatch):
    from bookfetch.model import Book
    from bookfetch.sources import ctext as ct

    monkeypatch.setattr(ct, "fetch", lambda url, *a, **kw: '<a href="x?chapter=1">書</a>')
    fr = ct.Ctext().fetch(Book(source="ctext", id="1", title="書"), resume_from=1)
    assert fr.chapters == [] and fr.content == ""


def test_untitled_books_get_distinct_partial_names():
    """无书名（CLI 不带 --title）→ <source>-<id>，不共用 untitled.txt.part。"""
    from bookfetch.fetch_cache import partial_fname
    from bookfetch.model import Book

    assert partial_fname(Book(source="biquge", id="1", title="")) == "biquge-1"
    assert partial_fname(Book(source="biquge", id="2", title="")) == "biquge-2"
    assert partial_fname(Book(source="biquge", id="1", title="三国演义")) == "三国演义"
