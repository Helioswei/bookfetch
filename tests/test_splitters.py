"""Offline tests for heading-based chapter splitting."""

from bookfetch.model import Chapter
from bookfetch.util.splitters import split_headings


def _text(chs):
    return "\n".join(c.text for c in chs)


def test_angle_bracket_titles():
    lines = ["淵海子平", "基礎", "五干屬陽，喜合。", "《論天干》", "甲木參天。", "《論地支》", "子丑合土。"]
    chs = split_headings(lines)
    assert [c.title for c in chs] == ["論天干", "論地支"]
    # preamble folds into the first chapter; nothing is lost
    assert _text(chs) == "\n".join(lines)
    assert chs[0].text.startswith("淵海子平\n基礎\n")


def test_no_headings_returns_empty():
    lines = ["五干屬陽，喜合。", "以甲為例★見甲：為比肩、兄弟。"]
    assert split_headings(lines) == []


def test_numbered_volume_headers():
    lines = ["卷之一 天干", "正文一", "卷二", "正文二", "第3章", "正文三"]
    chs = split_headings(lines)
    assert [c.title for c in chs] == ["卷二", "第3章"]
    # "卷之一 天干" shares the line with trailing text -> not a header
    assert _text(chs) == "\n".join(lines)


def test_bare_markers():
    lines = ["書名", "凡例", "一、不載生剋。", "序", "此書之作。", "正文"]
    chs = split_headings(lines)
    assert [c.title for c in chs] == ["凡例", "序"]
    assert _text(chs) == "\n".join(lines)


def test_sentence_like_lines_never_split():
    # long sentences and lines with sentence punctuation are not headers
    lines = ["《論五行》各有所喜所害例", "甲木參天，脫胎要火。", "論曰：此乃要訣。", "第二十三章節錄"]
    assert split_headings(lines) == []


def test_headings_kept_in_text_for_lossless_roundtrip():
    lines = ["前言一句。", "《論日為主》", "日主之說。", "《論月令》", "月令之說。"]
    chs = split_headings(lines)
    assert _text(chs) == "\n".join(lines)
    assert chs[0].text.startswith("前言一句。\n《論日為主》")
