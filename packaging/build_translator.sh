#!/bin/bash
# 编译 macOS 系统翻译桥 → packaging/build/translate_bridge
# 要求：macOS 26+（TranslationSession.init(installedSource:) 需 26.0）
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p build
swiftc -parse-as-library -O translate_bridge.swift -o build/translate_bridge
echo "OK: $(pwd)/build/translate_bridge"
