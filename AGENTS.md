# AGENTS.md — 给 AI Agent 的 bookfetch 使用指南

bookfetch 是多源电子书检索与下载工具（CLI + 桌面 App + 浏览器 UI，同一内核）。
本文件是仓库内 agent（Claude Code / Codex / Cursor / OpenClaw 等）的调用指南；
**命令细节、JSON 字段、源表与合规的完整说明一律以 README.md 为准**——本文只留速查与
README 没有的 agent 规则，避免多份文档复制不同步。

## 项目形态（选择正确的入口）

- **CLI（agent 用）**：`bookfetch search` / `bookfetch get` — 结构化 JSON，适合 agent 编排
- **桌面 App / `bookfetch serve`（人用）**：搜索/书架/阅读器三视图 UI。用户要「边看边下」、
  浏览书库、阅读时，用 `serve`（自动开浏览器）或 `gui`；**不要替用户静默启动 GUI**，除非用户明确要求

## 环境

```bash
uv sync && uv run bookfetch --help   # 源码（本仓库，功能最全）
pip install bookfetch                # PyPI 发布版（正式 tag 快照；日常迭代先进 main，PyPI 在下次 tag 发布时对齐）
```

## 命令速查（完整说明见 README「用法」）

```bash
bookfetch search <书名> [--source ctext] [--limit N] [--human]   # 跨源搜索
bookfetch get <source> <id> --out <目录> [--format txt|epub] [--split] [--simplify]
```

- search 输出稳定 JSON（cmd / query / results[] / count / errors{}），完整字段示例见 README「用法 → 搜索」
- 源速查（完整表含网络/合规备注见 README「已支持的书源」）：ctext 古籍 · github 古籍仓库 ·
  wikisource 中/英公版（需代理）· gutenberg 英文公版 · biquge 网文（⚠️ 版权期内自审）·
  libgen 英文现代书（官方迁移中，待适配）

## Agent 规则（必须遵守；README 未覆盖的行为约定）

- `errors` 非空 = 部分源失败（网络/源站变更），失败的源带原因——**不要静默重试同一查询**，可换源或告知用户
- 同书多源/多版本很正常（源站常有多个整理版本），**把候选呈现给用户选**，不要擅自 pick 第一个
- id 一律来自 search 结果，不要自己编；**下载后向用户报告产物绝对路径**
- 正文一字不改（`--simplify` 除外）；古籍默认繁体
- biquge 等源的网文可能含**版权期内作品**：向用户如实标注来源与风险，下载与使用的合法性由使用者自审（详见 README「源与合规」）
