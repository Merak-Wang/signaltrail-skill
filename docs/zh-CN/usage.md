# 使用说明

**状态：** 已验证 · **负责人：** 仓库维护者 · **最后验证：** 2026-09-08

完成[快速开始](../../README.md)后，用本文配置本地运行、宿主接入和报告目录。
[English](../usage.md)

## 安装

在仓库运行 `python -m pip install -e .`，然后让智能体加载根目录的 `SKILL.md`。
保留仓库目录：来源配置、Schema 和模板也是运行输入。从仓库外启动时，将
`DAILY_INTEL_SKILL_DIR` 设为仓库绝对路径。

Windows 可以使用系统 Edge。macOS 或 Linux 的浏览器采集需要在同一 Python 环境安装 Chromium：

```sh
python -m playwright install chromium
```

全新的 Debian 或 Ubuntu 还需运行 `python -m playwright install-deps chromium` 安装系统库，
该步骤可能需要管理员权限。README 中的 Hermes 安装脚本会把 Skill 同步到
`skills/research/signaltrail`；Windows 细节见[安装参考](../../references/windows-setup.md)。

## 数据目录

在子命令前传入 `--data-dir DATA_DIR`，或设置 `DAILY_INTEL_DATA_DIR`。升级时沿用现有目录。
Hermes 在 Windows 默认使用 `%LOCALAPPDATA%\hermes\daily-intelligence`，
macOS/Linux 默认使用 `~/.hermes/daily-intelligence`。
配置了 `HERMES_HOME` 时使用其中的 `daily-intelligence/` 子目录。

```sh
signaltrail --data-dir DATA_DIR data-root status
```

首次运行绑定数据根。`data-root adopt` 会明确改变绑定，仅用于主动迁移；
它不会把已有报告复制到新目录。运行清单和引用的产物必须属于同一数据根。

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

## Hermes 完整计量入口

针对已审计的 Hermes 0.21 接入，使用：

```sh
signaltrail-hermes run --ledger DATA_DIR --hermes-python HERMES_PYTHON --prompt-file PROMPT.txt --timeout 3600
```

将大写占位符替换为路径。`HERMES_PYTHON` 是已安装 SignalTrail 的 Hermes 虚拟环境 Python，
`PROMPT.txt` 包含本次报告请求；可用 `--provider` 和 `--model` 选择供应商和模型。

此入口在模型启动前接通计量，包含工作线程及支持的辅助调用，并用单独任务启动独立评估。
封账前核对宿主计数，缺失观测保持 partial。直接 Hermes CLI 和旧 Cron 不会自动获得同等覆盖。
具体限制及 Codex/OpenClaw 导入见[用量说明](../../references/llm-usage.md)。

其他智能体也可以处理相同写作包。没有已审计适配器时，运行仍可使用，但明确标为
`unmetered`，token 总量为 null。没有自动评估调度的宿主需要自行派发评估包，
并调用 `finalize-evaluation`。

## 报告与恢复

| `DATA_DIR` 下的路径 | 内容 |
| --- | --- |
| `reports/YYYY-MM-DD/EDITION-rN.json` 和 `.md` | 版本化原始报告 |
| 同名 `.html` 和 `.pdf` | 阅读与打印副本 |
| `reports/index.html` | 本地报告历史 |
| `runs/YYYY-MM-DD/EDITION.json` | 当前阶段、产物路径、错误和后续命令 |
| `usage/` 和 `host-runs/` | 用量事件和宿主启动回执 |

工作流还会生成便携桌面 HTML，嵌入已取得并验证的图片。HTML 先返回，PDF、已请求的 Notion
交付和评估随后在可重试的后台流程完成。PDF 默认软体积预算为 50 MiB，超出会记录警告。

HTML 阅读页采用三栏报头，展示报告日期、版次和实际记录的生成时间；白底黑字与红色来源横线
组织整期连续新闻。原悬浮目录保留展开、收起和滚动定位，新闻顺序、中英文标题、图片尺寸与
摘要位置保持不变。搜索、日报中心、PDF 和来源状态入口仍可使用，不设阅读模式切换标签。

重试前先读运行清单；尚未完成的交付执行其中的 `tail.command`。
不要手改状态 JSON，也不要在进程活动时删除锁。各阶段恢复方法见[运行手册](../../references/runbook.md)。

采集会保留登录、验证挑战、限流和失败状态。准备好操作浏览器时，用 `verify-pending`
处理待验证来源。无人值守运行不得传入 `--open-verification`。

Notion 为可选项，需要显式 `--publish` 和[配置凭据](../../references/notion-setup.md)。
远程交付失败时，本地报告仍然可用。
