# 迹简情报台 · SignalTrail

[简体中文](README.md) | [English](README.en.md)

SignalTrail 是一个在本机运行的新闻工作流：从配置的公开来源采集材料，生成保留原文链接的中文或英文日报，并可将日报改编成可切换的动态 HTML 图文演示。阅读页可导出 PDF，也可按需同步到 Notion。

Python 程序负责采集、证据和状态管理、校验及版本化存档；智能体按有界证据包撰写内容。日报讲解使用口语化、有节奏、轻幽默的主播风格，并按新闻需要选择地缘政治、AI／技术、市场等分析视角。每条中文讲解为 200–350 个非空白字符；代表新闻不设整期篇数上限，按每批成本上限拆分处理。

[快速开始](#快速开始) · [图文演示](#动态-html-图文演示) · [本地监控](#本地监控) · [文档索引](docs/README.md) · [开发指南](docs/development.md)

## 你可以用它做什么

- **生成日报：** 采集公开来源，撰写摘要与分析，保存版本化 JSON／Markdown，并输出本地 HTML 和 PDF。HTML 阅读页支持桌面和移动设备。
- **浏览本地新闻流：** 刷新 RSS／Atom 与配置的静态网页来源，按故事聚类并查看来源状态。监控刷新和聚类不调用模型。
- **制作图文演示：** 从已保存日报选取代表新闻，按批次写讲解，渲染为独立动态 HTML；有演示文件时也会嵌入日报页面，保留独立打开入口。
- **拓展阅读：** 可选实验性 explainer 和并行研究流程，详见各自文档。它们不属于当前新闻讲解演示的稳定日报路径。

## 动态 HTML 图文演示

![SignalTrail 新闻幻灯片预览](assets/readme/news-slides-preview.png)

图中为界面示例，并非真实新闻。

每条新闻占一页，使用风格化的主播讲解，同时呈现日报摘要、来源和可用的封面／正文图片。程序优先合并清晰图片、保留原站 caption，并提供缩略图、放大查看、100% 原始尺寸和原图链接。图片只展示采集到的内容，不生成或猜测图片和图注；来源没有可用配图时会如实留空。

演示可在日报的“今日图文演示”容器中切换，也可通过“独立打开演示”按钮作为单独 HTML 页面放映。动画与版式在本地模板中渲染，不增加模型调用。TTS 和视频合成目前尚未实现。

代表新闻按默认筛选规则从日报精选与重要简报中选取，整期没有固定篇数上限。每批默认最多四条，并对输入和输出 token 估算设置门槛；如果新闻较多，会分多批完成。门槛是批次大小控制，不是费用报价，也不保证宿主报告精确用量。中文讲解通过 200–350 个非空白字符校验；写作只在有证据支持时选择分析视角。

从一份已保存的日报及匹配索引开始：

```sh
signaltrail slides prepare --report REPORT.json --index INDEX.json
```

智能体读取准备好的批次包并写入结果 JSON，然后逐批提交并检查进度：

```sh
signaltrail slides submit --packet PACKET.json --input DRAFT.json
signaltrail slides status --plan PLAN.json
signaltrail slides render --plan PLAN.json
```

`render` 在所有批次就绪后生成演示 HTML，并更新对应日报页面中的嵌入入口。完整写作数据包、预算参数和恢复说明见[图文幻灯片指南](docs/news-slides.md)。

## 快速开始

需要 Python 3.11+ 和一个已配置模型的智能体宿主；从源码克隆时还需要 Git。可从 GitHub 克隆源码，或下载 [SignalTrail 2.1.0 完整安装包](https://github.com/Merak-Wang/signaltrail-skill/releases/latest)。

```sh
git clone https://github.com/Merak-Wang/signaltrail-skill.git
cd signaltrail-skill
python -m pip install -e .
signaltrail --help
```

在智能体中加载仓库根目录的 [`SKILL.md`](SKILL.md)，然后提出报告需求，例如：

```text
使用 SignalTrail 生成今天的中文晨报，保存本地 HTML 和 PDF。
```

`signaltrail` 是统一命令入口；Python 包可 `import signaltrail`，也可用 `python -m signaltrail.cli` 启动。命令行准备可复现的采集、校验和存档步骤；智能体根据证据包完成写作。仅运行 `run-edition` 会停在写作交接阶段，不会自行生成完整日报。

### Hermes 安装

在仓库目录或已解压的完整安装包根目录运行对应脚本：

```powershell
# Windows
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install.ps1
```

```sh
# macOS / Linux
bash ./scripts/install.sh
```

脚本会将 Skill 同步到 Hermes 并安装 Python 命令。Windows 浏览器采集可使用系统 Microsoft Edge；macOS／Linux 的安装脚本会在同一 Python 环境安装 Playwright Chromium。手动安装时运行：

```sh
python -m playwright install chromium
```

从旧版升级时，请先卸载 `daily-intelligence-skill` Python 包，再安装此版本的 `signaltrail-skill`。停止运行中的任务后，将旧的 Hermes 数据目录和专用浏览器配置目录改名为 `signaltrail`；目录改名保留全部历史报告。完整步骤见[升级说明](docs/zh-CN/usage.md#从旧版升级)。

更完整的配置、数据目录、计量运行和恢复说明见[使用指南](docs/zh-CN/usage.md)。

## 本地监控

```sh
signaltrail refresh-monitor
signaltrail serve --open --refresh-minutes 30
```

监控会刷新来源、整理新闻流并按内容聚类，不调用模型。服务默认仅监听本机 `127.0.0.1`；关闭进程后停止刷新。正式报告来源配置在 [`configs/sources.yaml`](configs/sources.yaml)，监控发现来源配置在 [`configs/discovery-sources.yaml`](configs/discovery-sources.yaml)。

## 数据、成本与能力边界

报告 JSON 和 Markdown 是版本化原始记录；HTML、PDF 是可重建的阅读投影。现有报告修订不会被覆盖。来源访问失败、限流和验证挑战会保留其实际状态。运行数据默认保存在本机的 Hermes `signaltrail/` 目录。旧版用户可按[升级说明](docs/zh-CN/usage.md#从旧版升级)将历史数据目录改名迁移，保留报告和运行历史。

采集、监控、图片处理和 HTML 演示渲染不调用模型。日报写作与图文讲解由智能体宿主执行；批次 token 门槛用于限制单批输入／输出规模，实际用量取决于宿主是否提供计量数据。新闻来源、网络状况、证据完整度和模型速度都会影响交付时间与内容覆盖。

图文演示是日报的独立 HTML 投影，不改变日报 JSON／Markdown。当前不提供语音播放或视频制作。实验性 explainer、并行研究与稳定日报及图文演示路径的边界见[文档索引](docs/README.md)和[路线图](docs/zh-CN/roadmap.md)。

## 文档

- [使用指南](docs/zh-CN/usage.md)：安装、宿主、运行、数据目录与恢复。
- [图文幻灯片](docs/zh-CN/news-slides.md)：讲解稿、图片、caption、预算和 HTML 渲染流程。
- [实验性 explainer](docs/zh-CN/explainers.md)与[并行研究](docs/zh-CN/research/2026-09-20-illustrated-workflow.md)：实验功能及准入限制。
- [架构](docs/zh-CN/ARCHITECTURE.md)、[开发指南](docs/zh-CN/development.md)和[已知问题](docs/zh-CN/exec-plans/tech-debt-tracker.md)：工程设计与开发维护。
- [变更记录](CHANGELOG.md) · [MIT License](LICENSE)

旧版晨报截图展示的是历史阅读器样式，不代表当前演示设计：

<details>
<summary>查看历史日报示例与旧版阅读器截图</summary>

[打开历史 HTML 示例](https://github.com/Merak-Wang/signaltrail-skill/raw/refs/heads/main/examples/reports/2026-08-25-morning-r1.html)（需浏览器本地打开；部分图片需要联网）。更多背景见[示例说明](https://github.com/Merak-Wang/signaltrail-skill/blob/v2.1.0/examples/README.md)。

![历史阅读器样式](assets/readme/morning-report-preview.png)

![历史分析综合页面](assets/readme/analysis-synthesis-preview.png)

![历史质量评估页面](assets/readme/quality-evaluation-preview.png)

<img src="assets/readme/mobile-report-preview.png" width="390" alt="历史移动端日报样式">

</details>

[English](README.en.md)
