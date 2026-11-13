# 日报运行手册

**权威语言：** 中文（单语运行参考）
**负责人：** 仓库维护者
**状态：** 已验证运行参考
**最后对照代码：** 2026-11-02
**上级地图：** [`ARCHITECTURE.md`](../ARCHITECTURE.md)

## 调度与预算

协调器读取运行清单中的 `artifacts.coordinator_path`。该投影保留选题证据和 Brief Plan，
限制历史状态、移除 Python 专用校验摘要以及已接收摘要的重复正文；候选中的 `url`、
`image_url` 和 `discovered_at` 仅从协调器副本省略，完整权威 Context 仍由 Python 使用，
作者 packet 也不受影响。旧运行没有该字段时才回退读取 `context_path`。

同一版固定输入复用已有索引、富化检查点、已接受草稿和图文讲稿；只有具体证据缺口才做有界补取。协调器只读紧凑回执、运行清单和协调器投影，遇到具体缺口才读取相关文件的小范围内容，不逐包读取正文或通读完整报告。

正文富化必须在 `begin-authoring` 之前完成。若中断在 `extracting_content`，重试
`signaltrail --data-dir DATA_DIR enrich-edition --run RUN.json` 即可恢复已绑定的选择；
也可传原来的完整 ID 列表，但不能换一组条目。完成的提取结果先存入运行专属
`content-checkpoints/`，再提交不可变索引，因此索引或 Context 写入失败不必重新抓取。
抓取中途、尚未形成完整提取检查点时，中断的一轮最多仍需重做原有的 12 条授权请求；
若恢复时已过运行截止时间，只复用已经完成的检查点，没有检查点则跳过新抓取并记录预算耗尽。
检查点不授予重试受限来源或扩大正文预算的权限。旧运行若缺少恢复绑定，需要显式重启。
已经派发作者任务后，新增富化或验证索引替换会被拒绝；先完成当前版次，或开启新尝试。

程序完成日期资格、材料可用性检查与输入冻结后即可派发简报作者。图文事件的语义合并和影响排序与简报写作并行，仍须审阅每源限额内的全部合格候选，并在报告定稿前保存完整决定。简报收录范围由当日来源索引决定，不依赖图文前五十条的选题结果。

默认每天生成一次 `daily`，按选定时区冻结生成前 24 小时的采集窗口。同一日期恢复既有运行；
只有明确重启时使用 `--restart`。`morning`／`evening` 用于历史恢复。调度时间由用户选择，
需要准点交付时预留采集与写作时间。

```text
采集补证及程序检查 → 简报、图片预取与全候选图文审阅并行 → 研判 → 校验与保存 HTML
→ tail 与图文讲稿 → 等待 tail 和讲稿完成 → 渲染 → edition-status 整期验收
```

默认配置的运行预算为 3600 秒、模型输入加输出 10,000,000 token，实际覆盖由所有启用来源中按原发时间选取的每源最多15条合格当日条目决定。采集脚本继续处理单源错误；brief/analysis authors 只消费计划内 packet 和影响研判的必要正文。开发/调试独立计量。时间对照必须分别列实际墙钟时间与给定输出速率的推算；缓存输入计入累计 token，模型输出速率只用于输出生成阶段。

日报按需执行采集，不启动常驻服务或后台定时采集。监控快照可作为采集输入；RSS/Atom、静态 HTML、时间解析、图片元数据、聚类和来源健康均不调用模型。需要单独检查时可运行 `refresh-monitor`；`serve --open` 默认只读。所有启用来源均参与日报采集，保留实际访问状态。

日报从版本所在上海自然日、冻结截止时刻之前的可核实原发新闻中，同源去重后按原发时间从新到旧选取每源最多15条，保留原始 `source_rank`。同源规范网址去重，跨来源保留各自位置；相同原文可复用写作结果。缺失或较早的原发日期、榜单与收录时间不作为当日资格。

用户请求日报即授权完成采集、写作、尾任务、幻灯片讲稿、渲染与整期验收。报告保存后发送进度说明并继续执行；动态 `edition-status` 返回待办时，按命令和 packet 路径继续推进，直至 `delivery_complete: true`。只有人工验证、明确请求但缺少独立执行者的评分等外部条件阻塞后续时，才向用户报告具体阻塞及恢复动作；已耗尽动作不反复重试。

质量评分默认关闭，仅当用户明确要求时在 `finalize-edition` 或 `complete-edition-tail` 加 `--evaluate`。请求写入本轮 `evaluation_requested` 并在恢复时沿用；未请求时不创建 evaluator、dossier 或评分用量任务，run 记为 `not_requested`。结构、引用和文件校验正常执行。以下评分调度与重试步骤仅适用于已明确请求的运行。

写作与评估保持角色隔离。`finalize-edition --defer-tail` 在不可变 JSON/Markdown 和 HTML 就绪后返回，随后继续完成整期交付。`complete-edition-tail` 生成 PDF、按请求发布 Notion，并处理用户明确请求的评分。图文讲稿可与 tail 同时进行；等待 tail 退出后再渲染，因为两项操作都可能更新日报投影。

评分 backend 默认是 external。独立 evaluator 只读不可变 dossier，按其 `evaluation_contract` 写入 JSON，再执行 `edition-status` 给出的 `finalize-evaluation` 命令。Evaluator 必须未参与报告写作；没有独立 Agent 时保留 pending。仅显式传 `--evaluation-backend hermes` 才调度 Hermes evaluator。评估完成后刷新 HTML、桌面副本和归档索引；已存在的同 revision PDF 会复用。目标日报显式请求 `--publish` 时，评估命令才追加 `--publish`。Hermes 调度恢复、Gateway 和计量限制见[用量说明](llm-usage.md)及[Hermes 集成](hermes-integration.md)。tail 或调度失败不撤回本地日报。每日日报优先读取前一日的日报和已有评估；评估尚未完成时按未评估历史处理。

需要独立质量复核时，在定稿前只安排一次未参与写作的独立 Agent，使用新上下文读取紧凑材料：按索引顺序固定抽取 6 条样本、3 个领域研判、综合研判，以及程序生成的校验和覆盖统计。复核者一次提出合并后的具体修改意见，作者按意见修正后执行程序校验；针对具体问题才读取相关证据。避免在长历史中反复串行审查、重写简报和研判、重做 PDF 与图文。此复核与用户明确请求的持久化评分分开执行。

## Harness 与用量接入

与运行关联的文字修订，通过 Python `save_report` 传入原 context 的 `coverage_targets` 和 `brief_plan_item_ids`，沿用覆盖目标与选择顺序，避免默认计划重建后改变排序；独立 `save-report` CLI 没有 `--run` 参数。

核心流程不要求特定 harness。全程复用同一个 `--data-dir`，会话建立后用源码入口 `--advance-edition RUN.json --data-dir DATA_DIR` 推进确定性步骤。新的完整写作投影保存在专用 `author-inputs/`，程序按材料体量降序返回最多三个任务票据；用 `--task-limit 空槽数` 控制本次数量，并重复 `--in-flight 批次ID或包路径` 排除运行任务。简报、分析和讲稿均提供 `input_parts_dir` 及有序 `input_parts` 文件名，每块至多 7500 个 `o200k_base` token，按序拼接的 UTF-8 字节与完整输入一致。作者按序逐块读取，每个工具结果只放一块，读完全部材料后写作。`input_file` 留作审计，作者不再打印大文件或自行分块。完整错误位于 `repair_errors_file`，异常问题位于 `issues_file`。保存 `draft_result_path` 后在同一次工具执行中运行 `check_command`，只输出简短结果；接收由推进程序完成。日期或榜单信号确定的 WATCH 在预检和接收时归一，文字、重要性及其余有效编辑判断保持原值。事件审阅通过 `--slides-review REVIEW.json` 传入，规范 URL 别名绑定报告文字时保留原 event ID。

`slides review --index INDEX.json --max-news 50 --model-input --parts-dir REVIEW_INPUT_DIR` 将每源限额内的全部合格候选按相同方法分块，模型仍需读完所有候选后给出决定。恢复已有冻结输入可运行 `scripts/run_signaltrail.py --prepare-input-parts FILE`。设置大的输出上限不能代替分块。每次只读一个 part，并把外层 pragma 和内层命令的输出上限均设为任务值（当前为 9000）：

```javascript
// @exec: {"max_output_tokens": 9000}
const r = await tools.exec_command({
  cmd: "Get-Content -Raw -LiteralPath 'INPUT_PART'",
  max_output_tokens: 9000
});
text(r.output);
```

协调者只读短回执、完成通知和路径，作者独立读取正文与修复错误。候选审阅的 lead 跳过导航和孤立短行，保留 `body_chars`、`evidence_chars` 供判断材料可用性，重大短公告继续保留审阅资格。

每次推进后沿用返回的 `continue_command`，追加空槽数和仍在途的任务 ID。收到作者完成通知后再移除对应的 `--in-flight`，程序跳过在途草稿，只为空闲槽位生成完整输入。整期只有一位协调者直接管理作者；四槽位最多容纳三位独立作者，不再常驻监督者或观察者。阶段切换和接收十批不会停派或产生接班协调者。Python 完成例行接收、组装和阶段推进，模型仅处理短票据、真实失败、编辑判断与最终交付。等待作者完成通知，长进程在工具内部等待；状态未变时不重新读取产物或启动额外审查。视频由当前协调者直接运行确定性导出命令并保留进程句柄。只有宿主实际上下文限制需要恢复时，才保存在途任务句柄、run/data/review 路径、继续命令及用户要求；旧 `--coordinator-start` 参数仍可读取，但不再强制交接。

优化时保留完整作者证据、实质内容和交付质量。时间与 token 目标用于改进调度和上下文复用；如实报告实测结果及未达目标，不能为满足数字而压缩应交付内容。

进入图文写作后，把 `background_commands` 返回的图片预取、未完成 tail/PDF 各作为后台工具进程启动一次，保留进程句柄；运行期间分别传 `--in-flight slides-images`、`--in-flight edition-tail`。二者与作者并行，渲染前在工具内等待全部结束，避免共同更新日报投影。图片手动命令为 `slides prefetch-images --plan PLAN.json`，原子写入同计划旁的 `images-slides-plan-rN.json`，渲染直接复用完整新闻图片和计量。重抓时加 `--refresh`，默认图片下载预算为 250 MiB。

有隔离 worker 时最多同时运行 3 个 packet，一个完成就补下一个；否则顺序执行。简报、研判和图文每项任务重新创建作者，上下文仅含当前任务和写作指令。Codex 使用 `spawn_agent(fork_turns="none")`；`followup_task` 保留旧上下文，不能用于跨批派发。任务尚在执行时从待办中排除；依赖完成通知调度，多个草稿一起提交。长进程在同一次工具脚本内等待。

Codex 运行的耗时和用量使用 `scripts/measure_codex_turn.py` 从运行记录确定性汇总，阶段耗时使用已有机器记录；不派模型执行计量。成本对照固定相同输入、模型和统计范围，包含协调器和全部子任务。cached input 是 token 数量，实际金额须有真实价格与计费数据；缺失时保留未知。

`signaltrail-usage` 只内置 `hermes`、`codex`、`openclaw` 三个 adapter。其他 harness 可以不绑定 usage task，此时工作流保持可运行，但预算回执必须显示 `coverage=unmetered` 且 observed/projected token 为 `null`；也可以在 Python 中实现 `UsageAdapter` 并注册固定字段白名单。不得把未知宿主格式冒充现有 adapter。Hermes 提供逐请求 Hook 和聚合补录；Codex 使用 rollout JSONL；OpenClaw 使用经审计的 per-agent SQLite v17 或旧 JSONL。完整接入与隐私边界见 [`llm-usage.md`](llm-usage.md)。

## 图文幻灯片

图文流是默认日报整期交付的必需组成部分，无论 run 为 metered 或 unmetered。报告 JSON/Markdown 与 HTML 可以先保存和交付；只有全部批次通过、渲染成功并通过整期验收，才标记为“整期交付完成”。从日报与对应索引准备批次，使用 manifest 中真实计划/packet 路径，读取每包 `payload.model_input` 并提交草稿；最多同时运行 3 个隔离 worker，一个完成就按序补下一个；也可由单个 Agent 顺序处理。全部批次通过且 tail 退出后渲染：

```text
signaltrail --data-dir DATA_DIR slides prepare --report REPORT.json --index INDEX.json
signaltrail --data-dir DATA_DIR slides submit --packet PACKET.json --input DRAFT.json
signaltrail --data-dir DATA_DIR slides status --plan PLAN.json
signaltrail --data-dir DATA_DIR slides render --plan PLAN.json
signaltrail --data-dir DATA_DIR edition-status --run RUN.json --require-complete
```

图文流先审阅今日候选与候补，按实质事件合并跨来源报道，依据影响和证据排序，默认最多 50 条；符合条件不足时交付实际数量。入选新闻先补充可用正文并审阅证据，再分派讲稿作者。正文不截断；默认按每批估算 64,000 token 拆批，显式上限为硬限制。渲染附加公开图片与图注，详见[新闻图文流参考](news-slides.md)。
渲染也更新日报 HTML 的嵌入容器及独立打开入口。`edition-status` 输出 `delivery_complete`、`report_status`、`pending_steps` 和图文流状态；只有动态命令返回 `delivery_complete: true`、`pending_steps` 为空且 `slides.status` 为 `rendered` 才能报告整期交付完成。不要依赖可能过期的 manifest 快照。更换图片和重新渲染不需要模型。完整恢复、图注、
大图、打印与本地配音视频的执行步骤见[新闻图文流参考](news-slides.md)。

并行研究与解释性故事属于实验流程，不是日报交付步骤。尤其研究组合页目前只支持 `preview`，
正式 `current` 准入保持阻断，细节见并行研究参考。

## 交互式验证

`run-edition` 默认只记录失败、待验证或限流页面，不启动 Edge，也不等待人工操作。用户准备好交互时运行 `verify-pending`；显式 `run-edition --open-verification` 复用同一实现，但会等待队列完成或超时。Windows 使用可见 Edge 和专用 profile；验证入口只打开队列页，不预先打开所有失败网站。由 CLI 启动时页面显示“采集器已连接”，并实时更新每条链接的等待、验证、采集和失败状态；直接双击静态 HTML 时显示“未连接”，不会假装正在采集。

- 用户点击链接且页面验证成功：立即从当前页面提取，并原子合并进新索引。
- 页面关闭、403、超时或提取失败：立即跳过，保留链接和失败状态。
- 页面显示 temporarily limited/restricted 或返回 429：标为 `rate_limited`，停止本轮自动重试，等待后续时段；不得反复刷新或尝试绕过。
- 部分成功：继续日报，不要求所有来源成功。
- 验证后无需 `resume`；若已有日报，当前 authoring coordinator 继续生成补充修订并发布。

host scheduler、Gateway 和其他无人值守会话不得传 `--open-verification`。`--unattended` 保留为默认非交互行为的兼容参数。

## 数据根与耗时诊断

若 Windows 检查点写入时报 `WinError 6`，但普通文件写入成功，先停止当前运行并保留运行清单与检查点。不要把 `replace`/重命名改成复制后删除，也不要把该检查点当作已提交。需要继续生成时，可显式用 `--data-dir` 指向已有的工作区数据副本，在该副本内保持唯一数据根；这不会回写原 canonical 数据根。要把副本正式迁回，必须另行执行有记录的显式迁移，不能悄悄混用两个数据根。

所有命令必须使用同一个 `DATA_DIR`。`data-root status` 显示当前绑定；只有确认迁移时才执行 `data-root adopt`。run 内的 `data_root` 与 artifact 路径必须一致，跨根引用在读取前失败。run 的 `artifacts.collection_metrics` 记录来源、候选、状态分布以及监控刷新/复用；`artifacts.enrichment.pipeline` 记录正文缓存、HTTP 提取、Edge 回退及各阶段耗时；报告保存结果的 `save_metrics` 区分编译校验、媒体、持久化、本地投影和状态更新。

`artifacts.authoring.metrics` 记录每个 brief 批次的 duration、API、输入/输出 token、模型、退出原因，以及 brief 合并、图片预取、紧凑研判与总写作时间；`artifacts.authoring.recovered_batches` 记录在分析准备时从合法 draft 恢复的批次，`missing_batches` 与 `coverage_targets` 记录恢复之后仍然缺失的批次及逐来源降级结果。选定宿主未提供的 queue/首 token/prefill/decode 字段保持空值，不能估算；当前 Hermes Hook 也不完整暴露这些字段。`milestones.local_html_ready_at`、`pdf_ready_at`、`notion_ready_at` 分开记录读者可见时间；`metrics.tail_seconds` 不混入 HTML 关键路径。`metrics.phase_durations_seconds` 汇总采集、context、正文、模型写作等待和验证/定稿，用这些机器计时定位慢点，不再用人工估算或一个总耗时混合后台工作。

所有任务命令在子命令前加全局 `--compact`，压缩标准输出并保留完整生产文件。图文流默认 50 条；模型复核初选新闻的新近性和重复覆盖，必要时排除过时或重复事件，由后续候选补位；单条补证后仍不足，定稿用 `--slides-exclude-event-id EVENT_ID`，独立准备用 `--exclude-event-id EVENT_ID`，按后续候选补位并复用已接受讲稿。

## 恢复

- 已有 run 先查 `edition-status --run RUN.json` 并按待办恢复；已有 session 时直接推进待处理草稿。报告已完成则继续 tail、图文或视频，不再推进 brief；`completed_partial` 本身不是重跑信号。视频需另查已有成品和诊断，`edition-status` 不检查视频；有效成品直接复用。
- `awaiting_selection`：选择 ID，运行 `enrich-edition`。
- `awaiting_authoring` 且没有 session：运行 `begin-authoring` 后，启动 `prefetch-media`；可在宿主支持并行进程时与作者同时运行，否则先完成预取。同时按顺序调度尚未复用的 packet，最多同时运行 3 个 author，一个 worker 完成后按序补入下一个。媒体预取只读固定 index/context、写入图片缓存和独立 receipt；等它退出并检查 receipt 后再运行 `prepare-analysis` 或定稿。每个 brief author 只读自己的 packet 及列出的证据，按 `output_schema` 写入指定 `draft_result_path`，再执行 `submission_command`。
- 已派发 packet 的输入缺陷修复后，运行 `begin-authoring --run RUN.json --refresh-context`，从冻结索引和采集窗口生成新版本情境及会话；旧 packet 和草稿保留，按新会话重新派发。
- authoring 批次已返回：把宿主提供的有界批次指标写入 session 指定路径并运行 `record-authoring-metrics`；`authoring-status` 全部完成后运行 `prepare-analysis`。即使宿主完成通知或不可变接收结果缺失，也不要先删 draft：`prepare-analysis` 会对每个缺 receipt 的授权 `draft_result_path` 执行原 packet 校验，合法草稿会被原子接收并列入 `recovered_batches`。检查恢复后的 `missing_batches`，只有输出 `deadline_exceeded: true` 时才能用 `prepare-analysis --allow-degraded`。
- brief 修复预算限制新一轮模型修复；预算耗尽后，已完成的合法草稿仍可通过校验并接收。
- authoring 降级：只降低缺失批次负责来源的覆盖目标，其他来源保持原计划。不得用本轮计划之外的旧缓存补位；已采集但缺少 brief 的来源要明确列出。
- `analysis_pending`：默认由一个新上下文作者完成原 analysis 包，再执行 `assemble-authoring`。需要缩短写作等待时显式选择 `prepare-analysis --parallel`：先返回 selection 包；完成其输出后运行 `analysis-stage --run RUN.json --stage domains`，并行完成三个领域包，再运行 `analysis-stage --run RUN.json --stage synthesis` 并完成综合包，最后运行 `analysis-stage --run RUN.json --stage assemble` 生成原 `analysis_result_path`。多阶段会重复输入共享内容，增加总输入 token；默认单包避免这部分开销。每任务使用仅含 packet 与绝对 CLI 的新上下文，遵循原 Schema；随后运行 `assemble-authoring`、`validate-report --run` 和 `finalize-edition --defer-tail`。观察信号写明对象、证据已有的复核时间和改变判断的方向；综合只解释具体跨域传导机制，无证据联系的领域保持独立。
- `finalizing` 在事实源持久化前失败：状态自动退回 `awaiting_authoring` 并记录错误；HTML/PDF 投影失败时 JSON/Markdown 仍有效，结果会记录 `local_output_error`，修复环境后重建投影即可，不要重新生成 revision。
- `tail.pending`：HTML 已有效；在后台执行 manifest 的精确 `tail.command`。
- `tail.partial`：读取 `tail.errors`，修复后重跑 `complete-edition-tail`；已存在 PDF/Notion 不会重复创建。
- 旧同步路径的 `publishing` 失败：重试 `finalize-edition --publish`。
- `failed`：阅读 manifest 的 `error`，先按失败阶段和已有产物恢复；确需重启采集时再用 `run-edition --restart`。
- `completed_partial`：本地报告有效；待验证链接可留到后续处理。
- `evaluation pending`：日报已经完成；先检查独立评估调度和不可变 evaluation。Hermes 集成只有在当前 report ID/content hash 尚无完成评估、且既有任务已明确 failed/expired 时，才创建一次新的有界评估尝试；其他 host scheduler 必须执行相同 preflight 和最多两次总尝试的边界。
- 评估失败：保留 pending/错误日志与失败 job 身份，按上述 preflight 显式重试；不得撤回日报、无限重调度或由 brief/analysis authors 自评。
- 监控部分失败：运行 `monitor-status` 查看来源状态；失败、限流和待验证不得改写为 `no_items`。旧快照仍可读取，下一次刷新会按 ETag/Last-Modified 和退避状态重试。

run manifest 固定在 `DATA_DIR/runs/YYYY-MM-DD/<edition>.json`。不要手改状态文件。删除过期锁前必须确认没有活动进程。

## 验收

报告保存检查：run/index/report 一致，普通 brief 按原发时间排序并保留原始排名，每源最多15条合格当日条目按计划覆盖，引用、正文访问等级、三个视角与综合符合证据；JSON、Markdown、HTML 与待验证链接可用。作者降级时检查 `recovered_batches`、`missing_batches` 和逐来源覆盖，不把写作缺失描述为未采集。

整期交付检查：运行 `edition-status --run RUN.json --require-complete` 并要求 `delivery_complete: true`、`pending_steps` 为空，图文流所有计划批次已接受且 HTML 已生成；如不满足，明确报告待办，不称整期完成。报告保存检查和整期交付检查是不同阶段。后台收尾检查：tail 为 `completed` 或有可操作的 `partial` 错误；PDF、`pdf_ready_at`、可选 Notion page ID/`notion_ready_at` 和独立评估调度彼此可重试，不影响前台 HTML 有效性。核对 `pdf_projection_seconds`、`pdf_bytes`、`pdf_size_budget_bytes` 和 `pdf_size_budget_status`；超预算是显式警告。PDF 必须在断开本地媒体目录与网络后仍能显示全部已物化图片；用页面栅格化抽查和 PDF image XObject 计数确认打印重采样后的图片已写入文件，且不含外链依赖。

已请求评分时检查：九维完整、总分正确、被评 report ID/hash 匹配、独立 artifact 存在、HTML 评估区已刷新、同 revision PDF 已复用且字节与修改时间未变（缺失时才生成）、可选 Notion 已附加更新版 HTML 或可重试、长期连续状态按建议更新。

运行复盘中的计数只能来自 manifest 和根级 `items[]`；不得把 `verification_required`、`failed` 或 `metadata_only` 说成 `no_items`。

监控检查：`snapshot.json` 的 `token_usage` 为 0、来源总数与配置一致、story ID 跨刷新稳定、缺失发布时间的条目明确回退到采集时间、`health.json` 保留每个失败原因。本地情报台默认只绑定 `127.0.0.1`。

## 长进程与作者分派

`begin-authoring` 前可用 `enrich-edition --run RUN.json --slides-candidates --max-items 100` 补充今日图文候选和候补的正文及原发日期；重复 `--item-id` 可优先指定条目。复用返回索引，用 `slides review --index INDEX.json --max-news 50` 提前审阅日期和证据质量。后续正式图文复核仍负责语义合并、影响排序及必要补位。

简报 session 和图文 plan 可用 `scripts/run_signaltrail.py --advance-dispatch INPUT.json --data-dir DATA_DIR [--run RUN.json]` 接收合法草稿并列出待写或修复任务；作者返回草稿路径，协调者在完成后再次推进。处理返回的 `issues`。分析包仍用 `--dispatch-plan`。

使用绝对解释器调用 `scripts/run_signaltrail.py`，并将共享 `author_instruction` 和票据交给作者。返回任务先排除已在执行的 batch ID 或 packet 路径；四槽位中一位协调者直接管理最多三名作者，有其他实际任务占槽时相应减少。作者使用新上下文，协调者批量提交。视频由当前协调者直接启动，按 `SKILL.md` 在工具内部等待，由进程输出进度，完成或失败后再进入模型。
