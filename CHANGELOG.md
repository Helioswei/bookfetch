# Changelog

bookfetch 版本历史。版本号遵循 [SemVer](https://semver.org/lang/zh-CN/)：0.x 为开发期（2026-09-03 ~ 09-05），1.0.0 起为稳定对外版。

## v1.0.1（2026-09-05）修复版

修 CLI `--version` 显示错误（v1.0.0 发布事故：`__init__.py` 的 `__version__` 常量漏 bump，显示 0.3.0）。**根治**：删除源码 `__version__` 常量（双写结构必漏），CLI `--version` 改读安装元数据（`importlib.metadata`，源码裸跑兜底读 pyproject）——**版本单一事实源 = pyproject.toml**。发布工具链同步：`scripts/release.sh` tag 自动取 pyproject version（可选传参一致性校验），README 顶加 PyPI 版本徽章（自动更新），文档/workflows 注释去版本号化。

## v1.0.0（2026-09-05）首个稳定版

0.3.0（PyPI 既有版）之后的全部迭代收口为第一个稳定版：0.4.0 的英文切章与下载体验三件套、书架管理、阅读器四修、中英双向翻译（macOS 系统翻译引擎）、代理设置、桌面 App 打包链与 CI 双平台发布，以及 2026-09-05 实测反馈批次 2/3 的全部修复（导入原生对话框、主题按钮语义、翻译桥打包、搜索源三修、**外文原版中文书名直达**——详见下方各段）。桌面 App（mac/win）与 CLI 双形态对外，PyPI 同步发布。

### 发布前实测修复（2026-09-05，全部并入 v1.0.0）

- **GitHub 下载包全源 SSL 失败修复**：CI 打包 python 漂移（uv 捡 runner 系统 framework python → 产物自带 openssl、CA 路径指向构建机，用户机器证书加载为空）→ 固定 uv managed standalone python 打包；桌面 App 搜索稳定性修复
- **「全部」分类中文书名被外文假阳性挤掉修复**：全源搜索按标题字母序排序 + 结果截断，机翻译名（如《将夜》→ General night）导致的英文不相关结果挤占前 30 条、中文源结果被截断——改为中文书名搜索时中文结果优先排序
- **搜索结果全量可达**：后端不再按源截断（每源一页全量返回），结果列表滚动加载分批展示（每批 30 条），用户要找的书不会被截断丢失

## v0.4.x 实测反馈批次 3（2026-09-05，并入 v1.0.0）

外文原版搜索中文书名闭环（方案 A + B 双做，少爷拍板）：

- **方案 A：内置高频书名词典**（`book_titles.py`，224 条）：中文书名（含变体）→ 标准英文名。搜「傲慢和偏见/傲慢和偏见变体」等直接命中，外文源用标准英文名检索——全平台一致、零延迟、不依赖翻译
- **方案 B：表外书名自动翻译**：复用 N3 翻译统一接口（darwin = macOS 系统翻译桥；Windows/Linux 待 N3 V2 在线 provider，同一接口搜索侧零改动），译名磁盘缓存（同书名二次搜索零成本）
- **透明标注**：翻译/查表后外文源命中 → 结果区提示「已按英文名 X 检索外文源」；仍 0 结果 → hint 区分原因（词典命中=可能未入公版；机器翻译=译名可能不精确；翻译不可用=直接建议搜英文原名）
- 动机实测：系统翻译对译名变体不稳定——「傲慢与偏见」→ Pride and Prejudice ✓，但「傲慢和偏见」→ Arrogance and prejudice ✗（英文站 0 结果）；词典把这类高频变体钉死
- 空结果文案缩短（「没有结果——换个关键词，或换个书籍分类再试」→「没有结果，试试换个关键词或分类」，窄容器不再从句子中间难看断行）
- 136 tests 绿（+9：词典命中跳过翻译桥/端到端变体搜索/翻译三态/缓存等）

## v0.4.x 实测反馈批次 2（2026-09-05，并入 v1.0.0）

少爷实机实测收尾修复：

- **书架导入一次弹出**：桌面壳导入改走后端原生 NSOpenPanel（绕 pywebview file-input 委托链首击丢失——其 alert 对话框有弹框前激活步骤、file dialog 路径没有）；serve/浏览器形态自动回退 HTML file input
- **主题按钮图标=当前态语义**（简繁按钮同款铁律）：阅读页日间 ☀️ / 夜间 🌙 + 红线；主页 🌗 补暗色激活态（明/暗持久二态原无标记）；⚙️ 等瞬时动作维持无激活态
- **翻译桥打包修复**：bookfetch.spec datas 补 translate_bridge + TranslationActivator.app（此前分发级 .app 翻译桥缺失靠 dev 兜底）；CI macOS 步骤预编译翻译资产
- **搜索源三修**：① wikisource 搜索改 `intitle:` 只匹配标题——MediaWiki 全文搜索把正文引用书名的司法文书当结果（搜「百年孤独」命中长宁区法院盗版案判决书）② gutenberg 中文 query percent-encode（原直拼 URL 抛 UnicodeEncodeError，中文搜索必炸）③ libgen 状态文案改真实原因（官方 2024 起迁移新版站登录+API keys，匿名接口停用；适配排 PRD P2）
- 125 tests 绿（+3 导入对话框 hook 测试）

## 下一步 / 候选（P2，未排期）

- Windows 端翻译（N3 V2：在线翻译 provider，用户自选服务商自配 key）
- Apple 开发者签名（$99/年，消除首次右键打开）
- 手机 App

## v0.4.0（2026-09-05，桌面包已发布；未单独上 PyPI——内容并入 v1.0.0）

英文切章 + 下载体验三件套 + CLI/UI 边界 + 实测收尾：

- **英文切章**：英文书 `CHAPTER/CHAP. + 数字/罗马` 独立标题行成章（含目录/逐章翻译），正文句/罗马页码行永不误切
- **B4 下载三件套**（serve/gui 任务系统专属，CLI get 同步直连不受影响）：UI 下载并发队列（上限 3、排队可取消）；单文件 Range 断点续传；逐章断点续传 + 下载中「读已下 N 章」边下边读
- **书架半成品上架**：下载中的书以「未完成」条目上架，可直接读已下部分；完成自动换正式条目、阅读进度无缝继承
- **书架管理**：删除书（级联清理）、导入本地书（.txt/.epub）、打开书库目录
- **阅读器修复**：切章回顶、目录面板不挡导航、简繁切换（OpenCC 可选）
- 122 tests 绿，CI macOS/Windows 双平台绿

## v0.3.0（2026-09-04，PyPI 已发布）

- 中文古籍/网文/公版外文 7 源路由：ctext、github 多仓（mymmsc/books、xiaopangxia 中医药）、wikisource 中英、gutenberg、biquge、libgen
- 章节感知渲染：EPUB 零依赖生成（含目录）、txt 章节分隔、古籍《》/卷/序跋标题识别
- N1 fetch 缓存（source:id → 命中零网络）、N2 桌面 App / 浏览器 UI（搜索/书架/阅读器，「书卷宣纸」主题）、代理三态设置
- 反爬验证页明确报错不静默、下载日志、中文错误文案
- GitHub Actions：main push 出桌面包 artifact，tag v* 挂 Release

## v0.2 / v0.1（2026-09-03，开发期内部里程碑）

- M1-M8 源与核心 CLI（ctext 起步 → github 多仓 → wikisource → gutenberg → biquge 网文 → libgen 镜像链）
- OpenCC 简繁转换（可选依赖）、epub 转换、合规声明与 license 实测标注
