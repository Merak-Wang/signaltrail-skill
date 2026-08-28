# 执行计划

**状态：** 已验证
**负责人：** 仓库维护者
**最后验证：** 2026-08-28

[Token 优化与专业叙事计划](active-evidence-driven-professional-narrative.md)正在实施。按本项目“只以模型 Token 衡量
省钱”的定义，Token 成本分析与缩减目标已经验收。当前阶段设计并将实现证据驱动的专业
叙事：融合新闻讲解与辩证研判、独立逐 beat 验证，并在 story-stream 或视频之前设置显式
已验证闸门。已知后续工作也记录在[技术债追踪器](tech-debt-tracker.md)。

跨越多个模块、迁移或检查点的工作应创建计划。计划必须说明目标、约束、受影响记录、验证
命令、回滚/恢复策略和进度。新进行中计划应在本目录以 `active-` 前缀保存；只有明确编目
的根级交付物可以例外。验证完成后改名为 `completed-YYYY-MM-DD-...`。不能因为实现结束
就删除决策历史。

英文权威版本见 [`exec-plans/index.md`](../../exec-plans/index.md)。

## 进行中的计划

- [可审计 Token 优化与证据驱动专业叙事](active-evidence-driven-professional-narrative.md)
  — 保留已经接受的受控 Token 节省证据，并推进叙事、独立验证、已验证媒体闸门、
  story-stream 与视频各阶段；金额只是可选遥测，不是成本验收指标。

## 已完成计划

- [2026-08-25 Hermes 早报验收记录](completed-2026-08-25-morning-report-acceptance.md)
  — 以零校验缺陷和 37/45 独立质量接受真实 DeepSeek V4 Flash Vision Exp 报告，同时把错过
  截止时间、未闭合调用、Cron 聚合路由和剩余受控实验继续保留为明确未通过事项。
- [2026-08-23 LLM 用量与优化实现记录](completed-2026-08-23-llm-usage-optimization-implementation.md)
  — 完成仓库内确定性的计量、预算、修复、连续性、缓存、评估器与 PDF 实现；记录带限定的
  受控 A/B 和已完成但被拒的 evaluator 矩阵，并把宿主路由、质量与稳定性保留为外部缺口。
- [2026-08-05 今日日报重生成与数据流实录](completed-2026-08-05-morning-report-regeneration.md)
  — 记录 32 个来源从采集、排序、context、语义复用、写作、校验到本地投影的实际流动，
  以及 Top1–15 修复、错误版本清理和代码审阅结论。
