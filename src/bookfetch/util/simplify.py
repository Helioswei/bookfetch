"""Optional Simplified<->Traditional conversion (extra dependency)."""

from __future__ import annotations

import re

_INSTANCES: dict = {}  # tag -> OpenCC；type: ignore 由运行时 import 提供

# 乾(qián) 专名保护：OpenCC t2s 词典把「乾」一律转「干」(gān 义)，但 乾坤/乾卦/乾元/
# 乾下乾上/乾乾/乾为天/乾造 等 qián 语境是专名，切简后不应变。
# 实现：t2s 转换前把整词冻结成私用区占位符（OpenCC 不碰），转换后解冻还原。
# 词表按语义类别收敛（2026-09-05 周易+滴天髓全书扫描收口）：
#   卦名/易传：乾坤 乾卦 乾下 乾上 乾为 乾元 乾乾 乾以 乾行 乾知 乾始 乾西北
#   命理(滴天髓)：乾造（男命）乾阳 乾宅 乾纲（乾宅/乾纲属堪舆术数）
#   历史/人名：乾隆（朝代号/年号） 乾龙(乾龙节?)
# 注：乾乾 整词冻结会伤「乾乾淨淨」（同形 gān 义 AABB 词）→ _freeze_qian 先把
# 乾乾淨淨 预简化为"干干净净"（繁简双向都该是这个结果，预替换幂等正确）再冻乾乾。
_QIAN_WORDS = ("乾坤", "乾元", "乾卦", "乾下", "乾上", "乾为", "乾爲", "乾阳", "乾陽",
               "乾龙", "乾龍", "乾纲", "乾宅", "乾隆", "乾乾", "乾造", "乾以", "乾行",
               "乾知", "乾始", "乾西北")
_QIAN_FREEZE = {w: chr(0xE000 + i) for i, w in enumerate(_QIAN_WORDS)}

# 输出侧精确锚点还原：易传里"乾"前随文言虚词/构成固定句式时 OpenCC 转出的"干"
# （如 夫乾/战乎乾/大哉乾乎/辟户谓之乾）。这些组合在简体正常文本里不存在
# （无"夫干/乎干/干乎/谓之干"等词），与 幹义（事之干也/才干）不冲突。
_QIAN_ANCHORS = (("夫干", "夫乾"), ("乎干", "乎乾"), ("干乎", "乾乎"),
                 ("谓之干", "谓之乾"), ("之谓干", "之谓乾"), ("《干》", "《乾》"),
                 ("。干，健也", "。乾，健也"), ("。干，天也", "。乾，天也"),
                 ("”干，阳物也", "”乾，阳物也"), ("曰“干", "曰“乾"))


def _freeze_qian(s: str) -> str:
    s = s.replace("乾乾淨淨", "干干净净")  # gān 义 AABB，防"乾乾"冻结误伤
    for w, ph in _QIAN_FREEZE.items():
        s = s.replace(w, ph)
    return s


def _thaw_qian(s: str) -> str:
    for w, ph in _QIAN_FREEZE.items():
        s = s.replace(ph, w)
    for a, b in _QIAN_ANCHORS:
        s = s.replace(a, b)
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
