"""bookfetch — agent-friendly ebook finder CLI.

版本单一事实源 = pyproject.toml `[project] version`（安装态经 dist-info 暴露，
CLI 由 importlib.metadata 读取）。勿在此加 __version__ 常量——双写必漏
（1.0.0 发布事故，见本地 skill 坑 55）。
"""
