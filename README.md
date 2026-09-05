# bookfetch

给 Agent 用的电子书查找与下载 CLI：把书名丢给它，它自动把请求路由到**实际能下到书**的源。

设计出发点（实测结论）：现成的 agent 找书技能几乎全部绑定 Z-Library / Libgen，而这两者对**中文古籍基本无效**（不收录 / 账号墙 / Cloudflare 墙）。中文古籍真正能用的源是 ctext.org（中国哲学书电子化计划：免费、带标点、国内直连）——没人把它做成 agent 工具，于是有了 bookfetch。

```
bookfetch search 渊海子平     # 跨源搜索，输出 JSON
bookfetch get ctext 727782    # 下载整本书到当前目录
bookfetch serve               # 浏览器 UI（搜索/书架/阅读器），自动开浏览器
```

## 特性

- 书源路由：按书种/语言分发到可用源，单个源故障不影响整体（errors 独立上报）
- **EPUB / 章节感知**：`--format epub` 零依赖生成手机可读的 epub（含目录）；`--split`
  在 txt 中插入章节分隔；古籍《》/卷/序跋类标题行自动识别为章节
- **中英双向翻译（Mac 阅读器，macOS 26.4+）**：章节内一键整章逐段沉浸式对照
  （原文每段下插译文）——英文书英译中、中文书中译英，方向自动；macOS 系统翻译引擎、完全离线
- JSON 优先输出：stdout 只吐结构化 JSON，agent 直接解析；`--human` 给人看
- 礼貌抓取：内置限速 + 重试退避 + 编码回退（GBK/Big5→UTF-8）
- **零运行时依赖**：纯 Python 标准库，任何环境装完即用（简体转换是可选扩展）
- 离线可测：解析测试基于真实抓包样本（fixtures），不依赖线上

## 安装

### 桌面 App（Mac）— 普通用户首选，免装 Python

一个 App 搞定搜索/下载/书架/阅读，无需终端：

1. 下载 Mac 版 zip（GitHub Releases 页的 `bookfetch-macos-arm64.zip`，约 15MB；适用于 Apple 芯片 M1 及以后的 Mac，Intel Mac 请走下方 CLI 方式；尚未上传时可向维护者索取），双击解压出 `bookfetch.app`
2. 把 `bookfetch.app` 拖进"应用程序"文件夹
3. 首次打开：因为尚未购买 Apple 开发者签名（$99/年），系统会拦截一次——**右键点 `bookfetch.app` → 选"打开" → 弹窗里再点一次"打开"**，之后即可正常双击启动
4. 书库在 `~/Books`（首次启动自动创建），下载的书都存在这里；进度自动记忆，下次接着读

数据完全本地：搜索从公开书源抓取，下载文件只落在你自己的 `~/Books`，不经过任何中间服务器。

界面右上角 ⚙ 设置可配网络代理（三选：跟随系统=默认 / 手动代理 / 直连）——被墙书源（wikisource、libgen）需要代理才能访问；Clash 等代理软件开着「系统代理」开关即零配置生效。

> 签名/平台状态：mac 版暂未签名（上述右键打开一次即可，签名需 Apple 开发者账号 $99/年）；Windows 版打包在规划中（需 CI 构建）；非 Mac 用户可走下方 CLI 方式。

### Python / CLI（开发者 / agent）

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

### 界面（桌面 App / 浏览器 serve）

桌面 App 与 `bookfetch serve` 是**同一套界面、同一套内核**——差别的只是外壳：

| 形态 | 启动方式 | 适合谁 |
|---|---|---|
| 桌面 App | 双击 `bookfetch.app`（见安装） | 普通用户 |
| 桌面 App（源码） | `uv sync --extra gui && bookfetch gui` | 开发者 |
| 浏览器 UI | `bookfetch serve`（自动开浏览器） | 开发者/局域网预览 |

界面三个视图：

- **搜索**：选书源胶囊（或"全部"并行搜索）→ 输入书名 → 朱红按钮搜索；结果卡片可直接下载原文件 / txt / epub
- **书架**：书库（默认 `~/Books`，桌面 App 可用环境变量 `BOOKFETCH_LIBRARY` 改）里的全部藏书，每行带续读进度条；点行即续读
- **阅读器**：书页排版（衬线/行距/夜间模式可调），进度自动记忆；支持深链 `#shelf` / `#reader/书名` 直达

#### 中英双向翻译（阅读器，macOS 26.4+）

章节顶部有「译」按钮（每章都有）：点一次把当前整章逐段翻译，**译文插在每段原文下方**
（沉浸式对照，原文一字不动）；再点「译」恢复纯原文。方向自动判定：英文书 → 英译中，
中文书 → 中译英，标题提示当前方向。

- 翻译完全在本地完成（macOS 系统翻译引擎），内容不出本机，无账号、无费用
- 每章每方向只翻一次，结果缓存（`~/.cache/bookfetch/translations/`），反复进出不重翻

**首次使用需要下载系统翻译语言包（约 1GB，一次性）**，两种方式任选：

1. **在 bookfetch 里直接完成（推荐）**：打开任一章节点「译」→ 提示语言包未装时点「确定」→
   弹出「翻译语言包准备器」→ 点「准备翻译语言包」→ 等它下载安装完成（几分钟）→
   回到阅读器再点「译」即可
2. **在系统设置里下载**：系统设置 → 通用 → 语言与地区 → 翻译 → 下载「简体中文」；
   若下载完 bookfetch 仍提示未装，用方式 1 的准备器补一次安装即可

语言包是系统级资产，装一次全机 App 共享；后续阅读完全离线。英文侧与中文侧模型
（各几十至几百 MB）在首次准备时会一并就位。

## 已支持的书源

| 源 | 覆盖 | 说明 |
|---|---|---|
| ctext | 中文古籍（免费全文、带标点） | 书目检索 + 多章节整本下载 |
| github | 公版中文古籍文本仓库 | 精选仓库树索引（7 天缓存），raw 直连下载 |
| wikisource | 中文/英文公版书（含现代公版：鲁迅等） | MediaWiki API + 渲染页解析，目录自动展开整本；大陆访问需代理 |
| gutenberg | 英文公版书 7 万+（小说/非小说） | 搜索页 → PG 官方 txt（自动剥离 Gutenberg 许可头尾）；大陆直连 |
| biquge | 中文现代网文/小说（笔趣阁镜像，繁体） | 搜索 → 目录 → 逐章正文（章节级 txt）；大陆直连；⚠️ 版权期内内容自审，见下 |
| libgen | 英文现代书（原文件 epub/pdf） | 探活式镜像链（域名轮换频繁），当前镜像不可达时会明确报错；需代理 |

> 网络提示：ctext/github/gutenberg/biquge 大陆直连可用；wikisource（Wikimedia）与 libgen 大陆直连不通，
> 需能访问对应站点的网络环境（如代理），本工具遵循系统 http_proxy/https_proxy 环境变量。

> ⚠️ **biquge 源特别提示**：本工具为中立下载工具（yt-dlp 模式），不存储/分发内容。笔趣阁镜像站收录的
> 中文网文多为**版权期内作品**（2025 年北京高院终审已判「笔趣阁」为盗版平台代名词）——请仅下载你有权
> 获取的内容（作者已开放/正版已下架/你已购买等），使用者自行承担下载与使用的合法性责任。该源默认输出繁体，
> 可用 `--simplify` 转换。

## 源与合规

- bookfetch 是**路由与下载工具**，不存储、不重新分发任何书籍内容；下载物只落在使用者本地
- 各源内容版权归原作者/整理者所有。公版内容可自由使用；**仍在版权期内的内容，请使用者自行确认下载与使用的合法性**
- 抓取行为遵守各源访问条款：公开页面、内置限速、不做任何绕过（登录墙/验证码/反爬规避）
- 测试 fixture 为各源页面/结构的极小样本，仅用于解析测试，来源记录见 tests/fixtures/README.md
- 任何权利方认为本工具对某源的使用不妥，请提 issue，我们会调整或移除该源

### GitHub 精选仓库 license 实测状态（2026-09-04 探活，repos API 逐仓核对）

| 仓库 | 内容 | license 实测 | 使用提示 |
|---|---|---|---|
| `mymmsc/books` | 综合资料库（含公版古籍/国学 txt，★2641） | 无 license 文件 | 公版古籍 + 公开资料汇编，使用前自审 |
| `xiaopangxia/TCM-Ancient-Books` | 中医药古籍文本 ~700 本（★1411） | 无 license 文件 | 古籍原文公版；转录/汇编权利状态不明，使用前自审 |

> search 输出中每个 github 结果带 `license` 字段；无 license 的源标注"权利状态不明，使用前自审"。
> 健康探活：仓库若 404（被删/转私有/改名），会在缓存中标记失效并在 search 的 errors 中明确报错，**不静默返回旧索引**。

## 开发与测试

```bash
uv sync --group dev
uv run pytest -q      # 离线测试，基于 tests/fixtures 真实抓包样本
```

## 发布（桌面包 + PyPI）

- **每次推 main**：GitHub Actions 自动构建 mac/win 桌面包 → Actions artifact（最新包随时可取）
- **正式发版**（一条命令，触发构建并挂到 Release 页）：

```bash
bash scripts/release.sh v0.4.0     # 打 tag 并推送 → Release 附件出现 mac/win zip
```

- PyPI 发布（CLI 形态）自理：`uv build && uv publish`（需 PyPI token）

## 路线图

- [x] M1: ctext 源 + search/get CLI（2026-09-03 完成）
- [x] M2: github 古籍源 + OpenCC 简繁转换 + 合规声明（2026-09-03 完成）
- [x] M3: EPUB 转换 + 章节切分（2026-09-04 完成，零依赖手写 zip+xhtml）
- [x] M4: wikisource 中/英公版源 + libgen 探活镜像链 + 白话注解 spike（2026-09-04 完成；白话注解判定放弃，见 PRD）
- [x] M5: SKILL.md agent 外壳 + PyPI 发布（2026-09-04 完成：仓库已 public、PyPI bookfetch 0.3.0 已上传，安装链路端到端验证通过）
- [x] M6: Gutenberg 英文公版源（2026-09-04 完成，许可头尾自动剥离；E2E《Alice's Adventures in Wonderland》txt/epub 全通）
- [x] M7: github 源多仓库化 + 搜索聚合（mymmsc/books + xiaopangxia 中医药 ~700 本；license 实测标注 + 404 死亡探活，2026-09-04 完成）
- [x] M8: 中文网文/小说源 biquge（2026-09-04 完成：spike 探测 5 站 → biquge.tw 唯一活体全链路通 → 收录；README 版权红字免责；繁体 --simplify）
- [x] N1: 已下载去重（yt-dlp archive 模式，2026-09-04 完成：fetch 层缓存 source:id → 命中零网络重渲染；txt/epub 互认；--force 重下）
- [x] N2 前端+serve（2026-09-04 完成：`bookfetch serve` 浏览器 UI——搜索/书架/阅读器三视图；下载逻辑与 CLI 共用同一套 fetch_cache+渲染内核；n2core API 层 serve 与桌面壳共用；全源并行搜索每源 20s 超时）
- [x] N2 壳（2026-09-04 完成：`bookfetch gui` pywebview 桌面窗口——指向内嵌 localhost HTTP，前端零改动；实测窗口渲染 + 8 源标签 + 键盘输入全通）
- [x] UI「书卷宣纸」主题 + mac .app 打包（2026-09-04 完成：宣纸暖底/墨字/朱红/「藏」印三视图定稿实拍验收；书架行式+续读进度条；hash 深链 `#shelf` `#reader/书名`；`packaging/desktop_entry.py` + PyInstaller → `dist/bookfetch.app` 31MB 实测启动渲染 ✓）
- [x] N3 翻译（2026-09-05 完成：中英双向沉浸式整章对照——macOS 系统翻译桥 swift + 逐段译文 UI；方向自动（英文书英译中/中文书中译英）；首次引导「翻译语言包准备器」一键下载+安装语言包约 1GB，全离线）
- [x] v0.4.0：英文切章 + B4 下载体验三件套 + CLI/UI 边界（2026-09-05 完成：英文书 `CHAPTER/CHAP. + 数字/罗马` 独立标题行切章（含目录/逐章翻译）；UI 下载并发队列（上限 3、排队可取消）、单文件 Range 断点续传、biquge 逐章断点 + 下载中「读已下 N 章」边下边读——均为 serve/gui 任务系统专属，CLI get 同步直连不受影响；106 tests 绿，CI 双平台绿）

## 许可

MIT。只面向公版/开放文本（ctext 收录均为公版古籍）。请遵守各源的访问条款。
