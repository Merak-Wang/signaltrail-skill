# 新闻图文流运行参考

**权威语言：** 中文（单语运行参考）

**状态：** 已验证的独立投影 · **负责人：** 仓库维护者 · **最后对照代码：** 2026-09-23

本流程从已保存日报及其索引生成独立动态 HTML。日报定稿会自动准备计划和写作包，并将路径登记在 `artifacts.slides`。本地报告可先保存并交付，但这只表示“报告已保存”；完成全部讲稿提交、渲染及整期交付验收后，才能称为“整期交付完成”。默认日报无论 metered 或 unmetered 都必须完成图文流。Python 从整份日报中去重、排序并选择有界批次，附加来源与图片；模型只写讲解，准备阶段不调用模型。原日报 JSON/Markdown 不变。有放映文件时，日报 HTML 屏幕端以嵌入式演示替代今日摘要，并保留“打开图文演示”独立入口；打印时隐藏演示并恢复摘要。准备失败记录在 `artifacts.slides.error`，不撤销本地日报。整期恢复时运行 `finalize-edition --run RUN.json --report SAVED_REPORT.json --defer-tail` 重新登记计划；单独运行 `slides prepare` 仍可独立准备，但不会更新运行清单。此流程不进入实验讲解的主张账本和独立审核流程。

图文流的候选范围是整份已保存日报中的精选事件与简报，不再按来源发布时间或报告日期二次筛选。来源发布日期缺失时继续保持未知；不得用发现时间、采集时间或索引更新时间补造日期。Hacker News、Lobsters 等发现型来源仍保留平台提交日期，原网页日期另存于 `metadata.content_source.published_at`；直接发布来源保留原站日期。跨日或含未知日期的聚合事件保留其完整来源引用，不删旧来源后沿用原摘要。

## 准备与续写

```text
signaltrail slides prepare --report REPORT.json --index INDEX.json
signaltrail slides prepare --report REPORT.json --index INDEX.json --max-news 50 --batch-size 4 --max-input-tokens 12000 --max-output-tokens 4000
signaltrail slides prepare --report REPORT.json --index INDEX.json --item-id ID_A --item-id ID_B
signaltrail slides submit --packet PACKET.json --input DRAFT.json
signaltrail slides status --plan PLAN.json
signaltrail slides render --plan PLAN.json
signaltrail slides render --plan PLAN.json --offline
```

候选覆盖整份已保存日报，包括其中全部精选事件和简报；不从日报之外的索引条目扩充。先按原文身份去重并合并来源引用，再按重要性降序排列，默认准备前 50 条。可用 `slides prepare --max-news N` 设置其他正整数；`finalize-edition --slides-max-news N` 用于定稿流程的日常配置。没有按来源分配名额的保证，某来源可能在前 N 条中没有入选。新一期默认前 50 条；恢复既有运行且未显式指定数量时沿用上次设置，明确修改数量才准备新计划。日期缺失或来源日期不同不再排除候选；日期值应忠实保留未知，不能用发现、采集或更新时间代替。没有图片不影响入选。此选择只影响图文流，不改变主日报。每个写作数据包仍是一组有界新闻，默认每批四条。

`prepare` 返回 `plan_path` 和 `packet_paths`；正式日报应直接采用 run manifest 的 `artifacts.slides.plan_path` 与 `artifacts.slides.packet_paths[]`，并保留每个文件的真实绝对路径。写作宿主只发送每个包的 `payload.model_input`；Schema 位于 `payload.model_input.output_schema`，预算位于 `payload.budget`。不要把整期日报、所有批次、历史对话、图片字节或 HTML 模板再塞进每个模型请求。包内已经有风格指引、日报摘要、来源访问等级和与本事件相关的条件分析。

各 packet 相互独立；宿主每波最多同时写作 3 个 packet，每个 worker 只读取和提交自己的包，整波返回后再分发下一波。SignalTrail 的 Hermes 集成通过 `delegate_task(background=False)` 同步等待整波返回，内部并发仍受 `max_concurrent_children=3` 限制。日报使用 `--defer-tail` 时，可在后台运行清单中的 `tail.command`，同时完成讲稿批次。全部批次通过且尾任务退出后再运行 `slides render`，避免 PDF/评估尾任务与日报 HTML 投影更新并发。无论是否计量，整期验收都要包含 `edition-status --run RUN.json --require-complete`。以该命令的动态结果为准；不得根据 `run.status`、可能过期的 manifest 图文流快照或 tail 单独推断完成。

每批一次写作，输出 `{"slides": [{"event_id": "...", "narration": "...", "perspectives": []}]}`。每个指定事件必须出现一次；中文讲解按非空白字符硬校验 200–350 字，标点计入。英文没有这个字符区间限制，但仍受 Schema 字段长度及批次输出估算限制。视角可以不选，只能选该事件已有分析中的 `geopolitics`、`markets`、`ai_technology`。不要在输出中重写标题、摘要、来源、图片或 caption。

成功提交后通过 `status` 查看待完成批号，恢复时复用已接受的结果。重复提交相同稿件返回已有产物，不重复生成版本；同一批已经接受另一份稿件时会拒绝。无效草稿不会自动请求修复模型。`render` 要求全部批次完成，缺批时拒绝整期渲染，避免静默漏新闻。

## 每批成本控制

默认每批最多四条；输入估算上限 12,000 token，输出估算上限 4,000 token。输入按序列化 `model_input` 的 UTF-8 字节数除以 2 向上取整，再加 512 token 预留；输出为每条新闻预留 700 token。任一限制不能容纳下一条时另起一批；单条仍不能容纳则提示调整额度。提交时也检查实际稿件的输出规模估算。

这些是规模估算门槛，不是 tokenizer 精确计数、实际账单或费用保证。宿主支持输出 token 参数时，应同时使用包里的 `max_output_tokens`；更大的隐藏上下文、推理 token 和宿主额外重试仍可能增加实际成本。模型调用由宿主执行，本模块不会直接调用服务商 API，也不会自动增加写作或审核调用。没有实际计量时，输入 token、输出 token、费用均为 `null`，不得写成零或把估算当实测。

默认最多准备 50 条代表新闻，修改 `--max-news` 可自定义条数；批次输入/输出预算仍分别约束单批大小。改版式、切换图片、打印和重新渲染都不需要模型。

## 图文与来源

标题、摘要和来源引用来自日报，索引补充来源名称、时间以及已有封面图和正文图候选。默认在线 `render` 还会读取入选新闻的公开原文页，补充正文图片和原站 caption；文章请求共用 HTTPX 连接池，并按域名轮转补足空闲并发槽位，同时遵守全局和单域上限。图片下载也使用有界并发。候选依据页面明确的 `srcset`、URL 宽度与 DPR 声明选择，并按媒体配置预算下载缓存。实际清晰度受发布者提供的版本、访问情况和下载结果限制，不保证每张图都能取得原尺寸。页面抓取或下载失败时保留已有索引候选。此过程不改写正文证据、正文状态或访问等级，也不增加模型调用。候选图片按 URL/图片身份去重，每条新闻不设固定图片上限。图集支持缩略图切换、查看大图、按原始尺寸 100% 查看，以及打开原始图片链接。更新图片候选时可复用已接受的讲稿。

`slides prepare` 只读取传入的日报和索引，不会联网抓取网页。需要补充正文证据时，先使用 `extract-content` 处理选定条目，再使用返回的富化索引准备演示；具体命令见[使用指南](../docs/zh-CN/usage.md)。该命令以正文提取为目标；在线 `render` 会另行补充图片候选。使用 `slides render --offline` 时只重放既有 deck 和本地图片文件，不访问原文页或下载图片，适合只改版式。

caption 保留网站抽取原文，缺失时不显示；alt、标题和模型描述不能替代原图注。模板对文本转义，来源与图片外链只接受 HTTP(S)。本地缓存图片内嵌到单文件 HTML；尚未缓存的远程配图需要网络，失败时保留原图注并显示图片不可用。

清单 JSON 和 Markdown 随讲解版本保存；HTML 是可重建投影。页面支持目录、键盘翻页、全屏、图片缩略图和大图查看、原始尺寸查看、转场、手机布局、减少动画偏好和无脚本连续阅读。内容依照已保存日报时间，不宣称是重新核验的实时新闻。TTS 与视频合成本次不实现。
