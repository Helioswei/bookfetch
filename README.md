# bookfetch

给 Agent 用的电子书查找与下载 CLI：把书名丢给它，它自动把请求路由到**实际能下到书**的源。

设计出发点（实测结论）：现成的 agent 找书技能几乎全部绑定 Z-Library / Libgen，而这两者对**中文古籍基本无效**（不收录 / 账号墙 / Cloudflare 墙）。中文古籍真正能用的源是 ctext.org（中国哲学书电子化计划：免费、带标点、国内直连）——没人把它做成 agent 工具，于是有了 bookfetch。

```
bookfetch search 渊海子平     # 跨源搜索，输出 JSON
bookfetch get ctext 727782    # 下载整本书到当前目录
```

## 特性

- 书源路由：按书种/语言分发到可用源，单个源故障不影响整体（errors 独立上报）
- JSON 优先输出：stdout 只吐结构化 JSON，agent 直接解析；`--human` 给人看
- 礼貌抓取：内置限速 + 重试退避 + 编码回退（GBK/Big5→UTF-8）
- **零运行时依赖**：纯 Python 标准库，任何环境装完即用
- 离线可测：解析测试基于真实抓包样本（fixtures），不依赖线上

## 安装

需要 Python >= 3.10。

```bash
# 推荐：uv
uv tool install git+https://github.com/Helioswei/bookfetch.git

# 或 pip
pip install git+https://github.com/Helioswei/bookfetch.git

# 本地开发
uv sync && uv run bookfetch search 论语
```

## 用法

### 搜索

```bash
bookfetch search <书名>
```

输出（JSON，字段稳定，供 agent 消费）：

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

`--source ctext` 限定源（可重复）；`--limit N` 限制条数；`--human` 输出人类可读列表。

### 下载

```bash
bookfetch get ctext 727782 --out ./books
```

把 id 对应的整本书下载为 UTF-8 纯文本（ctext 的书会自动按序抓取全部章节并拼接）。

## 已支持的书源

| 源 | 覆盖 | 说明 |
|---|---|---|
| ctext | 中文古籍（免费全文、带标点） | 书目检索 + 多章节整本下载 |

（英文书源 libgen 等：规划中）

## 开发与测试

```bash
uv sync --group dev
uv run pytest -q      # 离线测试，基于 tests/fixtures 真实抓包样本
```

## 路线图

- [x] M1: ctext 源 + search/get CLI（2026-09-03 完成）
- [ ] M2: GitHub 古籍文本库源（mymmsc/books 等）
- [ ] M3: SKILL.md agent 外壳 + PyPI 发布
- [ ] 规划中: 英文书源（libgen 镜像链）、epub 转换、格式钩子

## 许可

MIT。只面向公版/开放文本（ctext 收录均为公版古籍）。请遵守各源的访问条款。
