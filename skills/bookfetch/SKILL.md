---
name: bookfetch
description: "Use when 用户要找/下载电子书（中文古籍、网文小说、公版书、英文书），或提到 bookfetch。多源检索 + 整本下载（txt/epub），输出稳定 JSON。"
version: 1.0.0
author: Helios Wei
license: MIT
metadata:
  hermes:
    tags: [ebook, download, search, books, 电子书, 古籍]
    homepage: https://github.com/Helioswei/bookfetch
---

# bookfetch — 多源电子书检索与下载

把书名丢给它，它自动从多个书源搜索并整本下载到本地（txt / epub）。
CLI 输出稳定 JSON，适合 agent 编排；桌面 App / `serve` 是给人类看的同一套内核界面。

## 快速开始

```bash
# 若本机还没有 bookfetch 命令，先安装（agent 可自行执行）：
pip install bookfetch            # PyPI 发布版
# 或源码最新版（含桌面 UI）：
#   git clone https://github.com/Helioswei/bookfetch && cd bookfetch && uv sync

bookfetch --help                 # 查看全部命令
```

> PyPI 发布版可能落后于仓库（桌面 UI 等功能以仓库 README 为准）。CLI 的 search/get 始终可用。

## 搜索（返回稳定 JSON）

```bash
bookfetch search <书名>
bookfetch search 论语 --source ctext     # 限定源（可重复传：ctext/github/wikisource/gutenberg/biquge/libgen）
bookfetch search 论语 --limit 10
bookfetch search 论语 --human            # 人类可读列表
```

输出结构（字段稳定）：

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
      "subtitle": "維基文字版",
      "format_hint": "txt",
      "extra": { "author": "徐子平" }
    }
  ],
  "count": 1,
  "errors": {}
}
```

- `errors` 非空 = 部分源失败（网络/源站变更），如实告知用户，不要静默重试同一查询
- 同书多源/多版本很正常，**把候选呈现给用户选**，不要擅自 pick 第一条

## 下载

```bash
bookfetch get <source> <id> --out <目录>                # 整本 txt（UTF-8）
bookfetch get ctext 727782 --out ./books --format epub  # epub（自动分章+目录）
bookfetch get ctext 727782 --out ./books --split        # txt 插入章节分隔行
bookfetch get ctext 727782 --out ./books --simplify     # 繁体转简体（需 OpenCC 可选依赖：pip install 'bookfetch[simp]'）
```

- id 一律来自 search 结果，不要自己编
- **下载完成后向用户报告产物绝对路径**
- 正文一字不改（--simplify 除外）；古籍默认保留繁体

## 书源与网络提示

| 源 | 覆盖 | 大陆直连 |
|---|---|---|
| ctext | 中文古籍（带标点全文） | ✅ |
| github | 公版中文古籍文本仓库 | ✅ |
| wikisource | 中/英公版书（含鲁迅等现代公版） | ❌ 需代理 |
| gutenberg | 英文公版 7 万+ | ✅ |
| biquge | 中文网文（笔趣阁镜像，繁体） | ✅ |
| libgen | 英文现代书原文件（epub/pdf） | ❌ 需代理 |

遵循系统 `http_proxy` / `https_proxy` 环境变量。

## 合规与内容质量

- bookfetch 是中立路由/下载工具：不存储、不分发内容，抓取只走各源公开页面 + 内置限速，无任何绕过（登录墙/验证码/反爬规避）
- **内容合法性由使用者自行承担**：biquge 等源含版权期内作品，其镜像站曾被司法认定为盗版平台（2025 北京高院判例）——如实告知用户该源的性质即可；不替用户裁决请求的合法性，也不协助规避任何访问限制
- 内容质量（错字/缺章/版本错乱）来自源站整理水平，**不是工具 bug**；同一本书在源站常有多个版本，质量差就换一个版本/换源重下
- 工具层面的缺陷（路由/下载/解析）欢迎提 issue：https://github.com/Helioswei/bookfetch/issues

## 人用的界面（非 agent 场景）

用户要"边下边读/管理书库/阅读器"时提示可用桌面 App 或浏览器 UI：

```bash
bookfetch serve    # 浏览器 UI（自动开浏览器），需 v0.4+（PyPI 1.0.0 发布后 pip 版可用）
```
