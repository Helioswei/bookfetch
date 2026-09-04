"""Offline tests for the N2 core (shelf / reader / progress / download)."""

import time

import pytest

from bookfetch import n2core, fetch_cache
from bookfetch.model import Book, Chapter, FetchResult
from bookfetch.util.epub import build_epub


@pytest.fixture()
def env(tmp_path, monkeypatch):
    lib = tmp_path / "Books"
    cache = tmp_path / "cache"
    cfg = tmp_path / "cfg"
    monkeypatch.setenv("BOOKFETCH_LIBRARY", str(lib))
    monkeypatch.setenv("BOOKFETCH_CACHE", str(cache))
    monkeypatch.setattr(n2core, "_CFG_DIR", cfg)  # module-level; env var too late
    monkeypatch.setattr(n2core, "_PROGRESS", cfg / "progress.json")
    return tmp_path


def _write_book(env, name: str, chapters: list[Chapter], fmt: str = "txt") -> str:
    lib = env / "Books"
    lib.mkdir(parents=True, exist_ok=True)
    if fmt == "txt":
        text = "\n\n".join(f"{c.title}\n{c.text}" for c in chapters)
        (lib / f"{name}.txt").write_text(text + "\n", encoding="utf-8")
        return f"{name}.txt"
    p = build_epub(name, chapters, lib / f"{name}.epub", creator="test")
    return f"{name}.epub"


# ---------------------------------------------------------------- shelf ---

def test_shelf_scans_library(env):
    _write_book(env, "甲书", [Chapter("卷一", "内容一")])
    _write_book(env, "乙书", [Chapter("chap", "content")], fmt="epub")
    r = n2core.shelf()
    assert r["library"].endswith("Books")
    titles = {b["title"] for b in r["books"]}
    assert titles == {"甲书", "乙书"}
    by = {b["title"]: b for b in r["books"]}
    # 章数随书架返回（前端算整本进度用）；单章书 chapters==1
    assert by["甲书"]["chapters"] == 1
    assert by["乙书"]["chapters"] == 1
    fmts = {b["format"] for b in r["books"]}
    assert fmts == {"txt", "epub"}


def test_path_escape_rejected(env):
    with pytest.raises(ValueError):
        n2core._resolve("../../etc/passwd")


# ---------------------------------------------------------------- read ---

def test_open_txt_chapters(env):
    rel = _write_book(env, "古籍", [
        Chapter("序", "这是序言"),
        Chapter("卷一", "正文第一段"),
        Chapter("卷二", "正文第二段"),
    ])
    ob = n2core.open_book(rel)
    assert ob["format"] == "txt"
    assert [c["title"] for c in ob["chapters"]] == ["序", "卷一", "卷二"]
    c1 = n2core.chapter(rel, 1)
    assert "正文第一段" in c1["text"]


def test_open_flat_txt_single_chapter(env):
    rel = _write_book(env, "无结构书", [Chapter("", "随便的文本没有章节标记")])
    ob = n2core.open_book(rel)
    assert len(ob["chapters"]) == 1


def test_open_own_epub_roundtrip(env):
    chapters = [Chapter("第一章", "第一段内容"), Chapter("第二章", "第二段内容")]
    rel = _write_book(env, "epub书", chapters, fmt="epub")
    ob = n2core.open_book(rel)
    assert ob["format"] == "epub"
    assert [c["title"] for c in ob["chapters"]] == ["第一章", "第二章"]
    assert n2core.chapter(rel, 0)["text"].startswith("第一段内容")
    assert n2core.chapter(rel, 1)["text"].startswith("第二段内容")


# ------------------------------------------------------------- progress ---

def test_proxy_settings_roundtrip(env):
    """settings_set persists + applies; settings_get reads back (D1 addendum)."""
    from bookfetch import util as _u
    from bookfetch.util import set_proxy

    r = n2core.settings_set({"mode": "manual", "url": "http://127.0.0.1:9999"})
    assert r["ok"]
    assert n2core.settings_get()["proxy"] == {"mode": "manual", "url": "http://127.0.0.1:9999"}
    assert _u._PROXY_MODE == "manual" and _u._PROXY_URL == "http://127.0.0.1:9999"
    # corrupt file -> graceful defaults
    (env / "cfg" / "settings.json").write_text("{not json", encoding="utf-8")
    assert n2core.settings_get()["proxy"] == {"mode": "system", "url": ""}
    # invalid mode rejected
    try:
        n2core.settings_set({"mode": "warp"})
        assert False, "invalid mode must raise"
    except ValueError:
        pass
    n2core.settings_set({"mode": "system"})
    set_proxy("system")


def test_reader_simp_conversion(env):
    """open_book/chapter simp=True 输出简体（OpenCC，dev 组已装）。"""
    rel = _write_book(env, "後漢書", [Chapter("卷一 帝紀", "後漢書曰：此見仁見智。")])
    ob = n2core.open_book(rel, simp=True)
    assert ob["chapters"][0]["title"] == "后汉书"  # 未分章时标题=文件名（已转简）
    assert ob["base"] == "trad"
    c = n2core.chapter(rel, 0, simp=True)
    assert "后汉书曰：此见仁见智。" in c["text"] and "後漢書曰" not in c["text"]
    # 不转时保持原文（繁体）
    c2 = n2core.chapter(rel, 0)
    assert "後漢書曰：此見仁見智。" in c2["text"]


def test_reader_traditional_conversion_simplified_book(env):
    """简体书也可切繁（s2t 反向）：base='simp' → simp=True 输出繁体。"""
    rel = _write_book(env, "渊海子平", [Chapter("卷一", "渊海子平曰：此见仁见智。")])
    ob = n2core.open_book(rel)
    assert ob["base"] == "simp"
    ob2 = n2core.open_book(rel, simp=True)
    assert ob2["chapters"][0]["title"] == "卷一"  # 无繁简差异的标题保持原样
    c = n2core.chapter(rel, 0, simp=True)
    assert "淵海子平曰：此見仁見智。" in c["text"] and "渊海子平曰" not in c["text"]
    # 切回原文仍简体
    assert "渊海子平曰：此见仁见智。" in n2core.chapter(rel, 0)["text"]


def test_progress_roundtrip(env):
    _write_book(env, "甲书", [Chapter("卷一", "内容一")])
    n2core.progress_set("甲书.txt", 3, pct=520)
    got = n2core.progress_get("甲书.txt")["progress"]
    assert got == {"chapter": 3, "pct": 520}
    assert n2core.progress_get("不存在.txt")["progress"] == {}


# -------------------------------------------------------------- download ---

class _FakeSrc:
    name = "fake"

    def __init__(self):
        self.calls = 0

    def fetch(self, book, *, on_progress=None):
        self.calls += 1
        return FetchResult(
            source="fake", id=book.id, title=book.title or "假书",
            chars=12, lines=2, format="txt",
            content="第一行\n第二行",
            chapters=[Chapter("第一节", "第一行\n第二行")],
        )


def _wait_task(task_id: str, timeout: float = 10.0) -> dict:
    t0 = time.time()
    while time.time() - t0 < timeout:
        st = n2core.task_status(task_id)
        if st["status"] in ("done", "error", "cancelled"):
            return st
        time.sleep(0.02)
    raise AssertionError("task did not finish")


def test_download_cancel_sets_cancelled_status(env, monkeypatch):
    """cancel() → the cooperative hook aborts the fetch with CancelledError."""
    from bookfetch.util import CancelledError

    class _CancelSrc:
        name = "cancelsrc"

        def fetch(self, book, *, on_progress=None):
            if on_progress and not on_progress(0, 10):
                raise CancelledError()  # what a real multi-chapter source does
            raise AssertionError("on_progress must have returned False after cancel")

    monkeypatch.setattr("bookfetch.n2core.get_source", lambda name: _CancelSrc())
    r = n2core.download("cancelsrc", "9", title="取消书", fmt="txt")
    st = n2core.cancel(r["task_id"])
    assert st["ok"] is True
    st = _wait_task(r["task_id"])
    assert st["status"] == "cancelled", st


def test_cancel_unknown_and_finished(env, monkeypatch):
    assert n2core.cancel("nope")["ok"] is False
    fake = _FakeSrc()
    monkeypatch.setattr("bookfetch.n2core.get_source", lambda name: fake)
    r = n2core.download("fake", "42", title="测试书", fmt="txt")
    _wait_task(r["task_id"])
    st = n2core.cancel(r["task_id"])
    assert st["ok"] is False and "已完成" in st["message"]


def test_download_writes_into_library(env, monkeypatch):
    fake = _FakeSrc()
    monkeypatch.setattr("bookfetch.n2core.get_source", lambda name: fake)
    r = n2core.download("fake", "42", title="测试书", fmt="txt")
    st = _wait_task(r["task_id"])
    assert st["status"] == "done", st
    assert st["out_rel"] == "测试书.txt"
    assert (env / "Books" / "测试书.txt").exists()


def test_download_cached_no_network(env, monkeypatch):
    """Cache hit → source.fetch is never called (N1 archive semantics)."""
    fake = _FakeSrc()
    monkeypatch.setattr("bookfetch.n2core.get_source", lambda name: fake)
    # prime the cache exactly as the CLI does
    fetch_cache.save("fake", "7", _FakeSrc().fetch(Book(source="fake", id="7", title="")))
    r = n2core.download("fake", "7", title="缓存书", fmt="epub")
    st = _wait_task(r["task_id"])
    assert st["status"] == "done", st
    assert fake.calls == 0, "cache hit must skip fetch"
    # cache hit renders from the *cached* title (缓存书 title param is ignored)
    assert (env / "Books" / "假书.epub").exists()


def test_download_raw_passthrough(env, monkeypatch):
    class _RawSrc:
        name = "rawsrc"

        def fetch(self, book, *, on_progress=None):
            return FetchResult(
                source="rawsrc", id=book.id, title="PDF书",
                chars=0, lines=0, format="pdf", content="", chapters=None,
                raw=b"%PDF-1.4 fake bytes",
            )

    monkeypatch.setattr("bookfetch.n2core.get_source", lambda name: _RawSrc())
    r = n2core.download("rawsrc", "x", title="PDF书", fmt="")
    st = _wait_task(r["task_id"])
    assert st["status"] == "done", st
    assert st["out_rel"] == "PDF书.pdf"  # original extension kept
    assert (env / "Books" / "PDF书.pdf").read_bytes() == b"%PDF-1.4 fake bytes"
