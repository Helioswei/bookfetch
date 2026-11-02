# TODO：防封 / 人机验证 后续事项

> 状态：**已审核，暂缓实施**（2026-11-02，Helios 确认）。
> 本轮（PR `feat/cli-resume-pacing`）只做了两件事：
> 1. CLI `get` 逐章断点续传，与桌面 App 同一实现（`fetch_cache.Checkpoint`）；
> 2. 请求节奏：每 host 一把锁、默认 2–4s 随机间隔、每 ~100 次请求长休 30–60s、
>    源级 `Source.min_interval`（能力已加，内置源均未设置）、CLI `--delay`、
>    桌面端同一源同时只跑一个下载任务（其余排队）。
>
> 下面各项**本轮未改**，古籍源与抓取策略保持原样。动手前需再次确认。

## (a) 识别 Cloudflare Turnstile 验证页

- 现状：`util._CHALLENGE_MARKS` 不含 Turnstile 特征。遇到 Turnstile 页时
  `looks_like_challenge()` 返回 False，页面被当成普通内容解析，结果是**空搜索结果 / 空章节**，
  用户看到的是“没找到”而不是“需要验证”。
- 计划：在 `_CHALLENGE_MARKS` 中加入
  - `cf-turnstile`
  - `challenges.cloudflare.com/turnstile`
  - `checking the security of your connection`
- 同时在 `tests/fixtures/` 加一份脱敏的 Turnstile 页面，补测试：
  `looks_like_challenge(fixture) is True`，且各源解析时抛 `HumanVerificationError`。
- 注意：只做“识别并停下”，**不做任何绕过**。

## (b) biquge：连续空章节应报错，并汇报跳过的章节

- 现状：`sources/biquge.py` 遇到空壳章节（解析为 `("", "")`）静默 `continue`。
  如果是被拦截导致的连续空页，会一路跳过，最终得到一本残缺的书且无提示。
- 计划：
  - 连续 N 章（暂定 3）为空 → 抛 `FetchError`/`HumanVerificationError`，断点保留，可续传；
  - 零星空章仍跳过，但在结果中记录（如 `FetchResult.extra["skipped"] = [章节名…]`），
    CLI JSON 输出与桌面任务完成提示中展示“跳过了 X 章”。

## (c) 遇到人机验证：保留进度、停下、引导用户自行验证后续传

- 现状：`n2core.friendly()` 对 `HumanVerificationError` 的文案是
  “……换个网络或代理节点后重试”。
- 计划：
  - 下载中遇到验证 → 立即停止（断点续传已就绪，进度不丢）；
  - 文案改为：请在**自己的浏览器**中打开该网站完成验证，稍后点击「继续下载」/
    重跑同一条 `bookfetch get` 命令续传；
  - 删除“换网络 / 换代理”的建议。
- 涉及错误文案变更，本轮按要求未动。

## (d) 多源回退建议

- 某源失败（被拦截 / 无结果 / 章节缺失）时，提示同一本书在其他源的可用版本
  （例如 ctext 失败 → 建议 wikisource / github 古籍仓库同名条目），由用户选择，**不自动切换**。
- 需要先定义书名匹配规则（繁简、卷数、版本差异），避免误配。

## (e) 待决策事项

1. **ctext 使用条款**：ctext.org 的条款不允许爬取，官方提供 API，但需要 API key。
   是否改为走 API（需申请 key、处理配额），或保留现状、降低使用频率，需要拍板。
2. **User-Agent 策略**：当前用 curl_cffi 模拟 Chrome 指纹（`_IMPERSONATE = "chrome"`）。
   另一种做法是使用诚实的 User-Agent（如 `bookfetch/<版本> (+项目地址)`），
   更透明，但更容易被 Cloudflare 一类的防护拦截。需要权衡后决定。

## 已知限制（与本轮改动相关）

- 断点续传依赖源实现 `on_checkpoint` / `resume_from`：目前 **biquge、ctext** 支持；
  wikisource、gutenberg、github、libgen 尚不支持（中断后从头下载）。
- ctext 以“wiki 页”为续传单位：一页拆出多章时，若恰好在写入这一页的几章之间崩溃，
  续传会从下一页开始（概率极低，写入之间没有网络请求）。
