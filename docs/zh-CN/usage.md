# 使用说明

**状态：** 已验证 · **负责人：** 仓库维护者 · **最后验证：** 2026-10-07

完成[快速开始](../../README.md)后，用本文配置本地运行、宿主接入和报告目录。
[English](../usage.md)

## 安装

在仓库运行 `python -m pip install -e .`，然后让智能体加载根目录的 `SKILL.md`。
Python 导入包为 `signaltrail`，模块入口为 `python -m signaltrail.cli`。保留仓库目录：来源配置、
Schema 和模板也是运行输入。从仓库外启动完整安装包时，可用 `SIGNALTRAIL_SKILL_DIR`
指定包目录；旧变量 `DAILY_INTEL_SKILL_DIR` 仍兼容。

仓库仅维护根目录的一份 `src/`。发布构建在 `dist/signaltrail/` 中生成完整安装包，包含
`SKILL.md`、源码、配置、Schema、模板、参考资料和资源。从仓库或解压后的完整包根目录运行
安装脚本；同步到 Hermes 是可选宿主安装，Python 项目可独立使用。脚本排除虚拟环境和
运行数据。开发时使用 `-Editable`（Windows）或 `--editable`（macOS/Linux），
Python 安装则关联原始源码目录。

Python 发行包现在为 `signaltrail-skill`，替代旧 `daily-intelligence-skill`。
主命令统一为 `signaltrail`，新安装不再提供 `daily-intel`。已有 Shell 脚本和定时任务需改用新命令。
旧 `DAILY_INTEL_*` 环境变量和已存报告 ID 继续兼容。

Windows 可以使用系统 Edge。macOS 或 Linux 的浏览器采集需要在同一 Python 环境安装 Chromium：

```sh
python -m playwright install chromium
```

全新的 Debian 或 Ubuntu 还需运行 `python -m playwright install-deps chromium` 安装系统库，
该步骤可能需要管理员权限。Hermes 专用安装见[可选集成参考](../../references/hermes-integration.md)；
Windows 浏览器细节见[安装参考](../../references/windows-setup.md)。

## 从旧版升级

升级前先停止 SignalTrail 与 Hermes 任务。卸载旧 Python 发行包，再从新仓库安装。
无需移动已有 Hermes 数据；继续显式使用它的绝对路径，并登记为以后无参数运行时的默认根。
Windows 示例：

将下列示例中的数据与 Profile 路径替换为实际既有的绝对路径；目录名可以是
`daily-intelligence` 或 `signaltrail`。

```powershell
python -m pip uninstall daily-intelligence-skill
python -m pip install -e .
$env:SIGNALTRAIL_PROFILE_DIR = "$env:LOCALAPPDATA\hermes\browser-profiles\daily-intelligence"
signaltrail --data-dir "$env:LOCALAPPDATA\hermes\daily-intelligence" data-root adopt
signaltrail --data-dir "$env:LOCALAPPDATA\hermes\daily-intelligence" data-root status
```

macOS/Linux 示例（在仓库或完整解压包目录运行）：

```sh
python -m pip uninstall daily-intelligence-skill
python -m pip install -e .
export SIGNALTRAIL_PROFILE_DIR="$HOME/.hermes/browser-profiles/daily-intelligence"
signaltrail --data-dir "$HOME/.hermes/daily-intelligence" data-root adopt
signaltrail --data-dir "$HOME/.hermes/daily-intelligence" data-root status
```

以上命令原地保留旧数据和 Profile。`data-root adopt` 在 SignalTrail 应用目录登记所选根，
不移动或复制文件。后续继续传同一个 `--data-dir` 或设置 `SIGNALTRAIL_DATA_DIR`；
并用 `SIGNALTRAIL_PROFILE_DIR` 或 `--profile-dir` 指向旧 Profile。还需更新定时任务命令。
以上环境变量赋值只作用于当前 Shell；调度任务应保存 Profile 环境变量或在命令中传入
`--profile-dir`。保留现有根目录：跨目录移动数据根还需要历史路径映射。

## 数据目录

在子命令前传入 `--data-dir DATA_DIR`，或设置 `SIGNALTRAIL_DATA_DIR`（旧变量
`DAILY_INTEL_DATA_DIR` 仍兼容）。Windows 默认使用 `%LOCALAPPDATA%\signaltrail`；
macOS/Linux 默认使用 `${XDG_DATA_HOME:-~/.local/share}/signaltrail`。
Profile 可由 `SIGNALTRAIL_PROFILE_DIR` 或 `--profile-dir` 指定；默认位于 SignalTrail
应用目录的 `browser-profiles/signaltrail/`。完整包从仓库外启动且无法定位资源时，设置
`SIGNALTRAIL_SKILL_DIR`。

```sh
signaltrail --data-dir DATA_DIR data-root status
```

显式 `--data-dir` 直接选定根，不会自动登记。`data-root adopt` 将根登记，供以后未指定目录时使用；
登记位于 SignalTrail 应用目录，不在 Hermes home。运行清单和引用的产物必须属于同一数据根。

## 语言与来源顺序

默认报告语言是 `zh-CN`。可以向智能体要求英文，或给 `run-edition` 传入 `--language en`。
该命令只准备运行，智能体仍需按 [SKILL.md](../../SKILL.md) 完成写作。
长期默认值在 `configs/sources.yaml` 中设置：

```yaml
output:
  language: en
```

译题、摘要、分析和阅读格式采用所选语言，新闻原题保留不变。

正式报告修改 [sources.yaml](../../configs/sources.yaml)，监控发现来源修改
[discovery-sources.yaml](../../configs/discovery-sources.yaml)。正式来源使用
`report_target: 15` 和 `report_max: 15`，候选不足时按实际数量生成。
发现来源这两个值均为零，不补充正式报告配额。

`collection.item_order: source` 保留网页、榜单或 Feed 的原始顺序；`published_at` 按已抓取索引中
有效发布时间从新到旧排列，缺失和并列时间保持输入顺序。来源可用自己的 `item_order` 覆盖全局值。
两种模式均保留 `source_rank`，普通摘要不再按重要性排序。
Hugging Face Papers 使用 Trending 顺序，其中可能包含较早发表的论文。

发现目录新增 TASS、俄罗斯央行、新华社英文、外交部发言人、商务部发布会和联合国会议报道。
Anadolu、IRNA 和 WAM 在本部署能够取得有效条目前保持禁用；ReliefWeb 在取得已批准的 API appname
前只保留为文档候选。详情见[入口实测记录](research/2026-09-20-collection-improvements.md)。
来源字段 origin_scope、coverage_regions、publisher_group 分开记录机构来源、报道范围和出版组，
不代表这些材料互相独立或已完成事实核验。

Feed 长内容单独保存，列表描述仍最多 600 字符，仅被选中富化的条目加载为部分正文证据。
浏览器回退在一个持久化会话内有界并发；可选 ready_selector 指定就绪元素，显式 wait_ms 优先。
采集环节不调用模型。

从已有索引提取指定新闻正文时，使用 `extract-content` 并明确传入条目 ID。命令会在同一数据根
创建富化后的新索引修订，不会改写输入索引；后续写作使用命令返回的新路径。若来源要求交互验证，
可以打开浏览器并指定持久化 Profile：

```sh
signaltrail --data-dir DATA_DIR extract-content --index INDEX.json --item-id ITEM_ID
signaltrail --data-dir DATA_DIR extract-content --index INDEX.json --item-id ITEM_ID --headed --profile-dir PROFILE_DIR
```

## Hermes 完整计量入口

针对已审计的 Hermes 0.21 接入，使用：

```sh
signaltrail-hermes run --ledger DATA_DIR --hermes-python HERMES_PYTHON --prompt-file PROMPT.txt --timeout 3600
```

将大写占位符替换为路径。`HERMES_PYTHON` 是已安装 SignalTrail 的 Hermes 虚拟环境 Python，
`PROMPT.txt` 包含本次报告请求；可用 `--provider` 和 `--model` 选择供应商和模型。

此入口在模型启动前接通计量，包含工作线程及支持的辅助调用，并支持用单独任务执行用户要求的质量评分。
封账前核对宿主计数，缺失观测保持 partial。直接 Hermes CLI 和旧 Cron 不会自动获得同等覆盖。
写作状态也会展示子批次的委派计量。Hermes 在该回调中报告的 prompt token 数包含缓存 token，
而回调没有分别提供未缓存输入和缓存桶。宿主报告总量也可能缺失，因此状态按批次总量覆盖标为
`exact`、`partial` 或 `unobservable`。这组数据只覆盖写作子任务，不包括 coordinator、辅助请求和
评估器调用；整次运行应以封存的 usage task 摘要为准。
具体限制及 Codex/OpenClaw 导入见[用量说明](../../references/llm-usage.md)。

其他 Agent 也可以处理相同写作包。没有已审计适配器时，运行仍可使用，但明确标为
`unmetered`，token 总量为 null。

质量评分默认关闭。用户明确要求时，在 `finalize-edition` 或 `complete-edition-tail` 加
`--evaluate`，请求随本轮运行保留，供后台收尾和恢复使用。普通定稿和 PDF 交付不会创建评分任务。
已有评分继续保留；未评分摘要不进入已批准的语义缓存，因此后续日报可能需要增加重新写作量。
结构和证据校验仍正常运行。

默认评估 backend 为 external。用户明确要求评分时，`--evaluate` 会生成绑定报告哈希的 dossier。
交由未参与报告写作的独立 Agent 只读 dossier，写出每个维度的 `id`、1–5 整数 `score` 和目标语言
`finding`，再执行 `edition-status` 返回的精确 `finalize-evaluation` 命令。若没有独立评估器，保留
pending。此路径不派发 Hermes，也不创建虚假的评估用量任务。只有草稿通过校验并保存后才记为完成。
有意使用 Hermes 时显式传入 `--evaluation-backend hermes`；Hermes 接入见[参考](../../references/hermes-integration.md)。

## 报告与恢复

| `DATA_DIR` 下的路径 | 内容 |
| --- | --- |
| `reports/YYYY-MM-DD/EDITION-rN.json` 和 `.md` | 版本化原始报告 |
| 同名 `.html` 和 `.pdf` | 阅读与打印副本 |
| `reports/index.html` | 本地报告历史 |
| `runs/YYYY-MM-DD/EDITION.json` | 当前阶段、产物路径、错误和后续命令 |
| `usage/` 和 `host-runs/` | 用量事件和宿主启动回执 |

工作流还会生成便携桌面 HTML，嵌入已取得并验证的图片。HTML 先返回，PDF、已请求的 Notion
交付和用户明确要求的评分随后在可重试的后台流程完成。PDF 默认软体积预算为 50 MiB，超出会记录警告。

图片保留新闻网站的原文图注及其语言；未取得图注时，报告的 `image.caption` 保存为空字符串，
不以新闻标题、alt 文本或生成描述替代。图片来源署名与图注分别保存。

HTML 阅读页采用三栏报头，展示报告日期、版次和实际记录的生成时间；白底黑字与红色来源横线
组织整期连续新闻。若已有动态幻灯片，屏幕上会在原“今日摘要”区域嵌入演示，并保留独立打开
HTML 的按钮；打印时隐藏演示并恢复摘要。没有幻灯片时继续显示普通摘要。原悬浮目录保留展开、
收起和滚动定位；搜索、日报中心、PDF 和来源状态入口仍可使用。详见[幻灯片指南](news-slides.md)。

重试前先读运行清单；尚未完成的交付执行其中的 `tail.command`。
不要手改状态 JSON，也不要在进程活动时删除锁。各阶段恢复方法见[运行手册](../../references/runbook.md)。

采集会保留登录、验证挑战、限流和失败状态。准备好操作浏览器时，用 `verify-pending`
处理待验证来源。无人值守运行不得传入 `--open-verification`。

Notion 为可选项，需要显式 `--publish` 和[配置凭据](../../references/notion-setup.md)。
远程交付失败时，本地报告仍然可用。
