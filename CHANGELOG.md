# Changelog

bookfetch 版本历史。版本号遵循 [SemVer](https://semver.org/lang/zh-CN/)：0.x 为开发期（2026-09-03 ~ 09-05），1.0.0 起为稳定对外版。

## 下一步 / 候选（P2，未排期）

- Windows 端翻译（N3 V2：在线翻译 provider，用户自选服务商自配 key）
- Apple 开发者签名（$99/年，消除首次右键打开）
- 手机 App

## v0.4.x（2026-09-05，桌面包已发布；PyPI 未同步）

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
