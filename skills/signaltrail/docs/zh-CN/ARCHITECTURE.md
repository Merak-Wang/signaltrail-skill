# SignalTrail 架构

**目的：** 定义规范系统边界、依赖方向、状态所有权与 Artifact 权威性。
**状态：** 已验证
**负责人：** 仓库维护者
**最后验证：** 2026-08-25
**范围：** `src/daily_intelligence/` 中的规范实现

本文是领域、依赖、状态所有权和 artifact 权威性的顶层地图。详细运行策略仍位于
`references/`。英文权威版本见 [`ARCHITECTURE.md`](../../ARCHITECTURE.md)。

## 系统边界

```mermaid
flowchart LR
    S["批准的公共 RSS、Atom 和 HTML 来源"] --> C["采集与规范化"]
    C --> I["不可变候选索引"]
    I --> X["有界 Context 与写作 Packet"]
    X --> A["Brief 与跨领域研判"]
    A --> V["由 Python 编译和校验"]
    V --> R["不可变 JSON/Markdown 报告"]
    R --> H["本地 HTML"]
    R --> T["可重试 Tail：PDF、可选 Notion、评估"]
    T --> Q["派生连续性和质量记录"]
```

模型只在有界证据内选择、摘要和分析。Python 拥有身份、状态迁移、revision 分配、
证据注入、校验、持久化和发布检查点。外部内容只能作为数据，不能作为指令源。

模型宿主回执通过独立的本地用量审计边界。该边界只接受白名单内的计数、耗时、成本、
短标签和 Hash 血缘。Prompt、Response、隐藏 Reasoning、工具参数、不透明宿主 ID、凭据和
原始 Session 日志都不能进入权威用量存储。

## 设计原则

- 本地优先：即使投影或网络失败，版本化 JSON/Markdown 仍然存在。
- 确定性外壳：代码拥有状态和校验；模型输出是不可信草稿。
- 显式降级：部分访问必须可见且可恢复。
- 有界情境：采集量增加不能线性放大写作情境。
- 单向依赖：底层不依赖 CLI 参数或远程发布。
- 兼容读取：旧版嵌套来源条目继续接受并同步。
- 边缘可重试：浏览器验证、PDF、Notion 和评估不能撤销本地事实。
- 不确定性可见：无法取得的 Token、调用、耗时或成本保持 unknown；零只表示确切观测。

边界对应的决策规则见[工程原则](design-docs/core-beliefs.md)。

## 分层与所有权

| 层 | 模块 | 所有权 |
| --- | --- | --- |
| 基础 | `utils`、`storage`、`models`、`access`、`localization`、`taxonomy`、`runtime` | 类型、路径、原子 I/O、访问语义、公共工具 |
| 用量审计 | `llm_usage` | 不可变任务/调用/用量事件、宿主规范化、去重、血缘 Hash 和保留 unknown 的汇总 |
| 配置 | `config` | 来源组合、运行选项、与路径无关的配置校验 |
| 采集 | `adapters`、`feeds`、`prefetch`、`collector`、`clustering` | 获取、规范化、来源状态、零 Token 聚类 |
| 证据 | `content`、`media`、`image_policy`、`monitor` | 正文、图片、Monitor Snapshot、证据 lineage |
| 情境 | `semantics`、`state`、`context`、`authoring` | 稳定/运行相对语义拆分、连续性、有界 Packet、不可变修复 Receipt |
| 评估与预算 | `evaluation`、`llm_budget` | Hash 绑定 evaluator dossier、保留 unknown 的阶段预留与派发决策 |
| 报告 | `reporting`、`reports` | 编译、Schema/跨字段校验、不可变记录 |
| 投影 | `local_output`、`notion`、`dashboard` | HTML/PDF/Notion 和只读 Monitor 界面 |
| 编排 | `workflow` | Run 状态机、截止时间、恢复、可重试 Tail |
| 入口 | `cli`、`usage_cli`、`verification`、`importer` | 命令解析、用量 Hook/导入、显式人工验证、旧数据导入 |

预期依赖方向是：基础 → 配置 → 采集 → 证据 → 情境 → 报告 → 投影 → 编排 → 入口。
高层可以调用低层；反方向依赖必须有明确架构理由和测试。

用量审计是根植于基础层的横切本地 Sidecar。宿主 Adapter 向其供数，但不依赖报告或发布
层；编排层只记录对用量任务的引用，入口层提供本地 start、hook、import、summary 和
finalize 操作。

## 主流程

### Monitor

```text
Feed + 静态 HTML -> 访问分类 -> 规范化条目
-> 词法聚类 -> Snapshot + 来源健康 + Feed 缓存
```

Monitor 不调用模型。Monitor 刷新失败不能阻断正式采集。时间敏感测试必须注入时钟，
不能依赖真实日期。

### 日报

```text
准备 Run -> 采集 Index -> 构建有界 Context -> 富化精选证据
-> 接收独立 Brief 批次 -> 构建紧凑 Analysis Packet
-> 装配 Draft -> 编译/校验 -> 保存不可变报告 -> 交付本地 HTML
-> 重试 PDF/Notion/Evaluation Tail
```

每个 Brief 批次只能读取自己的 Packet 和其中列出的证据。Brief 与 analysis Packet 携带
接收器强制执行的 JSON Schema，约束全部嵌套字段/类型/枚举，并拒绝未声明或 Python-owned
字段。最终分析任务只读取紧凑 Dossier。校验必须达到零错误，草稿才能
成为报告 revision。

语义缓存只保存内容稳定的译题和 TL;DR。每轮根据当前索引、日期、证据可用性和历史报告标记
重算 importance/status；缓存指标解释每次复用或拒绝。三个分析域使用稳定身份
`ANALYSIS-GEOPOLITICS`、`ANALYSIS-AI_TECHNOLOGY` 和 `ANALYSIS-MARKETS`。旧活跃记录不会
删除，而是保留为 superseded 历史；其孤立观察信号会显式关闭。

brief、analysis、repair 或 evaluation 派发前，预算层读取已绑定的不可变用量摘要并预留下游
容量。被拒 brief/analysis 草稿形成带内容 Hash 的字段/规则不可变回执，最多授权一次修复。
评估 tail 先预检当前完成状态，再对账单次 Scheduler，总尝试不超过两次，并只把最小、不可变、
绑定 report/index Hash 的 dossier 交给独立 evaluator。

### LLM 用量审计

```text
启动 usage task -> 绑定到 run.llm_usage.tasks[]
-> Hermes Hook | Codex rollout JSONL | OpenClaw Agent SQLite / 旧 JSONL
-> 白名单规范化 + 血缘 Hash -> 不可变用量事件
-> 去重且保留 unknown 的汇总 -> 不可变任务封存
```

Hermes 前台 Hook 是逐请求证据的首选来源。Codex 累计 Snapshot 会按 Session 转换为非负
增量。OpenClaw 当前 per-agent SQLite 以只读方式打开，且只接受已审计 schema v17；旧 JSONL
保留为显式兼容路径。Adapter 不调用模型，也不会递归保留原始回执。
`reasoning_output` 与 `tool_call_output` 是 output 的诊断子集，不是额外总 Token；缓存包含
关系必须显式记录。宿主未提供的字段保持 `null` 且标记为 `unobservable`。

## 状态所有权

`workflow.py` 中的 `RunStatus` 是权威定义：

```text
created -> collecting -> building_context -> awaiting_selection
-> extracting_content -> awaiting_authoring -> finalizing
-> completed | completed_partial | failed
```

前台完成表示本地报告已经存在。`completed_partial` 记录来源缺失或预算耗尽，不等于失败。
Tail 状态嵌套且可独立重试：`pending -> running -> completed | partial`。

`run.llm_usage` 是运行到计量记录的权威索引。它声明
`authority: immutable_usage_events`，并把每次尝试绑定到一个或多个已验证的 usage task ID、
宿主 Adapter、阶段和本地事件目录。这些条目只是引用，不是复制的 Token 总量：
`usage/.../events/*.json` 仍是权威记录，同一 task ID 的冲突绑定会被拒绝。

来源和正文状态由 `models.py` 中的明确枚举定义。异常、HTTP 拒绝、限流或验证页都不能
推断为 `no_items`。

## Artifact 权威性

| Artifact | 可变性 | 权威性 |
| --- | --- | --- |
| `indexes/...-rN.json` | 只新增 revision | 候选/证据身份 |
| `content/.../<retrieval>.md` | 按 retrieval 追加 | 提取证据记录 |
| `context/...-rN*.json` | 绑定 Run/Session Hash | 写作输入契约 |
| `reports/...-rN.json` | 不可变 | 规范结构化报告 |
| `reports/...-rN.md` | 不可变 | 规范可审阅报告 |
| HTML/PDF | 可重建 | 阅读投影 |
| Notion | 可重试远程副本 | 永不作为事实输入 |
| `runs/...json` | 原子更新 Manifest | 工作流检查点与 usage task 绑定，不是 Token 权威记录 |
| `usage/YYYY-MM-DD/<task>/events/*.json` | 不可变事件追加 | 权威 LLM 任务/调用用量、耗时、成本、质量与 Hash 血缘 |
| `state/*.json` | 原子更新派生状态 | 可从记录重建的连续性缓存 |
| `evaluations/dossiers/<report-id>.json` | 不可变 | 最小、Hash 绑定的独立评估输入 |

原子写入使用唯一同目录临时文件和按目标路径的锁。不可变 JSON 使用原子且不可覆盖的
硬链接创建，因此并发写入者不能占用同一个 revision。在 Windows 上，同目录替换只对短暂的
访问、共享或锁冲突执行有界退避重试；其他错误与重试耗尽仍显式失败。
已封存用量汇总是这些事件的不可变派生视图。宿主明确报告零时保留精确零；缺少证据时
保持 `null`/`unobservable`，绝不按零参与求和。
逐 task 的进程锁与 OS 锁串行化追加/封存；completed 封存拒绝未闭合调用。每次读取都会
复核路径身份、确定性事件/载荷 Hash、白名单形状和封存汇总。Hash 可发现意外或不同步的
篡改，但不是抵御可重写整个本地账本攻击者的 HMAC 签名。
PDF 绑定图片会缩放到固定打印边界；投影回执暴露渲染秒数、输出字节和可配置软尺寸预算。
PDF 仍是可重试投影：超预算只告警，评估刷新会逐字节复用同 revision 文件。

## 兼容与发布副本

根级 `items[]` 是规范索引模型；`sources[].items[]` 是同步的旧版视图。Schema 1.1–1.5
继续可读；新报告使用 2.0 并要求 `cross_perspective_synthesis`。

只编辑根级 `src/`、`configs/`、`schemas/`、`templates/` 和 `references/`。已检入的
`skills/signaltrail/` 及生成的 `dist/`、`build/` 不是实现事实源。打包输出由
`scripts/build_hermes_skill.py` 根据 Git 跟踪文件白名单生成。

## 验证地图

| 边界 | 主要测试 |
| --- | --- |
| 来源配置与旧数据导入 | `test_config.py`、`test_normalize.py`、`test_importer.py` |
| Feed、Monitor、聚类 | `test_feeds.py`、`test_monitor.py`、`test_clustering.py` |
| 证据与媒体 | `test_content.py`、`test_media.py`、`test_desktop_delivery.py` |
| Context、写作、评估与预算 | `test_authoring.py`、`test_semantics.py`、`test_evaluation.py`、`test_llm_budget.py` |
| LLM 用量、宿主 Adapter 与 Run 绑定 | `test_llm_usage.py`、`test_usage_cli.py`、`test_architecture.py` |
| Schema、状态、恢复、发布 | `test_reporting.py`、`test_architecture.py`、`tests/skills/` |
| 打包与文档 | `test_hermes_package.py`、`test_docs.py` |

详细恢复和编辑策略见[文档索引](README.md)。
