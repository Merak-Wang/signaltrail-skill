# 新闻图文流运行参考

**权威语言：** 中文（单语运行参考）

**状态：** 已验证的独立投影 · **负责人：** 仓库维护者 · **最后对照代码：** 2026-09-23

本流程从已保存日报及其索引生成独立动态 HTML。日报定稿会自动准备计划和写作包，并将路径登记在 `artifacts.slides`；宿主完成写作批次并渲染后，日报才算完成。Python 筛选代表新闻、拆分写作批次并附加来源与图片；模型只写讲解，准备阶段不调用模型。原日报 JSON/Markdown 不变。有放映文件时，日报 HTML 屏幕端以嵌入式演示替代今日摘要，并保留“打开图文演示”独立入口；打印时隐藏演示并恢复摘要。准备失败记录在 `artifacts.slides.error`，不撤销本地日报；可从保存报告恢复。此流程不进入实验讲解的主张账本和独立审核流程。

Feed 更新时间不代替发布时间。Hacker News、Lobsters 等发现型来源以平台当天转发日期为准，原文可以更早发布；正文抽取时保留转发日期，原网页日期另存于 `metadata.content_source.published_at`。直接来自新闻网站的条目以原站发布日期为准。跨日或含未知日期来源的聚合事件不直接沿用摘要；改由满足日期和重要性条件的当天独立简报入选，避免只删除旧引用却保留旧来源写成的内容。

## 准备与续写

```text
signaltrail slides prepare --report REPORT.json --index INDEX.json
signaltrail slides prepare --report REPORT.json --index INDEX.json --min-importance 70 --batch-size 4 --max-input-tokens 12000 --max-output-tokens 4000
signaltrail slides prepare --report REPORT.json --index INDEX.json --item-id ID_A --item-id ID_B
signaltrail slides submit --packet PACKET.json --input DRAFT.json
signaltrail slides status --plan PLAN.json
signaltrail slides render --plan PLAN.json
signaltrail slides render --plan PLAN.json --offline
```

默认合并日报精选事件和重要性不低于 70 的简报，已由精选事件引用的简报不再重复展示。随后只保留 `report.date` 当天发布的新闻；以权威索引 `index.items[].published_at` 为准，按 `report.timezone`、`index.timezone`、`Asia/Shanghai` 的优先顺序转换到本地日期。发布时间缺失或无效即排除；不得用采集时间或索引更新时间代替。重复指定 `--item-id` 会覆盖重要性默认筛选，但不能绕过日期规则；ID 必须属于该日报，不能直接添加索引中未经日报处理的条目。该规则只筛图文流，不改变主日报。没有条目入选时明确报错，不偷偷回退到全部新闻。

`prepare` 返回 `plan_path` 和 `packet_paths`。写作宿主只发送每个包的 `payload.model_input`；Schema 位于 `payload.model_input.output_schema`，预算位于 `payload.budget`。不要把整期日报、所有批次、历史对话、图片字节或 HTML 模板再塞进每个模型请求。包内已经有风格指引、日报摘要、来源访问等级和与本事件相关的条件分析。

各 packet 相互独立；宿主每波最多同时写作 3 个 packet，每个 worker 只读取和提交自己的包，整波返回后再分发下一波。SignalTrail 的 Hermes 集成通过 `delegate_task(background=False)` 同步等待整波返回，内部并发仍受 `max_concurrent_children=3` 限制。日报使用 `--defer-tail` 时，可在后台运行清单中的 `tail.command`，同时完成讲稿批次。全部批次通过且尾任务退出后再运行 `slides render`，避免 PDF/评估尾任务与日报 HTML 投影更新并发。

每批一次写作，输出 `{"slides": [{"event_id": "...", "narration": "...", "perspectives": []}]}`。每个指定事件必须出现一次；中文讲解按非空白字符硬校验 200–350 字，标点计入。英文没有这个字符区间限制，但仍受 Schema 字段长度及批次输出估算限制。视角可以不选，只能选该事件已有分析中的 `geopolitics`、`markets`、`ai_technology`。不要在输出中重写标题、摘要、来源、图片或 caption。

成功提交后通过 `status` 查看待完成批号，恢复时复用已接受的结果。重复提交相同稿件返回已有产物，不重复生成版本；同一批已经接受另一份稿件时会拒绝。无效草稿不会自动请求修复模型。`render` 要求全部批次完成，缺批时拒绝整期渲染，避免静默漏新闻。

## 每批成本控制

默认每批最多四条；输入估算上限 12,000 token，输出估算上限 4,000 token。输入按序列化 `model_input` 的 UTF-8 字节数除以 2 向上取整，再加 512 token 预留；输出为每条新闻预留 700 token。任一限制不能容纳下一条时另起一批；单条仍不能容纳则提示调整额度。提交时也检查实际稿件的输出规模估算。

这些是规模估算门槛，不是 tokenizer 精确计数、实际账单或费用保证。宿主支持输出 token 参数时，应同时使用包里的 `max_output_tokens`；更大的隐藏上下文、推理 token 和宿主额外重试仍可能增加实际成本。模型调用由宿主执行，本模块不会直接调用服务商 API，也不会自动增加写作或审核调用。没有实际计量时，输入 token、输出 token、费用均为 `null`，不得写成零或把估算当实测。

全部代表新闻分批完成，不设每期总额度。改版式、切换图片、打印和重新渲染都不需要模型。

## 图文与来源

标题、摘要和来源引用来自日报，索引补充来源名称、时间以及已有封面图和正文图候选。默认在线 `render` 还会读取入选新闻的公开原文页，补充正文图片和原站 caption；文章请求共用 HTTPX 连接池，并按域名轮转补足空闲并发槽位，同时遵守全局和单域上限。图片下载也使用有界并发。候选依据页面明确的 `srcset`、URL 宽度与 DPR 声明选择，并按媒体配置预算下载缓存。实际清晰度受发布者提供的版本、访问情况和下载结果限制，不保证每张图都能取得原尺寸。页面抓取或下载失败时保留已有索引候选。此过程不改写正文证据、正文状态或访问等级，也不增加模型调用。候选图片按 URL/图片身份去重，每条新闻不设固定图片上限。图集支持缩略图切换、查看大图、按原始尺寸 100% 查看，以及打开原始图片链接。更新图片候选时可复用已接受的讲稿。

`slides prepare` 只读取传入的日报和索引，不会联网抓取网页。需要补充正文证据时，先使用 `extract-content` 处理选定条目，再使用返回的富化索引准备演示；具体命令见[使用指南](../docs/zh-CN/usage.md)。该命令以正文提取为目标；在线 `render` 会另行补充图片候选。使用 `slides render --offline` 时只重放既有 deck 和本地图片文件，不访问原文页或下载图片，适合只改版式。

caption 保留网站抽取原文，缺失时不显示；alt、标题和模型描述不能替代原图注。模板对文本转义，来源与图片外链只接受 HTTP(S)。本地缓存图片内嵌到单文件 HTML；尚未缓存的远程配图需要网络，失败时保留原图注并显示图片不可用。

清单 JSON 和 Markdown 随讲解版本保存；HTML 是可重建投影。页面支持目录、键盘翻页、全屏、图片缩略图和大图查看、原始尺寸查看、转场、手机布局、减少动画偏好和无脚本连续阅读。内容依照已保存日报时间，不宣称是重新核验的实时新闻。TTS 与视频合成本次不实现。
