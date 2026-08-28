# 技术债追踪器

**目的：** 以证据和明确下一步持续公开已知实现与审计差距。
**状态：** 已验证
**负责人：** 仓库维护者
**最后验证：** 2026-08-25

| ID | 优先级 | 差距 | 证据 | 下一步 |
| --- | --- | --- | --- | --- |
| TD-001 | 高 | 受 Git 跟踪的 <code>skills/signaltrail/</code> 发布快照已与根级规范源码漂移。 | 实现、references、configs 和 templates 的文件 Hash 不同；活动 Hermes 安装已单独迁移，31 个 Python 模块现与规范源码一致。 | 仅在明确发布时重建受跟踪快照；不要手改，也不要把发布重建混入普通实现工作。 |
| TD-002 | 中 | 校验和渲染集中在少数超长函数中。 | `validate_report_data`、`compile_report_data`、`render_report_markdown` 和 `report_to_blocks` 最大。 | 先补刻画测试，再按规则/渲染族拆分，不改变 Schema 或输出。 |
| TD-003 | 中 | 详细 `references/` 主要为中文，运行入口主要为英文。 | 记录有用，但语言权威性是隐式的。 | 只在触及时翻译；保持英文工程摘要，不重复运行策略。 |
| TD-004 | 低 | CLI 已统一 JSON 输出/读取，但命令分派仍然很大。 | `main()` 仍拥有许多独立命令。 | 先补命令级刻画测试，再迁移到类型化处理器。 |
| TD-005 | 中 | 零模型监控会把微博等使用专用适配器的正式来源标为 `unsupported`，虽然正式日报采集器可以正常获取。 | 2026-08-05 监控将 `weibo_hot` 记为 unsupported，但正式索引是 `success` 且有 50 条；`pboc_monetary_reports` 与 `bytedance_seed_papers` 也处于同一边界。 | 增加中性的 `collector_only` 监控能力/状态（或等价显式字段），不计入失败率，并显示为“仅日报采集”；不要因此让监控调用浏览器或专用采集器。 |
| TD-006 | 高 | 正文富化发生进程级异常时，运行可能滞留在普通入口无法恢复的 <code>extracting_content</code>。 | <code>enrich_edition</code> 在未受保护的 <code>extract_content</code> 调用前持久化该状态，而普通准备入口会原样返回现有非终态运行。 | 让富化阶段具备检查点和可重入能力，保留索引血缘，并补充状态迁移后及不可变索引创建期间的故障注入测试。 |
| TD-007 | 高 | 写作任务包可被覆盖，且未通过密码学摘要绑定到不可变 context 或写作 session。 | 任务包使用可覆盖写入；session 只计算主 context 的 Hash，提交则信任磁盘上的当前任务包。 | 不可变地创建任务包，在 context/session 中持久化逐包 Hash 和授权条目 ID，并在开始、提交和恢复阶段复核。 |
| TD-008 | 高 | 状态变化后，来源缓存健康度和写作 session 血缘可能被高估。 | 缓存条目可让正式结果成为 <code>success</code>，即使监控采集带 partial/error；写作 session 派发后仍允许富化重建 context。 | 将采集健康度与条目可用性分开记录；富化重建已绑定 context 时拒绝或显式作废写作 session。 |
| TD-009 | 中 | Context 压缩可能遗漏低于逐来源容量上限、但已被显式富化的条目。 | <code>_compact_candidates</code> 按已富化条目数量扩展前缀，而不是按最靠后的已富化位置扩展；因此只有一个排名低于25的已富化条目时仍可能被排除。 | 把显式富化证据并入有界 context，同时保持不可变 Top 选择顺序，并增加排名26以后条目的回归测试。 |
| TD-010 | 中 | 报告持久化仍缺少修订事务，不同 evaluator 尝试仍共享一个可变草稿路径。 | JSON 仍可能在 Markdown 前单独落盘。评估修订分配、恢复、当前报告门禁和投影现已共用 edition 锁，但两个 Agent 尝试仍可能在进入该锁前覆盖同一草稿。 | 增加报告修订事务和不可变逐尝试评估草稿；保留现有数字修订、陈旧报告隔离和崩溃恢复不变量。 |
| TD-011 | 低 | 采集路径遥测仍比其他写作证据粗。 | 不可变有界拒绝回执已保留 brief/analysis 尝试 Hash、字段/规则错误、usage task、修复预算与授权；分析形状/证据也在组装前检查。实时采集仍统一记为 <code>browser_or_http</code>，宿主缺少派发遥测时旧批次耗时仍可能从 session 起点计算。 | 拆分采集路径指标；宿主提供时优先用派发时间，不得编造缺失耗时。 |
| TD-012 | 中 | Monitor 快照资格与投影就绪里程碑没有由同一事实检查约束。 | 预检对未来时间、Token 用量和结构的检查比直接加载更严格；HTML 失败后仍可能无条件写入就绪里程碑。 | 共享一个 Monitor 快照校验器，并只从确认存在的工件派生就绪里程碑。 |
| TD-013 | 中 | <code>published_at</code> 只能排序 adapter 返回的有界条目。 | adapter 可能在共享排序器看到更多条目前已经截断页面/Feed，因此只能保证“已取子集内最新”，不能保证来源全量最新。 | 定义时间排序所需采集深度，暴露截断遥测，并刻画分页/窗口行为。 |
| TD-014 | 高 | 独立 <code>save-report</code> 可在没有 run 所持 brief-plan 边界时编译。 | 命令只要求 index 和草稿，不要求 context plan；<code>finalize_edition</code> 之外的调用者可能绕过精确 <code>default_item_ids</code> 约束。 | 强制要求 context/plan 工件，或把独立命令明确限制为诊断；在 CLI 边界增加越界条目拒绝测试。 |
| TD-015 | 中 | 已验证多页来源合并缺少充分行为刻画。 | 顺序、重复替换和血缘规则分散在 capture/merge 路径，现有测试未覆盖足够的多页/重试组合。 | 重构前增加页顺序、重复、部分页和重试 fixture。 |
| TD-016 | 中 | 名义 45 条写作批次只是软均衡目标。 | 完整来源分组可能形成超过 45 条的 packet，因此下游输出/Token 上限不是硬不变量。 | 持久化明确硬上限，或文档化并校验完整来源分组允许的最大超量。 |
| TD-017 | 低 | PDF 图片重采样已有预算和视觉回归，但尚未实测生产规模收益。 | Edge/ReportLab 均使用 1600×1000、质量 82 的打印投影；输出记录渲染秒数/字节并使用 50 MiB 软预算；PDF 已延后，评估刷新会复用，Poppler 栅格冒烟测试通过。尚无可比生产报告测量新首绘大小与耗时。 | 测量下一份图片密集报告，保留页面检查证据；只有可读性或尺寸预算失败时才调整打印边界。 |
| TD-019 | 中 | 叙事连续性和正文内 evidence 引用尚未完全机器约束。 | 结构化 evidence ID 可校验，但正文仍可能提到精选事件证据之外的 brief；<code>change_from_prior</code> 也可能锚定非紧邻版本。 | 提取/校验正文 item ID，并把连续性写作绑定到紧邻合格报告 ID 与 claim。 |
| TD-020 | 高 | Hermes Cron 尚不能把 evaluator 逐请求 Hook 路由到任务专属子账本。 | v2 直接隔离 evaluator 在成功、失败、repair 与 recovery 调用中都保留了 pre/post/error Hook 和 evaluation-attempt 血缘。2026-08-25 的调度 evaluator 再次没有产生任务路由的逐叶事件；必须把其精确的 27 次调用 / 1,591,283 Token Session 聚合导入 Hash-bound 子任务。已安装 Cron CLI 在首次 Provider 调用前仍没有 job 专属环境/工具 Schema。 | 增加经审计的 Hermes 插件/job 环境映射，再在调度 evaluator 中验证逐叶覆盖，不改写直接或 Cron 账本。 |
| TD-021 | 中 | Codex 与 OpenClaw 用量 Adapter 缺少从已知真实宿主版本提取的脱敏 Fixture。 | Codex 累计计数与 OpenClaw 当前 SQLite schema-v17 Parser 已有合成回归 Fixture，并在非审计布局上显式失败，但宿主格式仍可能变化。 | 从明确版本提取最小无秘密真实 Fixture，有意识地更新审计边界，并继续 fail-closed。 |
| TD-023 | 中 | 宿主未暴露时，Provider 成本与工具调用 Token 拆分仍不可取得。 | 账本会正确把这些字段记为 <code>unobservable</code>；Hermes Hook 可能提供工具调用次数，但不提供工具调用输出 Token，而 Provider 回执也经常不含实际计费成本。 | 宿主提供时保留 exact 字段；否则只能增加带版本和价目表来源、可审计的 estimate，绝不能把估算重标为 Provider 回报用量。 |
| TD-025 | 高 | 多个 workflow mutator 在取得 edition 锁前读取 run，之后可能提交旧 attempt/artifact 状态。 | begin/prepare-analysis/assemble/enrich/finalize 可能等待锁时保留 restart 前的 run 对象；<code>adopt_index_for_run</code> 还缺少同一锁边界。 | 在锁内重读并验证 run attempt 与 artifact 血缘；长操作提交时用 attempt/context Hash CAS，并增加确定性 restart 竞态测试。 |
| TD-026 | 中 | Durable host 导入范围与文件尺寸边界还不能按任务筛选。 | OpenClaw SQLite 仅接受已审计 schema v17，但当前会读取传入 per-agent DB 的全部 usage transcript；Codex JSONL 有固定 64 MiB 安全上限。 | 增加明确 agent/session/time filter，并以有界记录流式解析 Codex；宿主未给 provider-attempt 数时继续保持调用数 unknown。 |
| TD-029 | 高 | 安全的 Python-owned event ID 尚无经过验证的跨条目连续机制。 | Analysis 草稿已不能伪造 <code>event_id</code>/<code>source_refs</code>，Python 会从当前授权 item 派生身份；但新文章确实更新旧事件时，还不能安全声明该血缘。 | 提供有界 prior-event 候选与受验证的 update/supersession 字段，由 Python 复核来源血缘和状态迁移，并同时测试伪造历史拒绝与合法跨日更新。 |
| TD-030 | 高 | Hermes 委派 worker 会继承父任务的完整 Toolset。 | 已安装的 `delegate_task` 实现明确拒绝模型选择/缩窄 Toolset，并传递 `toolsets=None`。v2 验收已验证直接 one-shot brief worker 只有 `file` Toolset 和固定 Packet/输出路径，但这不能从委派子请求中移除浏览器、搜索与委派 Schema。 | 增加宿主支持的逐子任务 Toolset 选择，再通过真实委派重复窄 brief-worker A/B，并验证请求 Schema、接受率、Token、调用和耗时。 |
| TD-031 | 高 | 除一次 analysis 阶段 A/B 外，受控优化证据未通过稳定质量/生命周期门禁。 | 冻结 v2 A/B 生成两份零错误、零警告报告，并精确测得 analysis 从 584,418 降至 174,588 Token（-70.1%），但恢复后的矩阵为 31/33/33/31，低于既有地板。2026-08-25 生产报告把真实报告质量修复到 37/45、连续性 `accept`，但它更换了模型/快照、错过截止时间且保留三个未闭合调用；这是质量证据，不是受控 batch/model 或稳定生命周期结果。 | 独立执行单变量 batch-size 与阶段模型实验，并至少增加一个可比的干净生命周期。保留被拒的 v2 矩阵，不得把生产通过改名为该矩阵的验收。 |
| TD-032 | 中 | Root-like provider turn 仍是宿主/编排集中点。 | 基线 root-like Session 使用 64 次调用、3,865,416 Token。2026-08-25 初始协调 Session 使用 33 次调用、1,785,325 Token，低于暂定调用目标；但完整恢复前台尝试了 108 次调用，并保留三个未闭合生命周期。模型、实时快照与恢复路径均已变化，无法形成可比的 root-only 结论。 | 在可比 Root Session 逐叶观测中测量重复 Context、Tool Schema 与轮询类别；只有调用降到最多 51、质量不退化且无未闭合生命周期时才接受。 |
| TD-033 | 高 | 成功的 Hermes one-shot 仍可能留下只有 pre Hook、没有 post/error 终态的调用。 | v2 Control brief 记录 24 个 attempted call，但只有 22 个带可核算 Token 的终态 observation；进程退出后两个终态仍缺失，使 Task 总量只能是显式下界。Finalization 正确保持 partial，但宿主没有提供安全终态原因或用量。 | 增加宿主侧 cancel/transport 终态 Hook 或 durable request 对账源；此类 Task 必须保持 partial，绝不能填补缺失 output、cache、total、tool call 或 latency。 |

2026-08-02 审计已解决：

- 用注入时钟替代依赖真实日期的 Monitor fixture。
- 统一 JSON、Text、Bytes 原子写入，并使用无冲突临时文件名。
- 保证不可变 JSON 在并发创建时也绝不覆盖。
- 集中类型化 JSON object 读取和 CLI JSON 输出。
- 为每个维护中的 Python 定义补充语义化中文“处理/输入/输出”契约：输入说明来源和消费字段，
  输出说明对下游的意义；关键边界增加行内理由，并用 AST 门禁拒绝空洞模板措辞。

2026-08-05 重生成已解决：

- 从正式报告资格中排除 Monitor 历史保留项。
- 实时采集成功时让实时结果优先，Monitor 只能去重补尾。
- 合并重试来源时保留原来源组位置。
- 为草稿注入仅校验身份且不修改输入。
- 用 shell 无关 Python 启动器和权威报告契约绝对路径绑定评估最终化到规范源码。
- 安装规范 <code>signaltrail</code> 运行时，核对 31 个 Python 模块，并把三处旧
  <code>daily-intelligence</code> 技能复制品移入 Windows 回收站。

2026-08-23 LLM 用量审计已解决：

- 增加本地不可变用量事件层、宿主专用白名单 Adapter、保留 unknown 的汇总，以及已验证的
  <code>run.llm_usage</code> task 绑定；不保存任何原始模型内容。
- 把独立评估器调度从重复执行三次改为单次幂等执行，并用规范
  <code>signaltrail</code> skill 替代旧的 <code>daily-intelligence</code> 名称。
- 同一报告 Hash 与语义等价草稿现在会返回当前已完成修订，也能恢复中断的最新修订；
  变化结论或非当前历史会形成新的数字修订。共享 edition 锁与当前报告门禁会阻止陈旧
  evaluator 推进当前投影；今日已有 r1/r2 继续作为历史保留。
- 增加显式 phase/batch/Agent/run/repair/evaluation/parent-session 关联、血缘覆盖汇总、
  Packet 关联提示和 CLI import 参数；父 Session 原 ID 仍只保存 Hash。
- brief、analysis、repair、evaluation 前执行 observed-plus-reserved 预算检查，同时让未计量
  用量保持 null 而不是零。
- 分离缓存内容语义与运行相对 status/importance，增加逐原因缓存指标和带版本定向失效，
  并保持当前计划顺序。
- 固定分析域迁移到稳定 ID；旧记录保留为 superseded 历史，孤立 watcher 会关闭而不截断事实源。
- 增加不可变有界 brief/analysis 拒绝回执、当前报告评估预检、Scheduler 对账、最多两次
  evaluator 尝试及最小不可变 Hash-bound evaluator dossier。
- 让 brief/analysis Packet 通过接收器强制执行的输出 Schema 实现自包含，明确嵌套对象、
  类型、枚举、禁止额外字段和 Python-owned 字段边界。

英文权威版本见 [`tech-debt-tracker.md`](../../exec-plans/tech-debt-tracker.md)。
