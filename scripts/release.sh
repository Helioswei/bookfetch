#!/usr/bin/env bash
# 一键发版：打 tag 并推送 → GitHub Actions 自动构建 mac/win 桌面包挂到 Release + PyPI 发布。
# 版本单一事实源 = pyproject.toml：tag 自动取 [project] version（勿再手传版本号，杜绝双写漏改）。
# 用法: bash scripts/release.sh           # tag = pyproject 的 version
#       bash scripts/release.sh v1.0.1    # 可选：显式传参（会校验 == pyproject version，不一致即退出）
set -euo pipefail

# 从 pyproject.toml 提取版本（格式固定：version = "x.y.z"）
VERSION="$(grep -m1 '^version = ' pyproject.toml | cut -d'"' -f2)"
TAG="v${VERSION}"

# 防呆 1：显式传参必须与 pyproject 一致（参数须带 v 前缀）
WANT="${1:-}"
if [ -n "$WANT" ]; then
  if [ "$WANT" != "${TAG}" ]; then
    echo "版本不一致，已中止：参数 $WANT != pyproject.toml 的 ${TAG}（版本只改 pyproject 一处）" >&2
    exit 1
  fi
fi

# 防呆 2：tag 已存在（本地或远端）则拒绝覆盖
if git rev-parse "${TAG}" >/dev/null 2>&1 || git ls-remote --tags origin "${TAG}" | grep -q "${TAG}"; then
  echo "tag ${TAG} 已存在（本地或远端），已中止——确认 pyproject version 是否已 bump" >&2
  exit 1
fi

git tag "${TAG}"
git push origin "${TAG}"
echo "✓ 已推送 tag ${TAG}（取自 pyproject.toml）→ Actions 正在构建桌面包 + 发 PyPI"
