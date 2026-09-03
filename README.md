# bookfetch

给 Agent 用的电子书查找与下载 CLI：把书名丢给它，它自动把请求路由到**实际能下到书**的源。

设计出发点（实测结论）：现成的 agent 找书技能几乎全部绑定 Z-Library / Libgen，而这两者对**中文古籍基本无效**（不收录 / 账号墙 / Cloudflare 墙）。中文古籍真正能用的源是 ctext.org（中国哲学书电子化计划：免费、带标点、国内直连）——没人把它做成 agent 工具，于是有了 bookfetch。

```
bookfetch search 渊海子平     # 跨源搜索，输出 JSON
bookfetch get ctext 727782    # 下载整本书到当前目录
```

## 特性

- 书源路由：按书种/语言分发到可用源，单个源故障不影响整体（errors 独立上报）
- **EPUB / 章节感知**：`--format epub` 零依赖生成手机可读的 epub（含目录）；`--split`
  在 txt 中插入章节分隔；古籍《》/卷/序跋类标题行自动识别为章节
- JSON 优先输出：stdout 只吐结构化 JSON，agent 直接解析；`--human` 给人看
- 礼貌抓取：内置限速 + 重试退避 + 编码回退（GBK/Big5→UTF-8）
- **零运行时依赖**：纯 Python 标准库，任何环境装完即用（简体转换是可选扩展）
- 离线可测：解析测试基于真实抓包样本（fixtures），不依赖线上

## 安装

需要 Python >= 3.10。已发布到 PyPI：

```bash
# 推荐：uv（或 pipx）
uv tool install bookfetch

# 或 pip
pip install bookfetch

# 需要繁→简转换时（OpenCC，可选）
uv tool install "bookfetch[simp]"

# 从源码（开发版）
uv tool install git+https://github.com/Helioswei/bookfetch.git

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
bookfetch get ctext 727782 --out ./books            # 默认 txt（整本合并）
bookfetch get ctext 727782 --format epub --out ./books   # 手机友好的 epub（自动分章+目录）
bookfetch get ctext 727782 --split --out ./books    # txt 中插入 === 章节 === 分隔
```

把 id 对应的整本书下载为 UTF-8 纯文本（ctext 的书会自动按序抓取全部章节并拼接）。
`epub` 与 `--split` 的章节来自源结构（ctext 分页）或《》/卷/序跋类标题行自动识别；
正文一字不改，标题行仅在阅读视图去重。

#### 繁转简（可选）

默认保留古籍繁体原文；需要简体版时加 `--simplify`（需先装可选依赖）：

```bash
uv tool install bookfetch --extra simp     # 或 pip install 'bookfetch[simp]'
bookfetch get ctext 727782 --out ./books --simplify
```

转换基于 OpenCC（t2s），文件与文件名会一并转为简体。古籍存在异体字/通假字，
转换非 100% 保真，学术用途请以原文为准。

## 已支持的书源

| 源 | 覆盖 | 说明 |
|---|---|---|
| ctext | 中文古籍（免费全文、带标点） | 书目检索 + 多章节整本下载 |
| github | 公版中文古籍文本仓库 | 精选仓库树索引（7 天缓存），raw 直连下载 |
| wikisource | 中文/英文公版书（含现代公版：鲁迅等） | MediaWiki API + 渲染页解析，目录自动展开整本；大陆访问需代理 |
| libgen | 英文现代书（原文件 epub/pdf） | 探活式镜像链（域名轮换频繁），当前镜像不可达时会明确报错；需代理 |

> 网络提示：ctext/github 大陆直连可用；wikisource（Wikimedia）与 libgen 大陆直连不通，
> 需能访问对应站点的网络环境（如代理），本工具遵循系统 http_proxy/https_proxy 环境变量。

## 源与合规

- bookfetch 是**路由与下载工具**，不存储、不重新分发任何书籍内容；下载物只落在使用者本地
- 各源内容版权归原作者/整理者所有。公版内容可自由使用；**仍在版权期内的内容，请使用者自行确认下载与使用的合法性**
- 抓取行为遵守各源访问条款：公开页面、内置限速、不做任何绕过（登录墙/验证码/反爬规避）
- 测试 fixture 为各源页面/结构的极小样本，仅用于解析测试，来源记录见 tests/fixtures/README.md
- 任何权利方认为本工具对某源的使用不妥，请提 issue，我们会调整或移除该源

## 开发与测试

```bash
uv sync --group dev
uv run pytest -q      # 离线测试，基于 tests/fixtures 真实抓包样本
```

## 路线图

- [x] M1: ctext 源 + search/get CLI（2026-09-03 完成）
- [x] M2: github 古籍源 + OpenCC 简繁转换 + 合规声明（2026-09-03 完成）
- [x] M3: EPUB 转换 + 章节切分（2026-09-04 完成，零依赖手写 zip+xhtml）
- [x] M4: wikisource 中/英公版源 + libgen 探活镜像链 + 白话注解 spike（2026-09-04 完成；白话注解判定放弃，见 PRD）
- [x] M5: SKILL.md agent 外壳 + PyPI 发布（2026-09-04 完成：仓库已 public、PyPI bookfetch 0.3.0 已上传，安装链路端到端验证通过）

## 许可

MIT。只面向公版/开放文本（ctext 收录均为公版古籍）。请遵守各源的访问条款。
