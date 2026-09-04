"""Optional Simplified<->Traditional conversion (extra dependency)."""

from __future__ import annotations

import re

_INSTANCES: dict = {}  # tag -> OpenCC；type: ignore 由运行时 import 提供

# 乾(qián) 专名保护：OpenCC t2s 词典把「乾」一律转「干」(gān 义)，但 乾坤/乾卦/乾元/
# 乾下乾上/乾乾/乾为天 等 qián 语境是专名，切简后不应变（2026-09-05 周易实测：
# '乾下乾上'→'干下干上'、'乾乾'→'干干'、《乾》→《干》）。
# 实现：t2s 转换前把整词冻结成私用区占位符（OpenCC 不碰），转换后解冻还原——
# 比输出后正则还原安全：不会误伤「乾乾淨淨」→"干干净净"这类真该简化的连续"干干"。
_QIAN_WORDS = ("乾坤", "乾元", "乾卦", "乾下", "乾上", "乾为", "乾爲",
               "乾阳", "乾陽", "乾龙", "乾龍", "乾纲", "乾宅", "终日乾乾", "乾隆")
_QIAN_FREEZE = {w: chr(0xE000 + i) for i, w in enumerate(_QIAN_WORDS)}


def _freeze_qian(s: str) -> str:
    for w, ph in _QIAN_FREEZE.items():
        s = s.replace(w, ph)
    return s


def _thaw_qian(s: str) -> str:
    for w, ph in _QIAN_FREEZE.items():
        s = s.replace(ph, w)
    return s


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
    out = _converter("t2s").convert(_freeze_qian(text))
    out = _thaw_qian(out)
    return out.replace("《干》", "《乾》")  # 单字卦名「《乾》」不在词表，输出后精确还原


def to_traditional(text: str) -> str:
    """Convert Simplified Chinese text to Traditional via OpenCC (s2t).

    阅读器「简⇄繁」双向切换需要：简体书转繁体读（s2t），繁体书转简体读（t2s）。
    """
    return _converter("s2t").convert(text)
