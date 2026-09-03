"""Offline tests for the probe-first libgen adapter."""

import json
from pathlib import Path

import pytest

from bookfetch.model import FetchResult
from bookfetch.sources.libgen import re_fullmatch_hex

FIX = Path(__file__).parent / "fixtures"


def test_md5_validation():
    assert re_fullmatch_hex("d41d8cd98f00b204e9800998ecf8427e")
    assert not re_fullmatch_hex("short")
    assert not re_fullmatch_hex("Z" * 32)


def test_parked_page_is_not_json():
    # libgen.lc 2026-09-04: parked "domain may be for sale" page, not a result
    body = (FIX / "libgen_parked.html").read_text(encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        json.loads(body)


def test_fetch_result_raw_roundtrip():
    fr = FetchResult(source="libgen", id="a" * 32, title="t", format="epub", raw=b"PK\x03\x04data")
    d = fr.to_dict()
    assert "raw" not in d  # binary never dumped to JSON
    assert d["format"] == "epub"
    assert fr.raw == b"PK\x03\x04data"
