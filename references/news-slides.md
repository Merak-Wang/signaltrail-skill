# 新闻图文流运行参考

**权威语言：** 中文（单语运行参考）

**状态：** 已验证的独立投影 · **负责人：** 仓库维护者 · **最后对照代码：** 2026-09-23

本流程从已保存日报及其索引生成独立动态 HTML。Python 筛选代表新闻、拆分写作批次并附加来源与图片；模型只写讲解。原日报 JSON/Markdown 不变。有放映文件时，日报 HTML 屏幕端以嵌入式演示替代今日摘要，并保留“打开图文演示”独立入口；打印时隐藏演示并恢复摘要。后续重建仍保留演示入口。此流程不进入实验讲解的主张账本和独立审核流程。

## 准备与续写

```text
signaltrail slides prepare --report REPORT.json --index INDEX.json
signaltrail slides prepare --report REPORT.json --index INDEX.json --min-importance 70 --batch-size 4 --max-input-tokens 12000 --max-output-tokens 4000
signaltrail slides prepare --report REPORT.json --index INDEX.json --item-id ID_A --item-id ID_B
signaltrail slides submit --packet PACKET.json --input DRAFT.json
signaltrail slides status --plan PLAN.json
signaltrail slides render --plan PLAN.json
```

默认合并日报精选事件和重要性不低于 70 的简报，已由精选事件引用的简报不再重复展示。整期新闻总数没有上限。重复指定 `--item-id` 会覆盖默认筛选；ID 必须属于该日报，不能直接添加索引中未经日报处理的条目。没有条目入选时明确报错，不偷偷回退到全部新闻。

`prepare` 返回 `plan_path` 和 `packet_paths`。写作宿主只发送每个包的 `payload.model_input`；Schema 位于 `payload.model_input.output_schema`，预算位于 `payload.budget`。不要把整期日报、所有批次、历史对话、图片字节或 HTML 模板再塞进每个模型请求。包内已经有风格指引、日报摘要、来源访问等级和与本事件相关的条件分析。

每批一次写作，输出 `{"slides": [{"event_id": "...", "narration": "...", "perspectives": []}]}`。每个指定事件必须出现一次；中文讲解按非空白字符硬校验 200–350 字，标点计入。英文没有这个字符区间限制，但仍受 Schema 字段长度及批次输出估算限制。视角可以不选，只能选该事件已有分析中的 `geopolitics`、`markets`、`ai_technology`。不要在输出中重写标题、摘要、来源、图片或 caption。

成功提交后通过 `status` 查看待完成批号，恢复时复用已接受的结果。重复提交相同稿件返回已有产物，不重复生成版本；同一批已经接受另一份稿件时会拒绝。无效草稿不会自动请求修复模型。`render` 要求全部批次完成，缺批时拒绝整期渲染，避免静默漏新闻。

## 每批成本控制

默认每批最多四条；输入估算上限 12,000 token，输出估算上限 4,000 token。输入按序列化 `model_input` 的 UTF-8 字节数除以 2 向上取整，再加 512 token 预留；输出为每条新闻预留 700 token。任一限制不能容纳下一条时另起一批；单条仍不能容纳则提示调整额度。提交时也检查实际稿件的输出规模估算。

这些是规模估算门槛，不是 tokenizer 精确计数、实际账单或费用保证。宿主支持输出 token 参数时，应同时使用包里的 `max_output_tokens`；更大的隐藏上下文、推理 token 和宿主额外重试仍可能增加实际成本。模型调用由宿主执行，本模块不会直接调用服务商 API，也不会自动增加写作或审核调用。没有实际计量时，输入 token、输出 token、费用均为 `null`，不得写成零或把估算当实测。

全部代表新闻分批完成，不设每期总额度。改版式、切换图片、打印和重新渲染都不需要模型。

## 图文与来源

标题、摘要和来源引用来自日报，索引补充来源名称、时间以及封面图、正文图候选和原始 caption。候选图片合并后按 URL/图片身份去重，并优先保留高清候选；每条新闻不设固定图片上限。相同来源、相同位置的响应式候选只保留适合展示的高清版本。图集支持缩略图切换、查看大图、按原始尺寸 100% 查看，以及打开原始图片链接。更新图片候选时可复用已接受的讲稿，不增加模型调用。

`slides prepare` 只读取传入的日报和索引，不会联网抓取网页。需要补充正文证据时，先使用 `extract-content` 处理选定条目，再使用返回的富化索引准备演示；具体命令见[使用指南](../docs/zh-CN/usage.md)。该命令以正文提取为目标，不保证下载配图；演示仅使用索引中实际记录的候选图片。

caption 保留网站抽取原文，缺失时不显示；alt、标题和模型描述不能替代原图注。模板对文本转义，来源与图片外链只接受 HTTP(S)。本地缓存图片内嵌到单文件 HTML；尚未缓存的远程配图需要网络，失败时保留原图注并显示图片不可用。

清单 JSON 和 Markdown 随讲解版本保存；HTML 是可重建投影。页面支持目录、键盘翻页、全屏、图片缩略图和大图查看、原始尺寸查看、转场、手机布局、减少动画偏好和无脚本连续阅读。内容依照已保存日报时间，不宣称是重新核验的实时新闻。TTS 与视频合成本次不实现。
