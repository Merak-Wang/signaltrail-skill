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

安装脚本可选同步到 Hermes Skill 目录。同步更新同名文件并保留额外文件，更新前备份自定义配置。Windows 的 `-Editable` 或 macOS/Linux 的 `--editable` 使用原始仓库。宿主设置见 [Hermes 集成](../../references/hermes-integration.md)。

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

## 来源与正文证据

在 [sources.yaml](../../configs/sources.yaml) 配置核心日报来源，在 [discovery-sources.yaml](../../configs/discovery-sources.yaml) 配置发现源。核心来源分别设置 `report_target` 和 `report_max`；发现源目标为零，可进入由 `collection.discovery_brief_limit` 控制的共享补充池，默认 30 条。配置说明见[采集扩展](platform.md)。

`collection.item_order: source` 保留页面、榜单或 Feed 顺序；`published_at` 按有效发布时间从新到旧排序，相同或未知时间保留输入顺序。来源可以单独覆盖设置。原站排名保留在 `metadata.source_rank`；Hugging Face Papers 等榜单来源沿用发现排名语义。

核心来源缓存复用要求冻结窗口内有当前覆盖。采集后，核心来源将窗口内条目排在未知日期或历史条目前。简报编排按 canonical URL 只占一个位置，遇到重复从同一来源后续唯一文章补位，保留来源名额和原始排名。补充发现池与这些已选核心文章去重。

纯日期保留日粒度，与未知发表时间一样使用 `WATCH`。来源修订和首次发现时间分别保存。旧论文和仓库可以凭本期新上榜、重新上榜、排名上升或修订信号进入研究雷达，状态为 `WATCH`；普通刷新沿用原信号时间。

写作证据依次使用文章正文、已保存的 Feed 文本／结构块、短描述。写作包为 Feed 材料提供独立路径和部分证据状态。补证建议综合重要度、可观察缺口、已有材料以及来源和领域分散度。Trafilatura 已作为默认本地备用器，并检查正文保留情况。文本 PDF 保留页码，状态为部分证据。可显式补取指定条目的正文：

```sh
signaltrail --data-dir DATA_DIR extract-content --index INDEX.json --item-id ITEM_ID
signaltrail --data-dir DATA_DIR extract-content --index INDEX.json --item-id ITEM_ID --headed --profile-dir PROFILE_DIR
```

提取生成新的增强索引修订，后续步骤使用返回路径。采集保留登录、验证、限流和失败状态；交互验证用 `verify-pending`。来源选择与证据处理见[编辑策略](../../references/editorial-policy.md)。

## 采集监控

```sh
signaltrail --data-dir DATA_DIR refresh-monitor
signaltrail --data-dir DATA_DIR serve --open
```

可选的本地监控展示新闻、事件聚类、来源健康和待验证项，采集与聚类无需模型调用。服务默认只读，不启动定时采集。日报按需生成，交付 HTML／PDF、幻灯片及可选视频。见[采集扩展与研究接口](platform.md)。

## 宿主用量与可选评分

简报作者只需读取一次 `signaltrail --data-dir DATA_DIR brief-input --packet PACKET.json`。单行输入保留完整候选证据、顺序、写作风格、Schema 与草稿及预检命令；候选 ID 与授权逐项相同时省去重复授权列表，旧包中的独立授权继续明示。正文按已列出的证据路径按需读取。

简报包携带日报日期与冻结采集窗口。作者结合本期新增进展、影响和时效评估重要性，旧研究保留原始发表时间与真实上榜变化，有据的重大持续影响仍可支持高分。对携带冻结结束时间的包，校验要求 `NEW` 有当天或前一天的明确发布时间，未知日期、纯日期与研究上榜信号使用 `WATCH`。协作作者执行 `preflight_command` 后交回草稿，由协调者通过 `submit-authoring-batch --all` 接收；独立作者按协调者指示提交。旧包可在 `submission_command` 后加 `--check-only` 进行预检。

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
