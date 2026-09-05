"""CLI（agent/skill 用）与 UI（serve/gui 用户用）的路径边界。

铁律（2026-09-05 少爷拍板）：UI 的体验机制（并发队列上限、逐章断点
续传、边下边读 .part）只作用于 n2core 任务系统（serve/gui 进程内），
CLI `get` 是同步直连源下载——并发无上限、无队列、无 checkpoint 协议。
CLI 或 agent 脚本若经由此处的任何变化被拖进 UI 任务系统 = 回归。

对照组（UI 下载确实走任务队列）由 tests/test_n2core.py 的
test_download_queue_caps_concurrency_and_queued_cancel 覆盖。
"""


class _CliOnlySrc:
    """CLI 语义的源：fetch 只吃 book，不认任何进度/断点 kwarg。

    若 CLI 路径被改成走 n2core 任务系统（恒传 on_checkpoint/resume_from），
    fetch 签名不匹配会直接 TypeError —— 用签名本身锁死边界。
    """

    def __init__(self):
        self.calls = []

    def fetch(self, book):
        self.calls.append(book)
        from bookfetch.model import Chapter, FetchResult

        return FetchResult(
            source=book.source, id=book.id, title="边界书",
            chars=6, lines=1, format="txt",
            content="正文", chapters=[Chapter("第一章", "正文")],
        )


def test_cli_get_is_direct_sync_and_never_touches_task_system(tmp_path, monkeypatch):
    """CLI get：同步直连源 fetch，不经过 n2core 任务系统（无队列/无断点）。

    哨兵：n2core.download / _run_job / _TASKS 全部换成计数假货——
    CLI 路径只要碰到任务系统任何一个入口，断言即炸。
    """
    import bookfetch.cli as cli_mod
    import bookfetch.n2core as n2core

    monkeypatch.setenv("BOOKFETCH_CACHE", str(tmp_path / "cache"))
    out = tmp_path / "out"

    src = _CliOnlySrc()
    monkeypatch.setattr("bookfetch.cli.get_source", lambda name: src)

    # UI 任务系统哨兵：调用即记录（不允许出现在 CLI 路径）
    touched = []

    def _boom(*a, **kw):
        touched.append(1)
        raise AssertionError("CLI get 不得进入 UI 任务系统")

    monkeypatch.setattr(n2core, "download", _boom)
    monkeypatch.setattr(n2core, "_run_job", _boom)
    monkeypatch.setattr(n2core, "_TASKS", {"t999": "哨兵"})

    # 多本连续 get（agent 批处理典型用法），各自同步直连
    for i in ("1", "2"):
        assert cli_mod.main(["get", "fake", i, "--out", str(out)]) == 0

    # 源被同步直连各调一次；任务系统零触碰
    assert [b.id for b in src.calls] == ["1", "2"]
    assert touched == []
    assert (out / "边界书.txt").exists()
