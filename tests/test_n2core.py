"""Offline tests for the N2 core (shelf / reader / progress / download)."""

import json
import sys
import time
from pathlib import Path

import pytest

from bookfetch import n2core, fetch_cache
from bookfetch.model import Book, Chapter, FetchResult
from bookfetch.util import CancelledError
from bookfetch.util.epub import build_epub
from bookfetch.util.translator import split_reader_paras


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
    assert ob["translate"] is (sys.platform == "darwin")  # A3：平台翻译可用性随书返回
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


def test_reader_base_detect_zhouyi_simplified_book(env):
    """简体周易（乾卦名 t2s 词典会转"干"）必须判 simp——旧单向 t2s 探测被
    乾→干 虚高改动数误导判成 trad，导致切简实际执行 t2s、全章只有"乾→干"。
    （2026-09-05 实测反馈：'点击繁切简，简切繁，只有乾这一个字变了'）"""
    rel = _write_book(env, "周易", [
        Chapter("上经 乾卦第一", "乾下乾上 《乾》：元，亨，利，贞。初九：潜龙勿用。九二：见龙在田，利见大人。九三：君子终日乾乾，夕惕若厉，无咎。大哉乾元，万物资始。"),
    ])
    ob = n2core.open_book(rel)
    assert ob["base"] == "simp"
    # 简体原文保持：t2s(切简)不动乾；s2t(切繁)正常出繁体且乾 仍为乾
    c = n2core.chapter(rel, 0)
    assert "乾下乾上" in c["text"] and "见龙在田" in c["text"]
    c2 = n2core.chapter(rel, 0, simp=True)
    assert "乾下乾上" in c2["text"] and "見龍在田" in c2["text"] and "乾" in c2["text"]
    assert "干" not in c2["text"]  # qián 专名全保持，繁体态不应出现"干"


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

    def fetch(self, book, *, on_progress=None, on_checkpoint=None, resume_from=0):
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


class _ChapSrc:
    """10 章全速逐章源：记录 resume_from（B4c 续传断言用）。"""

    name = "chapsrc"
    total = 10

    def __init__(self):
        self.resume_seen = []

    def fetch(self, book, *, on_progress=None, on_checkpoint=None, resume_from=0):
        self.resume_seen.append(resume_from)
        chs = []
        for i in range(resume_from, self.total):
            if on_progress and not on_progress(i, self.total):
                raise CancelledError()
            c = Chapter(title=f"第{i}章", text=f"正文{i}")
            chs.append(c)
            if on_checkpoint:
                on_checkpoint(i, c)
        return FetchResult(
            source=self.name, id=book.id, title=book.title, chars=0, lines=0,
            format="txt", content="", chapters=chs,
        )


def _seed_partial(env, name: str, n: int, meta: dict) -> Path:
    """预置书库半成品（.part + .meta），模拟重启后的残留状态（checkpoint 同款格式）。"""
    lib = env / "Books"
    lib.mkdir(parents=True, exist_ok=True)
    blocks = [f"=== 第{i}章 ===\n正文{i}" for i in range(n)]
    (lib / f"{name}.txt.part").write_text("\n\n".join(blocks) + "\n", encoding="utf-8")
    (lib / f"{name}.txt.part.meta").write_text(
        json.dumps(meta, ensure_ascii=False), encoding="utf-8"
    )
    return lib / f"{name}.txt.part"


def test_download_cancel_sets_cancelled_status(env, monkeypatch):
    """cancel() → the cooperative hook aborts the fetch with CancelledError."""
    from bookfetch.util import CancelledError

    class _CancelSrc:
        name = "cancelsrc"

        def fetch(self, book, *, on_progress=None, on_checkpoint=None, resume_from=0):
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


def test_download_queue_caps_concurrency_and_queued_cancel(env, monkeypatch):
    """并发上限 3：第 4 个任务 queued；排队中的任务可直接取消不阻塞。"""
    import threading

    gate = threading.Event()
    active = []

    class _GateSrc:
        name = "gatesrc"

        def fetch(self, book, *, on_progress=None, on_checkpoint=None, resume_from=0):
            active.append(book.id)
            gate.wait(5)
            return FetchResult(
                source=self.name, id=book.id, title=f"门卫{book.id}",
                chars=4, lines=1, format="txt",
                content="正文", chapters=[Chapter("章", "正文")],
            )

    monkeypatch.setattr("bookfetch.n2core.get_source", lambda name: _GateSrc())
    ids = [n2core.download("gatesrc", str(i), title=f"门卫{i}", fmt="txt")["task_id"] for i in range(4)]
    try:
        t0 = time.time()
        while len(active) < 3 and time.time() - t0 < 5:
            time.sleep(0.02)
        assert len(active) == 3, "前 3 个任务应同时进入 fetch（并发上限 3）"
        assert n2core.task_status(ids[3])["status"] == "queued"
        st = n2core.cancel(ids[3])
        assert st["ok"] is True
        assert _wait_task(ids[3])["status"] == "cancelled"
    finally:
        gate.set()  # 释放卡住的 fetch，防槽位泄漏卡死后续测试
    for tid in ids[:3]:
        assert _wait_task(tid)["status"] == "done"


def test_b4_partial_survives_cancel_and_resumes(env, monkeypatch):
    """B4 断点续传：取消后 .part+meta 保留 → 重下同书自动续传 → 完成清理。

    边下边读：下载中任务能通过 task_status.partial_rel 打开已下部分。
    """
    import threading

    from bookfetch.util import CancelledError

    class _ChSrc:
        name = "chsrc"

        def __init__(self):
            self.gate = threading.Event()  # 章间门闩：模拟真实网络延迟
            self.resume_seen = []
            self.fetched = []  # 成功章 toc 索引

        def fetch(self, book, *, on_progress=None, on_checkpoint=None, resume_from=0):
            self.resume_seen.append(resume_from)
            chs = []
            for i in range(resume_from, 10):
                if len(self.fetched) >= 5:
                    self.gate.wait(5)  # 抓满 5 章后停下等主线程（模拟慢网）
                if on_progress and not on_progress(i, 10):
                    raise CancelledError()
                c = Chapter(title=f"第{i}章", text=f"正文{i}")
                chs.append(c)
                self.fetched.append(i)
                if on_checkpoint:
                    on_checkpoint(i, c)
            return FetchResult(
                source=self.name, id=book.id, title="长夜书", chars=0, lines=0,
                format="txt", content="", chapters=chs,
            )

    s = _ChSrc()
    monkeypatch.setattr("bookfetch.n2core.get_source", lambda name: s)

    # 第一次下载：抓满 5 章后取消
    r1 = n2core.download("chsrc", "7", title="长夜书", fmt="txt")
    t0 = time.time()
    while len(s.fetched) < 5 and time.time() - t0 < 10:
        time.sleep(0.02)
    assert n2core.cancel(r1["task_id"])["ok"] is True
    s.gate.set()  # 放行：源撞上 on_progress → CancelledError
    assert _wait_task(r1["task_id"])["status"] == "cancelled"

    # 取消后：.part（可读）+ meta 保留
    part = env / "Books" / "长夜书.txt.part"
    meta = env / "Books" / "长夜书.txt.part.meta"
    assert part.exists() and meta.exists()
    # meta 存完整任务元信息（书架「继续下载」resume_partial 靠它还原 download 参数）
    m = json.loads(meta.read_text(encoding="utf-8"))
    assert m == {"source": "chsrc", "id": "7", "title": "长夜书", "fmt": "txt", "index": 4}
    st = n2core.task_status(r1["task_id"])
    assert st["partial_rel"] == "长夜书.txt.part"
    # .part 打开即可读（split_rendered 还原 5 章）
    ob = n2core._open(part)
    assert [c.title for c in ob.chapters] == [f"第{i}章" for i in range(5)]

    # 第二次下载同书：自动续传（resume_from=5），只抓尾段
    r2 = n2core.download("chsrc", "7", title="长夜书", fmt="txt")
    assert _wait_task(r2["task_id"])["status"] == "done"
    assert s.resume_seen == [0, 5], s.resume_seen
    assert len(s.fetched) == 10  # 0..4 + 5..9，无重复无遗漏
    # 完成：.part/meta 清理，正式书完整 10 章
    assert not part.exists() and not meta.exists()
    shelf_books = {b["rel"]: b for b in n2core.shelf()["books"]}
    assert "长夜书.txt" in shelf_books
    ob = n2core._open(env / "Books" / "长夜书.txt")
    assert [c.title for c in ob.chapters] == [f"第{i}章" for i in range(10)]


def test_resume_partial_fast_path_from_bookcase(env, monkeypatch):
    """书架「继续下载」快路径（2026-09-05）：meta 含完整任务信息 → 直接续传。

    模拟应用重启后的书库残留（_TASKS 内存态已清，.part/.meta 在位）——
    resume_partial 是半成品的唯一恢复入口。
    """
    s = _ChapSrc()
    monkeypatch.setattr("bookfetch.n2core.get_source", lambda name: s)
    _seed_partial(
        env, "长夜书", 5,
        {"source": "chapsrc", "id": "7", "title": "长夜书", "fmt": "txt", "index": 4},
    )
    r = n2core.resume_partial("长夜书.txt.part")
    assert r["title"] == "长夜书" and r["fmt"] == "txt" and r["task_id"]
    st = _wait_task(r["task_id"])
    assert st["status"] == "done", st
    assert s.resume_seen == [5]  # 从最后成功章 index+1 续传，已下 5 章不重抓
    assert not (env / "Books" / "长夜书.txt.part").exists()  # 完成：半成品清理
    ob = n2core._open(env / "Books" / "长夜书.txt")
    assert [c.title for c in ob.chapters] == [f"第{i}章" for i in range(10)]


def test_resume_partial_old_meta_recovers_id_by_search(env, monkeypatch):
    """旧版 meta（只有 source+index，无 id）→ 按书名在该源内搜索找回同名条目续传。"""
    s = _ChapSrc()
    monkeypatch.setattr("bookfetch.n2core.get_source", lambda name: s)
    seen = {}

    def _fake_search(query, sources=None, limit=30):
        seen["q"], seen["s"] = query, sources
        return {"results": [{"source": "chapsrc", "id": "7", "title": "长夜书"}]}

    monkeypatch.setattr("bookfetch.n2core.search", _fake_search)
    _seed_partial(env, "长夜书", 4, {"source": "chapsrc", "index": 3})
    r = n2core.resume_partial("长夜书.txt.part")
    assert seen == {"q": "长夜书", "s": ["chapsrc"]}
    st = _wait_task(r["task_id"])
    assert st["status"] == "done", st
    assert s.resume_seen == [4]  # meta.index=3 → resume_from=4
    ob = n2core._open(env / "Books" / "长夜书.txt")
    assert len(ob.chapters) == 10  # 旧 4 章 + 新 6 章，无重复无遗漏


def test_resume_partial_old_meta_no_match_raises(env, monkeypatch):
    """搜索找不回同名条目 → 中文报错引导（绝不静默续到别的书）。"""
    monkeypatch.setattr(
        "bookfetch.n2core.search", lambda q, sources=None, limit=30: {"results": []}
    )
    _seed_partial(env, "长夜书", 3, {"source": "chapsrc", "index": 2})
    with pytest.raises(ValueError, match="找不到"):
        n2core.resume_partial("长夜书.txt.part")


def test_resume_partial_old_meta_multiple_hits_raises(env, monkeypatch):
    """同名多命中（转载版，biquge 將夜/詭秘之主 实测各 3-5 条）→ 不自动挑，引导手动选。"""
    monkeypatch.setattr(
        "bookfetch.n2core.search",
        lambda q, sources=None, limit=30: {
            "results": [
                {"source": "chapsrc", "id": "7", "title": "长夜书"},
                {"source": "chapsrc", "id": "8", "title": "长夜书"},
                {"source": "chapsrc", "id": "9", "title": "另一个名字"},
            ]
        },
    )
    _seed_partial(env, "长夜书", 3, {"source": "chapsrc", "index": 2})
    with pytest.raises(ValueError, match="同名条目"):
        n2core.resume_partial("长夜书.txt.part")


def test_partial_meta_id_mismatch_restarts_clean(env, monkeypatch):
    """meta 带 id 时精确绑定任务：同书名不同 id（另一个转载版）→ 不误续旧 .part，
    清空残留从头下（防混版/章节重复）。"""
    s = _ChapSrc()
    monkeypatch.setattr("bookfetch.n2core.get_source", lambda name: s)
    _seed_partial(
        env, "长夜书", 5,
        {"source": "chapsrc", "id": "7", "title": "长夜书", "fmt": "txt", "index": 4},
    )
    r = n2core.download("chapsrc", "8", title="长夜书", fmt="txt")
    st = _wait_task(r["task_id"])
    assert st["status"] == "done", st
    assert s.resume_seen == [0]  # id 不匹配 → 不续传，从头
    ob = n2core._open(env / "Books" / "长夜书.txt")
    assert [c.title for c in ob.chapters] == [f"第{i}章" for i in range(10)]  # 无混版无重复
    assert not (env / "Books" / "长夜书.txt.part").exists()


def test_resume_partial_rejects_non_partial_rel(env):
    _write_book(env, "甲书", [Chapter("卷一", "内容一")])
    with pytest.raises(ValueError, match="未完成"):
        n2core.resume_partial("甲书.txt")


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

        def fetch(self, book, *, on_progress=None, on_checkpoint=None, resume_from=0):
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


# --------------------------------------------------------- translate (N3) ---

def test_translate_chinese_book_zh2en(env, monkeypatch):
    """中文章：dir=zh2en、走桥、译文对齐切段。"""
    _write_book(env, "周易", [Chapter("乾卦", "乾下乾上。\n\n大哉乾元，万物资始。")])
    monkeypatch.setattr(n2core, "_TR_CACHE_DIR", env / "cfg" / "tr")
    seen = {}

    def fake(texts, direction="en2zh"):
        seen["direction"] = direction
        seen["texts"] = list(texts)
        return [f"T{i}" for i in range(len(texts))]

    monkeypatch.setattr("bookfetch.n2core.translate_paragraphs", fake)
    r = n2core.translate("周易.txt", 0)
    assert r["dir"] == "zh2en"
    assert seen["direction"] == "zh2en"
    assert len(r["trs"]) == len(seen["texts"]) > 0
    assert r["trs"][0] == "T0"


def test_translate_english_chapter_caches(env, monkeypatch):
    """英文章：dir=en2zh；译文对齐标题过滤后的段落；二次调用命中磁盘缓存不重翻。"""
    text = ("One two three four five six seven eight nine ten eleven "
            "twelve thirteen fourteen fifteen sixteen.")
    _write_book(env, "EnBook", [Chapter("Ch1", text)])
    monkeypatch.setattr(n2core, "_TR_CACHE_DIR", env / "cfg" / "tr")
    calls = []
    dirs = []

    def fake(texts, direction="en2zh"):
        calls.append(list(texts))
        dirs.append(direction)
        return [f"译{i}" for i in range(len(texts))]

    monkeypatch.setattr("bookfetch.n2core.translate_paragraphs", fake)
    r1 = n2core.translate("EnBook.txt", 0)
    # txt 往返后 c.title=文件名、正文保留内部 "Ch1" 行 → 段落数以实际解析为准
    ob = n2core._open(n2core._resolve("EnBook.txt"))
    expect_n = len(split_reader_paras(ob.chapters[0].text, ob.chapters[0].title))
    assert r1["dir"] == "en2zh"
    assert dirs == ["en2zh"]
    assert len(r1["trs"]) == expect_n
    assert expect_n > 0
    r2 = n2core.translate("EnBook.txt", 0)
    assert r2["trs"] == r1["trs"]
    assert r2["dir"] == "en2zh"
    assert len(calls) == 1                # 缓存命中，桥只调一次


def test_translate_paragraph_count_mismatch_raises(env, monkeypatch):
    _write_book(env, "EnBook", [
        Chapter("Ch1", ("One two three four five six seven eight nine ten eleven "
                        "twelve thirteen fourteen fifteen sixteen.\n\n"
                        "Second para with enough words here to count too."))])
    monkeypatch.setattr(n2core, "_TR_CACHE_DIR", env / "cfg" / "tr")
    monkeypatch.setattr(
        "bookfetch.n2core.translate_paragraphs",
        lambda texts, direction="en2zh": [])
    with pytest.raises(ValueError, match="段落数"):
        n2core.translate("EnBook.txt", 0)


def test_translate_out_of_range(env, monkeypatch):
    _write_book(env, "EnBook", [Chapter("Ch1", "one two three four five six seven")])
    with pytest.raises(ValueError):
        n2core.translate("EnBook.txt", 5)


def test_chapter_dir_flag(env):
    """chapter() 返回 dir（方向唯一判定在后端）：英文章 en2zh、中文章 zh2en。"""
    rel = _write_book(env, "EnBook", [
        Chapter("Ch1", "one two three four five six seven eight nine ten "
                        "eleven twelve thirteen fourteen fifteen")])
    assert n2core.chapter(rel, 0)["dir"] == "en2zh"
    rel2 = _write_book(env, "中書", [Chapter("第一章", "汉字正文内容若干。")])
    assert n2core.chapter(rel2, 0)["dir"] == "zh2en"


def test_open_activator_launches(env, monkeypatch):
    """open_activator 定位激活器并用 open 拉起（detach）。"""
    calls = []

    def fake_find():
        return env / "TranslationActivator.app"

    def fake_popen(cmd):
        calls.append(cmd)
        return object()

    monkeypatch.setattr("bookfetch.util.translator.find_activator", fake_find)
    monkeypatch.setattr(n2core.subprocess, "Popen", fake_popen)
    r = n2core.open_activator()
    assert r["ok"] is True
    assert calls == [["open", str(env / "TranslationActivator.app")]]


def test_open_activator_missing_raises(env, monkeypatch):
    def boom():
        raise ValueError("翻译语言包准备器缺失（macOS 26.4+ 的 bookfetch.app 应自带）")

    monkeypatch.setattr("bookfetch.util.translator.find_activator", boom)
    with pytest.raises(ValueError, match="准备器缺失"):
        n2core.open_activator()


# --------------------------------------------------------- B4c 书架半成品/进度继承 ---

def _write_part(env, name: str, n: int) -> str:
    """写 B4c 半成品库文件（书名.txt.part，=== 标题 === 分隔）"""
    (env / "Books").mkdir(parents=True, exist_ok=True)
    text = "\n\n".join(f"=== 第{i}章 ===\n正文{i}" for i in range(n))
    (env / "Books" / f"{name}.txt.part").write_text(text + "\n", encoding="utf-8")
    return f"{name}.txt.part"


def test_shelf_lists_partial_book_and_skips_residual(env):
    """书架列出未完成下载（.part）：partial 标识 + 已下章数 + 干净书名。

    同名正式书已存在 → .part 残留不双列（正常完成路径会删，防旧残留）。
    """
    rel = _write_part(env, "连载中", 5)
    (env / "Books" / "已完成书.txt").write_text("=== 一 ===\n正文\n", encoding="utf-8")
    _write_part(env, "已完成书", 9)  # 与正式书同名的残留 .part
    books = n2core.shelf()["books"]
    rows = {b["rel"]: b for b in books}
    p = rows[rel]
    assert p["partial"] is True
    assert p["title"] == "连载中"          # 书名.txt.part → 书名
    assert p["chapters"] == 5
    # 正式书条目无 partial 标识；同名残留 .part 不双列
    assert "partial" not in rows["已完成书.txt"]
    assert "已完成书.txt.part" not in rows


def test_partial_progress_inherited_by_formal_book(env):
    """进度 key 归一：读 .part 的进度记在正式书名下 → 下载完成后书架换
    正式条目进度无缝继承（不从头）。"""
    rel = _write_part(env, "追更书", 8)
    n2core.progress_set(rel, chapter_idx=3, pct=500)  # 读半成品到第 4 章
    # .part 条目显示进度
    rows = {b["rel"]: b for b in n2core.shelf()["books"]}
    assert rows[rel]["progress"]["chapter"] == 3
    # 正式书（同书名）打开读到同一进度
    (env / "Books" / "追更书.txt").write_text(
        "\n\n".join(f"=== 第{i}章 ===\n正文{i}" for i in range(120)), encoding="utf-8")
    pg = n2core.progress_get("追更书.txt")
    assert pg["progress"]["chapter"] == 3
    # progress_set 也归一（.part key 不再产生第二份）
    n2core.progress_set("追更书.txt", chapter_idx=5, pct=0)
    assert n2core.progress_get(rel)["progress"]["chapter"] == 5


def test_open_partial_book_clean_title(env):
    rel = _write_part(env, "半本", 3)
    ob = n2core.open_book(rel)
    assert ob["title"] == "半本"
    assert len(ob["chapters"]) == 3


# ------------------------------------------------- 书架管理（删/导/开）---

def _b64(s: bytes) -> str:
    import base64
    return base64.b64encode(s).decode("ascii")


def test_delete_book_removes_file_and_progress(env):
    rel = _write_book(env, "甲书", [Chapter("卷一", "内容一"), Chapter("卷二", "内容二")])
    n2core.progress_set(rel, 1, 500)
    r = n2core.delete_book(rel)
    assert r["ok"] and "甲书.txt" in r["deleted"]
    assert not (env / "Books" / "甲书.txt").exists()
    assert n2core.progress_get(rel)["progress"] == {}


def test_delete_book_partial_cascades_meta_and_norm_progress(env):
    _seed_partial(env, "长夜书", 3, {"source": "chsrc", "id": "7", "title": "长夜书", "fmt": "txt", "index": 2})
    # 半成品阅读进度记在归一的正式书名 key（B4c）——删除必须一并清
    n2core.progress_set("长夜书.txt.part", 2, 100)
    r = n2core.delete_book("长夜书.txt.part")
    assert r["ok"] and "长夜书.txt.part" in r["deleted"] and "长夜书.txt.part.meta" in r["deleted"]
    assert not (env / "Books" / "长夜书.txt.part").exists()
    assert not (env / "Books" / "长夜书.txt.part.meta").exists()
    assert n2core.progress_get("长夜书.txt.part")["progress"] == {}


def test_delete_book_rejects_escape_and_garbage(env):
    with pytest.raises(ValueError):
        n2core.delete_book("../../etc/passwd")
    (env / "Books").mkdir(parents=True, exist_ok=True)
    (env / "Books" / "readme.md").write_text("x", encoding="utf-8")
    with pytest.raises(ValueError):
        n2core.delete_book("readme.md")


def test_import_book_roundtrip_dedup_and_sanitize(env):
    n2core.import_book("新书.txt", _b64("第一章\n\n正文".encode("utf-8")))
    assert (env / "Books" / "新书.txt").exists()
    # 同名不覆盖 → 自动序号
    r = n2core.import_book("新书.txt", _b64(b"dup"))
    assert r["rel"] == "新书(1).txt"
    # 文件名净化：去路径只取 basename（防目录穿越）
    r = n2core.import_book("../怪谈.txt", _b64(b"x"))
    assert r["rel"] == "怪谈.txt"
    assert not (env / "Books" / ".." / "怪谈.txt").exists()
    # 非 txt/epub 拒绝
    with pytest.raises(ValueError, match="只支持"):
        n2core.import_book("evil.pdf", _b64(b"x"))


def test_open_library_opens_finder_on_macos(env, monkeypatch):
    calls = []
    monkeypatch.setattr(n2core.subprocess, "Popen", lambda cmd, **kw: calls.append(cmd))
    r = n2core.open_library()
    assert r["ok"] and calls == [["open", str(env / "Books")]]
