"""Model contract tests: FetchResult carries content/chapters, JSON stays lean."""

from bookfetch.model import Chapter, FetchResult


def test_fetch_result_to_dict_excludes_bulk_content():
    fr = FetchResult(
        source="ctext",
        id="1",
        title="書",
        out_path="/x/書.txt",
        chars=10,
        lines=2,
        format="txt",
        content="第一章\n第二章",
        chapters=[Chapter("一", "第一章"), Chapter("二", "第二章")],
    )
    d = fr.to_dict()
    assert "content" not in d
    assert d["chapters"] == ["一", "二"]
    assert d["out_path"] == "/x/書.txt"


def test_fetch_result_chapters_none_by_default():
    fr = FetchResult(source="github", id="r:p", title="t")
    assert fr.to_dict()["chapters"] is None
