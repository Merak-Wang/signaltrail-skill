# 系统设计

**权威语言：** 中文（单语运行参考）
**负责人：** 仓库维护者
**状态：** 已验证详细设计
**最后对照代码：** 2026-09-11
**上级地图：** [`ARCHITECTURE.md`](../ARCHITECTURE.md)

## 边界

```text
RSS/Atom 条件请求 + 静态 HTML -> 零 token 监控快照 -> 事件聚类/来源健康
-> 核心来源适配器/必要时 Edge -> 不可变候选索引 -> 压缩上下文
-> 并行：受约束 brief 批次 | 图片预取
-> Python 合并 brief -> 紧凑事件 dossier -> analysis author 只写一次研判
-> Python schema 2.0 装配/校验 -> 不可变 JSON/Markdown -> 立即交付 HTML
-> 后台：PDF | 可重试 Notion（可选远程投影）
-> independent evaluator 只评分 -> 独立评估 artifact
-> 刷新 HTML 评估区、复用同修订 PDF -> 可选追加 Notion -> 受评估约束的长期连续状态
```

Python 拥有状态迁移、revision、访问等级映射、限额、验证和发布；brief authors 只产出 packet 约束的标题翻译与摘要，analysis author 只产出紧凑 analysis packet 约束的精选与研判；independent evaluator 只审查已经保存的不可变报告。事实身份校验在发布前完成，主报告不等待主观质量评分；后置评估只给修改和连续性建议，不修改报告。

## 内容模型

资讯固定为国际、国内新闻、军事、市场；技术固定为技术新闻、值得阅读的论文、今日值得关注的开源项目；研判单独渲染。七个内容 section 始终存在。

`briefs[]` 是显示和覆盖单位，负责标题、TL;DR、内部重要性、原始来源排名、链接和可选的确定性 `image` 记录；`items[]` 是精选事件与连续性单位，只承载需要完整证据链或支撑研判的少量事件。这样增加新闻数量不会按比例放大评分、全文读取和研判引用成本。所有正式来源的 `report_target` 与 `report_max` 都是 15；有至少 15 个真实候选时，普通 brief 使用当前索引顺序的前 15 条，不设重要性入选门槛。报告 JSON、Markdown、HTML、PDF 与 Notion 投影都保留这一 canonical 顺序，不再按 `importance` 重排；`source_rank` 只负责显示原始来源 TopN。数值评分和正文访问状态留在 JSON，不进入读者版。

研判固定分为“地缘政治专家视角”“AI 研究/开发工程师视角”“股票分析师视角”。schema 2.0 要求三个视角读取同一份 6—10 个精选事件 dossier，分别输出因果链、假设、时间跨度、证据缺口、相对上一版变化和失效条件；最后用跨视角综合显式记录共识、分歧来源、“地缘政治 → 技术 → 市场”传导链与共同观察信号。独立评估控制下一次连续性可接受、选择性排除或完全拒绝的范围。

## 来源发现与验证

来源分成两层：`configs/sources.yaml` 的 32 个正式来源统一使用 `report_target=15`、`report_max=15`；`configs/discovery-sources.yaml` 的扩展来源只进入监控、聚类和候选发现，`report_target=0`、`report_max=0`。来源声明 `tier`、`role`、`bundle`、可选 `feed_urls`、`item_order` 与刷新间隔。新增发现源不会按比例放大摘要、全文读取或研判 token。

全局 `collection.item_order` 默认为 `source`，并可由单个来源覆盖。`source` 依据原始 `source_rank` 保留页面、榜单或 Feed Top 顺序，历史快照保留项置后；`published_at` 按有效发布时间倒序，时间缺失和并列时保持输入稳定顺序。采集、Feed、监控与多页合并都调用同一排序函数，随后把最终顺序写入当前 index；原始 `source_rank` 不随排序模式改变。context、编译器和所有阅读投影只消费当前 index 顺序，不再自行推导另一套时间或重要性顺序。

监控先读取 RSS/Atom，使用 `ETag`、`Last-Modified`、304、本地解析结果缓存、失败退避与 `Retry-After`。响应必须通过 XML/HTML 嗅探；验证码或 HTML 中间页不得按 feed 解析。来源没有 feed 或 feed 失败时，可自动发现页面声明的 feed，再回退到无脚本 HTML。发布时间缺失的条目保留并标记，只能以采集时间显示，不能参与 NEW/新鲜度。标题词法特征哈希与余弦相似度完成零模型 token 的事件聚类；上一快照的 item 身份用于稳定 story ID。

来源 YAML 声明基础页和静态探索页。operator 或 authoring coordinator 可以通过 CLI 写入 `state/source-pages.json` 增加同域名、高价值的动态栏目页；每来源最多 5 个。动态页是可撤销配置，不改变适配器代码。

一次来源采集可以访问多个栏目页并去重。通用公开索引先用 httpx/Beautiful Soup 做无脚本预取，受全局与同域 semaphore 约束；无条目、登录/挑战、401/403、JavaScript 页面和专用 adapter 才进入顺序 Edge 回退，避免并发操作同一个持久化 profile。正文读取同样使用共享 `httpx.AsyncClient` 并发提取静态正文和元数据，将仍可能补足的壳页或部分正文交给一次 Edge 尝试；明确拒绝、限流、不支持类型、已知截断或带不完整提示的部分正文停止升级。完整且通过本地路径/可用哈希复核的正文才直接复用。正文没有独立的 rate_limited 枚举，沿用 verification_required 并在 challenge 与 completion 中标明限流；来源层仍保留 rate_limited。多页结果按轮询合并，避免 BBC/Guardian 的第一个栏目占满上限而饿死后续栏目。部分栏目成功、部分失败时，来源状态是 partial，且 page_results 保存每页状态和链接。访问失败永远不能静默变成 no_items。

`run-edition` 默认不调用手工验证，避免 GUI 等待阻塞生成流程。用户显式运行 `verify-pending` 或传 `--open-verification` 时才启动本地 Edge 队列。队列汇总失败和待验证页面，用户点击链接后，采集器监听新标签并复用当前已登录页面立即提取；只有成功提取到条目才算完成。结果被原子合并到新索引；失败页面继续保留。已发布 run 会进入待修订状态，原报告保持不变，补充内容进入新 revision。同一日期与 edition 的后续 revision 可以复用自身上一 revision 的事件 ID 和来源条目；跨 edition、跨日期或换用另一事件 ID 时仍执行 `NEW` 重复拦截。`--unattended` 保留为默认非交互行为的兼容参数。

## 状态机与文件

正文抽取在 HTTP 与浏览器路径共享 `content_extraction` 规则。具体正文区域优先于宽泛
`main/body`，候选同时检查正文块、链接密度和不完整提示；达到字符数不再自动证明完整。
短公告可标为 `full_text`，并在 `metadata.content_quality.extraction_status` 记录
`short_complete`；宽泛区域、截断响应或可见的不完整提示最多为 `partial`。这些结果是
`structural_heuristic`，不是事实核验。只有标题、加载提示或链接列表时仍为 `metadata_only`。
HTTP 非 HTML 错误响应也保留失败或待验证状态。

每次有效抽取写入唯一名称的结构 JSON 与派生 Markdown；`content_path` 继续指向 Markdown，
`metadata.content_blocks_path` 指向 JSON。JSON 保留 `item_id`、原 URL、采集路径、选择器、
质量记录，以及带 `block_id` 的标题、段落、列表和表格块；表格保存单元格文字、表头标记及
跨行跨列声明。旧正文继续可读和复用，不把历史压平文本伪装成已恢复结构的新证据。

正文 JSON schema 1.1 增加输入指纹与页面自述元信息；索引中的 `content_input` 记录 SHA-256、
字节数、输入类型及截断，`content_artifacts` 记录 Markdown/结构 JSON 哈希。
HTTP 指纹覆盖有界响应字节；浏览器指纹覆盖去除隐藏元素后的可见 DOM UTF-8，不是原响应。
`content_source` 仅记录 page_declared 的作者、发布者、语言，`independent_origin` 保持 null。
`collection.retain_public_html` 默认 false，开启后只对可用的无登录 HTTP 正文在运行目录写入
`.response.bin`；不保存浏览器会话 HTML、响应头或挑战页。旧版无哈希文件继续可读。

`collection.fallback_extractor` 允许 none（默认）和 trafilatura（可选 extraction 依赖）。
备用库只读取已清理 HTML，失败与缺依赖保留基线；选用候选始终至多 partial。
浏览器在来源等待时限内轮询可见文字，空容器挂载不等于正文就绪；超时仍保留实际不足状态。
质量补充 title_overlap、numeric_tables_without_headers，关键字段和媒体核验未知时为 null。
逐次 content_attempts 与最终 content_completion 分开；后一次失败不撤销前一次可用正文。
complete 只表示未观测到正文结构缺口，with_gaps 保留 unresolved 与 stop_reason，主张充分性
始终 not_assessed。新的 content_metrics 同时给出 successful、complete 和 with_gaps 计数。

上下文增加 collection_coverage（已配置地区/主题/来源角色）及 enrichment_plan（有界正文建议）。
覆盖从规范根级条目计算，排除历史保留项，失败与未采集分开；来源数量不代表独立核验。
监控快照同样提供 collection_coverage，但 scope 为 current_monitor_refresh，只计本次选中来源
及其刷新候选；包含选中的发现来源，不使用旧轮次记录扩张本次覆盖。
失败 Feed 保留的缓存条目带 metadata.feed_stale，覆盖诊断排除它们，阅读缓存仍继续保留。
计划不会执行搜索或改变来源排序，最终选中 ID 仍由协调器传入，run 的累计 12 篇限制不变。
content_observations 将紧凑质量及停止原因传入 brief/analysis 数据包，原始响应不进入写作输入。

连续性状态中的 `analysis_id` 仅表示三个固定栏目；具体论点使用 Python 根据领域、规范化
判断和已编译事件集合派生的 `thesis_id`。`theses.json` 与 `watchlist.json` 使用状态 schema
1.2，保留 `analysis_id` 兼容字段；`analysis-domains.json` 提供每栏目最新状态的兼容投影。
旧论点没有具体身份时保留历史并标记 `identity_scope=legacy_unresolved`，不按同领域关系
自动取代。共享连续性锁避免并发丢失状态；迟到报告不倒退同一论点或栏目。

观察项绑定具体 `thesis_id` 与规范化信号文字。仅排版差异复用 ID；不同措辞不会被猜测为
同一触发条件。未在新报告出现的观察项保持原状态，只有对应具体论点明确 `closed` 或
`invalidated` 才关闭其观察项。跨措辞、跨证据版本的受验证延续尚未实现，见 TD-039。

```text
created -> collecting -> building_context -> awaiting_selection
-> extracting_content -> awaiting_authoring -> finalizing
-> completed | completed_partial + tail.pending

tail.pending -> tail.running -> tail.completed | tail.partial
tail.partial -> tail.running（只续跑未完成投影）

completed[_partial] -> evaluation pending
-> 独立评估 artifact -> HTML/PDF refresh / [Notion append] / 长期连续状态

机械异常 -> failed；本地 finalization 失败 -> awaiting_authoring
```

```text
data/
  monitor/{snapshot,health,feed-registry}.json
  monitor/feed-cache/<sha256>.json
  indexes/YYYY-MM-DD/<edition>-rN.json
  content/<source>/<item>/<retrieval>.md
  media/image-cache.json
  media/images/<sha-prefix>/<sha256>.<ext>
  context/YYYY-MM-DD/<edition>-rN.json
  context/YYYY-MM-DD/<edition>-rN-authoring/{session,brief-skeleton,analysis-packet,...}.json
  reports/index.html
  reports/YYYY-MM-DD/<edition>-rN.{json,md,html,pdf}
  evaluations/YYYY-MM-DD/<edition>-rN.json
  runs/YYYY-MM-DD/<edition>.json
  state/{events,theses,watchlist,predictions,source-pages,user-feedback}.json
  state/semantic-cache.json
  state/history/<kind>/YYYY-MM-DD-rN.json
  publishing/notion-registry.json
  locks/YYYY-MM-DD-<edition>.lock
```

report JSON/Markdown revision 与内容寻址图片不可覆盖；它们是事实源。报告先完成编译和语义校验，再进入媒体物化；图片 URL 缓存记录内容摘要、验证元数据和失败重试时间，使用共享连接池、全局并发及同域并发限制。默认在 brief authoring 运行时预热图片，因此定稿只读取暖缓存。HTML 是前台交付门槛；PDF、Notion 与独立评估属于可重试 tail，不进入用户等待关键路径。版本化 HTML 使用指向内容寻址媒体的相对路径，桌面 HTML 将已校验图片内嵌为可单独移动的单文件；标题与图片的 DOM 顺序在两种投影中保持一致。PDF 的 Edge 自包含输入把已校验图片按 1600×1000 打印边界转为质量 82 的 JPEG 数据 URI，ReportLab 降级路径对同一受控文件执行相同重采样；两条路径最终都把位图对象写入 PDF。投影回执记录渲染秒数、字节数和默认 50 MiB 软预算，超出时告警但不撤回 JSON/Markdown/HTML。评估只改变同一 revision 的评估区，因此原子刷新 HTML、桌面副本和归档索引时复用已存在的 PDF；只有 PDF 缺失或 report 内容 revision 改变时才重新渲染。Notion 页面只保存元数据并附加便携 HTML；HTML upload ID、内容 hash 和失败信息只写入可重试的发布登记，Notion 仍只是可选远端副本。

## 上下文预算

上下文不嵌入全文，也不重复整个 candidate index。默认每来源最多 25 个紧凑候选，并原样保留采集层已经写入的当前 index 顺序；正文状态不能把 enriched 候选提到前面，context 也不能再次按发布时间排序，否则会改变本轮 Top1–15。所有正式来源的 `report_target` 与 `report_max` 都是 15。上下文先读取 `state/semantic-cache.json`：只有内容指纹一致、独立评估通过门槛、输出语言一致且 item ID 位于本轮对应 `brief_plan.default_item_ids` 的 brief 才能进入 `reusable_briefs`；其余计划内 ID 进入 `author_item_ids`。编译器同样使用 `brief_plan.default_item_ids` 作为缓存补齐、草稿保留和普通 brief 排序的边界，不能用 Top15 之外的历史缓存补位。

context 先剔除 Top15 之外的备用候选和可复用语义，只把真实写作缺口按完整来源均衡拆成最多 12 个 `brief_authoring_batches`，目标约 45 条/包。authoring coordinator 按有序波次每次最多并发 3 包，一波完成后再分发下一波；不支持隔离并发的宿主可以顺序处理。这个上限避免把满载约 480 条内容压进少数超大输出，也不规定宿主必须提供哪一种 delegation API。每个 brief author 的输入只有独立 packet 和其中列出的正文路径；其唯一写入输出是 packet 指定的 draft path，随后执行 packet 的提交命令。该角色不能浏览、搜索、运行其他脚本、生成全篇报告或处理其他批次。Brief 与 analysis packet 都携带接收器执行的 `output_schema`，完整约束嵌套类型、枚举、长度、额外字段和 Python-owned 身份；接收器先报告不复制草稿正文的路径/规则错误，再执行语言、摘要、证据与完整报告校验。若命令报告校验错误，最多修复并再次提交一次。Python 校验并原子接收各批，原样合并缓存与已接收 brief，再将最多 18 个高价值候选压缩为 analysis packet。analysis author 不再重读数百条 brief，只选择 packet 声明数量的精选事件并完成一次三视角研判。Python 最后装配完整 schema 2.0 草稿。Hermes 集成当前用 `delegate_task` 映射这些工作单元，其默认 `max_concurrent_children=3` 与上述波次上限一致；其他 harness 可以使用等价 worker 或顺序执行。

authoring session 绑定 run attempt、context 绝对路径与 SHA-256，分发后 context 改变会硬失败，不能混合新旧批次。session 记录 run deadline 减去 120 秒的 `analysis_deadline_at`。`prepare-analysis` 在计算缺失批次前，会读取尚无不可变 receipt 的授权 draft，按原 packet 再次完整校验；合法草稿被原子接收并记录到 `recovered_batches`，非法或不完整草稿仍保持 missing。截止前缺批次必须等待或修复；截止后才允许确定性降级，coverage override 只能降低对应 missing batch 所负责来源的目标，其他完成批次来源仍保持原计划目标（候选不少于 15 时为 15），报告草稿不能自行降低目标。每批记录耗时、API、输入/输出 token、模型和退出原因；宿主若提供 queue、首 token、prefill、decode 和缓存 token，也以可选字段保留。宿主的自由文本完成通知和工具轨迹不进入运行指标。索引存在 section 候选但最终没有已校验 brief 时，投影列出每个缺失来源及“已验证摘要/计划”计数，即使同 section 的其他来源已成功；只有索引确实没有候选时才显示“未采集到可展示内容”。保存报告先写 pending cache，独立评估对事实可靠性、摘要准确性、合规边界和连续性给出合格结果后才提升为 approved；标题、URL、摘要、发布时间、正文状态或正文路径改变都会使指纹失效。每次累计最多读取 12 篇正文；历史报告只转换为稳定 ID、结构化判断和评估诊断。

每个 run 记录自己的绝对 `data_root`。任意 harness 都可显式传入 `--data-dir`；当前兼容层仍在 Hermes Home 保存唯一根绑定，以延续既有安装和数据根。所有直接 artifact 命令和状态迁移都先校验路径与 manifest，防止从一套目录读取 enrich 结果、向另一套目录发布日报。`artifacts.enrichment.successful_item_ids` 是正文证据 lineage；finalize 发现这些 ID 在最终 index 中退化或消失会硬失败。

## 宿主集成边界

核心流水线只要求宿主能够执行本地命令、读取自包含 packet、把一个结构化 JSON 写到指定路径，并把确定性提交命令的结果交回 authoring coordinator；它不依赖 Hermes 的会话或任务对象。`daily-intel` 的显式 `--config`、`--data-dir` 与 `--profile-dir` 可由任意 harness 使用。缺少并发 worker 时可以顺序执行 packet，安全、覆盖和最多一次修复不变量保持不变。

用量 sidecar 当前只内置 `hermes`、`codex`、`openclaw` 三个 adapter。其他 harness 可以不绑定 usage task，使预算回执明确保持 `coverage=unmetered` 且 token 为 `null`，也可以通过 Python `UsageAdapter` 协议实现并注册白名单解析器；不得把未知宿主回执交给近似 adapter 或保存 raw receipt。自动 independent evaluator 调度和任务对账支持 `signaltrail-hermes` 的本地计量进程，以及保留兼容的 Hermes Cron 路径；覆盖区别见 [用量说明](llm-usage.md)。其他宿主仍可只读同一 hash-bound dossier、在外部调度 independent evaluator 并调用 `finalize-evaluation`，但不能把手工或外部调度声称为内置自动调度。

## 兼容性

根级 `items[]` 是规范索引模型。采集与 enrich 同步维护旧 `sources[].items[]`，以兼容既有 Hermes 数据根和旧工具。schema 1.1—1.5 仍可读取；新报告使用 2.0。新 context 标记为 2.0 时，发布门禁拒绝 1.5 草稿，避免回退路径绕过跨视角综合。监控快照是新增的独立读取模型，不改变旧索引 JSON 的根级形状。
