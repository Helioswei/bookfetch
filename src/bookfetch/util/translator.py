"""英→中翻译桥客户端（macOS 系统翻译，可选能力；N3）。

定位翻译桥二进制并批量调用：stdin JSON 段落数组 → stdout JSON 译文数组。
桥 = packaging/translate_bridge.swift 编译产物（build_translator.sh）。
非 macOS / 桥缺失 / 语言包未装 → translate_paragraphs 抛 ValueError（中文文案），
调用方（n2core.translate API）透传给前端做引导提示。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

# 与前端 app.js 阅读器渲染完全一致的段落切分：
#   const paras = c.text.split(/\n{2,}|\n(?=\S)/).map(trim).filter(Boolean)
#     .filter(s => s !== title && s !== '《'+title+'》')
# 译文按此规则对齐到前端 <p> 序号。改这里必须同步 app.js（坑 29 铁律：渲染与还原对称）。
_READER_SPLIT = re.compile(r"\n{2,}|\n(?=\S)")

# "章节含英文才显示翻译钮"的判定：≥ 此数量 2+ 字母单词视为英文章
_LATIN_WORD_RE = re.compile(r"[A-Za-z]{2,}")
_LATIN_THRESHOLD = 15


def split_reader_paras(text: str, title: str = "") -> list[str]:
    """按阅读器渲染规则切正文段落并过滤标题行（与 app.js loadChapter 对齐）。"""
    paras = [s.strip() for s in _READER_SPLIT.split(text)]
    paras = [s for s in paras if s]
    if title:
        paras = [s for s in paras if s != title and s != "《" + title + "》"]
    return paras


def has_latin(text: str, threshold: int = _LATIN_THRESHOLD) -> bool:
    """粗判英文文本（含较多 2+ 字母拉丁单词）——翻译按钮显隐依据。"""
    return len(_LATIN_WORD_RE.findall(text)) >= threshold


def _bridge_candidates() -> list[Path]:
    cands: list[Path] = []
    env = os.environ.get("BOOKFETCH_TRANSLATE_BIN")
    if env:
        cands.append(Path(env))
    mei = getattr(sys, "_MEIPASS", None)  # PyInstaller 解包目录
    if mei:
        # onedir 会剥离 datas 目标的 app 名前缀（'bookfetch/x' → _MEIPASS/x），
        # 也兼容未剥离形态；Resources 真身在 _MEIPASS 的 symlink 后可见
        cands.append(Path(mei) / "bookfetch" / "translate_bridge")
        cands.append(Path(mei) / "translate_bridge")
    repo = Path(__file__).resolve().parents[3]  # src/bookfetch/util → 仓库根
    cands.append(repo / "packaging" / "build" / "translate_bridge")
    return cands


def _activator_candidates() -> list[Path]:
    """语言包准备器 .app（首次翻译未装语言包时拉起，让用户点一下完成下载+安装）。"""
    cands: list[Path] = []
    env = os.environ.get("BOOKFETCH_TRANSLATE_ACTIVATOR")
    if env:
        cands.append(Path(env))
    mei = getattr(sys, "_MEIPASS", None)
    if mei:
        cands.append(Path(mei) / "bookfetch" / "TranslationActivator.app")
        cands.append(Path(mei) / "TranslationActivator.app")
    repo = Path(__file__).resolve().parents[3]
    cands.append(repo / "packaging" / "activator" / "TranslationActivator.app")
    return cands


def find_activator() -> Path:
    for p in _activator_candidates():
        if (p / "Contents" / "MacOS" / "TranslationActivator").is_file():
            return p
    raise ValueError("翻译语言包准备器缺失（macOS 26.4+ 的 bookfetch.app 应自带）")


def _find_bridge() -> Path:
    for p in _bridge_candidates():
        if p.is_file() and os.access(p, os.X_OK):
            return p
    raise ValueError("翻译桥不可用（需 macOS 26+ 且已构建 packaging/build/translate_bridge）")


def translate_paragraphs(texts: list[str], timeout: float = 600.0) -> list[str | None]:
    """批量翻译段落（整章一次进程调用）。返回与输入等长的译文数组，单段失败为 None。

    非 macOS / 桥缺失 / 语言包未装 → ValueError（中文友好文案，前端直接展示）。
    """
    if not texts:
        return []
    bridge = _find_bridge()
    payload = json.dumps(texts, ensure_ascii=False).encode("utf-8")
    try:
        proc = subprocess.run(
            [str(bridge)], input=payload, capture_output=True, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        raise ValueError("翻译超时：章节过长或系统翻译无响应，请重试") from None
    except OSError as e:
        raise ValueError(f"翻译桥启动失败：{e}") from None
    if proc.returncode != 0:
        try:
            err = json.loads(proc.stdout.decode("utf-8", "replace"))
            raise ValueError(err.get("message", "翻译失败（系统翻译不可用）"))
        except json.JSONDecodeError:
            raise ValueError("翻译失败（系统翻译不可用）") from None
    try:
        out = json.loads(proc.stdout.decode("utf-8", "replace"))
    except json.JSONDecodeError:
        raise ValueError("翻译响应解析失败") from None
    if not isinstance(out, list):
        raise ValueError("翻译响应格式异常") from None
    return [t if isinstance(t, str) else None for t in out]
