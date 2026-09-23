# 使用说明

**状态：** 已验证 · **负责人：** 仓库维护者 · **最后验证：** 2026-09-23

完成[快速开始](../../README.md)后，用本文配置本地运行、宿主接入和报告目录。
[English](../usage.md)

## 安装

在仓库运行 `python -m pip install -e .`，然后让智能体加载根目录的 `SKILL.md`。
保留仓库目录：来源配置、Schema 和模板也是运行输入。从仓库外启动时，将
`DAILY_INTEL_SKILL_DIR` 设为仓库绝对路径。

仓库仅维护根目录的一份 `src/`。发布构建在 `dist/signaltrail/` 中生成完整安装包，包含
`SKILL.md`、源码、配置、Schema、模板、参考资料和资源。从仓库或解压后的完整包根目录运行
安装脚本；脚本先将完整 Skill 同步到 Hermes，再从该目录安装 Python 项目，排除虚拟环境和
运行数据。开发时使用 `-Editable`（Windows）或 `--editable`（macOS/Linux），
Python 安装则关联原始源码目录。

主命令统一为 `signaltrail`，新安装不再提供 `daily-intel`。已有 Shell 脚本和定时命令需改用
`signaltrail`，并重新安装项目以刷新命令入口。已有数据路径和 `DAILY_INTEL_*` 环境变量保持有效。

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
具体限制及 Codex/OpenClaw 导入见[用量说明](../../references/llm-usage.md)。

其他智能体也可以处理相同写作包。没有已审计适配器时，运行仍可使用，但明确标为
`unmetered`，token 总量为 null。没有自动评估调度的宿主仅在用户要求质量评分时自行派发评估包，
并调用 `finalize-evaluation`。

质量评分默认关闭。用户明确要求时，在 `finalize-edition` 或 `complete-edition-tail` 加
`--evaluate`，请求随本轮运行保留，供后台收尾和恢复使用。普通定稿和 PDF 交付不会创建评分任务。
已有评分继续保留；未评分摘要不进入已批准的语义缓存，因此后续日报可能需要增加重新写作量。
结构和证据校验仍正常运行。

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
