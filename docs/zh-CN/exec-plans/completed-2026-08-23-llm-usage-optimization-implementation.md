# 2026-08-23 LLM 用量与优化实现记录

**目的：** 记录可审计用量与日报优化活动计划中已完成的仓库实现及带限定的外部证据，
同时不夸大部分完成的实验结果。
**状态：** 已验证
**负责人：** 仓库维护者
**最后验证：** 2026-08-24

## 结果

计划中确定性且可测试的仓库范围已经实现：

- 跨宿主不可变用量账本、严格 Schema、Hermes/Codex/OpenClaw Adapter、CLI、安全的
  task/run 绑定、调用生命周期校验、Hash 血缘和保留 unknown 的汇总；
- 显式 phase、batch、Agent 角色、run、repair、evaluation 与 parent-session 关联，以及
  Packet 提示、Hook 环境输入、durable import 参数和覆盖诊断；
- brief、analysis、repair 和 evaluator 前的 observed-plus-reserved Token 门禁；
- 稳定分析域身份，以及不删除历史的 supersession 与 watcher closure；
- 稳定译题/TL;DR 与运行相对 importance/status 的语义缓存拆分、逐原因指标和带版本定向失效；
- 不可变结构化拒绝回执，以及 brief/analysis 最多一次修复的硬上限；
- 模型任务包与接收器共享的自包含 brief/analysis 输出 Schema，包括嵌套类型、枚举、
  additional-property 边界和 Python-owned 字段排除；
- 当前报告 evaluator preflight、只读 Hermes Cron 对账、最多两次总尝试、parent-linked
  evaluator usage task 和不可变 report/index Hash dossier；
- 延后 PDF、同 revision 复用、打印边界图片重采样、显式耗时/尺寸回执、50 MiB 软预算和
  Poppler 页面栅格回归。

根级[测量计划](../../../plan.md)仍是 2026-08-23 两次实测运行及外部验收的权威记录。本实现
记录不声称组合运行已经取得耗时或质量成功。

## 带限定的外部验收

不可变 `projection-ab-v2` 实验固定了同一 index、干净 skeleton、嵌入式缓存决策 Snapshot、
模型/Provider、输出契约和 file-only 工具面。Brief Packet 字节减少 41.6%，analysis Packet
字节减少 79.5%。两个 analysis 臂都在首轮通过，并编译成当前校验零错误、零警告的报告。
投影 analysis 使用 5 次调用、174,588 个精确 Token；Control 使用 9 次调用、584,418 个
精确 Token，即调用减少 44.4%、Token 减少 70.1%。Provider 墙钟基本不变（+0.5%），且投影
输出 Token 增加 11.8%，因此只接受它是 analysis 阶段资源结果。

Brief 对比仍有限定：Control Task 有两个未闭合 API 生命周期，其 658,525 个已知 Token 只是
下界；投影臂 228,465 个 Token 为精确值。两份报告均通过校验。首批两个反向配对 evaluator
单元均为 31/45、连续性 `selective`；其余两格及一个全新恢复最初都在写入输出前返回
`api_request_error`。Provider 于 2026-08-24 恢复后，只追加的 `resume-2` 生命周期让
control/dossier 与 projected/full 都在首轮完成，评分均为 33/45、连续性 `accept`。完整矩阵
因此为 31/33/33/31，四格都低于既有 34/45 总分及维度地板。Control dossier 精确使用
227,083 Token，对应 full 的 1,419,766 个已知 Token；projected dossier 有 736,545 个已知
Token，而 full 为精确 489,658。方向相反的结果明确拒绝 dossier 等价、稳定节省与质量验收，
而不只是把它们保留为未知。

恢复证据独立通过：已持久化的中断评估在完成后让 preflight 与调度入口都短路，且未创建
宿主 Job；真实 Hermes Job `c71034b5b9bb` 通过只读对账从持久化 `scheduled` 修正为
`failed / host_job_error`。Runner 首次投影的对象共享缺陷从原始 Hash-bound 模型草稿恢复，
没有再次调用模型；错误投影保留而未被覆盖。

## 仍需外部验收

仓库测试不能替代 Provider 与宿主证据。以下事项继续保留在技术债追踪器：

- evaluator 逐请求 Hook 需要 Hermes job 专属环境/插件路由（TD-020）；
- 真正缩窄子任务 Tool Schema 需要 Hermes 支持逐委派 Toolset（TD-030）；
- 受控 A/B 已得到一个精确 analysis 阶段结果并完成 evaluator 矩阵，但该矩阵未通过质量
  地板；仍需独立 batch/model 实验、质量修复和多运行稳定性证据（TD-031）；
- 隔离 analysis 调用已从 9 降至 5，但 root-like provider turn 降幅仍需要 root Session
  逐叶证据（TD-032）。

这些事项不会从单元测试推断完成。

## 验证

只有仓库完整门禁通过时才接受本实现：

```powershell
python -m pytest
python -m ruff check .
python -m compileall -q src tests scripts
python scripts/check_code_comments.py
python scripts/check_docs.py
git diff --check
```

聚焦回归位于 `test_llm_usage*.py`、`test_usage_cli.py`、`test_llm_budget.py`、
`test_evaluation.py`、`test_authoring.py`、`test_semantics.py`、`test_reporting.py`、
`test_architecture.py` 和 `test_desktop_delivery.py`。

## 恢复

新增权威记录均为只追加或可原子替换的派生状态。被拒优化实验继续保留其 ledger、report 与
evaluation 实测 Artifact。回滚投影或路由必须从根级规范源码重建；不得把手改生成/安装
Snapshot 当作恢复捷径。
