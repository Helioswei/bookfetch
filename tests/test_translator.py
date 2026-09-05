"""N3 翻译 util 单测：段落切分对齐 / 英文检测 / 桥缺失容错 / 双向方向。"""

import json

import pytest

from bookfetch.util import translator
from bookfetch.util.translator import has_latin, split_reader_paras, translate_paragraphs


# ----------------------------------------------------- split_reader_paras ---

def test_split_reader_paras_matches_js_rules():
    """与 app.js loadChapter 同一规则：/\\n{2,}|\\n(?=\\S)/ + trim + 标题过滤。

    注意 \\n(?=\\S)：单个换行后接非空白（行首顶格）也会切段——阅读器按行成段。
    """
    text = "Chapter One\n\nThe first line.\nSecond para, still same para.\nline 3.\n\nThird para."
    paras = split_reader_paras(text, title="Chapter One")
    assert paras == [
        "The first line.",
        "Second para, still same para.",
        "line 3.",
        "Third para.",
    ]


def test_split_reader_paras_title_forms():
    text = "第一章\n\n正文一。\n\n《第一章》\n\n正文二。"
    # 标题行两种形态都要滤掉（对齐前端 `s !== title && s !== '《'+title+'》'`）
    assert split_reader_paras(text, title="第一章") == ["正文一。", "正文二。"]


def test_split_reader_paras_no_title():
    text = "段一。\n\n段二。"
    assert split_reader_paras(text, title="") == ["段一。", "段二。"]


def test_split_reader_paras_title_reference_anywhere_filtered():
    """前端是对全数组 filter（不限定位置）——《标题》形态出现在任何位置都会被滤，译文对齐必须一致。"""
    text = "正文一。\n\n《红楼梦》\n\n正文二。"
    assert split_reader_paras(text, title="红楼梦") == ["正文一。", "正文二。"]


# ---------------------------------------------------------- has_latin ---

def test_has_latin_english_passage():
    t = ("The quick brown fox jumps over the lazy dog. " * 6)  # 60+ 词
    assert has_latin(t) is True


def test_has_latin_chinese_with_few_loanwords():
    t = "这是中文正文，偶尔夹一个 word 和 API 这样的英文词，但整体仍以汉字为主。"
    assert has_latin(t) is False


def test_has_latin_threshold_boundary():
    words = " ".join(["word"] * 15)
    assert has_latin(words) is True
    assert has_latin(" ".join(["word"] * 14)) is False


# ------------------------------------------------- translate_paragraphs ---

def test_translate_bridge_missing_raises_friendly(monkeypatch):
    monkeypatch.setattr(translator, "_bridge_candidates", lambda: [])
    with pytest.raises(ValueError, match="翻译桥不可用"):
        translate_paragraphs(["hello"])


def test_translate_paragraphs_empty():
    assert translate_paragraphs([]) == []


def test_translate_paragraphs_payload_dir(monkeypatch, tmp_path):
    """桥协议对象化：载荷含 paras 与 dir（方向直通桥）。"""
    bridge = tmp_path / "bridge"
    bridge.write_text("#!/bin/sh\nexit 0\n")
    bridge.chmod(0o755)
    monkeypatch.setattr(translator, "_find_bridge", lambda: bridge)

    class _R:
        returncode = 0
        stdout = b'["English out."]'

    import subprocess as sp

    seen = {}
    monkeypatch.setattr(sp, "run", lambda *a, **k: seen.update(k) or _R())
    out = translate_paragraphs(["中文句。"], direction="zh2en")
    assert out == ["English out."]
    payload = json.loads(seen["input"])
    assert payload == {"paras": ["中文句。"], "dir": "zh2en"}
    # 缺省方向 en2zh（向后兼容旧调用形态）
    monkeypatch.setattr(sp, "run", lambda *a, **k: seen.update(k) or _R())
    translate_paragraphs(["Hello."])
    assert json.loads(seen["input"])["dir"] == "en2zh"


def test_translate_paragraphs_bad_direction(tmp_path, monkeypatch):
    monkeypatch.setattr(translator, "_find_bridge", lambda: tmp_path / "bridge")
    with pytest.raises(ValueError, match="方向"):
        translate_paragraphs(["x"], direction="fr2de")


def _make_fake_app(root):
    """在 root 下造一个最小 TranslationActivator.app 结构（find_activator 校验路径）。"""
    exe = root / "TranslationActivator.app" / "Contents" / "MacOS" / "TranslationActivator"
    exe.parent.mkdir(parents=True)
    exe.write_text("#!/bin/sh\nexit 0\n")
    exe.chmod(0o755)
    return exe.parent.parent.parent


def test_find_activator_returns_first_valid(monkeypatch, tmp_path):
    """候选命中校验：Contents/MacOS/TranslationActivator 存在才返回。"""
    app = _make_fake_app(tmp_path)
    monkeypatch.setattr(translator, "_activator_candidates", lambda: [app])
    assert translator.find_activator() == app


def test_find_activator_skips_invalid(tmp_path, monkeypatch):
    """候选缺失可执行文件时跳过，继续下一个候选。"""
    app = _make_fake_app(tmp_path)
    (app / "Contents" / "MacOS" / "TranslationActivator").unlink()
    empty = tmp_path / "empty.app"
    empty.mkdir()
    monkeypatch.setattr(translator, "_activator_candidates", lambda: [app, empty, empty])
    with pytest.raises(ValueError, match="准备器缺失"):
        translator.find_activator()


def test_find_activator_locates_repo_app():
    """开发环境：仓库 packaging/activator/ 下编译产物应被定位到（产物缺失时跳过——CI checkout 无 gitignored 产物）。"""
    repo_app = translator._REPO_ROOT / "packaging" / "activator" / "TranslationActivator.app"
    if not (repo_app / "Contents" / "MacOS" / "TranslationActivator").is_file():
        pytest.skip("本地未编译激活器产物（bash packaging/build_activator.sh）")
    p = translator.find_activator()
    assert p.name == "TranslationActivator.app"
    assert (p / "Contents" / "MacOS" / "TranslationActivator").is_file()


def test_find_activator_missing_raises(monkeypatch):
    monkeypatch.setattr(translator, "_activator_candidates", lambda: [])
    with pytest.raises(ValueError, match="准备器缺失"):
        translator.find_activator()


def test_translate_available_platform_gate(monkeypatch):
    """A3：翻译可用性 = 平台门（仅 macOS）。前端据此藏「译」钮。"""
    monkeypatch.setattr(translator.sys, "platform", "darwin")
    assert translator.translate_available() is True
    monkeypatch.setattr(translator.sys, "platform", "win32")
    assert translator.translate_available() is False
    monkeypatch.setattr(translator.sys, "platform", "linux")
    assert translator.translate_available() is False
