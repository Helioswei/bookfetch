"""Optional Traditional -> Simplified conversion (extra dependency)."""

from __future__ import annotations


def to_simplified(text: str) -> str:
    """Convert Traditional Chinese text to Simplified via OpenCC.

    Requires the optional extra: pip install 'bookfetch[simp]'
    (or uv tool install bookfetch --extra simp).
    """
    try:
        from opencc import OpenCC
    except ImportError as e:
        raise ValueError(
            "--simplify 需要可选依赖：安装 'bookfetch[simp]' "
            "（uv tool install bookfetch --extra simp 或 pip install 'bookfetch[simp]'）"
        ) from e
    return OpenCC("t2s").convert(text)
