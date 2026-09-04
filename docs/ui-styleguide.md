# bookfetch UI 样式规范（组件族速查）

> 本文件是「后加 UI 必须与整体一致」的纪律依据（2026-09-05 少爷实测反馈定稿）。
> 任何新 UI 元素先在这里找归属族，**禁止自造新视觉**。token 与主题详见
> `style.css` 顶部注释与 `references/ui-paper-ink-theme.md`（Hermes skill）。

## 设计语言（一句话）

宣纸暖底 · 墨字 · 印泥朱红做唯一强调色。纸墨朱之外不再引入新主色。

## 按钮分级（只有这三族，新增按钮对号入座）

| 族 | 位置 | 视觉 | 激活态 | 说明 |
|---|---|---|---|---|
| A. 顶栏按钮族 | topbar / reader-top 内的 `<button>` | 无框字钮：`background:none;border:none`，墨灰字，hover 朱红 | 朱红字 + 底部 2px 朱红下划线（`margin-bottom:-1px` 压住容器底边线），加 `.on` 或 `.active` | **不用写任何 class**，CSS 已按容器选择器覆盖。`.tab`（主视图"搜索/书架"双字导航）额外带 `letter-spacing:.3em` 字距，其它按钮不加字距（阅读页紧凑排布） |
| B. 内容区操作钮 | 搜索提交、卡片"下载"，阅读器底栏"上一章/下一章" | 1px 细线描边圆角钮（`border:1px solid #cfc3ab`，透明底）hover 朱红描边+字 | 实心朱红（`background:var(--seal)`，如 epub 下载钮） | 第一版定稿语言，保持现状别动 |
| C. 面板内小钮 | 任务面板 `.mini`、设置模态 `✕`/`保存` | 小号描边 / `.primary` 实心朱红 | — | 只出现于浮层面板 |

图标/emoji 工具钮（🌗 ⚙ Aa 🌙）一律归 A 族：同 `padding:.3rem .42rem`、`display:inline-flex;align-items:center`，与文字钮视觉等高，**不要给它们加边框**。emoji 字形视觉小于汉字：🌗⚙🌙 图标钮统一 `font-size:1.25rem`（CSS 已含 `#tab-theme,#tab-settings,#reader-theme`），⚙ 齿轮纤细须再单列 `#tab-settings{font-size:1.4rem}` 才与 🌗 像素级齐平（2026-09-05 截图实测：两图标 ink 高 26 vs 25px）。

## 激活态（.on / .active）语义登记

- `#tab-search / #tab-shelf .active`：当前主视图
- `#reader-toc-toggle .on`：目录面板开
- `#reader-simp .on`：正在读简体（按钮文字=当前语言：繁书初始「繁」，简书初始「简」，点击双向切换）
- `#reader-theme .on`：阅读器夜间模式开

其它"开关类"新控件照此约定加 `.on`。瞬时动作（切换主题、字号）不加激活态。

## 布局要点与坑

1. 顶栏容器（topbar/reader-top）有 `border-bottom:1px solid var(--line)`；激活钮的 2px 下划线靠 `margin-bottom:-1px` 与容器线重叠——复制 `.tab` 的做法，不要用 `box-shadow` 模拟。
2. reader-top 左侧导航（← 书架/搜索）、右侧工具（目录/简繁/字号/夜间）；书名 `#reader-title` 占中自动省略。目录面板（280px，`z-index:5`）开时正文 `padding-left:300px`，按钮仍在顶栏、永远不被面板盖住。
3. `.hidden{display:none!important}` 是唯一显隐手段；模态遮罩点外关闭、任务面板 ✕=收起不取消 等交互约定见 PRD。
4. 文案：按钮文字=当前态语义（"简"=现在读简体，点它转繁体），不用目标态。
5. 前端渲染任何网络文本先 `esc()`；`button` 的 `font-family:inherit` 必须带（Pico 会改字体）。
6. 历史：v0.1 定稿全一致；D1 后新增的 `.ghost-btn`（1px 边框小圆角钮）与第一版割裂，2026-09-05 已废除并入 A 族。看到 `.ghost-btn`/`.toc-btn` 残留 = 旧债，删并归族。
7. emoji 图标大小验证用像素法：截图 + PIL 按列统计非背景像素的 ink bbox（两图标 ink 高差 ≤1px 为齐平）；vision 目测 ±20% 不可靠，别信。

## 验收（改完样式必做）

1. `uv run pytest tests/ -q` 全绿
2. serve 起后 Chrome headless / browser_exec 截图主页 + 阅读页 + 目录开态三视图（深链 `#shelf` / `#reader/<rel>`），vision 检查按钮族一致、无遮挡
3. 新增按钮族组件时同步更新本表
