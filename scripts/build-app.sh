#!/usr/bin/env bash
# 本地打 macOS 桌面包（dist/bookfetch.app）——一条命令搞定
# 用法：bash scripts/build-app.sh           # 打包并启动
#       bash scripts/build-app.sh --no-open # 只打包不启动
set -euo pipefail
cd "$(dirname "$0")/.."

# 1. 编译产物前置（gitignored，bookfetch.spec 直接引用——缺了打包出的 app 没翻译桥/激活器）
if [[ ! -x packaging/build/translate_bridge ]]; then
  echo "→ 编译翻译桥（translate_bridge.swift）…"
  bash packaging/build_translator.sh
fi
if [[ ! -d packaging/activator/TranslationActivator.app ]]; then
  echo "→ 构建翻译激活器（TranslationActivator.app）…"
  bash packaging/build_activator.sh
fi

# 2. 依赖（pyinstaller=build 组、pytest/opencc=dev 组、pywebview=gui extra——spec 要 collect webview，
#    漏 gui extra 会被 uv sync 清掉 → 打出的 app 启动即报「需要 GUI 依赖」，与 CI 命令保持一致）
uv sync --extra gui --group build --group dev

# 3. 打包（spec 已含 webview/opencc collect-all + static + 桥/激活器，见坑 22/32/39）
rm -rf dist/bookfetch.app build/bookfetch
.venv/bin/pyinstaller bookfetch.spec --noconfirm --log-level WARN

SIZE=$(du -sh dist/bookfetch.app | cut -f1)
echo "✓ 打包完成：dist/bookfetch.app（${SIZE}）"

if [[ "${1:-}" != "--no-open" ]]; then
  open dist/bookfetch.app
  echo "→ 已启动（pywebview 冷启动约 15 秒出窗口，正常）"
fi
