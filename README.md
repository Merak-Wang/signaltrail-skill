# 迹简情报台 · SignalTrail

[简体中文](README.md) | [English](README.en.md)

> 信号化繁为简，来源有迹可循。

迹简情报台（SignalTrail）是一套面向智能体 harness 的本地优先情报简报 Skill 与 CLI。
任何能够读取 `SKILL.md`、执行本地命令、处理自包含写作 packet 并写回结构化 JSON 的
harness 都可以驱动核心流水线。它从经批准的公开来源收集更新，聚合同一事件的重复报道，
再由所选 harness 中的模型生成中文或英文成品简报。报告保留证据链、来源健康状态与跨期
连续性，把分散信号整理成可复核、可汇报、可持续跟踪的判断路径。

[展示效果](#一份报告里有什么) · [报告展厅](#报告展厅) · [快速开始](#快速开始) ·
[工程文档](docs/zh-CN/README.md) ·
[Skill 执行流程](SKILL.md)

[![License](https://img.shields.io/github/license/Merak-Wang/signaltrail-skill?style=flat-square)](LICENSE)

![迹简情报台报告预览](https://raw.githubusercontent.com/Merak-Wang/signaltrail-skill/main/assets/readme/morning-report-preview.png)

## 一份报告里有什么

当前 schema 2.0 把完整采集视图、精选证据、研判和质量边界放进同一份可搜索报告：

- 来源索引保留每条 brief 的原题、链接、时间、访问状态和来源顺序；编辑层从完整索引中
  选择 6—10 个证据事件。
- 地缘政治、AI/技术和市场三个视角分别给出 4—7 段读者叙事，并可展开论证与证据；
  跨视角综合明确共同结论、关键分歧、传导链和后续观察信号。
- 独立评估绑定不可变报告内容 Hash，按九个维度展示得分、证据缺口和可接受边界；搜索、
  折叠目录、桌面单文件和响应式移动阅读使用同一版本内容。

| 跨视角综合 | 独立质量评估 |
| --- | --- |
| ![跨视角综合展示](https://raw.githubusercontent.com/Merak-Wang/signaltrail-skill/main/assets/readme/analysis-synthesis-preview.png) | ![独立质量评估展示](https://raw.githubusercontent.com/Merak-Wang/signaltrail-skill/main/assets/readme/quality-evaluation-preview.png) |

<p align="center">
  <img src="https://raw.githubusercontent.com/Merak-Wang/signaltrail-skill/main/assets/readme/mobile-report-preview.png" width="390" alt="迹简情报台移动端报告展示">
</p>
<p align="center"><sub>同一份报告在 390 px 视口下保持可搜索、可导航和可阅读。</sub></p>

## 产品交付

迹简情报台把庞杂的每日阅读队列压缩为结构稳定、可以复核和归档的决策材料：

- **可直接阅读的晨报与晚报**：HTML 自动交付，PDF 便于汇报与分享，Markdown 和
  JSON 作为可持续维护的本地记录。
- **灵活的智能体编排**：自包含 packet 可并发分发，也可在并发受限时顺序执行；采集、状态、
  校验和投影在本地保持一致。
- **可追溯的信息覆盖**：摘要同时保留原题、来源、链接、发布时间及访问限制。
- **七个固定栏目**：覆盖国际、国内、军事、市场、技术、论文与开源项目。
- **三个分析视角与综合研判**：从地缘政治、AI/技术、市场分别展开，并总结共同信号、
  分歧与下一步观察指标。
- **零模型 Token 的本地监控层**：信息流刷新、缓存、去重、聚类和来源健康检查由
  Python 在本机完成；模型只在正式报告的筛选、目标语言写作与研判阶段参与。
- **有界生成与失败回执**：brief 和研判必须通过结构约束；无效提交只允许一次受预算
  门禁控制的修复，并保存不含草稿正文的 Hash 绑定拒绝回执。
- **可审计的模型用量**：按运行和阶段保存只含白名单计数的不可变事件；缺少精确观测时，
  用量状态记录为 `unknown` 或 `unmetered`。
- **默认本地所有权**：版本化文件、可移动的桌面单文件 HTML，以及按需启用的
  Notion 交付。

内置配置把 32 个正式日报来源与 51 个发现来源分开管理。所有正式来源的
`report_target` 与 `report_max` 都是 15：候选充足时，每个来源交付当前索引顺序中的
前 15 条；不足 15 条时只使用实际候选。发现来源的两个值为 0，仅进入本地信号发现，
不占用正式日报配额。

满载时最多需要撰写 480 条普通 brief。系统只把计划内 Top15 缺口拆成最多 12 个
有界 packet，并按宿主的子任务能力分波执行，默认每波最多 3 个 worker；并发受限的
harness 可以顺序处理。默认完整运行采用 60 分钟硬预算，超限后停止派发新阶段。
需要固定在 06:00/18:00 交付时，应预留供应商延迟、访问验证和重试余量并相应提前启动。

## 报告展厅

当前示例展示 schema 2.0 的完整采集视图、精选事件、跨视角综合和独立评估。

| 当前示例 | 完整采集视图 | 精选与研判 | 独立评估 |
| --- | ---: | ---: | --- |
| [下载 2026-08-25 晨报 r1 HTML](https://github.com/Merak-Wang/signaltrail-skill/raw/refs/heads/main/examples/reports/2026-08-25-morning-r1.html) | 30/32 个正式来源有输出 · 424 条 brief | 8 个证据事件 · 3 个领域研判 · 1 个跨视角综合 | 37/45 |

该示例披露 metadata 级证据、过期 WATCH、缺失发布时间等质量边界。完整运行用时
3974 秒，超过 3600 秒硬预算。HTML 不包含凭据或本地运行路径；136 张配图使用公共来源
URL，浏览完整图文内容时需要联网。

测试样例与报告展厅说明见
[examples/README.md](https://github.com/Merak-Wang/signaltrail-skill/blob/main/examples/README.md)。

## 未来方向

下一阶段围绕“可验证的新闻讲解”展开。以下能力均处于 Draft 或计划状态，现有版本尚未提供：

- **证据驱动的讲解稿**：从已经完成的报告与索引生成有界叙事 packet，把精选新闻、背景、
  反面证据和多视角研判组织成自然的章节式讲解。
- **逐段独立核验**：每个 claim 或 beat 都绑定当前报告证据和内容 Hash；独立验证失败、证据
  过期或版本不匹配时，讲解稿不会进入阅读与媒体阶段。
- **Story stream**：把已验证 beat、引用、授权图片和显式备用素材编排成可复现的讲解序列，
  同时保留每一段的来源路径。
- **语音、字幕与新闻讲解视频**：在 story stream 通过闸门后生成合法授权的 TTS、实测字幕和
  可复现视频，并分别执行技术质量、内容一致性和媒体权利检查。
- **多宿主执行与验收**：通用 packet 协议继续服务不同 harness；发布前需要连续三期晨报/晚报
  通过预先冻结的 Token、证据、质量和时效门槛。

详细边界见[架构草案](docs/zh-CN/design-docs/evidence-driven-professional-narrative-report.md)、
[产品规格](docs/zh-CN/product-specs/evidence-driven-professional-narrative-report.md)和
[进行中的执行计划](docs/zh-CN/exec-plans/active-evidence-driven-professional-narrative.md)。

## 适用场景

迹简情报台面向使用任意智能体 harness、或直接编排本地 CLI，希望生成固定结构中英文简报的
个人研究者与小团队。当“为什么选这条”“来源是否读取成功”与摘要本身同样重要时，它尤其合适。

当前产品范围不含付费研报库、全网社交媒体数据、移动客户端、SSO、RBAC 或 SLA。
来源访问遵循登录、验证码、付费墙、限流及其他访问控制。

| 需求 | 迹简情报台的交付方式 |
| --- | --- |
| 每日管理层汇报 | 固定晨报/晚报结构与有界的重点选择 |
| 证据复核 | 原始来源、原题、链接、时间和状态保持可见 |
| 持续态势感知 | 本地信息台、事件聚类、来源健康与人工验证队列 |
| 中英文交付 | 内容、界面、PDF 与 Markdown 使用同一目标语言 |
| 长期归档 | JSON/Markdown 为本地事实源，HTML/PDF 可重建 |
| 远程协作 | 可选 Notion 元数据页面与便携 HTML 附件 |

## 快速开始

### 环境要求

- Git 与 Python 3.11 或更高版本
- 能够读取 `SKILL.md`、执行本地命令并让 worker 写回结构化 JSON 的智能体 harness；
  不支持子任务并发时可以顺序处理 packet
- Windows 可使用系统 Microsoft Edge；macOS 和 Linux 可使用 Playwright Chromium
- Hermes 快捷接入另需已配置的 [Hermes Agent](https://hermes-agent.nousresearch.com/) 与
  Hermes Gateway

### 安装并加载 Skill

克隆仓库并安装 CLI，然后在所选 harness 中加载根级 `SKILL.md`：

```text
git clone https://github.com/Merak-Wang/signaltrail-skill.git
cd signaltrail-skill
python -m pip install -e .
daily-intel --help
```

通过 `--data-dir` 或 `DAILY_INTEL_DATA_DIR` 指定数据目录。从仓库外启动 CLI 时，使用
`DAILY_INTEL_SKILL_DIR` 指向包含 `SKILL.md`、`configs/` 和 `schemas/` 的目录。写作 packet
的处理流程见 [SKILL.md](SKILL.md)，用量与评估调度见
[模型用量说明](references/llm-usage.md)和[运行手册](references/runbook.md)。

Hermes 0.21 的完整计量运行从模型启动前接线，包括委派、辅助调用和独立评估：

```text
signaltrail-hermes run --ledger DATA_DIR --hermes-python HERMES_PYTHON --prompt-file PROMPT.txt --timeout 3600
```

`HERMES_PYTHON` 是安装了本项目的 Hermes 虚拟环境 Python；可加 `--provider` 和 `--model`。
入口会等待工作波次，并与 Hermes 本次会话的用量数据库对账；缺失记录保留为 `partial`。

### Hermes 快捷安装

下列脚本会安装 Python 包，并把 Skill 同步到 Hermes 的 `skills/research/signaltrail`。

Windows：

```powershell
git clone https://github.com/Merak-Wang/signaltrail-skill.git
cd signaltrail-skill
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install.ps1
```

macOS / Linux：

```bash
git clone https://github.com/Merak-Wang/signaltrail-skill.git
cd signaltrail-skill
bash ./scripts/install.sh
```

全新 Ubuntu 或 Debian 机器还需安装 Chromium 系统依赖：

```bash
python -m playwright install-deps chromium
```

安装完成后验证 CLI：

```text
daily-intel --help
```

### 在所选 harness 中生成第一份报告

加载 Skill 后，可以这样生成第一份报告：

```text
使用迹简情报台（SignalTrail）生成今天的中文晨报，保存为本地 HTML 和 PDF。
```

或者：

```text
使用 SignalTrail 生成英文晚报，说明今天发生了哪些变化，并给出明日观察信号。
```

默认输出语言是 `zh-CN`。单次生成英文报告：

```text
daily-intel run-edition --edition morning --language en
```

长期默认值写在 `configs/sources.yaml`：

```yaml
output:
  language: zh-CN  # zh-CN 或 en
```

选定语言后，摘要、研判、栏目名、HTML、PDF 和 Markdown 会使用同一种语言。新闻原题
保持不变，只在需要时补充译题。

## 工作流程

```mermaid
flowchart LR
    A["采集经批准的公开来源"] --> B["规范化、去重并聚合同一事件"]
    B --> C["生成有界证据包并选择重点"]
    C --> D["用中文或英文编写简报"]
    D --> E["校验 Schema、引用、状态与语言"]
    E --> F["立即交付桌面 HTML"]
    F --> G["在可重试尾部完成 PDF、可选 Notion 与独立评估"]
```

来源访问异常、限流、待人工验证和未完成写作会在报告中保留明确状态、已验证/计划计数
以及恢复路径。

每次派发 brief、研判、修复或评估前，预算门禁都会从不可变用量事件重建已观测下界，
再加上版本化的下游预留；超过上限时停止开启新阶段，并保留已经完成的索引、草稿和
报告产物。语义缓存仅复用内容指纹、语言和独立评估状态仍匹配且位于本轮来源计划内的
译题与摘要。

## 本地情报台

刷新并检查信息流：

```text
daily-intel refresh-monitor
daily-intel monitor-status
```

打开本地信息台，并在进程运行期间每 30 分钟刷新：

```text
daily-intel serve --open --refresh-minutes 30
```

信息台默认只监听 `127.0.0.1`。安装不会注册系统服务；无人值守刷新需要保持该进程
运行，或配置操作系统计划任务。

来源组合可以直接修改：

- 正式日报来源：[configs/sources.yaml](configs/sources.yaml)
- 发现来源：[configs/discovery-sources.yaml](configs/discovery-sources.yaml)

所有来源共用 `collection.item_order`。默认 `source`，正式日报采用网页、榜单或 Feed
给出的原始 Top1–15；改为 `published_at` 后，正式日报采用当前索引中按有效发布时间
从新到旧排列的前 15 条，缺失发布时间和时间并列的条目保持稳定输入顺序。单个来源
也可以设置同名 `item_order` 覆盖全局值。无论选择哪种顺序，索引都会保留原始
`source_rank`，普通 brief 也不会再按 `importance` 二次重排。Hugging Face Papers
使用 Trending 榜单；因此 `source` 模式按当前榜单 Top 排列，即使其中包含较早发表的论文。

## 输出约定

| 产物 | 用途 |
| --- | --- |
| `reports/YYYY-MM-DD/EDITION-rN.json` | 版本化结构记录，不覆盖已有修订 |
| `reports/YYYY-MM-DD/EDITION-rN.md` | 便于审阅、比较与归档 |
| `reports/YYYY-MM-DD/EDITION-rN.html` | 完整本地阅读版本 |
| `reports/YYYY-MM-DD/EDITION-rN.pdf` | 打印与分享版本；图片按打印边界重采样，并记录耗时、字节数与默认 50 MiB 软预算 |
| `reports/index.html` | 按日期与修订浏览本地历史 |
| `Desktop/daily-intelligence-…html` | 图片内嵌、可独立移动的单文件副本 |
| `evaluations/dossiers/REPORT_ID.json` | 与报告及索引 Hash 绑定的独立评估只读输入 |
| `usage/YYYY-MM-DD/TASK_ID/events/*.json` | 不含 prompt/正文的不可变模型用量审计事件 |
| `host-runs/TASK_ID/receipt.json` | 完整计量启动的封存回执及宿主数据库对账 |
| Notion | 可选的元数据页面与便携 HTML 附件 |

`--data-dir` 或 `DAILY_INTEL_DATA_DIR` 指定本地数据根，报告历史位于其中的 `reports/`。
Hermes 快捷安装默认使用 Windows 的
`%LOCALAPPDATA%\hermes\daily-intelligence` 或 macOS/Linux 的
`~/.hermes/daily-intelligence`；设置 `HERMES_HOME` 后沿用其中的
`daily-intelligence/` 子目录。

Notion 完全可选；不配置凭据也能获得全部本地文件。如果桌面复制、PDF 或 Notion
交付失败，版本化本地记录仍会保留，相应投影可以单独重试。

## 文档

- 仓库地图：[AGENTS.md](docs/zh-CN/AGENTS.md)
- 顶层架构：[ARCHITECTURE.md](docs/zh-CN/ARCHITECTURE.md)
- 工程记录目录：[docs/zh-CN/README.md](docs/zh-CN/README.md)
- Skill 执行流程：[SKILL.md](SKILL.md)
- 日常运行与恢复：[references/runbook.md](references/runbook.md)
- 编辑与证据规则：[references/editorial-policy.md](references/editorial-policy.md)
- 详细架构与状态模型：[references/system-design.md](references/system-design.md)
- 模型用量审计与宿主接入：[references/llm-usage.md](references/llm-usage.md)
- Windows 上的 Hermes 快捷接入：[references/windows-setup.md](references/windows-setup.md)
- Notion 配置：[references/notion-setup.md](references/notion-setup.md)
- 版本记录：[CHANGELOG.md](CHANGELOG.md)

## 参与开发

工程边界、文档同步规则与完整验证门禁集中在 [AGENTS.md](AGENTS.md) 和
[工程记录目录](docs/zh-CN/README.md)。CI 统一检查测试、静态分析、编译和文档一致性。
运行时 `data/`、浏览器 profile、Cookie、账号截图、认证 HTML 和密钥均位于版本控制边界之外。

## License

[MIT](LICENSE) © Wang Mingfeng
