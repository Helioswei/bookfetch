#!/usr/bin/env bash
# 一键发版：打 tag 并推送 → GitHub Actions 自动构建 mac/win 桌面包挂到 Release。
# 用法: bash scripts/release.sh v0.4.0
set -euo pipefail

TAG="${1:-}"
if [ -z "$TAG" ]; then
  echo "用法: bash scripts/release.sh v0.4.0" >&2
  exit 1
fi
if ! git rev-parse "$TAG" >/dev/null 2>&1; then
  git tag "$TAG"
fi
git push origin "$TAG"
echo "✓ 已推送 tag $TAG → GitHub Actions 正在构建桌面包，稍后见 Release 页"
