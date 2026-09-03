"""Unit tests for shared utilities."""

from bookfetch.util import decode_bytes, sanitize_filename


def test_decode_utf8():
    assert decode_bytes("淵海子平".encode("utf-8")) == "淵海子平"


def test_decode_gb18030_fallback():
    raw = "渊海子平".encode("gb18030")
    assert decode_bytes(raw) == "渊海子平"


def test_sanitize_filename():
    # ？* map to _ then get stripped from the tail; inner ： becomes _
    assert sanitize_filename("淵海子平：論天干？*") == "淵海子平_論天干"
    assert sanitize_filename("a/b\\c:d") == "a_b_c_d"
    assert sanitize_filename("   ") == "untitled"
