# 文档

**状态：** 已验证 · **负责人：** 仓库维护者 · **最后验证：** 2026-09-08

按当前任务选择入口。英文工程记录与本目录的中文译文一起维护。[English](../README.md)

| 指南 | 内容 |
| --- | --- |
| [使用说明](usage.md) | 安装、数据路径、语言、来源、完整计量和恢复 |
| [开发指南](development.md) | 测试选择、命名、代码与文档约定 |
| [架构](ARCHITECTURE.md) | 模块归属、状态、文件和模型边界 |
| [智能体说明](AGENTS.md) | 修改本仓库的规则 |
| [路线图](roadmap.md) | 讲解、验证、音视频草案，尚未实现 |
| [技术债](exec-plans/tech-debt-tracker.md) | 已知实现缺口和退出条件 |

## 运行参考

以下是仓库维护者负责的中文权威运行文档，各自记录验证日期。
Schema 修复说明是英文历史兼容记录。按任务读取需要的那一份。

| 参考 | 用途 |
| --- | --- |
| [SKILL.md](../../SKILL.md) | 智能体执行步骤，英文运行入口 |
| [运行手册](../../references/runbook.md) | 阶段恢复和运行检查 |
| [系统契约](../../references/system-design.md) | 数据字段、状态和产物约定 |
| [编辑策略](../../references/editorial-policy.md) | 来源选择、证据、访问和排序 |
| [叙事研判](../../references/narrative-analysis.md) | 修复分析内容 |
| [报告契约](../../templates/report-contract.md)和 [Schema](../../schemas/report.schema.json) | 草稿结构和机器校验 |
| [用量说明](../../references/llm-usage.md) | 宿主适配器、计量和覆盖限制 |
| [Windows 安装](../../references/windows-setup.md) | Windows 上的 Hermes 安装 |
| [Notion 配置](../../references/notion-setup.md)和[Schema 修复](../../references/notion-schema-fix.md) | 可选远程交付 |

## 历史

已完成的运行记录解释当时的决定和测量结果，属于历史资料，不作为当前运行指令。
其原验证日期不因时间推移失效。

- [2026-08-25 晨报验收](exec-plans/completed-2026-08-25-morning-report-acceptance.md)
- [2026-08-23 用量与优化实施](exec-plans/completed-2026-08-23-llm-usage-optimization-implementation.md)
- [2026-08-05 日报重建](exec-plans/completed-2026-08-05-morning-report-regeneration.md)
- [版本历史](../../CHANGELOG.md)和[发布说明](../../RELEASE_NOTES.md)
- [示例报告](https://github.com/Merak-Wang/signaltrail-skill/blob/main/examples/README.md)：脱敏的历史输出

`skills/signaltrail/`、`build/` 和 `dist/` 是生成的发布或安装快照，不参与当前文档检查，
仅通过明确要求的重建更新。本地被忽略的审计笔记不属于公开工程记录。

当前记录使用 Verified、Draft 或 Active，已完成记录使用 Historical，机械快照使用 Generated。
维护中的文档说明目的、负责人和日期。维护约定与检查见[开发指南](development.md)。
