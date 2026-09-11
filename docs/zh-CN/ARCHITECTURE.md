# 架构

**状态：** 已验证 · **负责人：** 仓库维护者 · **最后验证：** 2026-09-11

本文说明 SignalTrail 的代码分工。[运行契约](../../references/system-design.md)解释数据字段
和恢复规则，[AGENTS.md](AGENTS.md)说明修改仓库时的约束。[English](../../ARCHITECTURE.md)

## 报告流程

```text
公开来源 → 索引 → 有界证据包 → 模型草稿
→ Python 编译与校验 → 版本化 JSON + Markdown → HTML
→ 可重试的 PDF、可选 Notion、独立评估
```

Python 负责身份、访问状态、修订分配、校验和持久化。模型只在指定证据范围内选择和写作。
外部内容即使出现在数据包中也仍是数据。模型草稿通过校验后才能成为报告。

监控单独运行：RSS/Atom 和静态 HTML → 规范条目 → 词汇聚类 → 快照、来源健康和 Feed 缓存。
监控不调用模型；监控失败时正式采集仍可继续。

## 代码地图

下表模块均位于 `src/daily_intelligence/`。

| 职责 | 模块 | 边界 |
| --- | --- | --- |
| 类型与 I/O | `models`、`storage`、`utils`、`runtime`、`access`、`localization`、`taxonomy` | 路径、枚举、原子写入、数据根绑定 |
| 配置 | `config` | 来源、限额和运行选项 |
| 采集 | `adapters`、`feeds`、`prefetch`、`collector`、`clustering` | 抓取、规范化、保留来源状态和顺序 |
| 采集诊断 | `collection_diagnostics` | 已配置来源覆盖、有界正文缺口建议和本地产物完整性 |
| 证据 | `content`、`content_extraction`、`content_images`、`media`、`image_policy`、`monitor` | 结构化正文块、抽取质量、含上下文的配图候选、快照和证据关联 |
| 写作 | `context`、`authoring`、`semantics`、`state` | 有界数据包、已接收批次、连续状态和缓存 |
| 报告契约 | `reporting` | 编译草稿、补齐证据、校验 Schema 及跨字段规则 |
| 报告存储 | `reports` | 保存报告和评估、渲染 Markdown、更新派生状态 |
| 实验讲解 | `narrative`、`narrative_contracts`、`narrative_store`、`narrative_verification`、`story_stream` | 不可变日报子产物、语言审核和解释图；实时新闻准入保持阻断 |
| 交付 | `local_output`、`notion`、`dashboard` | HTML/PDF、远程副本和只读监控界面 |
| 工作流 | `workflow` | 检查点、期限、恢复和评估调度 |
| 用量与预算 | `llm_usage/`、`llm_budget`、`evaluation` | 不可变用量事件、派发预留和评估数据包 |
| 宿主接入 | `hosts/`、`hermes_runner`、`usage_cli` | 计量启动、Hook 和持久日志导入 |
| 命令 | `cli`、`commands/`、`verification`、`importer` | 参数解析、配置绑定、调用领域函数 |

依赖从入口经过编排流向领域代码和公共 I/O。领域模块不得导入 `cli` 或 `commands`。
`commands/parser.py` 定义参数，注册表把命令映射到处理函数，各命令组通过类型化
`CommandContext` 调用领域代码。`daily-intel` 和 `signaltrail` 使用同一入口。

`daily_intelligence`、`DAILY_INTEL_*` 和现有报告 ID 因兼容性继续保留。
产品和新 CLI 名称为 SignalTrail。新增别名或包前请看[开发指南](development.md)。

## 状态与文件

`workflow.py` 的 `RunStatus` 定义前台状态：

```text
created → collecting → building_context → awaiting_selection
→ extracting_content → awaiting_authoring → finalizing
→ completed | completed_partial | failed
```

`completed_partial` 表示本地报告已存在，并记录了缺口。PDF、Notion 和评估拥有独立的
可重试状态，其失败不能撤回已保存的报告。

| 数据根下的文件 | 归属 |
| --- | --- |
| `indexes/`、`content/`、`reports/` | 版本化证据和报告，不覆盖已有修订 |
| `context/` | 绑定运行的写作输入与回执；数据包完整性缺口见 TD-007 |
| `runs/` | 原子更新的检查点，包含用量任务引用 |
| `usage/…/events/` | 不可变、仅含允许字段的用量事件，用量合计的事实源 |
| `evaluations/dossiers/` | 绑定报告与索引哈希的不可变输入，当前使用 `-v2.json` |
| `state/` | 派生连续状态和语义缓存 |
| HTML、PDF、Notion | 可重建或重试的投影 |

根索引 `items[]` 是规范视图，`sources[].items[]` 是同步的旧视图。
Schema 1.1–1.5 报告保持可读，新报告使用 2.0 并要求跨视角综合。
原子写入使用唯一同目录临时文件和锁，不可变创建拒绝碰撞；成对报告写入的事务缺口见 TD-010。

## 模型边界

写作包声明输出 Schema 和允许的证据。Python 拒绝额外字段及虚构身份，记录不可变拒绝回执，
最多允许一次预算批准的修复。语义缓存保存稳定译题和摘要，每轮重算重要性和状态。
报告保留三个稳定领域栏目 ID。连续状态另用判断与证据绑定的论点 ID，以及绑定具体论点的
观察项；未提及的信号保持活跃。旧身份不明确的记录保留历史，`analysis-domains.json` 提供
每栏目最新状态投影。跨措辞延续仍属于 TD-039。

用量存储只接受计数、耗时、金额、有界标签和哈希关联；不收录 prompt、回复、推理、工具参数、
原始宿主 ID 或密钥。未知观测保持 null。任务锁串行化追加与封账，封账拒绝未闭合调用。
哈希能够发现不一致的本地修改，不能防御可重写整个账本的攻击者。

`signaltrail-hermes` 在模型启动前接通计量，等待工作波次，观测辅助请求，封账前核对同会话
宿主计数。独立评估使用单独任务和本地一次性进程。直接 CLI/Cron 路径仍有已记录的覆盖缺口。
适配器格式、计量语义和兼容范围见[用量说明](../../references/llm-usage.md)。

编译器、校验器和渲染器中的超长函数仍记为[技术债](exec-plans/tech-debt-tracker.md) TD-002。
测试选择和完整检查见[开发指南](development.md)。
