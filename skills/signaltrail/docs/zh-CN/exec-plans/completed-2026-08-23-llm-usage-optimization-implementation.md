# 2026-08-23 LLM 用量与优化实现记录

**目的：** 保留 2026-08-23 用量工作的已验收实现边界、优化实测证据、Artifact 血缘和
尚未完成的后续事项。
**状态：** 已验证
**负责人：** 仓库维护者
**最后验证：** 2026-08-28

## 结果

已验收的确定性能力包括：

- 与 harness 解耦的 Packet authoring 和不可变用量账本；内置 usage Adapter 为 Hermes、
  Codex、OpenClaw，其他宿主保持 `unmetered` 或增加 Python Adapter；
- 已校验的 task/run 生命周期、Hash 血缘、phase/batch/author/repair/evaluation 关联、保留
  unknown 的汇总和 observed-plus-reserved Token 门禁；
- 接收器强制执行的 brief/analysis Schema、最多一次修复回执、稳定分析身份，以及内容稳定
  文本与运行相对状态之间的语义缓存拆分；
- Hash-bound evaluator preflight 与 dossier，自动调度和对账由 Hermes Cron 集成实现；
- 延后且记录尺寸的 PDF，同 revision 复用与打印边界图片重采样。

2026-08-23 实验与 2026-08-24 evaluator 恢复是实测权威。
[进行中叙事计划](active-evidence-driven-professional-narrative.md)承接后续交付闸门。

## 带限定的外部验收

`projection-ab-v2` 固定 index、干净 skeleton、缓存决策 Snapshot、模型/Provider、输出契约
和 file-only 能力面。brief Packet 字节减少 41.6%，analysis Packet 字节减少 79.5%；两个
analysis 臂首轮通过且校验零错误、零警告。投影 analysis 使用 5 次调用、174,588 个精确
Token，Control 使用 9 次调用、584,418 个精确 Token，即调用减少 44.4%、Token 减少
70.1%。墙钟变化 +0.5%，投影输出 Token 增加 11.8%；验收结论限定为隔离 analysis 阶段
资源使用。

Control brief 有两个未闭合调用，658,525 个已知 Token 保持下界；投影 brief 为 228,465 个
精确 Token。两份报告均通过校验。恢复后的 evaluator 矩阵为 31/33/33/31，低于 34/45 总分
与维度地板。Control dossier/full 为 227,083 个精确 Token 对 1,419,766 个已知 Token；
projected dossier/full 为 736,545 个已知 Token 对 489,658 个精确 Token。交叉结果拒绝
dossier 等价、稳定端到端节省和质量验收。

已持久化的完成评估让 preflight 与调度停止，且未创建另一个 Job。Hermes Job
`c71034b5b9bb` 从 `scheduled` 对账为 `failed / host_job_error`。原始 Hash-bound 草稿在
不增加模型调用的条件下重建对象共享缺陷，并保留错误投影。

## Artifact 血缘与持久决策

血缘相对于绑定的 `DATA_DIR`：

```text
runs/... -> indexes/... -> context/...-authoring/* -> reports/... -> evaluations/dossiers/... -> evaluations/...
usage/YYYY-MM-DD/<task-id>/events/*.json -> run.llm_usage.tasks[] 与 evaluator parent_task_id
```

持久决策：

- 缺少终态的 usage 保持 `partial`，已知 Token 总量保持下界；
- 优化验收必须达到既有质量地板，并提供可比的干净生命周期；
- 任何 scheduler 动作之前，evaluator completion 都按 report ID 与 content Hash 预检；
- Hermes Job 对账保留为集成层结果，Packet 与账本合同保持 harness-neutral；
- 权威证据只追加保存，派生投影从规范事实源重建。

## 仍需外部验收

开放事项仍需要 Provider 与宿主证据，详见规范
[技术债追踪器](../../exec-plans/tech-debt-tracker.md#open-items)：

- [TD-020](../../exec-plans/tech-debt-tracker.md#open-items)：Hermes 调度 evaluator 的 Hook 路由；
- [TD-030](../../exec-plans/tech-debt-tracker.md#open-items)：Hermes 逐子任务最小权限 Toolset；
- [TD-031](../../exec-plans/tech-debt-tracker.md#open-items)：稳定的受控优化质量与生命周期证据；
- [TD-032](../../exec-plans/tech-debt-tracker.md#open-items)：可比的 root-like provider-turn 证据。

## 验证

验收使用仓库完整的测试、Lint、编译、代码注释、文档和 Diff 门禁。聚焦回归继续覆盖
LLM usage、usage CLI、预算、evaluation、authoring、semantics、reporting、architecture 与
desktop delivery 测试族。
