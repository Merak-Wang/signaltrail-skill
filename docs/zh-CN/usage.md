# 使用说明

**状态：** 已验证 · **负责人：** 仓库维护者 · **最后验证：** 2026-11-02

本文说明安装后的本地配置、来源与语言选择，以及报告查看和恢复。完整的 Agent 工作流程见 [SKILL.md](../../SKILL.md)。[English](../usage.md)

## 安装

在完整仓库或解压后的 Skill 包目录运行：

```sh
python -m pip install -e .
signaltrail --help
```

在宿主 Agent 中加载根目录 `SKILL.md`。配置、模板、Schema 和资源会在运行时读取，需保留完整目录。Python 分发包名为 `signaltrail-skill`，命令为 `signaltrail`，模块入口为 `python -m signaltrail.cli`。

两个平台的安装入口按相同的文件规则将项目同步到 Hermes Skill 目录。同步更新同名文件并保留额外文件，更新前备份自定义配置。Windows 的 `-Editable` 或 macOS/Linux 的 `--editable` 使用原始仓库。宿主设置见 [Hermes 集成](../../references/hermes-integration.md)。

Windows 可使用系统 Edge；macOS/Linux 的浏览器采集需在同一 Python 环境安装 Chromium：

```sh
python -m playwright install chromium
```

Debian/Ubuntu 可能还需执行 `python -m playwright install-deps chromium`。

## 数据目录与浏览器配置

在子命令前传入 `--data-dir`，或设置 `SIGNALTRAIL_DATA_DIR`。默认目录为 Windows 的 `%LOCALAPPDATA%\signaltrail`，macOS/Linux 的 `${XDG_DATA_HOME:-~/.local/share}/signaltrail`。用 `SIGNALTRAIL_PROFILE_DIR` 或 `--profile-dir` 指定浏览器配置目录。

```sh
signaltrail --data-dir DATA_DIR data-root status
signaltrail --data-dir DATA_DIR data-root adopt
```

`adopt` 将现有目录登记为后续默认数据根，文件保留原位。运行清单及其引用产物应属于同一数据根。若从仓库外运行时找不到资源，将 `SIGNALTRAIL_SKILL_DIR` 指向完整 Skill 目录。

<a id="从旧版升级"></a>

升级旧安装时，先停止活动任务，卸载 `daily-intelligence-skill`，再安装当前包。保留原数据与浏览器目录，继续传入其绝对路径。旧 `DAILY_INTEL_*` 环境变量和报告 ID 仍受支持。定时任务改用 `signaltrail`，并保留数据和浏览器配置。

## 日报与语言

```sh
signaltrail --timezone Asia/Shanghai run-edition --edition daily
signaltrail --timezone Asia/Shanghai run-edition --edition daily --language en
```

命令准备运行，宿主 Agent 按 Skill 完成选题和写作。日报采用所选时区中开始前 24 小时的窗口。每天固定时间运行一次，中断后恢复 `runs/DATE/daily.json`；明确使用 `--restart` 才创建新尝试。已有晨报和晚报仍可恢复。

默认输出 `zh-CN`。可直接要求 Agent 输出英文，传入 `--language en`，或在配置中设置：

```yaml
output:
  language: en
```

标题、摘要、分析、图文讲解和语音使用所选语言，原始标题与来源链接保留供查阅。
简报主标题使用目标语言，下方保留发布者原题，TL;DR 位于配图前。来源只给出日期时标注“发布日期”。
简体中文日报为繁体来源写简体主标题，下方保留发布者原题。

## 来源与正文证据

发布者列表只提供日期时，同一发布者当前 Feed 中的同篇原文可以补足精确发布时间。合并时核对发布者身份和日期相容性，转换时区后仍按本期截止时刻筛选。

[sources.yaml](../../configs/sources.yaml) 和 [discovery-sources.yaml](../../configs/discovery-sources.yaml) 中的启用来源均按现有module/category进入正式日报栏目。默认配置共 45 项，其中 43 项启用。每源从有限公开Feed/页面响应内的合格当日新闻中，同源去重后按原发时间选取最新最多15条；采集索引保留完整观察证据及来源状态。见[采集扩展](platform.md)。

`collection.item_order: source` 保留页面、榜单或 Feed 顺序；`published_at` 按有效发布时间从新到旧排序，相同或未知时间保留输入顺序。来源可以单独覆盖设置。原站排名保留在 `metadata.source_rank`；Hugging Face Papers 等榜单来源沿用发现排名语义。

来源缓存复用保留原文日期和来源排名。简报计划对当日合格条目同源规范URL去重后，按原发时间从新到旧选取每源最多15条；跨源各保引用与位置，相同原文复用写作，不再使用共享补充名额或按固定目标补位。

纯日期保留日粒度，与未知发表时间一样使用 `WATCH`。来源修订和首次发现时间分别保存。旧论文和仓库可以凭本期新上榜、重新上榜、排名上升或修订信号进入研究雷达，状态为 `WATCH`；普通刷新沿用原信号时间。

写作证据依次使用文章正文、已保存的 Feed 文本／结构块、短描述。写作包为 Feed 材料提供独立路径和部分证据状态。补证建议综合重要度、可观察缺口、已有材料以及来源和领域分散度。Trafilatura 已作为默认本地备用器，并检查正文保留情况。文本 PDF 保留页码，状态为部分证据。可显式补取指定条目的正文：

```sh
signaltrail --data-dir DATA_DIR extract-content --index INDEX.json --item-id ITEM_ID
signaltrail --data-dir DATA_DIR extract-content --index INDEX.json --item-id ITEM_ID --headed --profile-dir PROFILE_DIR
```

提取生成新的增强索引修订，后续步骤使用返回路径。采集保留登录、验证、限流和失败状态；交互验证用 `verify-pending`。来源选择与证据处理见[编辑策略](../../references/editorial-policy.md)。

整期生成使用 `enrich-edition --run RUN.json --all-slide-candidates`，程序每批处理最多 100 条，依据更新后的索引继续补齐候选，跳过已处理条目。可用 `--max-items` 指定批大小，最终回执列出末批及剩余候选数，已到截止时刻的运行保留剩余数量。

## 采集监控

```sh
signaltrail --data-dir DATA_DIR refresh-monitor
signaltrail --data-dir DATA_DIR serve --open
```

可选的本地监控展示新闻、事件聚类、来源健康和待验证项，采集与聚类无需模型调用。服务默认只读，不启动定时采集。日报按需生成，交付 HTML／PDF、幻灯片及可选视频。见[采集扩展与档案接口](platform.md)。

## 宿主用量与可选评分

本地 Codex 调度器直接读取完整作者文件。同一次调用的多个任务共用内容完全相同的指令和 Schema。通过工具读取材料的宿主按下述顺序读取分块。

整期推进程序在专用 `author-inputs/` 中生成完整输入，保留证据、顺序、写作风格和 Schema。通过工具读取的简报、分析、图文任务均提供 `input_parts_dir` 和有序 `input_parts` 文件名，每块至多 7500 个 `o200k_base` token，按序拼接 UTF-8 字节可还原完整输入。作者逐块读取，每个工具结果只放一块，读完所有材料后写作。每项任务使用没有前批历史的新上下文；完整输入文件留作程序使用和审计。

程序完成日期、证据检查、富化与输入冻结后，图文事件审阅可与简报作者并行。审阅仍覆盖每源限额内的全部合格候选，并在定稿前保存合并、排序决定；简报收录范围独立依据来源索引，不依赖图文前五十条的选题。

简报包携带日报日期与冻结采集窗口。作者结合本期新增进展、影响和时效评估重要性，旧研究保留原始发表时间与真实上榜变化，有据的重大持续影响仍可支持高分。对携带冻结结束时间的包，校验要求 `NEW` 有当天或前一天的明确发布时间，未知日期、纯日期与研究上榜信号使用 `WATCH`。推进程序统一校验提交的草稿，并返回具体修复错误。单独使用的旧包仍保留可选预检和提交命令，供手工恢复。

具备写作能力的宿主 Agent 均可处理写作包。没有审计适配器时，运行记录为 `unmetered`，用量总计为 `null`。Hermes 的审计计量通过以下入口启动：

```sh
signaltrail-hermes run --ledger DATA_DIR --hermes-python HERMES_PYTHON --prompt-file PROMPT.txt --timeout 3600
```

启动器在模型工作前开始计量，并与宿主计数核对受支持调用。`--provider` 和 `--model` 选择路由。覆盖范围和其他宿主导入见[用量说明](../../references/llm-usage.md)，安装见 [Hermes 集成](../../references/hermes-integration.md)。

独立质量评分按需开启：为 `finalize-edition` 或 `complete-edition-tail` 加上 `--evaluate`。默认外部后端返回 dossier 和提交命令，交由独立 Agent 评分；`--evaluation-backend hermes` 使用 Hermes 调度。恢复时沿用已记录的评分请求。未评分简报保留在已批准语义缓存之外。

默认分析使用一个新上下文包。`prepare-analysis --parallel` 提供分阶段路径：选题、三个领域分析、综合、组装；它可缩短写作等待，但会重复输入共享材料。按返回命令和[运行手册](../../references/runbook.md)执行。子命令前加全局 `--compact` 可缩短标准输出，保存产物仍完整。

## 产物与恢复

| `DATA_DIR` 下的路径 | 内容 |
| --- | --- |
| `reports/YYYY-MM-DD/EDITION-rN.json` 和 `.md` | 版本化日报记录 |
| 同名 `.html` 和 `.pdf` | 阅读与打印副本 |
| `reports/index.html` | 日报历史 |
| `runs/YYYY-MM-DD/EDITION.json` | 阶段、产物、错误和后续命令 |
| `usage/` 和 `host-runs/` | 用量记录与宿主启动回执 |

流程先返回 HTML，并生成内嵌可用图片的便携桌面副本。PDF、请求的 Notion 发布和评分由可重试尾任务完成。PDF 默认大小预算为 50 MiB，超出时记录警告。

日报 HTML 内嵌已渲染幻灯片并提供独立链接；视频导出后在同一区域播放。打印恢复日报摘要。每期日报都要求完成幻灯片渲染，用 `edition-status --run RUN.json --require-complete` 检查整期交付。见[幻灯片与视频](news-slides.md)。

重试前先读取运行清单，待交付工作使用其真实 `tail.command`。各阶段恢复见[运行手册](../../references/runbook.md)。Notion 发布需要显式 `--publish` 和[已配置的凭据](../../references/notion-setup.md)。

## 采集文件保留

新一轮日报采集前自动将超过七天的采集文件移入系统回收站，按文件修改时间计算。范围为 `indexes/`、`content/`、`snapshots/`、监控快照与 `media/images/` 中未被引用的原图；运行中日报仍引用的证据继续保留。日报 JSON／Markdown／HTML／PDF、图文、讲稿与视频长期保存，日报、讲稿及活跃运行记录引用的原图同样保留。图片成功移入回收站后才移除对应媒体缓存条目；回收失败时图片和缓存条目均保留。

```sh
signaltrail --data-dir DATA_DIR cleanup --days 7
signaltrail --data-dir DATA_DIR cleanup --days 7 --apply
```

默认命令只预览，`--apply` 执行回收。移入回收站失败时保留原文件，并在结果中说明原因。

## 绑定源码执行

使用绝对 Python 路径运行完整工作区中的 `scripts/run_signaltrail.py`，入口会在导入 CLI 前优先本工作区源码，避免宿主启动钩子插入旧技能副本。采集、补证和 `begin-authoring` 完成后，运行 `--advance-edition RUN.json --data-dir DATA_DIR`。程序接收已有草稿、准备分析、组装并保存日报，随后完成尾任务和已接收图文的渲染；遇到作者任务或选题判断时返回。已完成的事件审阅通过 `--slides-review REVIEW.json` 传入。

程序每次返回最多三个短任务票据，包含分块读取信息、`draft_result_path` 和 `read_max_output_tokens`。用 `--task-limit` 指定空槽数，重复 `--in-flight 批次ID或包路径` 排除运行任务。完整错误留在 `repair_errors_file`，异常问题留在 `issues_file`，由负责作者直接读取。每项任务重新建立上下文，Codex 使用 `fork_turns="none"`。作者直接读取给定分块，不打印完整大文件或自行分块；外层 `functions.exec` 与内层 `exec_command` 的输出上限均用任务值，每个结果只放一块。保存草稿后在同次工具执行中运行 `check_command`，只输出简短结果。程序在预检和接收前统一确定性的 WATCH。单独会话可用 `--advance-dispatch INPUT.json --materialize-inputs --compact-dispatch`，恢复冻结输入可用 `--prepare-input-parts FILE`。

候选审阅提取有界 lead 时跳过导航，并在精简输入中保留 `body_chars`、`evidence_chars`。这些字段说明材料量，短公告继续保留审阅资格。从索引提前生成的审阅在绑定报告文字时解析规范 URL 别名，保留原 event ID 以及合并的来源引用。

`slides review --index INDEX.json --max-news 50 --model-input --parts-dir REVIEW_INPUT_DIR` 将每源限额内的全部合格候选按相同格式分块；审阅者读完所有块后合并、排序。

图文作者阶段返回图片预取及未完成 tail/PDF 的 `background_commands`。与作者并行各启动一次，保留进程句柄，运行期间分别传 `--in-flight slides-images`、`--in-flight edition-tail`；渲染前等待全部结束，避免共同更新日报投影。`slides prefetch-images --plan PLAN.json` 将逐事件配图和计量原子写入计划旁的 `images-slides-plan-rN.json`，渲染直接复用。`--refresh` 可重抓图片；未预取时保持原有渲染采图行为。

HTTP 索引预取最多读取 `browser.http_prefetch_max_bytes` 字节的解压内容（默认 8 MiB）。截断页面保留已有候选并补采一次浏览器页面；页面诊断记录两次尝试。

写作时并行运行 `prefetch-media`，预先填充共享图片缓存。独立的
`media.prefetch_max_total_bytes` 默认允许下载 250 MiB 新图片，缓存命中不占用下载额度。
请求按域轮转，先尝试已有的最高分辨率候选，失败后再回退。最终报告仍按模型接受的重要性排序选图，
使用单独的 `media.max_total_bytes` 预算，默认 250 MiB。预取回执记录就绪图片、实际下载字节、
缓存复用、失败与预算遗漏；失败 URL 继续使用既有的 60 分钟重试间隔。同一宿主至少两次传输失败且
本轮没有成功响应时，预取暂缓该宿主剩余 URL，继续其他宿主候选；HTTP 错误仍允许尺寸回退。
