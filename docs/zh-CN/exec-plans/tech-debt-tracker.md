# 技术债追踪器

**目的：** 通过精简的证据、影响与可测退出条件，持续记录尚未解决的实现和集成缺口。
**状态：** 已验证
**负责人：** 仓库维护者
**最后验证：** 2026-09-20

## 开放事项

| ID | 优先级 | 差距 | 证据 / 影响 | 退出条件 |
| --- | --- | --- | --- | --- |
| TD-002 | 中 | 校验与渲染仍集中在少数超长函数。 | `validate_report_data`、`compile_report_data`、`render_report_markdown` 和 `report_to_blocks` 各自混合多组规则或渲染职责，提高了变更和审阅风险。 | 刻画测试保护当前输出，各规则与渲染族由内聚的类型化 Helper 分别承担。 |
| TD-005 | 中 | 零模型 Monitor 会把部分 collector-only 正式来源标为 `unsupported`。 | [2026-08-05 运行](completed-2026-08-05-morning-report-regeneration.md)记录了微博的差异；PBOC 与 ByteDance 也受影响，失败率因此偏高。 | 状态展示 collector-only 并从失败率中排除；Monitor 刷新不调用专用采集。 |
| TD-008 | 高 | 部分采集后来源缓存健康度仍可能被高估。 | 缓存条目可能形成正式 `success`；本次已禁止派发后富化或替换索引，并在接收和恢复时验证 Session 血缘。 | 采集健康度与条目可用性分开存储，并覆盖部分页面失败与缓存命中的组合。 |
| TD-010 | 中 | 报告持久化缺少共享 Revision 事务，Evaluator 尝试仍共用可变的保存前草稿路径。 | JSON 可能先于 Markdown 落盘；并发 Evaluator 尝试可在进入 Edition 锁前替换同一草稿。 | 一个报告 Revision 事务覆盖配对工件，每次 Evaluator 尝试使用不可变草稿，并具备崩溃与碰撞覆盖。 |
| TD-011 | 低 | 采集路径遥测比写作遥测粗。 | 实时采集统一记为 `browser_or_http`；宿主省略派发时间时，旧批次耗时可能从 Session 创建时间开始，限制了耗时诊断。 | Browser 与 HTTP 路径分别计量；存在宿主派发时间时采用该时间，缺失耗时保持 unknown。 |
| TD-012 | 中 | Monitor 资格与投影就绪里程碑使用不同的事实检查。 | 直接加载会接受预检拒绝的状态，HTML 失败后也可能出现无条件就绪里程碑。 | 所有读取方共用 Monitor 快照校验器，就绪状态仅由已确认存在的工件派生。 |
| TD-013 | 中 | `published_at` 排序只覆盖 Adapter 返回的有界条目。 | Adapter 可能在共享排序前截断结果，因此新鲜度保证只适用于已取子集。 | 每个 Adapter 声明采集深度和截断状态，分页与窗口 Fixture 确定受支持的新鲜度边界。 |
| TD-014 | 高 | 独立 `save-report` 可以绕过 Run 持有的 Brief Plan。 | 其 Index 与 Draft 接口允许在 `finalize_edition` 之外编译，无法强制精确的 `default_item_ids`。 | 命令要求 Context/Plan 工件或被限制为诊断用途，CLI Fixture 会拒绝计划外条目。 |
| TD-015 | 中 | 已验证多页来源合并缺少充分行为覆盖。 | 顺序、重复替换、部分页面血缘和重试行为分布在 Capture 与 Merge 路径。 | 页顺序、重复、部分页和重试 Fixture 在重构前完成边界刻画。 |
| TD-016 | 中 | 名义上的 45 条写作批次仍是软均衡目标。 | 完整来源分组可能产生更大的 Packet，使输出和 Token 暴露缺少严格的逐包不变量。 | 持久化硬上限，或由文档与校验共同约束完整来源分组的最大超量。 |
| TD-017 | 低 | PDF 图片重采样缺少可比的生产前后测量。 | Edge 与 ReportLab 共用 1600×1000、质量 82 的打印投影、50 MiB 软预算和视觉冒烟覆盖。稳定输入下的生产可读性、首绘大小与耗时尚未对比。 | 一份图片密集报告提供可比的大小、耗时和渲染页面证据，并满足可读性与尺寸边界。 |
| TD-019 | 中 | 叙事连续性和正文 evidence 引用尚未完全机器约束。 | 结构化 evidence ID 可以校验，正文仍可能提到精选事件之外的证据，`change_from_prior` 也可能选择非紧邻报告。 | 正文 item ID 按精选事件证据校验，连续性绑定紧邻的合格报告及其 Claim。 |
| TD-020 | 高 | **Hermes 集成：** 调度 Evaluator 无法把逐请求 Hook 路由到任务专属子账本。 | 直接 Hook 可保留终态血缘；[2026-08-25 调度运行](completed-2026-08-25-morning-report-acceptance.md)没有任务路由叶子，需要导入 Session 聚合。 | 经审计的 Job 环境映射让调度 Hermes Evaluator 产生完整 pre/post/error 叶子和精确子账本。 |
| TD-021 | 中 | **Codex/OpenClaw 集成：** Usage Adapter 缺少来自明确真实宿主版本的脱敏 Fixture。 | 累计计数和 SQLite schema-v17 的合成 Fixture 覆盖已审计布局，真实样本尚未验证宿主格式变化。 | 最小无秘密 Fixture 带有明确宿主版本，并通过 fail-closed Parser 回归。 |
| TD-023 | 中 | **宿主集成：** 宿主省略 Provider 成本或工具调用 Token 拆分时，这些字段不可取得。 | 账本将省略字段记为 `unobservable`，在保持核算真实性的同时限制成本比较。 | 宿主字段按原值保留；派生值具有版本、来源并明确标为估算；不可取得的字段继续为 unobservable。 |
| TD-026 | 中 | **Codex/OpenClaw 集成：** Durable Log 导入缺少任务级范围选择。 | OpenClaw 导入会读取所提供已审计 Per-agent 数据库中的全部 Usage 行；Codex JSONL 采用固定 64 MiB 上限，且没有 Session/Time Filter。 | Agent、Session 与时间 Filter 约束两种导入；Codex 流式解析有界记录，缺失 Provider Attempt 数继续保持 unknown。 |
| TD-029 | 高 | 编译器所有的 Event ID 缺少经过验证的跨条目连续机制。 | Python 从当前授权 item 派生 ID，新文章更新旧事件时缺少安全的血缘声明。 | 有界 Prior-event 候选集与经校验的 Update/Supersession 字段支持合法延续，并拒绝伪造历史。 |
| TD-030 | 高 | **Hermes 集成：** 委派 Worker 继承父任务 Toolset。 | 当前 `delegate_task` 请求仍包含 Browser、Search 和 Delegation Schema，即使 Packet 和输出路径已经收窄。核心 Packet 校验继续约束可接受数据。 | Hermes 支持逐子任务最小权限 Toolset，委派请求 Schema 测试确认预期的窄能力集。 |
| TD-031 | 高 | 受控优化证据尚未达到稳定质量与生命周期门禁。 | v2 试验减少 70.1% Analysis Token，质量低于地板；2026-08-25 运行在输入变化后达到 37/45，并有截止时间和未闭合调用限定。已冻结的评估结论还可能把合法的栏目内排序误判为全局排序错误，分数需经过证据复核。 | 单变量 Batch-size 与阶段模型试验达到经复核的质量地板，一个可比生命周期在预算内完成且未闭合调用为 0。 |
| TD-032 | 中 | **宿主编排：** Root-like Provider Turn 仍是 Context 与 Tool Schema 集中点。 | 现有 Session 的模型、快照和恢复路径不同；观测调用总数分布在 33 至 108，无法形成因果比较。 | 可比的逐叶测量对重复 Context、Tool Schema 与轮询分类；接受结果最多 51 次调用、质量稳定且未闭合生命周期为 0。 |
| TD-033 | 高 | **Hermes 集成：** 成功的 One-shot 工作可能缺少终态 Hook 事件。 | 一次 v2 对照记录 24 次尝试和 22 个可核算 Token 的终态 Observation。缺失终态使 Task 总量成为下界；核心 Finalization 正确保留 `partial`。 | Cancel/Transport 终态或 Durable 对账源闭合每个已尝试请求；未解析字段保持 unknown，Task 保持 partial。 |
| TD-037 | 低 | 部分旧 docstring 仍使用泛化模板。 | 基础和报告模块中仍有只称输入为任意路径、输出为处理结果的说明；格式检查不能证明语义质量。 | 随所属函数修改逐步重写，说明真实来源和下游意义，保留简短中文描述。 |
| TD-038 | 高 | 讲解实验尚不支持实时新闻准入和正式验收。 | 已绑定脚本、模型审核和解释图支持快照预览；更正链取证、逐主张过期、宿主完整计量调度和读者理解测试尚缺。上下文标签检查不能强制宿主隔离。 | 可信时效适配器记录确切证据与更正链，执行逐主张及版次截止，变化事实返回上游，并通过冻结的模型/读者测试及多宿主连续三期验收。 |
| TD-039 | 中 | 跨措辞或证据变化的论点与观察项缺少经过验证的结构化延续身份。 | 状态已保留独立判断/证据身份，不再关闭未提及观察项；但改写和新证据可能产生并行记录。 | 有界旧论点引用与结构化触发条件支持经校验延续和显式结算，并覆盖歧义迁移及伪造引用测试。 |
| TD-040 | 中 | 正文抽取和图片相关性仍为确定性启发式。 | 结构质量与图注词法关联修复了局部反例；复杂版式、歧义图注、裁切版本和目标输出适配尚无语料验收。 | 冻结多语页面/图片语料测量正文污染、完整度及真实像素/裁切适配，不确定结果保留明确质量边界。 |
| TD-041 | 中 | 自动定向研究与经过标定的来源多样性仍未完成。 | 9 月 20 日已增加冻结研究范围、原始记录/同文去重、问题驱动正文检索与有范围的主张；原始来源仍依赖提供的元数据，尚无独立核对、搜索 Provider、主体清单或收益/成本标定。 | 有测量的定向检索和经过核对的原始/支持/反驳关系覆盖明确主体缺口，并满足有界成本和固定读者/质量验收。 |

9 月 20 日晚报实跑补充 TD-031/032/040 的证据：422 条简报已交付，但第一波三个任务使用了
正文提取前的旧证据包路径，18 项研判候选仅含 1 项全文和 1 项部分正文，来源列表混入了导航页
与广告。可选独立评估包约 843 KB，已观测用量超过 520 万 token（包含缓存输入，计量不完整）。
质量评分现已改为明确请求才执行；压缩已请求评分的上下文、对齐正文提取与重点研判、过滤非新闻
候选仍待解决。当前按来源顺序取 Top15 允许旧论文在榜，但仍需区分发表时间与真实更新。

## 已解决事项

2026-09-12 [成本与耗时优化](completed-2026-09-12-runtime-cost-optimization.md)完成：

- TD-006：富化按已绑定选择恢复，完整提取检查点避免索引与 Context 提交失败后的重复抓取；抓取尚未完成时仍可能重做该有界阶段。
- TD-007：新 Brief 与 Analysis 输入不可变，Context/Session 绑定逐包摘要及授权 ID，开始、提交、恢复和组装复验。旧无摘要会话仍有兼容边界。
- TD-009：前缀以外的已富化条目进入候选，排名 29 的回归保持 Top15 不变。
- TD-025：九个运行变更入口在 Edition 锁内重读并验证尝试及产物血缘；抢锁前运行变化的注入测试会拒绝旧状态覆盖。


2026-09-11 的[报告 A 审阅](completed-2026-09-11-report-a-code-review.md)修复了正文结构与
选择、响应式图片排序、领域与论点身份碰撞，以及因未提及而关闭观察项的问题。
其余能力缺口见上方开放事项。

2026-09-08 已解决：

- TD-003：文档入口及各运行参考已声明权威语言。
- TD-004：CLI 按职责拆到 `commands/`，共用类型化上下文，并测试别名、参数传递、输出、退出码和跨数据根拒绝。



完整计量 Hermes 启动器为显式本地运行提供 TD-020 与 TD-033 的绕行实现：路由评估器环境，
等待工作波次，并核对宿主数据库。历史直接 CLI/Cron 入口仍保留上述缺口。辅助原始流（包括
MoA）、未知辅助会话谱系以及未来不兼容的 Hermes API 尚不在桥接审计范围内；在 Fixture 与
对账覆盖前，必须拒绝把这些运行视为精确验收通过。

2026-08-28 文档与发布清理已解决：

- TD-001：受 Git 跟踪的 `skills/signaltrail/` 快照已从白名单规范文件重建；打包
  副本于 2026-09-20 完全移除。实现仅维护根目录的 `src/`，完整发布包在被忽略的
  `dist/signaltrail/` 中生成；打包测试验证源码、运行资源的完整性和安装同步。

2026-08-02 审计已解决：

- 时间敏感的 Monitor Fixture 使用注入时钟。
- JSON、Text 与 Byte Writer 共用防碰撞原子替换。
- 不可变 JSON 创建会拒绝并发覆盖。
- 类型化 JSON Object 读取与 CLI JSON 输出使用共享 Helper。
- 维护中的 Python 定义具有语义化中文输入/输出契约，AST 与行内理由检查覆盖已记录边界。

[2026-08-05 重生成](completed-2026-08-05-morning-report-regeneration.md)期间已解决：

- 正式报告资格排除 Monitor 历史保留项。
- 实时采集成功时排在去重 Monitor 补尾之前。
- 重试合并保留来源组原位置。
- 草稿校验在不改变输入的情况下使用仅供校验的身份。
- 评估最终化通过 Shell 无关启动器绑定规范源码与权威契约。
- 规范 SignalTrail 运行时已经核验，旧 Skill 副本已经退役。

[2026-08-23 LLM 用量审计](completed-2026-08-23-llm-usage-optimization-implementation.md)期间已解决：

- 不可变本地 Usage 事件、白名单宿主 Adapter、保留 unknown 的汇总和已验证的
  `run.llm_usage` Task 绑定省略原始模型内容。
- 独立评估调度在规范 SignalTrail Skill 身份下单次、幂等执行。
- Evaluation Save 能恢复中断的当前 Revision、保留历史 Revision，并阻止陈旧 Evaluator
  推进当前投影。
- Phase、Batch、Role、Run、Repair、Evaluation 与 Hash 化 Parent-session 血缘保持显式。
- Observed-plus-reserved 预算门禁覆盖 Brief、Analysis、Repair 与 Evaluation 阶段；未计量值
  保持 null。
- Semantic Cache 将内容稳定字段与 Run 相对状态分离，记录带版本的失效原因并保持 Plan 顺序。
- 当时的稳定 Analysis-domain ID 保留 Superseded 历史并关闭孤立 Watcher；2026-09-11 审阅
  已用独立论点身份替代按领域自动取代的机制。
- Brief/Analysis 拒绝回执、Evaluation Preflight、Scheduler 对账、有界 Evaluator 尝试和
  Hash-bound Evaluator Dossier 均不可变。
- Brief 与 Analysis Packet 自包含，并由接收器通过嵌套输出 Schema 和显式 Python-owned
  字段完成校验。

英文权威版本见 [`tech-debt-tracker.md`](../../exec-plans/tech-debt-tracker.md)。
