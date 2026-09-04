"""N3 翻译 util 单测：段落切分对齐 / 英文检测 / 桥缺失容错。"""

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


def test_find_activator_locates_repo_app():
    """开发环境：仓库 packaging/activator/ 下编译产物应被定位到。"""
    p = translator.find_activator()
    assert p.name == "TranslationActivator.app"
    assert (p / "Contents" / "MacOS" / "TranslationActivator").is_file()


def test_find_activator_missing_raises(monkeypatch):
    monkeypatch.setattr(translator, "_activator_candidates", lambda: [])
    with pytest.raises(ValueError, match="准备器缺失"):
        translator.find_activator()
