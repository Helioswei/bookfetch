"""Offline tests for the optional simplified-Chinese conversion."""

import pytest

opencc = pytest.importorskip("opencc")  # requires the [simp] extra / dev group

from bookfetch.util.simplify import to_simplified, to_traditional


def test_basic_conversion():
    assert to_simplified("淵海子平") == "渊海子平"
    assert to_simplified("五干屬陽，喜合。") == "五干属阳，喜合。"
    assert to_traditional("渊海子平") == "淵海子平"  # s2t 反向（阅读器简书转繁读）
    assert to_traditional("此见仁见智") == "此見仁見智"


def test_qian_qiangua_name_kept_in_t2s():
    """乾(qián) 专名保护：卦名/乾坤/乾乾 切简不得变"干"，而 gān 义(干净)仍正常简化。
    （2026-09-05 周易实测：'乾下乾上' 曾变 '干下干上'、'君子终日乾乾' 变 '君子终日干干'）"""
    for s in ("乾下乾上", "《乾》：元，亨。", "大哉乾元，万物资始",
              "乾卦第一", "乾坤定矣", "乾为天", "乾隆年间", "君子终日乾乾，夕惕若厉"):
        assert to_simplified(s) == s, f"qián 专名被误转: {s} -> {to_simplified(s)}"
    # gān 义不受保护影响（乾乾 不能整词冻结——"乾乾淨淨"里同形）
    assert to_simplified("乾乾淨淨") == "干干净净"
    assert to_simplified("乾杯") == "干杯"


def test_convert_rejects_when_extra_missing(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "opencc":
            raise ImportError("no opencc")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(ValueError, match="simp"):
        to_simplified("淵海子平")
