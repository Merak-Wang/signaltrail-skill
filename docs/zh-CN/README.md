# 文档

**状态：** 已验证 · **负责人：** 仓库维护者 · **最后验证：** 2026-11-02

按当前任务选择入口。英文工程记录与本目录的中文译文一起维护。[English](../README.md)

| 指南 | 内容 |
| --- | --- |
| [使用说明](usage.md) | 安装、数据路径、语言、来源、完整计量和恢复 |
| [采集扩展与档案接口](platform.md) | 采集监控、RSSHub/Crawl4AI、发现简报及日报与事件档案接口 |
| [开发指南](development.md) | 模块评估、命名、代码与文档约定 |
| [架构](ARCHITECTURE.md) | 模块归属、状态、文件和模型边界 |
| [智能体说明](agent-instructions.md) | 修改本仓库的规则 |
| [新闻幻灯片](news-slides.md) | 日报与独立索引、图文演示、本地视频和音色配置 |
| [路线图](roadmap.md) | 日报、图文与视频的维护范围 |
| [技术债](exec-plans/tech-debt-tracker.md) | 已知实现缺口和退出条件 |

[输出样例](https://github.com/Merak-Wang/signaltrail-skill/blob/main/examples/README.md)：当前日报、图文演示、配音视频与历史样例。

## 目录用途

| 位置 | 用途 |
| --- | --- |
| `docs/` | 使用、架构与开发等工程指南。 |
| `references/` | Skill 引用的运行策略与恢复细则。 |
| `docs/research/` | 按日期保存的研究和实验提案。 |
| `docs/exec-plans/` | 历史实施记录与当前技术债清单。 |
| `examples/` | 当前与历史日报、图文、视频样例及合成评估输入。 |
| `evals/` | 模块评估负载、质量检查与 Skill 触发案例。 |

## 历史研究

`docs/research/` 保存早期采集研究与实验方案。独立讲解和研究原型已于 2026-11-07 退场。
当前维护日报、图文幻灯片与配音视频。

## 运行参考

以下是仓库维护者负责的中文权威运行文档，各自记录验证日期。
Schema 修复说明是英文历史兼容记录。按任务读取需要的那一份。

| 参考 | 用途 |
| --- | --- |
| [SKILL.md](../../SKILL.md) | 智能体执行步骤，英文运行入口 |
| [运行手册](../../references/runbook.md) | 阶段恢复和运行检查 |
| [系统契约](../../references/system-design.md) | 数据字段、状态和产物约定 |
| [编辑策略](../../references/editorial-policy.md) | 来源选择、证据、访问和排序 |
| [新闻幻灯片参考](../../references/news-slides.md) | 批次数据包、token 估算门槛和完整渲染要求 |
| [叙事研判](../../references/narrative-analysis.md) | 修复分析内容 |
| [报告契约](../../templates/report-contract.md)和 [Schema](../../schemas/report.schema.json) | 草稿结构和机器校验 |
| [用量说明](../../references/llm-usage.md) | 宿主适配器、计量和覆盖限制 |
| [Hermes 集成](../../references/hermes-integration.md) | 可选 Hermes 计量和评估接入 |
| [Windows 安装](../../references/windows-setup.md) | Windows 上的 Hermes 安装 |
| [Notion 配置](../../references/notion-setup.md)和[Schema 修复](../../references/notion-schema-fix.md) | 可选远程交付 |

## 历史

已完成的运行记录解释当时的决定和测量结果，属于历史资料，不作为当前运行指令。
其原验证日期不因时间推移失效。

- [2026-09-12 运行成本优化](exec-plans/completed-2026-09-12-runtime-cost-optimization.md)
- [2026-09-11 报告 A 代码审阅](exec-plans/completed-2026-09-11-report-a-code-review.md)
- [2026-08-25 晨报验收](exec-plans/completed-2026-08-25-morning-report-acceptance.md)
- [2026-08-23 用量与优化实施](exec-plans/completed-2026-08-23-llm-usage-optimization-implementation.md)
- [2026-08-05 日报重建](exec-plans/completed-2026-08-05-morning-report-regeneration.md)
- [版本历史](../../CHANGELOG.md)和[发布说明](../../RELEASE_NOTES.md)
