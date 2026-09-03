"""Offline tests for the optional simplified-Chinese conversion."""

import pytest

opencc = pytest.importorskip("opencc")  # requires the [simp] extra / dev group

from bookfetch.util.simplify import to_simplified


def test_basic_conversion():
    assert to_simplified("淵海子平") == "渊海子平"
    assert to_simplified("五干屬陽，喜合。") == "五干属阳，喜合。"


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
