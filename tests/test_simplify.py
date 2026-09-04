"""Offline tests for the optional simplified-Chinese conversion."""

import pytest

opencc = pytest.importorskip("opencc")  # requires the [simp] extra / dev group

from bookfetch.util.simplify import to_simplified, to_traditional


def test_basic_conversion():
    assert to_simplified("淵海子平") == "渊海子平"
    assert to_simplified("五干屬陽，喜合。") == "五干属阳，喜合。"
    assert to_traditional("渊海子平") == "淵海子平"  # s2t 反向（阅读器简书转繁读）
    assert to_traditional("此见仁见智") == "此見仁見智"


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
