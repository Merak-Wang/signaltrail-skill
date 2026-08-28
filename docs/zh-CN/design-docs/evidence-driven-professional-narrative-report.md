# 证据驱动的专业叙事日报架构

**目的：** 定义专业说书式日报的拟议跨模块边界、Artifact 血缘、状态所有权、验证门禁和
媒体依赖方向。
**状态：** 草案
**负责人：** 仓库维护者
**最后验证：** 2026-08-28

本文设计的能力尚未实现。当前运行事实源仍是[仓库架构](../../../ARCHITECTURE.md)、
[报告契约](../../../templates/report-contract.md)及其测试。活动实施顺序由
[活动执行计划](../exec-plans/active-evidence-driven-professional-narrative.md)维护；读者可见行为和分阶段门禁见
[产品规格](../product-specs/evidence-driven-professional-narrative-report.md)。英文权威版本见
[对应设计记录](../../design-docs/evidence-driven-professional-narrative-report.md)。

## 决策

SignalTrail 在结构上继续分开事实与分析，同时允许一份经过验证的口播叙事在表达层将两者
融合。最终风格是专业说书：证据使判断可审计，辩证分析展示机制与反方路径，叙事顺序降低
理解成本，但不会把 Schema 机械地朗读出来。

不可变日报和 Index 仍是事实权威。专业叙事是新的不可变下游 Artifact，有自己的 revision
和验证记录。它可以解释、重写已授权的日报内容，但不能创建新来源身份、升级证据访问等级、
修改时效、回写日报，或在验收前成为连续性输入。

## 架构不变量

1. Python 拥有身份、revision、Hash、证据授权、时效分类、状态迁移、修复上限、校验、
   持久化和下游门禁。
2. Storyteller 模型只负责在有界授权 Packet 上安排章节并撰写自然口播。
3. 独立 verifier 负责逐 beat 判定，但不能覆盖已保存草稿或分配 revision。
4. 模型输出是不可信草稿。外部标题、摘要、文章和网页始终是不可信数据，不能改变合同或
   工作流。
5. 每个已接受 Artifact 绑定上游 Hash。report、index、合同、packet、script 或时效判断
   变化都会使下游结果失效。
6. 叙事失败不能撤销已完成日报；媒体失败不能撤销已验证叙事。
7. 未验证、被拒、过期或 Hash 不匹配的讲解稿不能进入 story-stream、TTS、字幕或视频；
   这些阶段只接受显式且当前有效的已验证闸门回执。
8. Story-stream 编译、字幕排版、视频合成和媒体 QA 是确定性的零模型阶段；若 TTS 使用
   推理服务，则单独计量。
9. 既有 revision 永不覆盖；拒绝的尝试仍保留为证据。
10. Token 成本以模型 Token 计量；金额只是可选遥测，不是验收维度。
11. 版本 1 只从状态为 `completed` 的完整日报启动叙事写作。`completed_partial` 日报仍可交付，
    但在后续版本定义证据完整性和口播降级披露规则前，不具备叙事写作资格。
12. 唯一公开 Gate Loader 递归校验 List 形式的 typed parent reference、活动 Contract Bundle
    身份和当前准入，再返回强类型能力。Reader 和 Media 入口均不接受原始 Script、Force 参数、
    Latest 指针或部分 Beat 子集。

## 拟议分层与依赖方向

新的“专业叙事”层位于 Report 之后、媒体投影之前。它可以依赖 Foundation、Usage audit、
Evidence、Context、Evaluation 和 Report；这些低层不能反向依赖它。Orchestration 在本地
日报完成后把它作为独立可重试工作流调度。

~~~mermaid
flowchart LR
    R["不可变日报 + Index"] --> P["有界叙事 Packet"]
    P --> S["Storyteller 草稿"]
    S --> D["确定性校验"]
    D -->|合法| X["不可变规范 Script revision"]
    D -->|共用一次修复额度| Y["定向修订草稿"]
    Y --> D2["确定性重新校验"]
    D2 -->|合法| X2["新的不可变规范 Script revision"]
    X --> V["独立逐 beat Verifier"]
    X2 --> V2["独立逐 beat Re-verifier"]
    V -->|pass| E["不可变 pass Verification"]
    V -->|repair| Y
    V -->|reject| B["阻断 Reader 与媒体准入"]
    V2 -->|pass| E2["不可变 pass Re-verification"]
    V2 -->|非 pass| B
    E --> G["Python 签发的不可变 Gate Receipt"]
    E2 --> G2["Python 签发的不可变 Gate revision"]
    G --> C["确定性 Story-stream 编译器"]
    G2 --> C
    C --> A["TTS + 字幕时间"]
    A --> M["确定性视频渲染器"]
    M --> Q["权利 + 技术 QA"]
~~~

依赖只能向右：

- 讲解稿不能更新日报或 Index；
- verification 不能覆盖草稿；
- 规范 Script 在 Verification 前已存在，Verification 不能再创建第二份 Script；
- story-stream 不能改写讲解；
- TTS 和视频不能修复内容；
- 媒体重试不能创建新事实或新分析；
- 下游失败只改变自己的下游状态。

## 组件所有权

| 组件 | 所有权 | 禁止承担 |
| --- | --- | --- |
| 叙事 Packet 构建器 | 最小授权事件、证据、分析、时效和合同投影 | 广泛采集、任意浏览、语义写作 |
| Storyteller | 结构化章节与自然的句子级 beat | ID、Hash、证据升级、时效、验证、状态、发布 |
| 确定性 Receiver | Schema、ID 子集、字段所有权、语言、证据/访问规则、时间规则、Hash、修复预算 | 语义发明或静默修正 |
| 独立 Verifier | 逐 beat 事实、时间、归因、因果、辩证、不确定性和表达判定 | 覆盖草稿、分配 revision、发布 |
| 叙事仓库 | 无碰撞 revision、不可变尝试/稿件/验证/闸门回执、latest 指针 | 修改事实源日报 |
| 已验证闸门 Loader | 递归校验 typed parent、data-root、文件/语义 Hash、Beat 集合、pass Verification 与当前准入；返回 `VerifiedNarrativeBundle` | 接受原始 Script、发现 latest、force/skip/allow-stale 参数、修复或发布 |
| Story-stream 编译器 | 显式闸门准入、已验证 beat 到 scene 的确定性映射、允许媒体、署名、权利状态、fallback、manifest Hash | 接受原始稿件、扫描目录、新讲解、新事实或新分析 |
| TTS/字幕层 | 引擎和音色身份、许可、音频 Hash、实际时长、词/段时间、字幕轨 | 文本修复或新闻核验 |
| 视频渲染器 | 可复现合成与技术回执 | 内容选择、事实判断、上游状态修改 |
| Orchestration | 独立调度、preflight、状态、恢复、usage 绑定和特性门 | 复制权威 Artifact 正文或 Token 总量 |

## 有界写作 Packet

Storyteller Packet 来自一个当前不可变日报 revision 及其绑定 Index。版本 1 要求该日报 Run
为 `completed`，不能是 `completed_partial`；资格检查发生在 Packet 分配前，不改变不合格
日报本身的交付。Packet 只包含：

- 版本 1 `mode = edition_narrative`：条件允许时选择 6—10 个精选事件，且最终已验证 Claim
  对日报全部不同精选事件的覆盖率至少为 60%；
- 最终 Claim 级 Registry 引用对 `geopolitics = 1/1`、`ai_technology = 1/1` 和
  `markets = 1/1` 三个分析域实现精确覆盖；
- 最终稿至少使用一个 `cross_perspective_synthesis` 引用；只有规范
  `cross_perspective_synthesis` 字段在版本化确定性规则下缺失或为空时，才保存不可变不适用
  回执；既有但较弱的内容不能被主观判为“不重要”；
- 每个被排除的精选事件 ID，以及一个合同枚举的排除原因；
- 授权 item/event ID；
- 可见标题、描述、发布时间、访问状态和有界正文摘录；
- 授权分析中的结构化事实、因果链、假设、反证、情景、失效信号和观察信号；
- 只有在服务中心问题时才加入跨视角综合；
- 目标语言、edition、时区、`as_of`、时效规则和严格输出 Schema；
- report、index、合同、policy 和 packet Hash。

它排除全部普通 brief 正文、无关日报散文、历史模型对话、远程指令、未选择证据、Cookie、
凭据、原始宿主回执，以及所有 Python-owned 身份和状态字段。metadata-only 证据只携带实际
观察到的文本。Packet 构建器记录纳入和排除计数，使有界性可审查。
版本 1 不提供聚焦单事件或小子集模式。定义：

~~~text
featured_event_coverage =
最终已验证 claim unit 引用的不同报告精选事件数
/
绑定报告中的不同精选事件总数
~~~

分母必须非零；验收要求 `featured_event_coverage >= 0.60` 且分析域覆盖 `3/3`。Python 只从绑定
日报中的 `sections[].items[].source_refs[].item_id -> sections[].items[].event_id` 派生权威
Claim-to-Event 映射。Packet 把结果保存为由 Python 拥有并排序的
`featured_event_evidence_membership[]` Row，每行含 `item_id`、`event_id` 和
`source_ref_sha256`，并保存 `membership_sha256`；Scope Receipt 绑定该 Hash。Claim 校验、当前
事件配额与 60% 指标只能消费这份 Registry。每个证据 Item 必须恰好映射一个精选事件；零、重复
或多重匹配均失败，不能猜测。多事件 Claim 对其中每个拥有映射证据 Item 的不同事件分别计数。
Chapter `event_ids[]` 只定义授权范围，必须包含章内 Claim 映射到的所有事件，且永不增加分子。

## 结构化叙事合同

一份稿件包含一个或多个 chapter。每个 chapter 只服务一个中心问题或可证伪论点，并引用
当前精选事件和分析身份的连贯子集。相同日期、相同领域或宽泛主题不构成因果联系。

模型提交句子级 beat，而不是另一份独立长稿。Python 按顺序拼接已接受 beat 形成 transcript，
避免平行散文字段与结构化证据漂移。

拟议根字段包括：

~~~text
schema_version
script_id
script_revision
report_id
report_content_hash
report_file_sha256
bound_index_file_sha256
contract_bundle_identity
contract_bundle_sha256
narrative_contract_sha256
narrative_packet_sha256
membership_sha256
script_evidence_closure_item_ids[]
script_evidence_closure_sha256
as_of
timezone
frozen_at
language
hydrated_analysis_refs[]
chapters[]
~~~

`script_id`、`script_revision`、Hash、时间戳和状态由 Python 拥有；名为 `revision` 的通用
Script 字段不合法。chapter 包含：

~~~text
chapter_id
chapter_title
central_question
core_thesis
event_ids[]
analysis_ref_ids[]
beats[]
~~~

每个 beat 包含：

~~~text
beat_id
kind
epistemic_status
text
evidence_item_ids[]
analysis_ref_ids[]
claim_units[]
assumptions[]
counter_evidence_item_ids[]
invalidation_signals[]
~~~

Packet 拥有 Python 生成的 `analysis_reference_registry[]`。每行包含稳定 `ref_id`、
`source_kind`（`analysis` 或 `cross_perspective_synthesis`）、可选 `analysis_id`、指向所绑定
不可变日报的精确 RFC 6901 `json_pointer`，以及强制的规范 `value_sha256`。该表示能统一处理
标量、数组条目、嵌套对象成员和跨视角综合。模型只输出获准的 `analysis_ref_ids[]`；Python
解析并把完整 typed row 注入规范 Script。模型不能输出路径或 Hash。

Packet 还拥有排序后的 `featured_event_evidence_membership[]` Row，每行含 `item_id`、
`event_id` 与 `source_ref_sha256`，并且只能从
`sections[].items[].source_refs[].item_id -> sections[].items[].event_id` 派生。对排序 Row
执行规范 JSON 后得到 `membership_sha256`，由 Scope Receipt 和 Script 绑定。Validator 不得从
模型文字、标题、Chapter Scope 或其他日报 View 推断事件归属。

Chapter 级分析引用只定义授权范围；Beat/Claim 级引用才是推断的证明，且永远不能替代事实
前提的 Item 证据。每个携带事实或推断的 Beat 都包含原子 `claim_units[]`；每个 Claim Unit
包含 Python-owned `claim_id`、按已保存 Beat 文本的 Unicode Code Point 计量且包含端为
`text_span.start`、不包含端为 `text_span.end` 的精确确定性定位、
`normalized_claim_sha256`、`epistemic_status`、`claim_type`、`criticality`、
`criticality_reason`、`evidence_item_ids[]`、`analysis_ref_ids[]`、`freshness_class` 和
`freshness_evidence_item_ids[]`。
`normalized_claim_sha256` 只能由精确 Slice 按版本化归一化规则派生，不能替代 Text Span。
Python 拒绝 Span 重叠、无效 Offset、Claim Span 并集之外的承载 Claim
文本，以及不能唯一映射到授权日报精选事件的证据 Item。`claim_type` 枚举为 `entity`、
`action`、`time`、`sequence`、`number`、`quotation`、`attribution`、
`factual_premise`、`inference` 或 `other`。Python 按版本化类型规则标记确定性的 Critical
Unit；Verifier 可以把 Noncritical 升级为 Critical，但不能降级 Python-critical Unit。只有
不携带 Claim 的 Transition 可以省略 Claim Unit。证据闭合率分母是非空的
“Python-critical 与 Verifier-escalated Unit 并集”，不能从复合句猜测。

Python 从每个 Claim 的直接证据派生其时效 Class 和排序、去重的发布时间证明 ID。
`freshness_evidence_item_ids[]` 始终是同一 Claim `evidence_item_ids[]` 的子集；它不能授权
证据，并且是该 Claim 时效分类和当前事件映射的唯一输入。

规范 Script 还保存排序、去重的 `script_evidence_closure_item_ids[]` 和
`script_evidence_closure_sha256`。Python 从 Beat、Claim、Counter-evidence ID，以及经每个已注入
Analysis Reference 传递到达的证据计算并集；模型不能增删或重排闭包成员。

Transcript 通常实现以下叙事功能：

~~~text
hook -> fact -> background -> mechanism -> analysis
-> counterpoint -> scenario -> watch_signal -> closing
~~~

这是语义合同，不是要显示的方法提纲。自然转场必须让听众知道说话者何时从已确认材料进入
来源声称、推断、不确定性或情景。

## 认识状态

最小枚举如下：

| 状态 | 含义 | 必须满足的边界 |
| --- | --- | --- |
| `confirmed_fact` | 有支持的当前或历史事实 | 授权证据和适用的发布时间 |
| `reported_claim` | 来源声称，系统未独立升级为事实 | 明确归因和授权证据 |
| `background` | 解释当前事件所需的较早材料 | 使用历史措辞，不能写“刚刚”或“最新” |
| `supported_inference` | 从授权事实和分析得到的判断 | 分析引用、假设、限定语和失效信号 |
| `contested` | 存在实质冲突的证据或解释 | 在已观察证据内呈现双方 |
| `scenario` | 有条件的未来路径 | 触发条件、时间范围、可观察信号、非事实措辞 |
| `unknown` | 重要但未解决的事项 | 显式不确定，不静默补全 |
| `watch_signal` | 能更新后续判断的可观察事实 | 可检验条件和下游含义 |
| `transition` | 不携带 claim 的叙事连接 | 不得新增人物、数字、动机、时间、引语或其他事实 |

Hook 若没有证据，也遵循 transition 规则。合同禁止虚构对话、第一人称经历、内幕、心理、
秘密动机、引语、时间顺序或戏剧化确定性。

## 证据与访问边界

所有 evidence ID 都必须是当前日报授权精选事件证据的子集。讲解稿不能仅因某个普通 brief
或其他日报 revision 存在于本地就引用它。

确定性校验检查身份、子集、访问状态和字段所有权；独立 verifier 检查证据是否真正支撑措辞：

- metadata-only 只能支撑已观察标题或公开描述明确表达的内容；
- `verification_required` 仍是带归因的未决声称；
- 数字、日期、实体、动作、引语和归因必须与有界证据一致；
- 未绑定分析散文不能成为事实来源；
- supported inference 必须公开事实前提和分析引用；
- 关键失败不能被高风格评分平均掉。

## 时效边界

每份稿件都有带时区的 `as_of`、声明的 IANA `timezone` 和 `frozen_at`。“当前日期”是 `as_of`
在该时区中的日历日期，“昨日”是同一时区紧邻的前一日；两者都不能来自机器日期或来源地区。
当前新闻身份只来自该规则下有效的 `published_at`；`collected_at` 永远不能赋予当前身份。
每个 Claim Unit（而不是每个 Beat）都携带一个经 Python 校验的 `freshness_class`：

~~~text
current
background
undated
not_applicable
~~~

`current` 要求非空发布时间证明集，其中所有直接引用 Item 都具有有效今日/昨日
`published_at`，且没有未来时间。`background` 和 `undated` 要求非空直接证明集分别符合其
时间类别。Scenario 或 Watch-signal Claim 使用 `not_applicable` 和空证明集；无 Claim 的
Transition 没有 Claim Unit，也没有 Class。`pending` 和 `excluded` 是工作流处置，不是已接受
Claim 的时效分类；`unknown` 仍是认识状态。Undated 材料不能使用当前新闻措辞。同一 Beat 可
包含混合 Claim Class，但不存在能在 Claim 之间转移时效性的 Beat 级标签。

`available_current_featured_event_count` 统计 Bound Membership Registry 中在 `as_of` 及其
时区下有有效当前日期/前一日期发布时间的不同日报精选事件，且必须非零。
`current_claim_candidate_count` 统计证明校验前标为 `current` 的全部最终 Claim Unit；
`current_claim_count` 统计其中证明有效的子集，两者之比必须为 `100%`。最终已验证稿满足
`current_claim_count > 0`，并至少引用
`min(2, available_current_featured_event_count)` 个不同当前精选事件的 Current Claim。计数
和事件映射都只能使用每个 Current Claim 的非空 `freshness_evidence_item_ids[]`；每个此类 ID
自身必须有有效今日/昨日 `published_at`，且通过 Bound Membership Registry 唯一映射。来自
“其他方面仍属当前”事件的旧或无日期 Item 不能计数。Verifier 检查当前措辞确由这些精确的
当前证明 Item 支撑，从而避免零分母或借用时效证明。

Script 永久绑定 `bound_index_file_sha256`。Reader 或媒体准入前，Freshness Preflight 应用
120 分钟软 TTL，并另行记录 `recheck_index_path` 和 `recheck_index_file_sha256`。Recheck 记录精确
固定的 `item_fingerprint_policy_id` 和 `item_fingerprint_algorithm_version`。去重后的已检查 Item ID 集必须与
`script_evidence_closure_item_ids[]` 完全相等；已检查 Source ID 集必须与这些 Item 的确定性
Source 集完全相等。每个必需 Item 都必须唯一解析，每个 Old/New Fingerprint 都存在且相等，
每个必需 Source Status 都只能是允许的成功状态。Missing、Foreign、Duplicate、Ambiguous、
Rate-limited、Challenged、`verification_required`、Failed 或 `no_items` 会把 Admission 设为
`blocked`，且不能签发 Gate。任何 Fingerprint、Source Membership 或 Status 变化都要求新的
`completed` Report、新 Script 和完整 Verification。

Python 在下一配置 Edition Window 边界设置 `script_hard_expiry_at`。初始 Gate 使用
`freshness_anchor_at = verified_at`；证据未变的续期 Gate 使用
`freshness_anchor_at = rechecked_at`。每个 Gate 都计算
`freshness_deadline_at = min(freshness_anchor_at + 120 minutes, script_hard_expiry_at)`。准入是
半开区间，必须同时满足 `clock < freshness_deadline_at` 和
`clock < script_hard_expiry_at`。证据未变时只能在这些界限内写不可变 Recheck Receipt 与新
Gate Revision，且绝不能延长硬期限。若相对当前新闻措辞存在，而按 Script 时区计算的运行时
日期跨越 `as_of` 锚定的当前日期，则要求新的 `completed` Report 与 Script。过期 Gate 永不
修改或复用。

## 辩证与专业分析边界

每个中心论点必须公开：

- 支撑事实与中间因果机制；
- 至少一个访问状态为 `partial` 或 `full_text` 的授权证据 Item；
- 重要行为体、利益、能力、约束和反作用；
- 假设和证据强度；
- 最强授权反方路径，或明确说明授权 dossier 内未发现重要反证；
- 会削弱或推翻判断的条件；
- 只使用授权情景，并带触发条件、时间范围和观察项；
- 后续日报可以验证的观察信号。

授权分析中有至少两个实质不同情景时，叙事至少保留两个；只有一个时，保留该情景并由 Python
签发 `scenario_evidence_gap = only_one_authorized_scenario`；一个都没有时，Storyteller 不得
发明情景，且 Python 记录
`scenario_not_applicable_reason = no_authorized_scenario_evidence`。Metadata-only 证据可以
支持经归因的背景，但不能成为一章核心论点的唯一支持。

这不会强迫人为五五开，而是防止 Storyteller 隐藏重要反证，或用一句无法改变判断的“另一
方面”充数。专业性来自可追溯机制、与证据匹配的结论强度和可证伪性，不来自术语密度。
相关性不能静默变成因果；单个案例不能静默变成趋势；短期冲击与结构性变化必须区分。

## 验证架构

Verifier 使用独立 task/session 和角色，不继承 Storyteller 隐藏对话。其不可变 dossier 绑定：

~~~text
report_id
report_content_hash
report_file_sha256
bound_index_file_sha256
report_contract_sha256
narrative_contract_sha256
storyteller_policy_sha256
verifier_model_policy_id
verifier_output_schema_sha256
narrative_packet_sha256
script_sha256
as_of
timezone
~~~

`verifier_model_policy_id` 解析到版本化的 Served Model 白名单和必需能力：Receiver 强制的
结构化输出、足以容纳有界 Dossier 的上下文、独立 Session，以及精确 Usage 可观测性。未知
模型、白名单外 Fallback，或 Model/Prompt/Policy/Contract 变化都会阻断 G3，并要求冻结红队
套件重新通过。

版本 1 红队套件固定为恰好 32 个规范用例：事实/证据 8 个、时间/时效 8 个、认识/因果/辩证
8 个、Prompt Injection/Authority Escalation 4 个，以及恰好 4 个干净对照。Expected-defect
Registry 必须同时拥有非零的 Critical 与 Noncritical 总数，每个 Expected Defect 都进入对应
分母。两次独立运行的每一次都必须达到 Critical Recall 100%、Noncritical Recall 至少 90%，
并且干净对照恰好 4/4 通过；禁止跨次合并。扩展套件必须创建新的版本化 Policy，不能静默
改变版本 1 分母。

Dossier 只包含稿件以及判断已提交 beat 所需的最小证据和分析。每个 beat 恰好收到一个
`pass`、`repair` 或 `reject` 判定，并检查：

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

事实、时间、归因、访问、事实/分析分离、Claim Unit 完整性和合规是布尔硬门。
`claim_unit_completeness` 要求 Verifier 确认每项可独立证伪的事实或推断断言都进入 Claim
Unit。主观叙事维度不能覆盖硬失败。

Verification Artifact 还包含 `script_rubric_scores[]` 和 `chapter_rubric_scores[]`；后者对
每个 Script `chapter_id` 恰好有一个 Row，不能出现外来或重复 Row。整稿集合和每个 Chapter
集合都恰好包含每个维度一次。每个维度是 1—5 的整数，并带 Finding 与
`evidence_beat_ids[]`：

~~~text
dialectical_rigor
narrative_coherence
professional_clarity
epistemic_transparency
restraint_and_non_sensationalism
~~~

Verifier 的每项整稿和逐章分数都必须至少为 4；任何汇总或跨章平均都不能掩盖较低维度。
人工验收采用可审计的两阶段盲审协议。在创建 Reviewer 可读
材料前，Python 从操作系统 CSPRNG 取得 256-bit Nonce，并在 Reveal 前把它保留在所有 Reviewer
可读 Artifact 之外。版本化 `commitment_scheme_id` 与 `canonicalization_id` 定义
Domain-separated SHA-256 Commitment；输入包含 Nonce、
`verification_sha256`、Rubric Hash 与同时包含两组 Score Array 的规范隐藏评分 Payload。

Python 先创建不可变 `<run-id>-blind-review-dossier.json`。它只含不透明 Verification Hash 与
Commitment，不含可解析 Verification Path、内嵌 Verification Artifact、Latest Pointer、Nonce
或 Verifier 分数。Reviewer 只能收到该 Dossier，并写入不可变
`<run-id>-human-review.json`，其中含 `reviewer_id`、Dossier Hash、`review_started_at`、
`scores_locked_at`、独立选择的相同五维分数和理由。锁定后 Python 才可创建
`<run-id>-score-reveal.json`，绑定 Human Receipt 并揭示 Nonce、Verifier 分数、Verification
Path/Hash 与 `scores_revealed_at`。验收重新计算 Commitment，并要求
`review_started_at <= scores_locked_at <= scores_revealed_at`。该协议审计的是系统在锁分前隐藏了
什么，不声称知晓 Reviewer 从系统外取得的信息。人工每项也必须至少为 4；两套分数不能平均。

Verifier 只写不可变判定和有界修复指令。一个 Story Attempt 在确定性和语义拒绝之间共用
一次修复额度。确定性拒绝写入不可变 Draft/Rejection Receipt，但不分配规范 Script
revision。只有通过确定性校验的 Draft 才成为规范 `sN`。Verifier 要求修复时，系统创建新
Draft；完整确定性验收后成为规范 `sN+1`，再执行完整独立复验。第二次非 pass 进入
`rejected`。

最终 `pass` 后，Python 派生一份独立的不可变已验证闸门回执，至少包含：

~~~text
decision = pass
schema_version
data_root_identity
report_id
report_content_hash
bound_index_file_sha256
contract_bundle_identity
contract_bundle_sha256
script_id
script_revision
script_sha256
verification_sha256
verified_at
freshness_anchor_at
freshness_deadline_at
script_hard_expiry_at
verified_beat_ids[]
parents[]
~~~

`parents[]` 始终是 List；每个 Row 恰好为
`{parent_kind, path, file_sha256, semantic_hash?}`，其中 `path` 是经验证 Data Root 下的规范相对
路径。初始 Gate 恰好各含一个 `report`、`bound_index`、`contract_bundle`、`packet`、
`scope_receipt`、`script`、`verification_dossier` 与 `verification` Parent Kind。续期 Gate 在同样
八个 Parent 上恰好再加一个 `prior_gate` 和一个 `freshness_recheck`。缺失、Foreign 或 Duplicate
Kind 都失败；Loader 还要求 Contract Bundle 与活动配置身份相等。签发 Gate 时，所有 Script
Beat ID、Verification Beat ID、Pass Beat ID 与 `verified_beat_ids[]` 必须形成完全相等、无重复
集合；只验证请求子集并不充分。该回执是最小化下游准入能力，不是讲解稿副本。任何非 pass
判定、半开截止条件失败、文件损坏或 Parent/Hash/Beat 不匹配，都不能创建或复用闸门。

## 状态与恢复

叙事内容状态嵌套在日报 Run 下，但不改变或重新计算日报完成状态：

~~~text
not_requested
-> pending
-> authoring
-> draft_persisted
-> deterministic_validation
-> script_accepted
-> verification_pending
-> verifying
-> verified | repair_required | rejected | failed

repair_required -> repairing -> draft_persisted（共用一次修复）
~~~

`verified` 是一个 Script revision 的语义终态；过期不会把它改写成 stale。Admission、Reader
投影、Story-stream 和视频保留独立可重试状态：

~~~text
admission current | recheck_pending | expired | blocked
reader pending -> rendering -> ready | partial
story pending -> compiling -> ready | blocked | partial
video pending -> rendering -> completed | partial | failed
~~~

恢复时先重新校验文件身份和 Hash。匹配的已完成输入返回 `already_completed`，不调用模型。
已持久化 draft 或 verification 只有在所有身份一致时才可接管。并发 revision 只有一个 winner；
其他 writer 读取 winner 或获得明确 collision。文件损坏、Hash 不匹配、任务身份冲突或修复
预算耗尽都显式失败，不得覆盖。

每个新叙事 Artifact 都包含 `schema_version`、`artifact_id`、`artifact_kind`、
`data_root_identity`、经验证 Data Root 下的规范相对路径，以及 List 形式的 typed
`parents[]` Row `{parent_kind, path, file_sha256, semantic_hash?}`。Keyed Parent Map、绝对路径、
裸 ID 与目录发现均不合法。Artifact 自身的 `<kind>_sha256`（包括文件名中使用的 Digest）是其
版本化规范 `semantic_payload` 的 Semantic Hash；该 Payload 排除持久化 Envelope、自身 Digest、
完整文件 Bytes 与 Path。`parents[].file_sha256` 则对该 Parent 的完整持久化 Bytes 取 Hash，
Artifact 永远不嵌入自己的 `file_sha256`。因此 Contract Bundle 文件名中的
`contract-bundle-sha256` 及其身份是 Semantic Hash，而不是完整文件 Byte Hash。唯一公开 Loader
`load_verified_narrative_gate(gate_path, data_dir, clock) -> VerifiedNarrativeBundle` 会递归
重新打开并校验 Gate 的精确 Parent Closure，并要求其不可变 Contract Bundle 与活动配置身份
相等。不存在 `force`、`skip_verification`、接受原始 Script、`allow_stale` 或寻找 Latest 的
变体。Run Manifest 只在
`professional_narrative.{current_script,current_verification,current_gate}` 下保存已校验的当前
引用与 Hash。

## Artifact 权威性

以下拟议路径尚不存在，因此以代码文字表示：

| Artifact | 可变性 | 权威性 |
| --- | --- | --- |
| `narratives/contracts/<policy-id>/<contract-bundle-sha256>.json` | 不可变 | 所有 Schema、Policy 与确定性规则版本的活动 Contract Bundle 快照和身份 |
| `narratives/packets/<report-id>-aN.json` | 不可变 | 授权的有界 Storyteller 输入，以及 Analysis Reference 与精选事件 Membership Registry |
| `narratives/scope-receipts/<report-id>-aN.json` | 不可变 | 已选/排除事件覆盖、Membership Hash、3/3 分析域和综合适用性 |
| `narratives/drafts/<report-id>-aN.json` | 不可变 | 已提交模型写作尝试；尚不是规范 Script |
| `narratives/validation-receipts/<report-id>-aN.json` | 不可变 | 确定性判定、失败路径/规则与剩余修复授权 |
| `narratives/scripts/<report-id>-sN.json` | 不可变新 revision | 规范结构化口播稿 |
| `narratives/verification-dossiers/<report-id>-sN-vN.json` | 不可变 | 精确 Script 的最小 Verifier 输入与递归 Parent Closure |
| `narratives/verifications/<report-id>-sN-vN.json` | 不可变新 revision | 独立逐 Beat 判定 |
| `narratives/repair-receipts/<report-id>-sN-vN.json` | 不可变 | 语义非 pass 判定、有界修复指令与剩余修复授权 |
| `narratives/freshness-rechecks/<report-id>-sN-fN.json` | 不可变新 Revision | TTL 过期后按固定 Fingerprint Policy 对精确 Evidence Closure/Source Set 比较 |
| `narratives/verified/<report-id>-sN-gN.json` | 不可变新 Revision | 基于 Pass Verification 或成功 Unchanged Recheck 的精确 Parent 当前 Gate |
| `narratives/projections/<report-id>-sN-gN-pN.md` | 不可变配对 Revision | 绑定恰好一个 Gate 的规范可审阅叙事投影 |
| `narratives/projections/<report-id>-sN-gN-pN.html` | 不可变配对 Revision | 绑定同一 Gate 与同一语义 Payload 的安全本地投影 |
| `narratives/acceptance/<policy-id>/<run-id>.json` | 不可变 | Fixture、红队、真实运行、恢复与 Token 验收证据 |
| `narratives/acceptance/<policy-id>/<run-id>-blind-review-dossier.json` | 不可变 | 隐藏 Score/Nonce/Path、仅含不透明 Verification Hash 与 Commitment 的人工输入 |
| `narratives/acceptance/<policy-id>/<run-id>-human-review.json` | 不可变 | 绑定 Blind Dossier 并锁定的具名人工五维评分 |
| `narratives/acceptance/<policy-id>/<run-id>-score-reveal.json` | 不可变 | 锁分后的 Nonce/Score/Path Reveal 时序与 Commitment 校验 |
| `story-streams/<report-id>-sN-cN.json` | 不可变新 revision | 确定性 Scene Manifest |
| `audio/<report-id>-sN/manifest-tN.json` | 不可变新 revision | TTS、时间、字幕和音频血缘 |
| `videos/<report-id>-sN/render-N.json` | 不可变新 revision | 渲染输入、输出 Hash 和 QA |

`aN`、`sN`、`vN`、`fN`、`gN`、`pN`、`cN`、`tN` 和 Render Number 分别是写作尝试、Script、
Verification、Freshness、Gate、Projection、Compilation、TTS/Audio 与 Render 身份；Report ID 已经
包含 Report revision，不能再附加含义模糊的第二个 `rN`。可变 Run Manifest 只保存引用和
Scheduler 状态，不复制权威稿件正文或 Token 总量。Latest 指针是原子派生视图，永远不能覆盖不可变
revision，也不能选择 Reader/Media 输入。

## Story-stream 与媒体边界

Reader 投影使用唯一确定性函数
`narrative_projection_semantic_payload(bundle: VerifiedNarrativeBundle) -> dict`。每个公开 Reader
Command 只接受 `verified_gate_path`，调用
`load_verified_narrative_gate(verified_gate_path, data_dir, clock)`，并且只传入其返回 Bundle。
Reader API 不接受原始 Script、Verification 或 Gate 对象。Markdown 与 HTML Generator 在不可变
配对 `<report-id>-sN-gN-pN.md|html` Revision 中消费并嵌入同一份规范语义 JSON。验收从两种投影
提取并精确比较该 Payload；字符串包含断言不能证明语义等价。

Reader 投影和编译只接受公开 Gate Loader 返回的 `VerifiedNarrativeBundle`，不接受原始
`script_path`，不扫描目录寻找“最新”文件，也没有 Force 或 Skip 路径。Loader 递归重算全部
Parent 身份与 Hash、校验 Data Root 和活动 Contract Bundle、要求完整
Script/Verification/Gate Beat 集合完全相等，并检查当前 Gate 或 Freshness-Recheck Gate 的半开
Deadline。Story-stream 必须按原顺序恰好覆盖每个 Script Beat
一次；只有新的不可变 Cut/Script 经过独立验证后才可剪辑，调用方不能请求任意子集。

Gate Loader 只负责 G7 准入。Scene Hash、权利和 Text-card Fallback 必须等确定性编译生成
Scene Manifest 后才能检查；这些后置编译检查属于 M1，不能被挪成依赖尚不存在 Scene 的循环
前置门。

Scene Schema 使用 Discriminator：

~~~text
media_asset:
  scene_type = media_asset
  image_sha256 required
  rights_status = owned | licensed | public_domain

text_card:
  scene_type = text_card
  image_sha256 absent
  fallback_reason required
~~~

公开可访问的媒体不自动等于获得公开视频许可。权利状态 `unknown` 或 `rejected` 时只能选择
候选不能进入公开视频，只能改选明确允许的素材或文字卡。首个媒体 MVP 只使用有许可的
静态图片、一个有许可的 TTS 音色、
来源署名和字幕；来源视频、声音克隆和权利不明音乐不在范围内。

M1 验收要求 Gate Beat 覆盖 100%、缺失/重复/外部 Beat 为 0、不安全权利媒体选中为 0、
编译器模型调用为 0、相同输入的语义 Hash 不匹配为 0。

TTS 记录引擎、版本、音色、许可、配置、用量、音频 Hash 和实际时间。字幕和 scene 时间来自
实际音频时长。视频记录 codec、分辨率、帧率、码率、字体、色彩设置、输入 Hash、输出 Hash
和技术 QA。渲染失败不影响日报和已验证稿件；视频不能缺失、重复或重排任何口播 Beat。

## Token 与调用边界

模型阶段分别计量：

~~~text
professional-narrative-storyteller
professional-narrative-repair
professional-narrative-verifier
professional-narrative-reverification
~~~

逻辑上限是一次初始 Storyteller、一次初始 Verifier、零或一次定向修复、零或一次复验。
运行时可以保存 exact、estimated、lower-bound 或 incomplete Observation，缺失用量保持
unknown，不得变零。正式验收要求每个实际执行的故事阶段都满足 `coverage = complete`、
`tokens.accounted_total.quality = exact`、具有非负整数
`tokens.accounted_total.value`、无 Open Call、无 Conflict、总量不重叠，并绑定当前日报和
稿件。四个 Phase Row 必须全部存在。未调用的 Repair/Reverification 只有在确定性 Scheduler
证据证明 Provider Call 为零时，才能写入 Value `0` 和 Exact Quality。金额不进入省 Token
门槛。

可执行的 Pipeline Total 只相加 Measurement 数值，绝不能相加 Aggregate Measurement 对象：

~~~text
story_pipeline_tokens =
phase["professional-narrative-storyteller"].tokens.accounted_total.value
+ phase["professional-narrative-verifier"].tokens.accounted_total.value
+ phase["professional-narrative-repair"].tokens.accounted_total.value
+ phase["professional-narrative-reverification"].tokens.accounted_total.value
~~~

版本 1 在运行前冻结整条故事流水线 `250_000` Accounted Token 的临时上限，但局部上限不能
绕过现有全局预算。每次 Preflight 同时满足：

~~~text
story_pipeline_tokens <= 250_000
AND global_observed_accounted_tokens
    + remaining_narrative_phase_reserve_tokens
    + downstream_required_reserve_tokens
    <= budget.max_agent_tokens
~~~

运行开始后两个上限都不得抬高；连续三期结果只能影响版本化的下一次运行前上限。

Packet 构建、校验、持久化、story-stream 编译、字幕排版、视频渲染和 QA 都不调用模型。
真实运行基线报告 Pipeline Total 和名称明确的归一化比率：

~~~text
normalized_tokens_per_chapter = story_pipeline_tokens / accepted_chapter_count
normalized_tokens_per_verified_beat = story_pipeline_tokens / verified_beat_count
normalized_tokens_per_selected_event =
    story_pipeline_tokens / distinct_selected_featured_event_count
normalized_tokens_per_1000_final_zh_characters =
    story_pipeline_tokens * 1000 / final_zh_han_character_count
normalized_tokens_per_final_spoken_minute =
    story_pipeline_tokens / (actual_audio_duration_ms / 60_000)
~~~

`final_zh_han_character_count` 只统计最终中文口播中经过 NFC 规范化的 Unicode Han-script Code
Point，排除空白、标点、Markup、Evidence Drawer 与 Metadata；实现 Manifest 必须固定 Unicode
Property 库与 Unicode 数据版本。`actual_audio_duration_ms` 是实测且为正的最终 TTS 时长。每个
分母都必须为正；零分母记为 `not_applicable`，不得记零。这些比率不是 Provider 阶段归因。

## 安全与隐私

- 外部内容始终是数据，不是指令。
- Storyteller 与 Verifier 不获得浏览器、Shell、Delegation、凭据、Cookie 或原始宿主访问，
  除非后续经过审计的设计明确要求。
- 持久化 Packet 只含有界日报证据，不含 Prompt、隐藏 Reasoning、原始 Session、工具参数或
  Secret。
- HTML 转义所有不可信文本，只接受安全本地链接或允许的来源链接。
- 生成稿不能授予媒体权利，也不能修改来源访问分类。
- Usage 账本沿用既有隐私边界，只保存白名单指标和 Hash 血缘。

## 实现影响

拟议实现预计增加聚焦的 Schema、叙事、验证、story-stream 和后续媒体模块及测试。现有报告
Schema 和当前架构在这些变更落地前仍然权威。实现阶段必须在同一已验证变更中更新顶层架构、
报告/用户合同、运行策略、Skill 步骤、打包白名单、示例和中英文记录。

## 验证地图

| 边界 | 拟议主要测试 |
| --- | --- |
| Packet 白名单、规范 Membership Registry、Script Evidence Closure、认识状态和 `as_of`/Timezone 规则 | `test_professional_narrative.py` |
| Verifier Dossier、逐 Beat 判定、修复、精确 Recheck Closure、半开过期/Hash 门 | `test_narrative_verification.py` |
| Contract Bundle、Gate 精确 List-form Parent、不可变 Revision、幂等、并发、恢复 | `test_architecture.py` |
| 仅 Bundle Reader 准入、配对 `pN` HTML/Markdown 语义一致与安全渲染 | `test_desktop_delivery.py` |
| Usage 绑定、Token 预算、open call 和重放 | `test_llm_usage.py`、`test_llm_budget.py` |
| Story scene、媒体 Hash、权利和确定性 fallback | `test_story_stream.py`、`test_media.py` |
| 打包和双语文档 | `test_hermes_package.py`、`test_docs.py` |

Acceptance Fixture 还覆盖：Synthesis 缺失/为空与既有但较弱的区别、OS-CSPRNG 盲评分 Nonce
隐藏与 Reveal、Commitment 重算、非活动 Contract Bundle、Gate Parent 缺失/Foreign/Duplicate、
Recheck 访问失败，以及 Reader/原始对象绕过尝试。

只有当 Schema、Python 状态与持久化、独立验证、测试、读者投影、恢复证据、Token 计量和产品
规格中的分阶段真实运行标准全部一致时，本草案才转为“已验证”。
