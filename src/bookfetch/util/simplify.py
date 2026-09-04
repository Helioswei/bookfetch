"""Optional Simplified<->Traditional conversion (extra dependency)."""

from __future__ import annotations

_INSTANCES: dict = {}  # tag -> OpenCC；type: ignore 由运行时 import 提供


def _converter(tag: str):
    """Lazy singleton OpenCC handles.

    单例缓存是必须的：OpenCC 构造要载入整本转换字典（~百 ms），
    目录转换逐条调用时若每次新建实例，64 章书要卡 5-15 秒。
    OpenCC convert 无内部可变状态，多线程（serve）共享实例安全。
    """
    try:
        from opencc import OpenCC
    except ImportError as e:
        raise ValueError(
            "简繁转换需要可选依赖：安装 'bookfetch[simp]' "
            "（uv tool install bookfetch --extra simp 或 pip install 'bookfetch[simp]'）"
        ) from e
    if tag not in _INSTANCES:
        _INSTANCES[tag] = OpenCC(tag)
    return _INSTANCES[tag]


def to_simplified(text: str) -> str:
    """Convert Traditional Chinese text to Simplified via OpenCC (t2s)."""
    return _converter("t2s").convert(text)


def to_traditional(text: str) -> str:
    """Convert Simplified Chinese text to Traditional via OpenCC (s2t).

    阅读器「简⇄繁」双向切换需要：简体书转繁体读（s2t），繁体书转简体读（t2s）。
    """
    return _converter("s2t").convert(text)
