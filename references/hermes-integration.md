# Hermes 可选接入

**权威语言：** 中文
**负责人：** 仓库维护者
**状态：** 已验证运行参考
**最后对照代码：** 2026-10-07

SignalTrail 的核心 CLI 和写作 packet 不要求 Hermes。以下内容只适用于选择 Hermes 作为宿主、希望使用其逐请求计量或 Hermes 调度评估器的安装。

## 完整计量入口

针对已审计的 Hermes 0.21 集成，在模型工作开始前从 Hermes Python 环境启动：

```text
signaltrail-hermes run --ledger DATA_DIR --hermes-python HERMES_PYTHON --prompt-file PROMPT.txt --timeout 3600
```

`HERMES_PYTHON` 是安装了 SignalTrail 的 Hermes 虚拟环境 Python；提示文件中写明日报请求。可用 `--provider` 和 `--model` 选择模型路由。该入口接通受支持的请求 Hook、工作线程和部分辅助调用，并在退出前对账及封账。缺少的观测仍是 unknown/partial。直接运行 Hermes CLI 或旧 Cron 不具备相同覆盖。

Hermes 子任务指标只覆盖其上报的委派调用，不包括 coordinator、所有辅助请求或评估器请求。部分 Hermes 回调把缓存 token 合并进 prompt token，不能据此拆分缓存和未缓存用量；整次运行以封账后的 usage task 摘要为准。不要把 Hermes 的字段套用到其他宿主。

## Hermes 评估器

只有用户明确请求评分时才添加 `--evaluate`。普通 CLI 默认 external；若普通 CLI 要用 Hermes evaluator，显式传入 `--evaluation-backend hermes`。专用 `signaltrail-hermes` launcher 会为子进程注入 Hermes backend，因此该入口下加 `--evaluate` 即使用 Hermes evaluator，并由独立计量进程执行。通用 external 路径由未参与报告写作的独立 Agent 读取 dossier、生成评分并执行 manifest 提供的 `finalize-evaluation` 命令。

Hermes Cron 路径依赖 Hermes Gateway 与本地任务状态。若调度状态未知，不得重复提交。恢复只允许 workflow 规定的有限次数，且需先确认已有任务明确失败或过期。计量边界和恢复语义见[用量说明](llm-usage.md)。

## 安装与升级

安装脚本可将完整项目同步至 Hermes Skill 目录，以保持 Hermes 的包发现和运行习惯；这只是一个安装目标，不是普通 SignalTrail CLI 的运行依赖。普通 CLI 默认将数据和浏览器 Profile 放在 SignalTrail 应用目录，不读取 Hermes `.env`。

专用 `signaltrail-hermes` launcher 读取 `HERMES_HOME/.env`，再向 Hermes 子进程传入数据根、Profile 和 Hermes evaluation backend。必填的 `--ledger DATA_DIR` 同时指定日报数据根与计量账本目录，优先于 `SIGNALTRAIL_DATA_DIR`／旧 `DAILY_INTEL_DATA_DIR`；向子进程传入的新旧变量均使用该显式目录。沿用旧数据时，将 `--ledger` 指向现有的 `HERMES_HOME/daily-intelligence` 或 `HERMES_HOME/signaltrail` 即可，无需搬动文件。Profile 先使用显式新／旧变量，否则使用 `HERMES_HOME/browser-profiles/signaltrail`；仅当该目录不存在而旧 `daily-intelligence` Profile 存在时沿用旧目录。详情见[使用说明](../docs/zh-CN/usage.md#从旧版升级)。
