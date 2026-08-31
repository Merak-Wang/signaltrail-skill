# 日报运行手册

**状态：** 已验证运行参考
**最后对照代码：** 2026-08-28
**上级地图：** [`ARCHITECTURE.md`](../ARCHITECTURE.md)

## 调度与预算

```text
最迟 05:00 启动满载候选/brief 分波与图片预取 -> 紧凑研判 -> 事实校验 -> 06:00 本地 HTML
HTML 交付后 -> 后台 PDF/可选 Notion -> 最多两次总尝试的有界独立评估 -> 刷新 HTML
最迟 17:00 启动满载候选/brief 分波与图片预取 -> 紧凑研判 -> 事实校验 -> 18:00 本地 HTML
HTML 交付后 -> 后台 PDF/可选 Notion -> 最多两次总尝试的有界独立评估 -> 刷新 HTML
```

每次正常运行最多 3600 秒，模型输入加输出最多 10,000,000 token。32 个正式来源满载时最多有 480 条普通 brief；需要准点交付时必须提前启动。采集脚本继续处理单源错误；brief/analysis authors 只消费计划内 packet 和影响研判的必要正文。开发/调试不受该预算限制。

监控层独立于模型预算。按需运行 `daily-intel refresh-monitor`，或用 `daily-intel serve --open --refresh-minutes 30` 在本地情报台后台刷新；RSS/Atom、静态 HTML、时间解析、图片元数据、聚类和来源健康均不调用模型。51 个发现来源的 `report_target` 和 `report_max` 均为 0，只扩展发现面，不扩大日报篇幅、正文读取上限或研判任务。`run-edition` 优先复用默认 90 分钟内的新鲜零-token 快照；仅在快照缺失或过期时刷新，刷新失败则保留旧快照并继续原采集流程。可用 `monitor.snapshot_max_age_minutes` 和 `monitor.reuse_fresh_snapshot_before_edition` 调整这一策略。

32 个正式来源的 `report_target` 和 `report_max` 均为 15。默认 `collection.item_order: source`，每来源候选充足时交付网页、榜单或 Feed 的原 Top1–15；切换为 `published_at` 时，采集层把有效发布时间从新到旧写入当前 index，缺失发布时间和时间并列的条目保持稳定输入顺序，日报再取前 15 条。单源覆盖使用同名 `item_order`。两种模式都保留原始 `source_rank`；context、普通 brief、Markdown、HTML、PDF 与 Notion 必须维持当前 index/`brief_plan` 顺序，不能按 `importance` 重排。Hugging Face Papers 的 `source` 模式以 Trending Top 为准，较早发表的论文仍可能出现在当前 Top15。

写作与评估保持角色隔离。`finalize-edition --defer-tail` 在不可变 JSON/Markdown 和 HTML 就绪后返回；authoring coordinator 立即交付 `artifacts.html_path`，再把 run 中的 `tail.command` 放进启用完成通知的后台 terminal。`complete-edition-tail` 生成 PDF、按请求发布 Notion，并先用当前 report/hash 预检已完成评估。内置的自动 host scheduler 当前只支持 Hermes Cron：它只读对账既有 job，每个 Cron 只执行一次；只有既有 job 明确失败或超过停滞窗口时才允许第二次且最后一次尝试，unknown/对账失败不会重复调度。independent evaluator 的输入只有 Python 生成的不可变 hash-bound dossier，输出是供 `finalize-evaluation` 接收的独立 JSON；它禁止修改报告。评估完成后刷新 HTML、桌面副本和归档索引，但同一 report revision 已存在的 PDF 直接复用；PDF 缺失时才补建，不能为加入评分重复渲染整份图片密集文档。目标日报显式使用了 `--publish` 时，调度合同才给评估命令追加 `--publish`。使用 Hermes 自动调度时，Gateway 必须运行并按部署要求保持可用；其他 harness 必须自行调度同一 dossier 并调用 `finalize-evaluation`，否则 tail 会如实保留为 `partial`。tail 或调度失败只写入 run，不撤回本地日报。晚间生成读取当天晨报和已存在的晨报评估；晨报评估尚未完成时按未评估历史处理。

## Harness 与用量接入

核心流程不要求特定 harness。宿主只需能运行本地命令、读取 packet、把结构化 JSON 写到 packet 指定路径，并把提交结果交给 authoring coordinator。所有宿主都应显式复用同一个 `--data-dir`；支持隔离 worker 时按最多 3 个并发 packet 分波，不支持时可以顺序执行。

`signaltrail-usage` 只内置 `hermes`、`codex`、`openclaw` 三个 adapter。其他 harness 可以不绑定 usage task，此时工作流保持可运行，但预算回执必须显示 `coverage=unmetered` 且 observed/projected token 为 `null`；也可以在 Python 中实现 `UsageAdapter` 并注册固定字段白名单。不得把未知宿主格式冒充现有 adapter。Hermes 提供逐请求 Hook 和聚合补录；Codex 使用 rollout JSONL；OpenClaw 使用经审计的 per-agent SQLite v17 或旧 JSONL。完整接入与隐私边界见 [`llm-usage.md`](llm-usage.md)。

## 交互式验证

`run-edition` 默认只记录失败、待验证或限流页面，不启动 Edge，也不等待人工操作。用户准备好交互时运行 `verify-pending`；显式 `run-edition --open-verification` 复用同一实现，但会等待队列完成或超时。Windows 使用可见 Edge 和专用 profile；验证入口只打开队列页，不预先打开所有失败网站。由 CLI 启动时页面显示“采集器已连接”，并实时更新每条链接的等待、验证、采集和失败状态；直接双击静态 HTML 时显示“未连接”，不会假装正在采集。

- 用户点击链接且页面验证成功：立即从当前页面提取，并原子合并进新索引。
- 页面关闭、403、超时或提取失败：立即跳过，保留链接和失败状态。
- 页面显示 temporarily limited/restricted 或返回 429：标为 `rate_limited`，停止本轮自动重试，等待后续时段；不得反复刷新或尝试绕过。
- 部分成功：继续日报，不要求所有来源成功。
- 验证后无需 `resume`；若已有日报，当前 authoring coordinator 继续生成补充修订并发布。

host scheduler、Gateway 和其他无人值守会话不得传 `--open-verification`。`--unattended` 保留为默认非交互行为的兼容参数。

## 数据根与耗时诊断

所有命令必须使用同一个 `DATA_DIR`。`data-root status` 显示当前绑定；只有确认迁移时才执行 `data-root adopt`。run 内的 `data_root` 与 artifact 路径必须一致，跨根引用在读取前失败。run 的 `artifacts.collection_metrics` 记录来源、候选、状态分布以及监控刷新/复用；`artifacts.enrichment.pipeline` 记录正文缓存、HTTP 提取、Edge 回退及各阶段耗时；报告保存结果的 `save_metrics` 区分编译校验、媒体、持久化、本地投影和状态更新。

`artifacts.authoring.metrics` 记录每个 brief 批次的 duration、API、输入/输出 token、模型、退出原因，以及 brief 合并、图片预取、紧凑研判与总写作时间；`artifacts.authoring.recovered_batches` 记录在分析准备时从合法 draft 恢复的批次，`missing_batches` 与 `coverage_targets` 记录恢复之后仍然缺失的批次及逐来源降级结果。选定宿主未提供的 queue/首 token/prefill/decode 字段保持空值，不能估算；当前 Hermes Hook 也不完整暴露这些字段。`milestones.local_html_ready_at`、`pdf_ready_at`、`notion_ready_at` 分开记录读者可见时间；`metrics.tail_seconds` 不混入 HTML 关键路径。`metrics.phase_durations_seconds` 汇总采集、context、正文、模型写作等待和验证/定稿，用这些机器计时定位慢点，不再用人工估算或一个总耗时混合后台工作。

## 恢复

- `awaiting_selection`：选择 ID，运行 `enrich-edition`。
- `awaiting_authoring` 且没有 session：运行 `begin-authoring`，只把计划内未复用缺口形成的 packet 按清单顺序分波；authoring coordinator 每波最多同时交付 3 个 packet，等待该波完成后再分发下一波，同时运行 `prefetch-media`。每个 brief author 的输入只有一个 packet 和其中列出的正文路径，输出只有指定 `draft_result_path` 的 JSON 与对 `submission_command` 的提交；`output_schema` 是字段、类型、枚举与额外字段的权威边界。Hermes 集成使用后台 `delegate_task`，且不得超过其 `max_concurrent_children=3`；其他 harness 使用等价 worker 或顺序执行，不得跳过后续波次。
- authoring 批次已返回：把宿主提供的有界批次指标写入 session 指定路径并运行 `record-authoring-metrics`；`authoring-status` 全部完成后运行 `prepare-analysis`。即使宿主完成通知或不可变接收结果缺失，也不要先删 draft：`prepare-analysis` 会对每个缺 receipt 的授权 `draft_result_path` 执行原 packet 校验，合法草稿会被原子接收并列入 `recovered_batches`。检查恢复后的 `missing_batches`，只有输出 `deadline_exceeded: true` 时才能用 `prepare-analysis --allow-degraded`。
- authoring 降级：只把对应 missing batch 所负责来源的 `coverage_targets` 降到该批实际接收数；其他已完成 batch 的来源仍保持原计划目标（候选不少于 15 时为 15）。semantic cache 和草稿都只能使用各来源 `brief_plan.default_item_ids`，不得用 Top15 之外的旧缓存补位。索引已有候选但 brief 缺失时，即使同栏目其他来源正常，也要列出缺失来源及“已验证摘要/计划”计数，不能写成未采集、`no_items`、来源失败或让该来源无提示消失。
- `analysis_pending`：analysis author 的输入只有 `analysis_packet_path`，其输出是严格满足 `output_schema` 的 `analysis_result_path`，并省略 `python_owned_output_fields` 列出的字段；authoring coordinator 随后运行 `assemble-authoring`、`validate-report --run` 和 `finalize-edition --defer-tail`。
- `finalizing` 在事实源持久化前失败：状态自动退回 `awaiting_authoring` 并记录错误；HTML/PDF 投影失败时 JSON/Markdown 仍有效，结果会记录 `local_output_error`，修复环境后重建投影即可，不要重新生成 revision。
- `tail.pending`：HTML 已有效；在后台执行 manifest 的精确 `tail.command`。
- `tail.partial`：读取 `tail.errors`，修复后重跑 `complete-edition-tail`；已存在 PDF/Notion 不会重复创建。
- 旧同步路径的 `publishing` 失败：重试 `finalize-edition --publish`。
- `failed`：阅读 manifest 的 `error`，修复后用 `run-edition --restart`。
- `completed_partial`：本地报告有效；待验证链接可留到后续处理。
- `evaluation pending`：日报已经完成；先检查独立评估调度和不可变 evaluation。Hermes 集成只有在当前 report ID/content hash 尚无完成评估、且既有 Cron 已明确 failed/expired 时，才创建一次新的有界评估尝试；其他 host scheduler 必须执行相同 preflight 和最多两次总尝试的边界。
- 评估失败：保留 pending/错误日志与失败 job 身份，按上述 preflight 显式重试；不得撤回日报、无限重调度或由 brief/analysis authors 自评。
- 监控部分失败：运行 `monitor-status` 查看来源状态；失败、限流和待验证不得改写为 `no_items`。旧快照仍可读取，下一次刷新会按 ETag/Last-Modified 和退避状态重试。

run manifest 固定在 `DATA_DIR/runs/YYYY-MM-DD/<edition>.json`。不要手改状态文件。删除过期锁前必须确认没有活动进程。

## 验收

前台交付检查：run/index/report 一致、schema 2.0、七个 section、所有正式来源目标/上限均为 15、有足够候选时正好使用本轮 `brief_plan` 的前 15 条、semantic cache 未越界、普通 brief 在 JSON/Markdown/HTML/PDF/Notion 中保持当前 index 顺序且未按 `importance` 重排、TL;DR 无访问状态话术、brief/精选事件关系、候选足够时满足精选新鲜度下限、发布时间（缺失时显示采集时间）与 NEW、URL/标题身份、正文访问等级、三个视角使用同一事件档案、每篇 `narrative` 为 4—7 个自然段、跨视角综合、JSON/Markdown/HTML、`reports/index.html`、`local_html_ready_at` 和待验证链接。若有 authoring 降级，还要核对 `recovered_batches`、`missing_batches` 与逐来源 `coverage_targets`，并确认已采集候选没有被描述为未采集。浏览器验收还要确认每条 brief 的标题先于配图、版本化 HTML 的相对图片存在，以及桌面 HTML 单独移入无媒体目录后所有内嵌图片均可加载。

后台收尾检查：tail 为 `completed` 或有可操作的 `partial` 错误；PDF、`pdf_ready_at`、可选 Notion page ID/`notion_ready_at` 和独立评估调度彼此可重试，不影响前台 HTML 有效性。核对 `pdf_projection_seconds`、`pdf_bytes`、`pdf_size_budget_bytes` 和 `pdf_size_budget_status`；超预算是显式警告。PDF 必须在断开本地媒体目录与网络后仍能显示全部已物化图片；用页面栅格化抽查和 PDF image XObject 计数确认打印重采样后的图片已写入文件，且不含外链依赖。

评估检查：九维完整、总分正确、被评 report ID/hash 匹配、独立 artifact 存在、HTML 评估区已刷新、同 revision PDF 已复用且字节与修改时间未变（缺失时才生成）、可选 Notion 已附加更新版 HTML 或可重试、长期连续状态按建议更新。

运行复盘中的计数只能来自 manifest 和根级 `items[]`；不得把 `verification_required`、`failed` 或 `metadata_only` 说成 `no_items`。

监控检查：`snapshot.json` 的 `token_usage` 为 0、来源总数与配置一致、story ID 跨刷新稳定、缺失发布时间的条目明确回退到采集时间、`health.json` 保留每个失败原因。本地情报台默认只绑定 `127.0.0.1`。
