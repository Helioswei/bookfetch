---
name: bookfetch
description: >-
  用户需要获取电子书/古籍/公版书/现代书（找书、搜书、下载整本书、转格式）时使用。
  bookfetch 是按书种自动路由的电子书获取 CLI：ctext（中文古籍全文）、GitHub 古籍文本库
  （mymmsc/books + xiaopangxia 中医药 ~700 本，多仓聚合、license 标注、404 自动失效探活）、
  Wikisource 中/英公版书（含鲁迅等现代公版）、Gutenberg 英文公版 7 万+、libgen 探活镜像
  （英文现代书）、biquge 中文网文镜像（繁体，⚠️版权期内自审，--simplify 转简）。默认输出
  结构化 JSON（agent 友好），支持 txt/epub 输出、章节切分、可选繁转简。
---

# bookfetch — agent 友好的电子书获取 CLI

bookfetch 是书源路由引擎：按书名搜索多个实际可用的源，把整本书下载落盘。
核心卖点：**运行时零依赖**（纯标准库）、**默认 JSON 输出**（agent 友好）、
源注册表架构（单源失败独立上报）。

## 何时用 / 何时不用

- 用：用户说「我要《X》/ 帮我找/下载某本书（中文古籍、公版书、鲁迅等现代公版、英文书）」
- 不用：用户只是问书的内容/做书摘（无下载意图）；GUI/在线服务类需求（本项目无 UI）

## 安装

```bash
uv tool install bookfetch          # 或 pipx install bookfetch
uv tool install "bookfetch[simp]"  # 需要繁→简转换时（OpenCC）
```

中国大陆网络注意：ctext / GitHub raw / Gutenberg 直连可用；Wikisource / libgen 需代理，
bookfetch 遵守 `http_proxy`/`https_proxy` 环境变量（设了即走代理）。

## 命令速查

```bash
# 跨源搜索（默认全源；JSON 到 stdout，errors 字典报单源失败）
bookfetch search 渊海子平
bookfetch search 呐喊 --source wikisource --human     # 限定源 / 人类可读
bookfetch search "alice in wonderland" --source gutenberg --human   # 英文公版（Gutenberg）
bookfetch get gutenberg 11 --title "Alice's Adventures in Wonderland" --format epub

# 下载（id 取 search 输出的 source + id 字段）
bookfetch get ctext 727782 --out ~/books --human
bookfetch get wikisource 吶喊 --format epub            # 整本 epub（自动展开目录→子页）
bookfetch get ctext 727782 --simplify                  # 繁转简（需 [simp] extra）
bookfetch get ctext 727782 --split                     # txt 插章节分隔
bookfetch get gutenberg 11 --force                     # 缓存命中时强制重新抓取

# 已下载去重（yt-dlp archive 模式，N1）
# 同一 (source, id) 下过一次后，再次 get（任意格式 txt/epub）不再联网，
# 直接从本地缓存重渲染；缓存目录 ~/.cache/bookfetch/fetched/，删了即重下。
bookfetch get gutenberg 11 --format epub    # 若上面下过 txt，这次零网络
bookfetch get libgen <md5>                             # 二进制原文件（epub/pdf）直存
```

`--human` 给人看；默认 JSON（含 `errors` 字典——某源失败不影响其他源结果）。

# 浏览器 UI（N2 serve）
# GUI 只负责浏览；搜索/下载与 CLI 是同一套代码路径（fetch_cache + 渲染内核）。
bookfetch serve                 # 打开 http://127.0.0.1:8756/（书库 ~/Books 自动建）
bookfetch serve --no-browser --port 9000   # 不开浏览器/改端口（远程预览用）

# 桌面 App（N2 gui，需 gui extra）
# pywebview 壳指向内嵌 localhost HTTP（不用 file://——WebKit 禁 file 页 fetch，
# pywebview js_api 桥在 macOS 6.x file:// 下不注入；统一 http 通道最稳）。
uv sync --extra gui              # 首次需装 gui 依赖
bookfetch gui                    # 桌面窗口（书库 ~/Books）

# 打包 mac .app（PyInstaller；dist/ 已 gitignore）
uv run pyinstaller --noconfirm --clean --windowed --name bookfetch \
  --collect-all webview --add-data "src/bookfetch/static:bookfetch/static" \
  packaging/desktop_entry.py
# 产物 dist/bookfetch.app（31MB，实测启动渲染正常；首启 WebKit 冷启动约 15s）
# Windows exe 需在 GitHub Actions CI 上打（本机 mac 打不了 Windows 包）

## 源路由表

| source | 内容 | id 形态 | 大陆直连 |
|---|---|---|---|
| ctext | 中文古籍全文（带标点） | 数字 res id | ✅ |
| github | 中文古籍文本仓库 | `owner/repo:路径/书名.txt` | ✅ |
| wikisource | 中文公版书（古籍+现代公版） | 页面标题（精确，注意异体字如「吶喊」） | 需代理 |
| wikisource-en | 英文公版书 | 页面标题 | 需代理 |
| libgen | 英文现代书（原文件） | md5 | 需代理；镜像轮换，全灭时明确报错 |

注意：Wikisource 中文标题有异体字坑——search 返回什么标题就用什么标题 get
（搜「呐喊」命中「吶喊」，直接 get 呐喊 会 missing）。

## 输出契约（agent 用）

search 输出（JSON）：`{cmd, query, results: [{source, id, title, url, ...}], errors: {}}`
get 输出（JSON）：`{cmd, source, id, title, out_path, chars, lines, format, chapters: [...]}`；
human 模式一行摘要。失败：exit 1 + JSON error；网络层错误必进 errors 字典，不静默。

## 合规（使用者须知，README 同款立场）

工具只做路由与下载，不存储/不分发内容；抓取全部走公开页面 + 内置限速，无任何绕过。
公版内容（古籍/公版书）自由使用；版权期内内容（libgen 英文现代书）请使用者自行确认合法性。
各源内容版权归原作者。

## 排障

- Wikimedia 429 → 内置 Retry-After 长退避，稍等自动重试；仍失败换时段
- libgen 报镜像不可达 → 镜像域名轮换中，属预期；过段时间重试
- 缺 opencc 报错提示装 `bookfetch[simp]` → 核心功能不受影响
- ctext 密集请求后响应挂起 → 冷却约 10 分钟再试（限速是源站行为）
