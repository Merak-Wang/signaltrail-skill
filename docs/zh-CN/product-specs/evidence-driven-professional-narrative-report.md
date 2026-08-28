# 证据驱动的专业叙事日报产品规格

**目的：** 定义日报、图文流和视频输出面向用户的叙事结构、证据与辩证要求、
时效规则、专业质量预期和分阶段验收标准。
**状态：** 草案
**负责人：** 仓库维护者
**最后验证：** 2026-08-28

本规格定义一项拟议能力。它不声称当前运行时已经能够生成或验证专业叙事、图文流、
TTS 音轨或视频。跨模块设计见[架构记录](../design-docs/evidence-driven-professional-narrative-report.md)；
交付顺序见[活动执行计划](../exec-plans/active-evidence-driven-professional-narrative.md)。

## 产品结果

对于一个已经通过验证的不可变日报 revision，SignalTrail 生成一份不可变的专业叙事，它：

- 把新闻讲解与报告的三个分析视角融合成一篇连贯的说书式口播文本；
- 保留证据、背景、归因性声称、推断、反方立场、情景、不确定性和观察信号之间的结构化边界；
- 解释行为体、激励、约束、因果机制、假设和失效条件，而不把分析方法变成口播字段清单；
- 能够完整追溯到当前报告和索引；
- 接受独立、逐 beat 的 LLM 验证；
- 只有通过确定性验证和独立验证后，才发布到读者投影；以及
- 暴露一个明确的经验证门禁回执，作为未来图文流和视频工作的唯一可接受输入。

本产品是专业说书，不是虚构戏剧化。叙事手法用于提升理解力；它不授权虚构事实、对话、
动机、时间顺序、引语、内幕或确定性。

## 对受众的承诺

听完或读完一章后，读者应能回答：

1. 发生了什么？
2. 哪些部分是已确认、经归因、历史背景、推断、存在争议或未知？
3. 为什么发生，又通过什么中间机制发生？
4. 哪些行为体获益、付出代价、施加约束或能够改变结果？
5. 最有力的实质性替代解释或反证是什么？
6. 哪些假设支撑当前判断？
7. 什么会削弱或推翻该判断？
8. 后续报告应检查哪些可观察信号？

主要阅读体验是一篇融合叙事，而不是先重复一遍“新闻讲解”，再复述三篇分析文章。
证据和论证细节可以折叠展开，但来源名称、发布时间、认知状态、`as_of` 和验证状态始终可见。

## 范围

### 叙事 MVP

MVP 包括：

- 基于精选事件和授权分析构建有界 packet；
- 结构化章节和句子大小的 beat；
- 确定性的 schema、证据、访问、时效和跨字段验证；
- 独立逐 beat 验证，以及全稿最多一次定向修复；
- 不可变脚本、验证和经验证门禁工件；
- 基于同一语义 payload 的 HTML 和 Markdown 读者投影；
- 幂等、并发、中断、陈旧 revision 和投影失败恢复；
- 在运行时保存每个模型阶段的精确或显式不完整 Token 用量，但正式通过 G4 必须具有精确、
  完整的阶段覆盖；以及
- 经测试的硬阻断，禁止未经验证的内容进入媒体阶段。

MVP 不要求 TTS 或 MP4 输出，但必须实现媒体门禁合同，确保后续阶段不能绕过验证。

### 后续媒体阶段

图文流阶段增加确定性、权利感知的 scene manifest 和联系表预览。视频阶段增加获得许可的
TTS、实际时间信息、字幕、可复现渲染和媒体 QA。来源视频摄取、声音克隆、背景音乐和权利
未知的素材不在首个视频 MVP 范围内。

## 面向读者的结构

每一章只服务于一个中心问题。自然顺序可以变化，但完整脚本必须能够识别以下功能：

~~~text
hook
-> 已确认或经归因的事件
-> 必要背景
-> 行为体、利益与约束
-> 中间因果机制
-> 当前判断
-> 最有力的反方立场或证据缺口
-> 条件情景
-> 失效条件
-> 可观察的观察信号
-> 收尾
~~~

UI 不必打印这些方法名称。不过，口播中的认知转场必须使用目标语言中等价于“已确认”、
“根据”、“一种有依据的解释”、“这假设”、“如果”和“尚未验证”的措辞，使事实与判断
能够被区分。

Hook 可以制造好奇，但若无证据，不得引入新的人物、组织、行动、数字、引语、动机、日期
或因果声称。结尾“扣子”必须是可观察的观察信号，不能是没有支持的悬念。

## 验收模型

八个硬门彼此独立。任何汇总分数都不能弥补某个门禁失败。

| 门禁 | 判定问题 | 必须达到的阈值 |
| --- | --- | --- |
| G0 — 上游绑定 | 脚本是否绑定到一个有效、当前且已完成的报告/索引/合同？ | Run 为 `completed`；报告 `0 errors / 0 warnings`；每个声明的 Hash 均匹配 |
| G1 — 证据和时效 | 每个关键声称是否在其声明角色下得到支持并具备时效？ | 关键声称证据闭合率 `100%`；当前声称时间合规率 `100%`；关键错误 `0` |
| G2 — 辩证专业叙事 | 每个论点是否在连贯故事中解释机制、反方立场、条件和可观察项？ | 每条结构硬规则通过；每个人工/verifier 评分维度 `>= 4/5` |
| G3 — 独立 verifier | 隔离的 verifier 是否覆盖每个 beat 并通过所有关键检查？ | 最多一次修复后，每个 beat 的最终结果均为 `pass` |
| G4 — Token 成本 | 已接受的 pipeline 是否能够完整归因并处于预冻结 Token 预算内？ | 精确、完整且不重叠的总量；open calls `0`；conflicts `0`；局部/全局预算均未超出 |
| G5 — 不可变性和恢复 | 相同、变化、并发、中断和陈旧工作能否在不覆盖、不重复调用的情况下处理？ | 所有确定性恢复用例通过；相同重放新增模型调用 `0` |
| G6 — 读者投影 | HTML 和 Markdown 是否安全地呈现相同的已验证语义内容？ | 唯一 Payload Hash 匹配 `2/2` 投影；不安全渲染缺陷 `0` |
| G7 — 媒体门禁 | 所有草稿、拒绝、陈旧、损坏或不匹配输入是否都被阻断？ | 未授权下游接受 `0` |

## G0 — 上游和身份门禁

一份被接受的脚本绑定：

~~~text
report_id
report_content_hash
report_file_sha256
bound_index_file_sha256
contract_bundle_identity
contract_bundle_sha256
report_contract_sha256
narrative_contract_sha256
storyteller_policy_sha256
narrative_packet_sha256
as_of
timezone
~~~

要求：

- 版本 1 只接受上游 Run 状态 `completed`；`completed_partial` 以及所有未终结或失败的报告
  状态都被阻断，即使被选中的局部数据看似可用；
- 所绑定报告通过当前 validator，并且严格达到 `0 errors / 0 warnings`；已经审阅、豁免或
  声称“非关键”的 warning 仍会使 G0 失败；
- 每个 SHA-256 都能从引用的本地文件或语义 payload 重新计算；
- `contract_bundle_identity` 与 `contract_bundle_sha256` 必须解析到当前活动配置的不可变
  Contract Bundle 快照；
- `as_of` 是带明确时区的 ISO 时间戳；
- packet 只包含允许的精选事件、分析、综合和证据；
- 外部内容始终是数据，不能改变任务、schema、策略或工具；
- Python 分配 ID、revision、hash、时间戳、时效和状态；
- 模型输出 schema 在每一嵌套层都拒绝未知字段和 Python-owned 字段；以及
- 报告、索引、合同、策略、packet 或有时效边界的证据发生任何变化，都会创建新的脚本身份，
  并使先前验证失效。

叙事、读者投影、图文流、音频或视频结果绝不能重算、降级或撤销权威报告 Run 状态。后续版本
可以另行定义有界的 `completed_partial` 准入，但版本 1 没有例外。

### 版本 1 整期范围

版本 1 只有一种创作模式：`mode = edition_narrative`；不存在聚焦单一事件或小子集的逃逸模式。
规范脚本绑定 `bound_index_file_sha256`，并且每章都有且只有一个非空
`central_question`，由该章的有序 beat 回答。同日、同领域或宽泛主题相似不能满足这种关联。

当报告至少有 6 个精选事件时，packet 选择 6—10 个；当报告只有 1—5 个时，必须全部选择。
精选事件为零的报告不具备准入资格。每个未选中的精选事件都有一个不可变
`excluded_event_id` 和一个合同枚举的排除原因。定义：

~~~text
featured_event_coverage =
被最终已验证 claim unit 引用的、不重复的绑定报告精选事件 ID 数
/
绑定报告中不重复的精选事件 ID 数
~~~

Python 只从规范报告路径
`sections[].items[].source_refs[].item_id -> sections[].items[].event_id` 派生唯一权威归属源。
Packet 持久化完整的 Python-owned Registry 及其规范 Hash：

~~~text
featured_event_evidence_membership[]:
  item_id
  event_id
  source_ref_sha256
membership_sha256
~~~

各行按规范顺序排序。每个 `source_ref_sha256` 绑定精确的规范 Source Ref Row，
`membership_sha256` 绑定完整有序 Registry。一个 Source Item 必须且只能映射一个精选事件
ID；重复 Row、一个 Item 映射多个事件、归属缺失或 Hash 不匹配都会使 Packet 校验失败，不能
猜测。不可变 Scope Receipt 通过 typed Packet Parent 绑定 `membership_sha256`，但不复制
Registry。Claim 校验、当前新闻配额和 60% 覆盖指标只能消费该 Registry；章级字段或其他事件
推断规则都不能创造归属。Claim 为某事件引用至少一个唯一归属的 Evidence Item 时才映射该
事件；多事件 Claim 只有为各事件分别携带唯一映射证据时才能计入多个事件。章级
`event_ids[]` 只授权范围，绝不创造覆盖；Claim/Evidence/章级事件不匹配会直接失败。

分母必须非零，并且 `featured_event_coverage >= 0.60`。最终 claim 级 Registry 引用必须
恰好覆盖 `geopolitics`、`ai_technology` 和 `markets` 三个分析域，达到 `3/3`，且每个
分析域至少有一个引用。仅在章级列出分析域不计入覆盖。

最终已验证 Claim 集还必须至少包含一个精确的
`source_kind = cross_perspective_synthesis` Registry 引用。唯一替代方案是由 Python 签发
不可变的不适用回执，证明绑定报告中经过验证的综合字段在一个版本化确定性规则下缺失或为空。
回执绑定报告和 Index Hash、已检查的 JSON Pointer、规则 ID、`decision = not_applicable`
以及合同枚举的原因。已有但较弱、简短、不方便或低置信度的综合内容不能被主观判定为“不具
实质性”；只要规范字段存在且非空，就必须使用精确 Registry 引用。Storyteller 声称综合
“不相关”不构成回执。

每一章必须至少包含一个最终已验证 Claim，其证据访问状态为 `partial` 或 `full_text`。
metadata-only 或 `verification_required` 证据可以在声明边界内补充该 Claim，但不能满足
章级证据深度门禁。

## G1 — 证据门禁

### 关键声称证据闭合率

定义：

~~~text
关键声称证据闭合率 =
拥有充分授权证据的关键声称
/
全部关键声称
~~~

候选 Claim Registry 是规范讲解稿中经过 Python 校验的 `claim_units[]` 集合；证据闭合率
分母在关键性分类和 Verifier 升级后最终确定。每个携带事实、归因、争议或推断的 Beat，都要
把每项可独立证伪的断言拆成 Claim Unit，包含：

~~~text
claim_id
text_span.start
text_span.end
normalized_claim_sha256
epistemic_status
claim_type
criticality
criticality_reason
evidence_item_ids[]
analysis_ref_ids[]
freshness_class
freshness_evidence_item_ids[]
~~~

`claim_id` 和 `normalized_claim_sha256` 由 Python 拥有。`text_span.start` 是包含端，
`text_span.end` 是不包含端；二者使用指向已保存 Beat 原文的 Unicode Code Point 偏移。
每个非空 Span 都必须在范围内，并准确定位 Claim 原文。`normalized_claim_sha256` 根据该
Slice 和版本化归一化算法派生；归一化文本或其 Checksum 绝不能替代精确 Start/End Locator。
携带 Claim 的文字不能游离在 Claim Unit 之外，也不能让一个复合句把多个关键声称藏在同一组
引文后面。

`claim_type` 只能是 `entity`、`action`、`time`、`sequence`、`number`、
`quotation`、`attribution`、`factual_premise`、`inference` 或 `other`。
`criticality` 是 `critical` 或 `noncritical`；`criticality_reason` 必须非空，并引用
适用的版本化分类规则。Python 先应用确定性类型规则。Verifier 可以把 Python 判定为
`noncritical` 的 unit 升级为 `critical`，但必须给出 Claim ID、原因和失败检查映射；
Verifier 不能降级 Python-critical unit。每次升级都持久化到
`verification.claim_criticality_escalations[]`，字段为 `claim_id`、
`from = noncritical`、`to = critical`、`reason` 和 `failed_checks[]`；未登记的升级或
任何降级都会使接收器失败。

Python 从该 Claim 的直接 `evidence_item_ids[]` 派生 `freshness_class` 和排序、去重的
`freshness_evidence_item_ids[]`；这两个字段都不能授权新证据。证明 ID 始终是同一 Claim
直接证据的子集，也是唯一可以确定其发布时间分类或当前事件归属的 ID。

关键声称包括：

- 人物、组织、产品、文档或地点的身份；
- 已经发生或没有发生的行动；
- 时间、顺序、数字、百分比、价格、金额或范围；
- 直接或间接引语；
- 对政策、申报文件、公告、研究结果或报道声称的归因；
- 会实质改变中心判断的事实前提。

要求的闭合率是 `100%`。其分母是 Python-critical 与 verifier-escalated unit 的非空并集。
证据 ID 必须存在于绑定索引中，并且是当前报告授权精选事件证据的子集。本地存在的普通
brief、旧报告或模型创建的 ID 均不构成授权。

按认知状态划分的规则：

- `confirmed_fact` 有支持证据，且不能只依赖 `verification_required`；
- `reported_claim` 保留明确归因，不能提升为独立事实；
- `background` 有证据，并使用毫无歧义的历史措辞；
- `supported_inference` 有 analysis reference，且有证据支持其前提；
- `contested` 表示有界证据中实际存在的实质冲突；
- `scenario` 是条件性的，而不是事实；
- `unknown` 保持未解决；
- `watch_signal` 能在未来被客观观察；
- `transition` 不包含事实声称。

Packet 携带由 Python 构建的 `analysis_reference_registry[]`。每个条目都有白名单
`ref_id`、`source_kind`、指向绑定报告的精确 RFC 6901 `json_pointer`，以及强制
`value_sha256`；适用时还带 `analysis_id`。该形式能统一定位标量、数组、嵌套 stakeholder
以及跨视角综合中的值。Storyteller 只能输出 Registry 中的 `analysis_ref_ids[]`，不能创建
Pointer 或 Hash。

章级分析引用只定义授权范围。`supported_inference` 只有通过 claim-unit 级或 beat 级的
精确引用才能闭合分析前提；这些引用绝不能替代事实前提所需的证据 ID。

metadata-only 证据只能支持已经观察到的标题或公开描述。脚本不能把它扩写为未见详情。
重要实体、数字、日期、引语和归因必须在语义上与证据匹配；一个关键不匹配就会使 G1 失败。

`claim_unit_completeness` 是 verifier 的布尔关键检查。只有当每个 beat 中所有可独立证伪的
事实、归因、争议或推断跨度都被一个或多个互不重叠的有效 claim unit 覆盖，每个 claim unit
都指向其已保存的精确文本跨度，并且无 Claim 的 transition 没有隐藏 Claim 时，检查才通过。
缺失或藏在复合句中的 Claim 必须返回精确未覆盖跨度和 `repair` 或 `reject`；绝不能把它
平均进风格评分。

## 时效门禁

每个 Claim Unit 都必须且只能具有以下一个经过 Python 校验的 `freshness_class`：

| Class | 可接受含义 |
| --- | --- |
| `current` | 非空直接证明集中的 Item 都有有效 `published_at`；本地日期均为 `as_of` 当日或前一日，且时间不晚于 `as_of` |
| `background` | 非空直接证明集具有有效但更早的发布时间，并以毫无歧义的历史背景措辞表达 |
| `undated` | 非空直接证明集的发布时间缺失或无效；绝不表达为当前消息，也不能闭合当前 Claim |
| `not_applicable` | 发布时间时效不适用的条件情景或观察信号；证明集为空 |

`pending` 和 `excluded` 是工作流处置，不是被接受的 Claim 时效分类；`unknown` 是认知状态。
无 Claim 的 Transition 没有 Claim Unit，因此也没有时效分类。未来时间必须被拒绝，不能
静默重新分类。`collected_at` 永远不能授予当前状态；历史或无日期材料不能使用“刚刚”、
“最新”或“今天发生”等语言；`verification_required` 保持为经归因、尚未解决的声称。同一
Beat 可以包含不同 Class 的 Claim Unit；任何 Beat 级标签都不能提升某一 Claim，也不能替
另一 Claim 提供发布时间证明。

把 `available_current_featured_event_count` 定义为绑定报告中至少拥有一个有效今日/昨日
`published_at` 的不重复精选事件数；今日/昨日必须以配置的 `timezone` 对 `as_of` 进行换算。
`current_claim_candidate_count` 是通过时间证明门禁前被标记为 `current` 的最终 Claim Unit
数量；`current_claim_count` 是其中非空 `freshness_evidence_item_ids[]` 通过上述规则的数量。
Current Claim 只能
通过这些精确证明 ID 和绑定的 `featured_event_evidence_membership[]` Registry 映射到精选事件；
被引用 Item 自身必须带有效的今日/昨日 `published_at`。旧、无日期、Beat 级、Chapter 级或仅仅
属于同一事件的其他证据都不能进入该映射。独立 Verifier 必须确认当前措辞由当前证明 Item
支撑，而不是只由另一条历史 Item 支撑。版本 1 要求：

~~~text
available_current_featured_event_count > 0
最终已验证 claim unit 引用的不重复当前精选事件数
    >= min(2, available_current_featured_event_count)
current_claim_count > 0
当前 Claim 时间合规率 =
    current_claim_count / current_claim_candidate_count = 100%
~~~

因此，当前新闻配额及其合规率分母都绝不为零。

规范讲解稿保存冻结的证据闭包：

~~~text
script_revision = sN
script_evidence_closure_item_ids[]
script_evidence_closure_sha256
~~~

`script_evidence_closure_item_ids[]` 按顺序排序且无重复。它是所有 Beat、Claim 和反证 Evidence
Item ID，加上通过活动 Contract Bundle 下的 `analysis_ref_ids[]` Registry Entry 传递到达的
全部 Evidence Item 的精确并集。Python 派生该集合及其规范
`script_evidence_closure_sha256`；Storyteller 和 Verifier 都不能增删或计算它的 Hash。
传递证据缺失、越界、重复或有歧义都会使确定性脚本校验失败。

版本 1 使用：

~~~text
freshness_recheck_ttl_minutes = 120
script_hard_expiry_at = 下一个已配置日报窗口边界
freshness_anchor_at = 初始闸门使用 verified_at；续期闸门使用 rechecked_at
freshness_deadline_at =
    min(freshness_anchor_at + 120 minutes, script_hard_expiry_at)
~~~

TTL 衡量的是自最近一次脚本时效验证以来的时间；它不会重新定义来源发布时间的时效。讲解稿
永久保留原始 `bound_index_file_sha256` 事实血缘。软 TTL 到期后启动延迟读者投影、图文流
或视频，必须针对一个单独标识的当前复查 Index 和来源状态执行确定性检查。
`script_hard_expiry_at` 由 Python 拥有，Storyteller 或 Verifier 都不能延长它。闸门有效期为
半开区间：必须同时满足 `clock < freshness_deadline_at` 和
`clock < script_hard_expiry_at`；等于任一边界即为过期，不是当前。

若选中证据发生变化，工作流绑定刷新后的报告/Index，创建新的规范讲解稿 revision，并重新
执行完整验证。若证据没有变化，Python 先写不可变时效复查回执，再写新的不可变闸门 revision。
复查回执绑定：

~~~text
parents[] = exactly one each of prior_gate, bound_index, recheck_index, script
script_evidence_closure_item_ids[]
script_evidence_closure_sha256
item_fingerprint_policy_id
item_fingerprint_algorithm_version
checked_item_ids[]
checked_item_old_new_fingerprints[]:
  item_id
  old_fingerprint
  new_fingerprint
required_source_ids[]
source_statuses[]:
  source_id
  acquisition_status
decision = unchanged
rechecked_at
freshness_anchor_at = rechecked_at
freshness_deadline_at
script_hard_expiry_at
~~~

Fingerprint Policy 和算法版本由活动 Contract Bundle 固定。只有
`checked_item_ids[]` 已排序、无重复，并且与 `script_evidence_closure_item_ids[]` 完全相等；
`checked_item_old_new_fingerprints[]` 对每个 Checked ID 恰好有一个 Row 且没有外来 Row；每个
必需 Item 在两个 Index 中都唯一存在；每个 Old Fingerprint 等于对应 New Fingerprint；
`required_source_ids[]` 恰好等于该闭包的来源集合；`source_statuses[]` 对每个必需来源恰好有
一个 Row 且没有外来 Row；并且每个必需来源的 Acquisition Status 都是 `success` 时，回执
才能判定 `unchanged`。Item 缺失、越界、重复、有歧义，Item 集合不完整，
或者必需来源处于 Rate Limit、Access Challenge、`verification_required`、`failed` 或
`no_items`，都会产生 `decision = blocked`，且不得创建闸门。Fingerprint 变化必须生成新的
`completed` 报告、新脚本并执行完整独立验证；任何 Partial Recheck 都不能声称 `unchanged`。

续期闸门通过 typed `parents[]` 绑定复查回执与前一闸门。过期闸门不会重新变成当前闸门，
任何文件都不原地修改；只有显式提供新的闸门路径后，媒体阶段才解除阻断。证据未变化的复查
只有在两个半开 Clock 比较都通过时才能续期，并且绝不能延长硬到期时间。跨越硬到期时间——
或在脚本使用“今天/刚刚”等相对时间措辞时跨越本地日历日期——必须重新生成 `completed`
报告、新脚本并执行完整独立验证。

## G2 — 辩证和专业叙事门禁

每一章恰好有一个中心问题。每个核心论点必须包含：

- 至少一个已确认事实或正确归因的声称；
- 至少一个最终 Claim，其事实前提由访问状态为 `partial` 或 `full_text` 的授权证据 Item
  支持；
- 中间因果机制，而不是从标题直接跳到结论；
- 实质性的行为体、利益、能力、约束和反应；
- 明确假设和与证据强度相称的措辞；
- 一个实质性反方立场、反证路径，或者一条明确且有界的说明：授权 dossier 中没有可用的
  实质反证；
- 一个或多个削弱或推翻论点的条件；
- 可观察的观察信号；以及
- 对未来演化进行证据感知的条件化处理。

非空数组本身并不足够。把论点换一种说法当成反方观点、使用泛泛的“另一种可能”，或者
给出无法观察的信号，都会使门禁失败。

合同不要求人为给予相同权重。它要求授权证据内最有力的实质性替代解释，并防止叙述者为了
戏剧效果删除不方便的证据。

对每个论点，统计由精确 Analysis Registry 引用和有证据支持的事实前提授权、且具有实质
差异的情景路径：

- 授权路径至少有两个时，本章至少包含两个；每个都带触发条件、时间跨度、可观察信号和
  Claim 级引用；
- 只授权一个时，本章包含该路径，并由 Python 签发不可变
  `scenario_evidence_gap = only_one_authorized_scenario` 回执；
- 一个也没有时，模型不得虚构，Python 记录
  `scenario_not_applicable_reason = no_authorized_scenario_evidence`；以及
- Verifier 必须把同一路径的两个表面改写判为不具实质差异。

只有一个或零个路径的分支不豁免反方立场、失效条件或观察信号要求；它们防止为了凑配额而
制造无支持的预测。

### 专业说书评分量表

一个独立 verifier 和一名具名人工验收审阅者分别对以下维度按 1 至 5 分评分：

| 维度 | 通过含义 |
| --- | --- |
| `dialectical_rigor` | 机制、行为体、假设、反方立场、条件和可观察项具有实质内容 |
| `narrative_coherence` | 一条故事按因果推进；不把互不相关的同日事件强行拼接 |
| `professional_clarity` | 技术概念得到解释；术语不能替代机制 |
| `epistemic_transparency` | 听众能够区分已确认、经归因、历史、推断、争议、情景和未知 |
| `restraint_and_non_sensationalism` | 没有虚构戏剧、绝对化语言、虚假确定性或被压制的反证 |

不可变 Verifier 结果包含 `script_rubric_scores[]` 和 `chapter_rubric_scores[]`。后者对每个
Script `chapter_id` 恰好有一个 Row，不能存在外来或重复 Row。整稿集合和每个 Chapter 集合都
恰好包含全部五个具名维度；每个维度都有整数评分、解释和支持/失败 Beat ID。人工验收使用
两阶段盲审协议：

1. Verification 不可变后，Python 从操作系统 CSPRNG 生成 256-bit Nonce。在 Reveal 前，
   Nonce 保存在所有 Reviewer-readable Artifact 和访问界面之外。Python 记录
   `commitment_scheme_id`、`canonicalization_id` 和
   `verifier_score_commitment_sha256`；版本 1 对 Nonce、`verification_sha256`、
   `rubric_sha256` 和同时包含 `script_rubric_scores[]` 与 `chapter_rubric_scores[]` 的规范隐藏
   Verifier Score Payload 执行带 Domain Separation 的 SHA-256：

   ~~~text
   SHA256(
     domain_separator
     || nonce_256_bits
     || verification_sha256
     || rubric_sha256
     || canonical_hidden_verifier_scores
   )
   ~~~

   版本 1 的 `domain_separator`、Byte Encoding、Score Ordering 与 Canonical JSON 规则由这两个
   版本化 ID 固定。
2. `<run-id>-blind-review-dossier.json` 绑定报告、脚本与 Rubric，省略 Nonce 和全部 Verifier
   Score，只暴露不透明的 `verification_sha256`、Commitment 及其两个 Scheme ID。它不包含
   Verification Path、Verification Artifact ID、Latest Pointer 或其他可解析的 Verification
   Handle。
3. `<run-id>-human-review.json` 绑定盲审 Dossier 路径/Hash、具名审阅者、
   `review_started_at`、`scores_locked_at`，以及带解释的全部五个
   `human_rubric_scores`。
4. 只有该不可变人工回执已经存在后，`<run-id>-score-reveal.json` 才能揭示 Nonce 与 Verifier
   Score Payload；通过 Typed Parent Row 绑定 Human Receipt 与 Verification（包括
   Verification Path/Hash）；记录 `scores_revealed_at`；并在所记录的 Scheme 与
   Canonicalization ID 下重新计算精确 Commitment，同时证明所要求的 Timestamp Ordering。

在评分锁定前，审阅界面只能暴露盲审 Dossier。审阅者不能是 Storyteller 或 Verifier。
验收要求 `review_started_at <= scores_locked_at <= scores_revealed_at`、Commitment 精确
相等，且三个 Artifact 的 Hash 全部不可变；Reveal 缺失、过早、不匹配或被改写都会失败。
该状态协议只证明锁分前工作流从 Reviewer-readable 界面隐藏了什么；它不声称知道审阅者从
系统外获得的信息。

整稿级每项 Verifier 分数、每个 Chapter Row 中的每项分数，以及五项整稿人工分数都必须各自
达到 `>= 4/5`。Chapter ID 和维度名必须精确匹配；不能用跨章、整稿/章节、Verifier/Human
或总平均分掩盖较低分数。签发闸门需要 Verifier 回执；正式通过 G2 和阶段 C 需要 Human
Review 和 Score Reveal 回执。关键事实和时效规则仍然是布尔硬门，而不是主观评分。

以下内容被禁止：

- 虚构对话、私人心理、内幕细节、秘密动机、第一人称经历、引语或时间顺序；
- 把相关性当成因果性；
- 在没有证据时把一个案例扩大为广泛趋势；
- 混淆短期冲击与结构性变化；
- 把情景写成必然预测；
- 为了强化故事而删除实质反证；
- 在没有证据时使用“震惊”、“彻底改变”、“不可避免”或等价的绝对化语言；以及
- 使用专业术语却不解释其机制。

## G3 — 独立 verifier 门禁

独立性要求：

- 独立的 task/session 和角色；
- 接收器强制执行的输出 schema 和策略 hash；
- 不继承 storyteller 的隐藏对话；
- 最小、不可变且 hash-bound 的 dossier；
- storyteller 无权写入最终验证；以及
- 记录 requested/served model、provider route、usage task 和 verifier policy hash。

版本化 `verifier_model_policy` 对 Provider Route、requested 和 served Model ID 做白名单。
每个允许的 Served Model 都必须有固定的能力 Manifest，证明它支持严格结构化输出；上下文
窗口足以容纳实测 Dossier 和冻结的响应预留；该角色禁用工具/网络访问；Task/Session 隔离；
并且用量报告与 G4 兼容。白名单之外的 fallback、缺失的 Served Model 身份、能力不足，或
白名单外的 requested/served 替换，都会在解释输出内容之前阻断验证。Verification 和红队
Manifest 绑定白名单及能力 Manifest Hash。

每个 beat 恰好得到一个 `pass`、`repair` 或 `reject` 结果，以及以下检查：

~~~text
factual_support
temporal_accuracy
attribution
access_boundary
fact_analysis_separation
claim_unit_completeness
causal_support
dialectical_completeness
uncertainty_language
narrative_integrity
professional_clarity
compliance_boundaries
~~~

以下是布尔关键检查，必须全部通过：

~~~text
factual_support
temporal_accuracy
attribution
access_boundary
fact_analysis_separation
claim_unit_completeness
compliance_boundaries
~~~

Beat ID 与 verdict 构成一一对应集合。未知、重复、缺失或跨脚本 ID 都会失败。Verifier 不能
编辑已经保存的脚本；它只能生成不可变判定和有界修复指令。

无效模型草稿只是不变的 `draft attempt`，绝不能获得规范讲解稿 revision。只有确定性校验
通过后，Python 才分配 `script_revision = sN`。Verifier dossier、verification 和 gate
必须满足：

~~~text
set(script.all_beat_ids)
==
set(verification.all_beat_ids)
==
set(gate.verified_beat_ids)
~~~

三个集合都没有重复 ID，每项 verification verdict 都是最终 `pass`，且 gate 不得包含
脚本之外的 ID。

全部内容验证阶段合计只允许一次修复。修复会创建新的脚本 revision 和 hash，把输入缩小到
失败 beat 及必要相邻上下文，不能扩大授权证据，并触发完整确定性验证和独立重新验证。
第二次非 `pass` 结果为 `rejected`。

### Verifier 红队验收

默认启用前，使用相同 Served Model、Prompt、策略、能力 Manifest 和合同，对规范版本 1
冻结集中的恰好 32 个用例运行两次：

- 8 个事实/证据错误；
- 8 个时间/当前与背景错误；
- 8 个认知、因果、辩证或虚构动机错误；
- 4 个 Prompt 注入或权限升级尝试；以及
- 4 个干净对照。

前四组恰好是 28 个对抗用例；版本 1 恰好有 4 个干净对照。增加用例必须创建版本化集合，
不能静默改变这些分母。
每个非干净用例都声明 `expected_defects[]`。每个 Defect 都有唯一 `defect_id`、
`severity`（`critical` 或 `noncritical`）、`expected_decision` 以及精确的
`expected_failed_checks[]`。评分以 Defect ID 为单位，而不仅是看所在用例是否失败；
一次泛化拒绝不能宣称检出了多个未映射缺陷。`critical_expected_defect_count > 0` 和
`noncritical_expected_defect_count > 0` 都是强制条件；每个已声明的预期 Defect 都必须
进入相应 Severity 分母。Parser Error、无效结构化响应和中止用例必须计为该用例所有预期
Defect 的漏检，不能从分母中消失。

两次运行必须各自达到以下结果，禁止合并两次运行：

| 指标 | 阈值 |
| --- | --- |
| 关键预期缺陷召回率 | 按 `defect_id` 达到 `100%`，且失败检查映射符合预期 |
| 非关键预期缺陷召回率 | 按 `defect_id` 达到 `>= 90%` |
| 干净对照 | 恰好 `4/4` 得到 `pass`，且没有虚构缺陷 |
| Prompt 注入逃逸 | `0` |
| 错误报告/脚本/hash 被接受 | `0` |

普通单元测试使用冻结 verifier fixture。真实远程模型验收集为每次运行生成不可变 Manifest，
其中包含全部预期和实际 Defect 映射；requested 或 served Model、白名单、能力 Manifest、
策略、Prompt 或合同变化时重新运行。

## G4 — Token 成本门禁

本项目中的成本指模型 Token 用量：

~~~text
story_pipeline_tokens =
phase["professional-narrative-storyteller"].tokens.accounted_total.value
+ phase["professional-narrative-verifier"].tokens.accounted_total.value
+ phase["professional-narrative-repair"].tokens.accounted_total.value
+ phase["professional-narrative-reverification"].tokens.accounted_total.value
~~~

四个 Phase Row 必须全部存在；`story_pipeline_tokens` 是其规范数值 `.value` 字段的整数和，
绝不能把 Aggregate Measurement 对象直接相加。只相加互不重叠的 Accounted Total。Cached
Input、Uncached Input、Output 以及任何诊断子集保持
可见；当 reasoning 或 tool output 已经包含在 output 中时，不重复相加。货币价格、币种和
Provider 账单不进入验收。

版本 1 在第一次验收运行前冻结暂定工程上限：

~~~text
story_pipeline_tokens <= 250_000
~~~

这是只覆盖四个叙事模型阶段的草案上限；上游报告分析不计入 `story_pipeline_tokens`。
该上限不是永久质量 KPI。它只能通过运行前的版本化决策修改，不能在看到失败运行后提高。

运行时持久化与正式验收刻意分开。运行被中断或计量降级时，用量可以保持
`coverage = partial`、下界、estimated 或 unobservable，并列明每个缺失的阶段、Call 或字段。
该记录是有效恢复证据，但不能通过 G4。缺失用量绝不能强制写成零。

一轮被接受的运行要求：

- 可以重新计算且互不重叠的 pipeline 总量；
- 每个已调用阶段都满足 `coverage == complete` 且
  `tokens.accounted_total.quality == exact`，并有非负整数
  `tokens.accounted_total.value`；
- 未调用的可选 repair 或 re-verification 阶段有精确 Scheduler 回执，证明 Provider Call
  数为 `0`；其必需 Phase Row 满足 `tokens.accounted_total.value == 0` 且
  `tokens.accounted_total.quality == exact`；
- `unclosed_call_count == 0`；
- usage conflicts 为 `0`；
- 每个 task 都绑定当前 run、report、script、role 和 phase；
- `story_pipeline_tokens <= 250_000`；
- 全局 `budget.max_agent_tokens > 0`，并且每个获准模型调用前都通过下方阶段准入不变量；
  以及
- 对相同已完成结果的重放新增 Provider 调用为零、Token 为零。

~~~text
global_observed_accounted_tokens
+ remaining_narrative_phase_reserve_tokens
+ downstream_required_reserve_tokens
<= budget.max_agent_tokens
~~~

两项 Reserve 都来自运行前的版本化策略，并且非负。运行时 Ledger 不完整时，使用已观察下界
执行提前阻断，但它不能证明最终余量。通过局部 250,000-Token 上限绝不能弥补违反全局
observed-plus-reserve 边界。
只有精确 Scheduler 回执证明该 Reserve 类别中已无任何获授权或已调度的剩余模型阶段时，
Reserve 才能等于零；缺失或未知的 Reserve 不是零。

逻辑调度允许：

~~~text
1 次初始 storyteller
1 次初始 verifier
0 或 1 次定向修复
0 或 1 次完整重新验证
~~~

如果输出范围、证据覆盖、质量或长度发生变化，更低的 Token 用量并不足以证明优化。
可比优化必须保持报告、索引、合同、范围和质量门禁稳定。

使用以下归一化公式，并同时报告精确分子和分母：

~~~text
normalized_tokens_per_chapter =
    story_pipeline_tokens / accepted_chapter_count

normalized_tokens_per_verified_beat =
    story_pipeline_tokens / verified_beat_count

normalized_tokens_per_selected_event =
    story_pipeline_tokens / distinct_selected_featured_event_count

normalized_tokens_per_1000_final_zh_characters =
    story_pipeline_tokens * 1000 / final_zh_han_character_count

normalized_tokens_per_final_spoken_minute =
    story_pipeline_tokens / (actual_audio_duration_ms / 60_000)

phase_share =
    exact_phase_accounted_tokens / story_pipeline_tokens
~~~

对于 `phase_share`，`exact_phase_accounted_tokens` 就是已经通过 Exact-quality 门禁后的
`phase[name].tokens.accounted_total.value`。

`final_zh_han_character_count` 是对确定性拼接的最终口播 Beat 进行 NFC 归一化后，其中 Unicode
Han Script Code Point 的数量；空白、标点、Markup、证据抽屉和 Metadata 不计数。只有已经
验收的音频具有实测正时长时，才计算每分钟口播指标。其他分母也都必须大于零；分母为零时
结果是 `not_applicable`，不能显示为零或用于比较。这些整条 Pipeline 比率只是归一化诊断，
不能声称每章、每个 Beat 或每个事件导致了相同的 Token 份额。首次通过率和修复率应作为
质量/过程诊断另行报告，不能当作 Token 节省。

实现验收 Manifest 固定记录 `character_counter.normalization = NFC`、
`character_counter.unicode_property = Script=Han`、`character_counter.library`、
`character_counter.library_version` 和 `character_counter.unicode_version`。其中任何
一项发生变化都创建新的指标版本；不同版本的结果不能直接比较。

## G5 — 不可变性、幂等、并发和恢复

规范脚本、Verifier Dossier、Verification、Repair Receipt、经验证 Gate Receipt、Contract
Bundle Snapshot 和两个 Reader Projection 均不可变。可变 Run Manifest 保存路径、Hash、
状态、Attempt 和 Usage Binding，不复制正文或 Token 总量。

每个 Artifact 都有 `schema_version`、`artifact_id`、`artifact_kind`、
`data_root_identity`、Typed `parents[]` 和 `policy_hashes`。`parents[]` 始终是 List；每个 Row
都使用以下公共结构，只有定义了语义 Hash 的 Parent Kind 才包含 `semantic_hash`：

~~~text
parent_kind
path
file_sha256
semantic_hash  # optional
~~~

Artifact 自身的 `<kind>_sha256`（包括用于 Filename 的 Digest）是语义 Hash：对该 Artifact
版本化规范 `semantic_payload` 执行 SHA-256。Hash 输入明确排除 `semantic_payload` 之外的所有
Envelope Field、Artifact 自身 Digest Field、持久化文件字节与格式，以及派生 Path/Filename。
任何 Artifact 都不能嵌入自身的 `file_sha256`。与此不同，`parents[].file_sha256` 是对已完整
持久化 Parent 文件字节执行的 SHA-256。Parent Kind 定义了语义 Hash 时，其 Parent Row 同时
携带该字节 Hash 与 `semantic_hash`；两者的 Hash Domain 不同，不要求相等。

每条 Parent Path 都相对于活动 Data Root。同一 Artifact 内 Parent Kind 必须唯一；缺少必需
Row、存在外来 Row 或重复 Row 都会校验失败。Python 通过 `require_data_root_path()` 解析每条
路径，并递归复核父依赖闭包；子 Artifact 不能依赖裸 ID、Latest Pointer、Keyed
`parents.<kind>` Object 或目录扫描。

当前活动配置的报告、叙事、Verifier、Projection、Freshness 与 Policy Identity 冻结为一份
不可变 Contract Bundle Snapshot，路径为
`narratives/contracts/<policy-id>/<contract-bundle-sha256>.json`。快照记录
`contract_bundle_identity`、规范 `contract_bundle_sha256`、每个组成 Contract 与 Policy 的
Identity/Hash、`data_root_identity`，以及空的 Root `parents[]` List。Bundle Hash 或 Identity
变化会创建不同路径；任何快照都不得覆盖。`<contract-bundle-sha256>` 与
`contract_bundle_sha256` 是同一个版本化规范 `semantic_payload` Hash，绝不是 Snapshot 文件
字节 Hash。Child 引用该 Snapshot 时，把这一数值保存为 `parents[].semantic_hash`，并把完整
Snapshot 字节的独立 Digest 保存为 `parents[].file_sha256`。

Revision 轴必须无歧义：报告 `rN`、故事尝试 `aN`、规范讲解稿 `sN`、验证 `vN`、时效
复查 `fN`、闸门 `gN`、投影 `pN`、图文编译 `cN`、TTS/音频 `tN` 和渲染 `render-N`。
每个 `pN` 只绑定一个 `gN`。若一个 Schema 或路径把同一个 Revision 标签用于不同含义，
测试必须失败。

可变 Run Manifest 保存显式当前引用：

~~~text
professional_narrative.current_script.{path,sha256}
professional_narrative.current_verification.{path,sha256}
professional_narrative.current_gate.{path,sha256}
~~~

这些是 Run Manifest Object 的 Root Path；外层不存在 `run` Wrapper。这些引用只是编排提示，
不是信任锚；每个消费者仍须重新校验。状态按职责拆分：

~~~text
verification: ... -> verifying -> verified | repair_required | rejected | failed
admission: current | recheck_pending | expired | blocked
reader: pending | rendering | ready | partial
story: pending | compiling | ready | blocked | partial
video: pending | rendering | completed | partial | failed
~~~

`verified` 和 `rejected` 是某一 script revision 的不可变内容判定。TTL 到期只把 admission
改为 `expired`，绝不把已验证稿改写成未验证。`failed` 是可恢复执行状态，`partial` 只属于
投影或下游媒体。

要求：

- 相同输入身份返回 `already_completed`，路径和 hash 相同，新增模型调用为零；
- 报告、索引、合同、策略、`as_of`、packet 或脚本发生变化时创建新 revision；
- 不覆盖任何现有脚本或验证；
- 一个 revision 的两个并发写入者只能有一个胜者；
- 失败者读取胜者结果，或收到明确 collision；
- 孤立草稿或验证只有在完整路径、身份和 hash 验证后才能被接管；
- 损坏、不匹配或冲突的工件显式失败；
- 修复回执绑定被拒草稿 hash、错误路径、规则 ID、授权、attempt 和修复是否仍获授权；
- 模型返回后、草稿持久化后、verifier 调度后、验证持久化后和读者投影后发生的中断均可恢复；
- 已有匹配不可变结果时，恢复绝不重复模型调用；
- 陈旧结果不能推进当前读者投影或媒体门禁；以及
- 投影失败不能撤回报告或已验证脚本。

至少执行一次真实故障演练，在 verifier/run 更新边界中断，并证明最终语义 hash 与不中断路径
相同，且没有不必要的新 Token。

## G6 — HTML 和 Markdown 门禁

主要阅读区域是一篇融合的专业叙事，包括：

- 说书式主文；
- 可区分的事实、归因、背景、判断、争议、情景和观察信号角色；
- 来源名称和发布时间；
- `as_of`、`verified_at`、时效和验证状态；以及
- 可折叠展开的论证和证据细节。

系统中有且只有一个确定性语义投影构建器：

~~~python
bundle = load_verified_narrative_gate(
    verified_gate_path,
    data_dir=data_dir,
    clock=clock,
)
payload = narrative_projection_semantic_payload(bundle)
render_markdown(payload)
render_html(payload)
~~~

其唯一签名是
`narrative_projection_semantic_payload(bundle: VerifiedNarrativeBundle) -> dict`。每条 Reader
Command 只接受一个 `verified_gate_path`，以及 Loader 必需的 `data_dir` 和 `clock` 依赖，并在
调用构建器前执行 `load_verified_narrative_gate()`。不存在接受 Raw Script、Verification、
Gate Object、Latest Pointer 或分离路径的公开 Reader API。

该不可变 Payload 包含有序章节/Beat 文本、`central_question`、认知与时效 Class、
Claim/Evidence/Analysis 引用、来源名称与发布时间、`as_of`、验证状态和闸门身份。HTML 和
Markdown Renderer 只能接受这一 Payload 类型；它们不能各自重新读取或解释 Script、
Verification、Report 或 Index。

一个 Projection Revision 同时写入以下两个不可变路径：

~~~text
narratives/projections/<report-id>-sN-gN-pN.md
narratives/projections/<report-id>-sN-gN-pN.html
~~~

两个 Artifact 共享一个 `pN`，各自恰好有一个指向同一 `gN` 的 Typed Gate Parent；Projection
Revision 永远不能重新绑定其他 Gate，也不能覆盖。

两种投影都嵌入或引用同一个 Payload 的 Canonical JSON 及其
`projection_payload_sha256`。验收会从每种投影重新提取 Payload，并要求其 Canonical
Payload Hash 与构建器输出精确相等：`2/2` 投影匹配，语义字段不匹配为 `0`。表现层字节
不要求相等。

HTML 对每个不可信字符串执行转义。链接使用现有安全 URL 策略。草稿、待修复、被拒、陈旧
或 hash 不匹配的内容绝不能标记为已验证，也不能显示在已发布叙事区域。读者投影失败不能
修改规范工件。真实验收包括桌面和窄屏视觉检查，覆盖裁切、重叠、证据链接漂移和误导性
状态标签。

## G7 — 经验证媒体门禁

媒体命令接受一个 `verified_gate_path`，而不是任意 `script_path`，也不能通过目录扫描寻找
最新文件。门禁回执至少绑定：

~~~text
schema_version
artifact_id
artifact_kind = verified_narrative_gate
data_root_identity
gate_revision = gN
decision = pass
report_id
report_content_hash
bound_index_file_sha256
contract_bundle_identity
contract_bundle_sha256
narrative_contract_sha256
script_id
script_revision
script_sha256
script_evidence_closure_sha256
verification_sha256
verified_at
freshness_anchor_at
freshness_deadline_at
script_hard_expiry_at
verified_beat_ids[]
parents[]
~~~

初始闸门的 `parents[]` 对以下每个 `parent_kind` 都恰好包含一个 Row：

~~~text
report
bound_index
contract_bundle
packet
scope_receipt
script
verification_dossier
verification
~~~

续期闸门恰好包含这八个 Row，并额外恰好包含一个 `prior_gate` Row 和一个
`freshness_recheck` Row。任何闸门都不能缺少必需 Kind，也不能包含外来或重复 Kind。每个 Row
使用 G5 定义的公共 List-Row 结构，每条路径都相对于闸门的活动 `data_root_identity`；不存在
Keyed `parents.<kind>` 形式，也不存在 `parents[]` 之外的续期引用。唯一公开的准入 API 是：

~~~python
bundle = load_verified_narrative_gate(verified_gate_path, data_dir=data_dir, clock=clock)
compile_story_stream(bundle, ...)
~~~

`load_verified_narrative_gate()` 校验闸门 Schema、执行 `require_data_root_path()`、递归读取并
重算完整父依赖闭包、检查 Pass 判定和精确 Beat 集合相等、校验当前 Report/Run 与 Data Root
Identity，并执行时效或绑定的续期回执检查。它还会重新打开 Contract Bundle Parent、重算其
Hash，并要求其 `contract_bundle_identity` 等于当前活动配置的 Contract Identity。它返回
`VerifiedNarrativeBundle`。公开编译器只接受该类型；不存在公开 Raw-Script 编译器，也不存在
`--force`、`--skip-verification` 或 `--allow-stale` 选项。TTS 只接受 Ready 的 Typed
Story-stream Handle；视频只接受 Ready 的 Typed Story-stream 及音频/字幕 Manifest。

只有以下条件全部成立时才能开始媒体阶段：

~~~text
gate.decision == pass
AND 每个 typed parent path 都位于活动 Data Root 内
AND 递归重算的 parent/hash 闭包完全匹配
AND set(script.all_beat_ids)
    == set(verification.all_passed_beat_ids)
    == set(gate.verified_beat_ids)
AND 三个 beat 集合均无重复
AND clock < freshness_deadline_at
AND clock < script_hard_expiry_at
~~~

G7 终止于经验证内容准入。它既不假设 Scene 已经存在，也不预先批准素材或 Fallback。
确定性编译器先从已准入 Bundle 和媒体候选集生成候选图文流 Manifest；然后 M1 执行下方的
编译后 `oneOf`、Hash、证据、权利、Fallback、覆盖和重放检查。

草稿、authoring、verifying、repair、rejected、stale、missing、damaged、cross-report 或
mismatched 输入必须在 `100%` 的情况下被拒绝。拒绝不得创建图文流、音频、字幕或视频
Artifact。负向验收测试同时攻击 CLI 入口和直接 Python 模块调用。

## 图文流验收

图文流编译是确定性的，并执行零次模型调用。每个 Scene 都绑定下列公共字段，并且恰好满足
一个 `oneOf` 分支：

~~~text
scene_id
beat_ids[]
event_ids[]
evidence_item_ids[]
scene_type
on_screen_text
aspect_ratio
crop
focal_point
safe_area
target_or_actual_time_range

oneOf:
  media_asset:
    scene_type = media_asset
    image_sha256 = 必填 SHA-256
    source = 非空
    credit = 非空
    rights_status = owned | licensed | public_domain
    fallback_reason = 不存在

  text_card:
    scene_type = text_card
    image_sha256 = 不存在
    rights_status = 不存在
    fallback_reason = no_allowed_asset | rights_unknown | rights_rejected | hash_failed
~~~

完整候选权利 Enum 是 `owned`、`licensed`、`public_domain`、`unknown` 或
`rejected`。只有前三项能够作为已选媒体素材的 `rights_status` 持久化。标记为 `unknown`
或 `rejected` 的候选素材绝不能被选中；编译器必须改选获准素材，或者生成带相应 Fallback
原因的 `text_card`。Python 只能从白名单内、Hash-bound 的权利或许可记录派生候选权利；
Model、公开 URL 或来源署名都不能分配它。

Scene 证据是已验证 beat 证据的子集。在完整 Manifest 中，所有 scene 的 `beat_ids[]` 保持
讲解稿顺序，并对闸门内每个 beat 恰好覆盖一次，不得缺失、重复或混入外部 ID。剪辑子集是
一份新的不可变 cut/script，必须重新通过确定性校验和独立验证；调用方不能通过 requested ID
临时剪辑。相同的经验证门禁、媒体集合和配置生成相同的语义 scene 顺序和 Manifest Hash。
未知或被拒的媒体权利会选择已许可素材或纯文字 fallback。公开 URL 或来源署名单独存在，
并不能证明允许在公开视频中复用。图文编译失败不会改变报告、脚本、验证或门禁。

每份 Manifest 以及相同输入连续编译两次的重放都必须满足以下 M1 验收阈值：

| 指标 | 必须达到的阈值 |
| --- | --- |
| 已验证 Beat 覆盖率 | `100%` |
| 缺失 / 重复 / 外部 Beat ID | `0 / 0 / 0` |
| Scene 证据超出其已验证 Beat | `0` |
| 选用 `unknown` 或 `rejected` 权利的媒体 | `0` |
| Scene `oneOf` 违规或未解决 Fallback | `0` |
| 图文编译器模型调用 / 模型 Token | `0 / 0` |
| 相同输入的语义 Scene 顺序或 Manifest Hash 不匹配 | `0` |

## 视频验收

首个视频 MVP：

- 只消费当前经验证门禁和 ready 图文流；
- 使用已授权（`owned`、`licensed` 或 `public_domain`）的静态图片或有效纯文字卡片、
  一个获得许可的 TTS 声音、媒体需要时的署名和字幕；
- 记录 TTS 引擎、版本、声音、许可、配置、用量、音频 hash 和实际时间信息；
- 从实际音频派生每个 scene 和字幕区间；
- 把视频、音频、字幕、字体、素材和 renderer 设置绑定到同一脚本；
- 使用可复现的 codec、分辨率、frame rate、bitrate、color 和字体设置；
- 通过 container、codec、duration、audio-track、subtitle 和 A/V synchronization 检查；
- 不得缺失、重复或重排任何口播 beat；
- 接受针对黑帧、裁剪、安全区、署名、字幕和水印的抽帧检查；
- 独立重试且不撤回报告或已验证脚本；以及
- 排除来源视频摄取、声音克隆和权利未知的音乐。

每个 Scene 边界和完整音轨的初始 A/V 时长容差都是 `250 ms`。后续平台 Profile 可以对
该值进行版本化。M2 验收还要求口播 Beat 与字幕覆盖率 `100%`、口播 Beat 缺失/重复/重排
`0 / 0 / 0`、字幕区间落在实测音频之外 `0`，以及视频帧使用 `unknown` 或 `rejected`
权利的媒体 `0`。

## 非证据

以下任何一项都不能证明完成：

- 生成一份长文档；
- 达到字数、段落数或章节数；
- 平均每段引用数；
- 来源或 URL 总数；
- 存在一个关键失败时仍取得较高的 verifier 汇总分数；
- storyteller 声称已经自我验证；
- 缺少 Hash-bound 盲审、锁分和评分揭示回执的人工评分；
- 模型置信度；
- 没有红队验收集时的低修复率；
- 出现“然而”，或者正面和负面句子的数量相等；
- 存在一个 HTML 文件；
- 可播放的 TTS，或能够打开的 MP4；
- 只有 output Token，而不是完整且不重叠的 input 和 output；
- 把缺失用量当成零；
- 使用 `collected_at` 作为发布时间；
- 当前报告级发布后 evaluator 返回 `accept`；
- 同一角色编写并批准自己的脚本；或者
- 一份成功的真实报告。

## 分阶段真实验收

### A — 确定性 fixture

冻结一个 report/index/analysis fixture，覆盖当前新闻、前一日新闻、旧背景、缺失和未来时间、
metadata-only 和 verification-required 访问、冲突证据、标量/数组/嵌套/综合分析引用、复合
Claim、三个分析、授权路径为两个/一个/零个的条件情景分支，以及失效信号。覆盖
`mode = edition_narrative`、`central_question`、绑定 Index 身份、四种 Claim 级 Freshness
Class、同一 Beat 中的混合时效 Claim、缺失/外来的发布时间证明 ID、来自“其他方面仍属当前”
事件的旧 Item、非零当前配额、Claim 类型/关键性/升级/完整性、规范
`sections[].items[].source_refs[]` 归属来源、Registry Row/Hash 篡改、重复与歧义归属、60%
精选事件覆盖、分析域 `3/3`、仅允许缺失/空值的严格跨视角综合不适用规则、每章
`partial`/`full_text` 深度、直接与传递 Script Evidence Closure，以及唯一 Typed-Bundle
语义投影 Payload。还要覆盖正确和畸形的初始/续期 Parent Kind List、非活动 Contract Bundle、
缺失或外来的 Closure Item、Partial Recheck、每种被阻断 Source Status、两个 Freshness
Deadline 的相等边界、绑定 Gate 的不可变 `pN` 路径、Hidden-Nonce Commitment/Reveal 篡改、
被拒绝的 `completed_partial` 输入，以及 Raw Reader/Compiler Direct-API 绕过尝试。所有叙事
Schema、跨字段、Hash、证据、时间、修复、状态、读者投影和 G7 准入门禁测试都必须通过。

验收 M1 时，在同一 Fixture 家族中增加两个 Scene `oneOf` 分支和全部定量图文流阈值。
图文流仍被明确延后时，该 M1 扩展不作为完成叙事 MVP 的前置条件。

保留的 2026-08-25 `completed_partial` 晨报验收工件只能用作负向与兼容性 Fixture。它不能
计入阶段 C 的任何一期日报、Token 基线、当前新闻配额证据、时效证据或发布证明。

### B — Verifier 红队

运行两次 32 用例验收集，两次都必须独立满足 G3 的每个阈值，包括按 Defect ID 评分，并且
每次恰好 `4/4` 干净对照通过。把 requested 和 served Model、Model 白名单与能力、Prompt、
策略、合同、用例/Defect Hash、原始结构化判定、用量和逐次摘要保存到不可变验收 Manifest。

### C — 连续三期真实日报

默认启用前，连续完成三期真实日报，其中至少包括一期晨报和一期晚报。下列每个阈值都必须
由每一期独立满足；禁止跨期合并分子、分母、评分、Warning 或 Defect：

- 报告和叙事确定性验证：`0 errors / 0 warnings`；
- 叙事模式：`edition_narrative`，章级 `central_question` 非空，并且具有精确
  `bound_index_file_sha256` 血缘；
- 精选事件覆盖：分母 `> 0`，覆盖率 `>= 60%`；
- 归属 Registry：每一行都来自规范报告路径，Item Ownership 唯一，`membership_sha256`
  匹配，重复/歧义/外来 Row 均为 `0`；
- 分析域覆盖：通过最终 Claim 级引用覆盖 `geopolitics`、`ai_technology` 和 `markets`，
  达到 `3/3`；
- 跨视角综合：至少一个最终精确引用，或一个有效的确定性不适用回执；
- 当前新闻配额：`available_current_featured_event_count > 0`、
  `current_claim_count > 0`，且最终不重复当前事件覆盖
  `>= min(2, available_current_featured_event_count)`；
- 关键声称证据闭合率：`100%`；
- Claim Unit 完整性：`pass`，且没有 Python-critical Claim 被降级；
- 论点证据深度：每个核心论点至少一个最终 Claim 由 `partial` 或 `full_text` 证据 Item
  支持，因此每章也至少一个；
- 当前声称时间合规率：`100%`；
- 时效：每个 Claim Unit 的 Class 都属于四值 Enum，每个证明 ID 集都满足所属 Class 与直接
  证据子集规则，混合 Class Beat 不能转移 Current 状态；初始闸门的 `freshness_anchor_at` 等于
  `verified_at`，续期闸门则等于 `rechecked_at`；截止时间等于该 Anchor 加软 TTL 与
  `script_hard_expiry_at` 的较小值；使用闸门时两个半开 `clock <` 比较都通过；
- 时效闭包：已排序且无重复的 Checked Item Set 与
  `script_evidence_closure_item_ids[]` 完全相等，Closure 与 Fingerprint Policy Hash 匹配，
  所有必需 Old/New Fingerprint 均唯一存在且相等，必需 Source Set 精确，且每个必需 Source
  Status 都是 `success`；
- 情景：每个论点都通过授权证据为两个/一个/零个的规则；
- 每个 beat 最终判定：`pass`；
- script、verification 与 gate 的 beat 集合：完全相等，重复 ID `0`；
- 修复：每份脚本最多一次；
- Verifier 量表：整稿五个维度以及每个精确 `chapter_id` 的五个维度都各自 `>= 4/5`，Chapter
  或 Dimension 缺失/外来/重复均为零，并有不可变 Verifier 回执；
- 人工量表：五个维度各自 `>= 4/5`，并有另一份不可变具名审阅者回执、匹配的 Blind
  Dossier 与 Score Reveal 回执、在 Reveal 前对 Reviewer 不可见的 OS-CSPRNG 256-bit
  Nonce、匹配的 Scheme/Canonicalization ID、Commitment 相等，且
  `review_started_at <= scores_locked_at <= scores_revealed_at`；
- Token 覆盖：每个已调用阶段精确且完整，可选零调用回执存在，总量互不重叠，Open Call
  `0`、Conflict `0`；
- Token 预算：`story_pipeline_tokens <= 250_000`，且全局
  `global_observed_accounted_tokens + remaining_narrative_phase_reserve_tokens + downstream_required_reserve_tokens <= budget.max_agent_tokens`
  不变量通过；
- HTML/Markdown：`2/2` 重新提取的语义 Payload Hash 与唯一构建器 Payload 精确相等，
  共享一个不可变且绑定 Gate 的 `pN`，不安全渲染缺陷 `0`；
- 经验证 Gate Contract：`data_root_identity` 匹配，活动 Contract Bundle 可重算 Hash，初始
  八个或续期十个必需 Parent Kind 精确，缺失/外来/重复 Kind 均为 `0`；以及
- 经验证门禁 hash：均可完整重新计算。

### D — 恢复与阻断演练

在至少一期真实日报上演练：相同重放、并发 revision 分配、草稿后中断、验证后/manifest 前中断、
投影失败、证据未变化时 TTL 过期、证据变化时 TTL 过期、Index Hash 变化、在
Partial Closure Recheck、Closure Item 缺失/歧义、每种非 Success 必需 Source Status、在
`freshness_deadline_at` 和 `script_hard_expiry_at` 的精确时点及之后尝试使用、使用相对时间
措辞时发生本地日期切换、非活动 Contract Bundle、Parent Kind 缺失/外来/重复、父路径/Hash
损坏、Projection Rebinding、Nonce 或 Commitment 篡改、Early Reveal、直接模块绕过，以及
被拒讲解稿的媒体尝试。

必须达到：

- 不可变覆盖 `0`；
- 重复 revision `0`；
- 相同重放新增 Provider 调用 `0`；
- 陈旧/被拒/不匹配输入在下游被接受 `0`；
- 证据未变化的复查生成新 gate revision，证据变化则强制生成新讲解稿并执行完整验证；
- 不完整、有歧义或非 Success 的复查被阻断，且不得创建 Gate；
- 任何复查都不能延长 `script_hard_expiry_at`；硬过期或相对时间措辞因日期变化而失效的
  脚本必须重新生成 `completed` 报告；
- 每个失败都有明确状态和回执；以及
- 报告交付保持完整。

## 发布判定

只有 G0–G7 和真实验收阶段 A–D 全部通过时，叙事 MVP 才算完成。图文流和视频可以继续延后，
但经验证媒体门禁必须已经实现并经过测试。

只有图文流阶段的确定性、证据、权利、fallback、幂等和故障隔离门禁全部通过时，该阶段才算完成。

只有 TTS、时间信息、字幕、可复现渲染、权利、技术 QA、恢复和交付门禁全部通过时，视频阶段
才算完成。

只有实现、schema、测试、真实验收证据、运行时/用户文档以及中英文记录全部一致时，本草案
才能改为“已验证”。

英文权威版本见[证据驱动的专业叙事日报产品规格](../../product-specs/evidence-driven-professional-narrative-report.md)。
