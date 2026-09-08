# LLM 用量审计与宿主接入

**状态：** 已验证运行参考
**Owner:** Repository maintainers
**Last verified:** 2026-09-08

本参考只在首次接入宿主、检查审计覆盖、补录 durable log 或扩展适配器时读取。
日常 brief 和 analysis packet 已经自包含，不需要把本文件放入写作上下文。

## 审计边界

一次前台 SignalTrail 运行只绑定一个 usage task；authoring coordinator、brief authors、
analysis author 和其他前台嵌套会话的模型调用都写入或补录到同一 task。independent
evaluator 使用 Python 在调度前创建的关联子 task；其 `parent_task_id` 指向前台 task，两个
账本分别封存。宿主必须在第一次模型调用之前创建 task，并把 task ID 传给 coordinator 与
所有 author 会话。若宿主在第一次 provider 调用后才执行 `start`，它只能计量后续调用，
不能宣称覆盖了完整任务。

计量库是确定性本地 Python，不发起网络请求或模型调用，因此运行它本身不产生
LLM token。账本位于 `DATA_DIR/usage/YYYY-MM-DD/TASK_ID/events/`，事件不可变、
可幂等重放。`parent_task_id` 只表达关系，不自动汇总子 task；完整生命周期总量必须从
非重叠 task 按血缘汇总，并同时报告各 task 的覆盖质量，不能改写任一不可变事件。

持久化 allowlist 仅包括 token/call/tool-call 计数、宿主明确报告的成本与耗时、
短 provider/model/phase/status 标签、时间以及外部 ID 的 SHA-256 关联值。禁止保存：

- prompt、system/developer 指令、对话正文、生成正文或 reasoning 内容；
- 工具名、工具参数、工具结果、命令正文和文件内容；
- API key、Cookie、Authorization、环境秘密和未经筛选的错误信息；
- 原始 session/turn/request/task ID 或完整 hook、rollout、session receipt。

`payload_hash` 只对已筛选的安全结构计算，不能用原始 receipt 生成。任务 ID、
`source_tag` 和 `phase` 也只能使用无秘密的短机器标签。

## 通用生命周期

宿主包装器应在启动 authoring coordinator 之前执行。下面以 PowerShell 为例；task ID 必须对并发
运行唯一：

```powershell
$dataDir = "C:\absolute\signaltrail-data"
$usageTask = "signaltrail-20260823-morning-a1b2c3"
$hostLabel = "hermes"       # 任意无秘密的安全短标签
$adapterName = "hermes"     # 内置名称只有 hermes、codex、openclaw
signaltrail-usage start --ledger $dataDir --agent $hostLabel --task-id $usageTask --source-tag signaltrail
$env:SIGNALTRAIL_USAGE_LEDGER = $dataDir
$env:SIGNALTRAIL_USAGE_TASK = $usageTask
$env:SIGNALTRAIL_USAGE_ADAPTER = $adapterName
$env:SIGNALTRAIL_USAGE_PHASE = "edition"
# 现在才启动宿主；coordinator 与所有 author 会话必须继承同一 task。
```

POSIX shell 使用同一顺序：

```bash
data_dir=/absolute/signaltrail-data
usage_task=signaltrail-20260823-morning-a1b2c3
host_label=hermes
adapter_name=hermes
signaltrail-usage start --ledger "$data_dir" --agent "$host_label" --task-id "$usage_task" --source-tag signaltrail
export SIGNALTRAIL_USAGE_LEDGER="$data_dir"
export SIGNALTRAIL_USAGE_TASK="$usage_task"
export SIGNALTRAIL_USAGE_ADAPTER="$adapter_name"
export SIGNALTRAIL_USAGE_PHASE=edition
# 现在才启动宿主；coordinator 与所有 author 会话必须继承同一 task。
```

`--agent` 是任务来源标签，可以使用任意安全 harness 名称；`SIGNALTRAIL_USAGE_ADAPTER`
接收已经注册的 adapter key。CLI 当前只注册 `hermes`、`codex`、`openclaw`。其他 harness 仍可用
显式 `--data-dir` 驱动完整报告流水线：如果不绑定 usage task，预算回执保持
`coverage=unmetered`，observed/projected token 为 `null`；如果需要审计，则应在 Python
中实现 `UsageAdapter.from_hook` / `from_path` 并注册固定字段白名单。不得把未知格式交给
近似 adapter，也不得把未计量运行宣称为完整覆盖。

可选关联环境变量如下。batch/角色等字段必须是安全短标签；父 Session 原值进入账本前会
Hash：

```text
SIGNALTRAIL_USAGE_BATCH
SIGNALTRAIL_USAGE_AGENT_ROLE
SIGNALTRAIL_USAGE_RUN_ATTEMPT
SIGNALTRAIL_USAGE_REPAIR_ATTEMPT
SIGNALTRAIL_USAGE_EVALUATION_ATTEMPT
SIGNALTRAIL_USAGE_PARENT_SESSION
```

brief/analysis packet 的 `usage_correlation` 给出当前工作单元的 phase、batch 和角色。能按
author session 注入环境的宿主插件应在 provider 调用前设置这些值。并发 author 不能通过修改
同一进程级环境来切换 batch；若宿主没有隔离能力，应在相应 author session 完成后对其 durable log
执行带 `--batch-id`、`--agent-role`、`--run-attempt`、`--repair-attempt`、
`--evaluation-attempt` 和 `--parent-session-id` 的显式 import。

结束时先确保宿主日志已经 flush、所有 author 会话已退出、所有补录均完成，再执行：

```text
signaltrail-usage summary --ledger DATA_DIR --task-id TASK_ID
signaltrail-usage finalize --ledger DATA_DIR --task-id TASK_ID --status completed
```

失败或取消也要先补录可获得的记录，再用安全短标签作为 `--status` 封存。finalize
之后账本拒绝新 observation；不要在仍有 author 会话或待补录文件时提前封存。

## Hermes：逐请求 hook

完整计量运行使用显式启动器（首次安装后也可用 `python -m daily_intelligence.hermes_runner`）：

```text
signaltrail-hermes run --ledger DATA_DIR --hermes-python HERMES_PYTHON --prompt-file PROMPT.txt --provider opencode-go --model deepseek-v4-flash-vision-exp --timeout 3600
```

启动器先创建唯一 task，再启动 Hermes 0.21 进程；任务与 `SIGNALTRAIL_USAGE_*` 在首个模型调用前
就已就绪。它用进程内观察器替代三个 SignalTrail shell 回调，保留其他插件及审批，并通过官方
Python 委派接口等待每波最多三个 worker（每个最多 40 轮）。主请求、委派和辅助模型的标题生成、
压缩等请求都记录开始与终态；辅助原始流或不支持的谱系明确使验收失败。没有修改全局 Hermes
源码或配置。worker goal 可使用 `[signaltrail-phase:brief-authoring]` 或
`[signaltrail-phase:analysis-authoring]` 指明阶段；未声明时仍计入所属任务并保留父子关联。

宿主退出后必须与同一批会话在 `state.db/session_model_usage` 的调用数和 token 数只读对账。
空任务、未知 token、写入故障、漏结束、冲突、缺失宿主回执或数据库不一致均封存为 `partial`。
安全回执位于 `DATA_DIR/host-runs/TASK_ID/receipt.json`；本地宿主回答和诊断在同目录保存，
不进入 `usage/`，也不应提交 Git。进程被终止时保留缺失事件，不能用累计值制造逐请求回执。

通过此入口执行 tail 时，`SIGNALTRAIL_HERMES_PYTHON` 选择 `metered-local` 评估后端：先建立
独立 evaluator task，再启动携带其环境的一次性进程；它独立封存并接受同样的数据库对账。
调度声明独占创建，收尾状态未知时不会重复派发。主任务和评估 task 的非重叠总量合计才是
生命周期成本。普通 CLI/Cron 启动仍遵循下述手工接线要求，不能自动声称完整计量。

写作子任务按 packet 的文件契约提交，带 `signaltrail-phase` 写作标记的任务不再附加工具回复
schema，避免文件已经写好后因口头回执格式触发整轮重写；Python 内容校验和有界修复仍然执行。
本进程限制每波最多三个子任务、每个最多四十轮，并等待子任务及标题请求收尾后再封账。
轮次耗尽的强制总结原本绕过常规 transport 和宿主计数；本入口单独补齐 OpenCode Go
亲和 header、请求事件和原生辅助 usage 记录。仅有数据库总量相等不足以证明未审计分支
没有调用；修复前已封账的漏记请求必须保留为外部覆盖缺口，不能倒填零 token。
本地独立评估直接接收同一不可变 dossier 的完整 JSON，输出仍由原有评估校验器检查。
v2 dossier 显式保留各 section 的精选排序证据，按栏目内 importance 降序评估，不能拼接后
要求全局重排。历史 v1 数据包和评分保持不可变；若发现误判，审计结论单独说明。

Hermes 的 `~/.hermes/config.yaml` 为三个 API observer 事件配置同一个本地命令：

```yaml
hooks:
  pre_api_request:
    - command: "signaltrail-usage hook"
      timeout: 10
  post_api_request:
    - command: "signaltrail-usage hook"
      timeout: 10
  api_request_error:
    - command: "signaltrail-usage hook"
      timeout: 10
```

Native Windows launchers must set `PYTHONUTF8=1` before starting Hermes and should use the hook
executable's absolute installed path; redirected legacy-code-page I/O can otherwise fail on
non-ASCII metadata before the observer records anything. Run `hermes hooks doctor` after approval
or an executable update. See [`windows-setup.md`](windows-setup.md) for the native path and process
environment boundary.

Hermes 将事件 JSON 写入 stdin；`hook` 只从 stdin 和 `SIGNALTRAIL_USAGE_*` 环境
变量取值，成功时 stdout 必须为空。三个事件使用同一 `api_request_id` 关联：pre
证明调用尝试已经开始，post 提供宿主实际暴露的 usage，error 保留失败调用；同一
调用的重复 hook 会幂等去重或择优汇总。pre/error 没有 usage 时保持 unknown，不能
用预估 prompt 大小充当实际 provider token。

一次性 Shell Session 的 pre/post/error 会按 API request correlation 自动形成调用生命周期；
Session 正常退出不代表每个 pre 一定有终态。若宿主取消、传输中断或漏发 post/error，
`unclosed_call_count` 必须保留，Task 只能封存为 partial，已知 Token 只能显示为下界。
不得用 Session 聚合、草稿是否生成或相邻调用的平均值填补缺失终态。

Shell hook 首次使用需要 Hermes 对每个 `(event, command)` 授权。交互式审核后运行
`hermes hooks list` 和 `hermes hooks doctor`，并在真实的一次受控调用后确认账本出现
对应 observation。非交互运行不要未经审核地全局自动接受 hook。hook 默认 fail-open；
错误不会阻止日报，但会形成覆盖缺口，最终摘要必须如实报告 unknown。长期 Gateway
或并发任务不能共用一个静态 task 环境变量；应使用能按运行映射 task 的受审插件，
否则改用隔离的一次性进程或 durable-log 补录。

Hermes 的旧兼容字段可能含原始消息或错误正文。本适配器只读取固定 usage、短标签、
耗时和关联 ID 路径，不保存这些正文。官方接口与安全边界见
[Hermes Event Hooks](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/hooks.md)
和 [Hermes Observability](https://github.com/NousResearch/hermes-agent/blob/main/docs/observability/README.md)。

## Codex、OpenClaw 与 durable log

Codex 与 OpenClaw 的初始模型调用可能发生在 authoring coordinator 有机会执行仓库命令之前，因此必须由
外层宿主先创建 task。运行结束并 flush 日志后，把 coordinator session 和每个 author session 的文件逐个导入
同一个 task：

```text
signaltrail-usage import --ledger DATA_DIR --task-id TASK_ID --adapter codex --phase edition PATH_TO_ROLLOUT.jsonl
signaltrail-usage import --ledger DATA_DIR --task-id TASK_ID --adapter openclaw --phase edition PATH_TO_OPENCLAW_AGENT.sqlite
```

Hermes 只有聚合 usage 文件而 hook 不完整时，也可使用 `--adapter hermes` 补录。
导入同一文件可幂等重放；适配器在内存中读取原日志，只把 allowlist observation 写入
账本。不要把原 rollout/session 文件复制进 `DATA_DIR/usage`，也不要扫描或导入不属于
本任务的其他会话。原日志仍可能含 prompt、response 和工具数据，继续遵循宿主自己的
权限与保留策略。

Codex 的 rollout 可能给出累计 usage snapshot；适配器按同一 session 计算非负增量，
跳过未增长的 rate-only 快照，并把 counter reset 作为新的可审计区段。当前实现有 64 MiB
JSONL 安全上限，超过上限即显式失败，不进行部分读取。

OpenClaw 当前事实源是 per-agent SQLite。适配器先检查 SQLite magic，再用 `mode=ro`、
`query_only` 和一个只读事务读取 `transcript_events`；仅接受同时满足 `user_version` 与
`schema_meta` 的已审计 per-agent schema v17。global DB、未知版本、缺列、版本冲突和损坏
事件都会 fail closed。历史 session JSONL 仍可显式导入，但不与当前 SQLite 混称同一格式。
当前公共导入接口尚无 session/time filter，因此传入共享 per-agent DB 会导入其中所有带
usage 的 transcript row；任务级精确审计应使用隔离 DB，或等待过滤器实现。一个 OpenClaw
turn 可能包含多次 tool-loop provider request；只有宿主提供显式调用数时才记录 exact，
否则调用数保持 `unobservable`，即使 token 总量可精确。

轮转、截断、未 flush 的日志以及漏掉的 parent/child 文件都会使覆盖不完整；不能用已导入
部分外推完整任务。若一个宿主同时
提供 hook 和 durable log，关联哈希会用于去重，但 exact 数值冲突仍会在 summary 中
显式列出，不能静默挑选更便宜的数字。

## 预算、修复与独立评估

`run.llm_budget.checks[]` 保存每次派发前的安全回执。门禁从绑定 usage task 的不可变事件
重建 `accounted_total`，再加版本化下游预留；brief/analysis 预留至少覆盖已测 independent evaluator
基线 2,884,621 token、288,463 contingency 和阶段比例。没有绑定 task 时工作流保持兼容，
但 `coverage=unmetered` 且 observed/projected 为 null，绝不能作为精确优化基线。已知下界
加预留超过 `budget.max_agent_tokens` 时阻断新阶段，并保留已完成 artifact。

brief 与 analysis 验证失败会写 `*-rejections/attempt-N.json`：只含 draft Hash、字段路径、
稳定 rule ID、短消息、usage task ID、预算回执和是否授权修复，不复制完整草稿。首次不同
无效提交最多授权一次修复；第二次不同无效提交是硬终态。同一无效草稿重放复用原回执。

独立评估调度先执行当前 report ID/content hash preflight。仓库内置的自动 host scheduler
当前只支持 Hermes：本地计量入口检查进程封账回执，其他入口只读对账 `hermes cron list --all`。
只有明确失败或超时才允许第二次总尝试；unknown/reconciliation failure 不会触发重复 job。
调度前创建 independent evaluator
子 usage task，并生成
`evaluations/dossiers/<report_id>-v2.json`（历史 v1 无此版本后缀）：dossier 绑定 report/index 文件 Hash 和语义 content
Hash，只携带九维评估所需验证结果、覆盖、排序、brief、精选事件、分析和相应索引证据。

未使用上述完整计量启动器时，Hermes Cron CLI 不能为独立 job 注入 task 专属 Hook 环境，因此“已创建/绑定 evaluator
task”不等于“逐请求 Hook 覆盖完成”；在宿主支持 job 级环境或插件映射前，必须把这项缺口
保留为 partial，并用带 evaluation attempt 的 durable aggregate/import 作为恢复证据。
其他 harness 可以由自己的 scheduler 只读同一 dossier、生成独立评估 JSON 并调用
`finalize-evaluation`，但当前代码没有其他自动 scheduler adapter；外部调度不得标记成
Hermes Cron，也不得声称已获得内置自动重试或逐请求用量覆盖。

## 字段语义与审计判读

- `covered_call_count` 是当前 observation 明确覆盖的模型调用数，不等于工具调用数。
- `tool_call_count` 仅在宿主提供显式计数或可判定节点时为 exact；不保存工具内容。
- `input` 与 `output` 是宿主报告的顶层 token。`cached_input` 和
  `cache_write_input` 保留 provider 的 subset/additional/unknown 关系，避免重复相加。
- `reasoning_output` 与 `tool_call_output` 永远是 `output` 的子集，不能再次加到总量。
  只有宿主单独暴露子桶时才能精确拆分；否则子桶为 unknown，但已报告的 `output`
  已经包含这些 token。若连 `output` 都未暴露，则相关总量也必须 unknown。
- `reported_total` 保留宿主总量；`accounted_total` 按已声明的包含关系计算。两者冲突
  时应调查，不能强制改成相等。
- 成本只接受宿主明确报告的金额与币种；本库不依据当前价格表反推成本。
- task `timing.wall_ms` 由 `task.started` 到 `task.finalized` 的有效 UTC 时间确定；开放
  task 保持 `unobservable`，不会用读取 summary 的当前时刻伪造结束时间。
- 每次调用的 queue、first-token、prefill、decode 与 latency wall time 只记录宿主
  实际暴露的字段，不能用 task 总耗时代替。

summary 的 `call_lifecycle` 分开记录 attempted、finished、failed、unclosed 和 orphan
finished；`usage_coverage` 分开记录有 observation、有可核算 token、无 observation、孤立
usage call 和无关联 observation。调用已开始或失败不代表 token 为零。`completed` 封存
会拒绝未闭合调用；失败/取消封存可以保留未闭合诊断。

每个 task 使用进程内 `RLock` 与 OS 文件锁覆盖开始、追加、批量导入、summary 和 finalize。
读取时复核 task/path/filename 身份、事件 ID、payload hash、字段 allowlist、规范值和 finalized
summary 的可重建性。该 Hash 链用于发现损坏或未同步篡改，不是 HMAC/数字签名；拥有完整
本地写权限的攻击者若同步重写事件和全部派生 Hash，超出当前威胁模型。

每个 measurement 带 `quality`: `exact`、`estimated` 或 `unobservable`。若任一相关
observation 不可观测，聚合 `value` 可以是 null，并同时保留已知部分
`known_value`；不得把 null、缺字段、未产生 observation 或“目前只知道一部分”渲染
成 0。只有确定没有模型调用的纯 Python monitor 才可报告其确定性零 token；不要把
hook/日志缺失当作零调用。

## 覆盖验收与扩展

封存前至少核对：task 在首个模型调用前创建；所选 adapter 要求的 hook 或 durable log
均已接入；coordinator 与所有 author 会话继承同一 task 或完成补录；Hermes 集成还必须确认
pre/post/error 三类 observer 均已注册。`conflicts` 应为空或有审计结论；调用数、token、成本
和耗时的 unknown 均被保留；没有 observation 含自由文本或原始外部 ID。输出报告应同时
给出数值、quality、来源、覆盖调用数和缺口，不能只展示一个总 token。

新增 harness 接入时实现纯解析的 `UsageAdapter.from_hook` / `from_path`，只读调用方
明确提供的本地数据，不发起网络或模型调用。新适配器必须使用固定键 allowlist、哈希
关联 ID、幂等去重键和 unknown-preserving measurement，并注册到
`DEFAULT_ADAPTERS`。同时增加脱敏、重复导入、冲突、父子会话、缺字段和发布包测试；若
事件结构扩展，先保持 schema 向后可读，再更新 CLI/reference。不得为了支持新宿主而
增加递归“搜 usage”或保存 raw receipt 的兜底逻辑。
