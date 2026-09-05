# AGENTS.md — 给 AI Agent 的 bookfetch 使用指南

bookfetch 是多源电子书检索与下载工具（CLI + 桌面 App + 浏览器 UI，同一内核）。
本文件帮助 Claude Code / Codex / Cursor / OpenClaw 等 agent 正确调用它。

## 项目形态（选择正确的入口）

- **CLI（agent 用）**：`bookfetch search` / `bookfetch get` — 结构化 JSON，适合 agent 编排
- **桌面 App / `bookfetch serve`（人用）**：搜索/书架/阅读器三视图 UI。用户要"边看边下"、浏览书库、阅读时，用 `serve`（自动开浏览器）或 `gui`；**不要替用户静默启动 GUI**，除非用户明确要求

## 环境

```bash
# 方式 1：源码（本仓库，开发中功能最全）
uv sync
uv run bookfetch --help

# 方式 2：PyPI 发布版（无源码）
pip install bookfetch
```

> PyPI 发布版可能落后于仓库若干功能；对外正式版本（v1.0.0）发布后两者对齐。

## 命令速查

### 搜索（返回稳定 JSON，供程序消费）

```bash
bookfetch search <书名>
bookfetch search 论语 --source ctext        # 限定源（可重复传）
bookfetch search 论语 --limit 10            # 限制条数
bookfetch search 论语 --human               # 人类可读列表
```

输出结构（字段稳定，勿依赖示例以外的字段）：

```json
{
  "cmd": "search",
  "query": "渊海子平",
  "results": [
    {
      "source": "ctext",
      "id": "727782",
      "title": "淵海子平",
      "url": "https://ctext.org/wiki.pl?if=gb&res=727782",
      "subtitle": "維基文字版：開放共同編輯的資料。",
      "format_hint": "txt",
      "extra": { "author": "徐子平" }
    }
  ],
  "count": 1,
  "errors": {}
}
```

- `errors` 非空 = 部分源失败（网络/源站变更），失败的源会带原因，**不要静默重试同一查询**，可换源或告知用户
- 同书多源/多版本很正常（源站常有多个整理版本），**把候选呈现给用户选**，不要擅自 pick 第一个

### 下载

```bash
bookfetch get <source> <id> --out <目录>                  # 整本 txt（UTF-8）
bookfetch get ctext 727782 --out ./books --format epub    # epub（自动分章+目录）
bookfetch get ctext 727782 --out ./books --split          # txt 插入章节分隔行
bookfetch get ctext 727782 --out ./books --simplify       # 繁体转简体（需 OpenCC 可选依赖）
```

- id 一律来自 search 结果，不要自己编
- **下载后向用户报告产物绝对路径**
- 正文一字不改（--simplify 除外）；古籍默认繁体

### 可选的源列表

| 源 | 覆盖 | 网络 |
|---|---|---|
| ctext | 中文古籍（带标点全文） | 大陆直连 |
| github | 公版中文古籍文本仓库 | 大陆直连 |
| wikisource | 中/英公版书（含鲁迅等现代公版） | **需代理** |
| gutenberg | 英文公版 7 万+ | 大陆直连 |
| biquge | 中文网文（笔趣阁镜像，繁体） | 大陆直连 |
| libgen | 英文现代书原文件（epub/pdf） | **需代理** |

代理遵循系统 `http_proxy` / `https_proxy` 环境变量。

## 合规红线（agent 必须遵守）

- biquge 等源的网文多为**版权期内作品**：只下载用户**有权获取**的内容（作者已开放/正版下架/已购等），不要应要求批量抓取热门在售小说
- bookfetch 是路由工具：不存储不分发，抓取只走公开页面+限速，无任何绕过
- 内容质量（错字/缺章）来自源站整理水平，**不是工具 bug**；多版本可换源重下
- 工具层面的缺陷（路由/下载/解析）才值得提 issue

## 测试与开发（贡献者）

```bash
uv sync --group dev
uv run pytest -q     # 离线测试，基于真实抓包样本 fixtures
```

红线：搜索/下载/渲染逻辑只有 n2core 一份实现；CLI 与 UI 都只是它的视图，不要另起炉灶复制逻辑。
