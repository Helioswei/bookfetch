"""Unit tests for shared utilities."""

from bookfetch.util import decode_bytes, looks_like_challenge, sanitize_filename


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


def test_looks_like_challenge_detects_antibot_pages():
    """Anti-bot pages must be detected (never silent) — D1 addendum."""
    samples = [
        "<html><head><title>Please confirm that you are human!</title>敬請輸入認證圖案</head></html>",
        "<html><title>Just a moment...</title><script>cf-challenge</script></html>",
        '<html><body><div id="challenge-platform">…</div></body></html>',
        "<html><title>Attention Required! | Cloudflare</title></html>",
    ]
    for s in samples:
        assert looks_like_challenge(s), s[:50]


def test_looks_like_challenge_ignores_normal_pages():
    """Ordinary book text / list pages must never be misclassified."""
    normal = [
        "<html><body><li>道德經正文內容，長篇古籍文字</li></body></html>",
        "Alice's Adventures in Wonderland\nChapter I\nDown the Rabbit-Hole",
        "<html><body>书籍列表页面的正常内容，无验证字样</body></html>",
    ]
    for s in normal:
        assert not looks_like_challenge(s), s[:50]
