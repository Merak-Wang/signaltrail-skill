# 开发指南

**状态：** 已验证 · **负责人：** 仓库维护者 · **最后验证：** 2026-11-13

本文说明本地开发和模块评估。代码归属见[架构](ARCHITECTURE.md)，不变量见
[agent-instructions.md](agent-instructions.md)。[English](../development.md)

## 环境与检查

```sh
python -m venv .venv
# 在当前 shell 激活 .venv，然后运行：
python -m pip install -e ".[dev]"
python scripts/evaluate_modules.py --repeat 3
python -m ruff check .
python -m compileall -q src scripts evals
python scripts/check_code_comments.py
python scripts/check_docs.py
git diff --check
```

## 模块评估

默认评估使用固定外部输入，运行完整生产链路，每个样本使用独立工作目录。编辑时用 `--modules`
选择一个或多个受影响模块。默认完整评估在 Windows 和 Ubuntu 上覆盖下列四个离线模块。

| 模块 | 流程与质量证据 | 性能指标 |
| --- | --- | --- |
| `collection` | 采集固定来源响应、解析日期和补证，核对索引、覆盖及访问状态 | 分阶段时延、文章吞吐、HTTP 请求与响应复用数量 |
| `report` | 编译固定作者稿和来源索引，核对覆盖与证据引用，检查 Markdown 和 HTML 内容及 PDF 可读性，拒绝缺稿并发布修订 | 保存与修订时延、每秒简报数、输出大小 |
| `slides` | 准备并接受固定图文稿，渲染并校验交付的演示文档 | 分阶段时延、每秒页数、输出大小 |
| `orchestration` | 经与 CLI 共用的批次接收函数派发和接收 13 批图文，保留在途草稿、修复失败批次，以单协调者完成 50 页渲染 | 派发轮数、强制交接数、作者占槽、整链时延和页面吞吐 |
| `video` | 使用生产配音与视频运行时导出指定的本地图文稿，解码成片并复测缓存复用 | 首次与重复导出时延、每秒处理的成片时长、缓存命中与生成的语音片段 |

每个样本记录负载、模块质量是否通过、墙钟时延、吞吐、Python 进程 CPU 时间和峰值驻留内存。
浏览器、编码器与配音子进程的 CPU 时间和内存另属其进程。回执汇总各模块墙钟时延的中位数与范围。
默认在 `output/module-evaluations/` 下创建新目录，保存 `results.json` 和样本产物。
显式传入 `--output` 时使用新路径。

性能对照使用同一机器、运行时、负载和缓存条件。串行运行对比，避免与同机的视频导出或模型任务
争用资源。通过 `--baseline` 传入前一次回执，可以限制墙钟
时延中位数的相对退化幅度。以下命令使用 20% 的上限，并将环境或负载不一致的结果记为不可比较。

```sh
python scripts/evaluate_modules.py --repeat 3 --baseline BASELINE.json --max-regression 0.2
```

测量前先准备本地视频运行环境。单独评估视频时，指定已接受的图文稿、对应数据根，以及已安装的
Qwen 模型、配音可执行文件和常驻 worker 路径，以便排除安装开销。首次导出可能复用现有音频。
解读首次和重复导出的时延时，结合各次实际缓存命中和新生成的语音片段数量。

```sh
python scripts/evaluate_modules.py --modules video --video-deck DECK.json --data-dir DATA --device vulkan --model-dir MODEL --tts-executable EXE --tts-worker WORKER --repeat 1
```

验证模型自动发现时，省略 `--model-dir` 并清除 `SIGNALTRAIL_TTS_MODEL_DIR`，使用尚无完整模型文件对的运行数据根和已安装的显式 worker。视频回执会记录所选文件对的目录和本轮模型缓存的新增文件。

模型时延与 token 用量使用同一输入、模型和测量范围在宿主中实际运行。Codex 使用宿主请求记录及
`scripts/measure_codex_turn.py` 汇总。模块评估的固定作者稿用于测量消费稿件的应用阶段。

### 整期验收

用一条指令在独立宿主任务里生成整期。从收到指令计至最终交付回复，将协调者、作者、重试及交付检查的模型响应按请求去重，分别合计输入和输出。总 token 等于两者之和。缓存输入已在输入内，推理输出已在输出内。另列采集启动至 MP4 就绪的生产耗时。对照时标明冻结回放和缓存预热条件。

```sh
python scripts/measure_codex_turn.py --completed-turn --log-root CODEX_SESSIONS --root-thread-id THREAD --root-turn-id TURN --run RUN.json --output USAGE.json
python scripts/evaluate_edition.py --run RUN.json --report REPORT.json --deck DECK.json --video VIDEO.mp4 --host-receipt USAGE.json --full-host-measurement --resources RESOURCES.json --editorial REVIEW.json --output SCORECARD.json
```

完整计量标志表示本期生成的所有工作均由该次指令完成。使用独立派发的生成协调者时，计量另传 `--subtree-thread-id`，评分另传同一 ID 的 `--expected-host-subtree-id`。工程聊天与人工截取的时间窗用于排查各阶段用量。其他宿主也可提供绑定本期运行的回执，标明 `scope=completed_turn`、`selection=completed_invocation`、起止时刻、时长、`total` 内逐请求去重的输入及输出，以及各模型与推理档的响应数。

使用实际交付的报告与图文修订。工具追溯图文引用的报告，并记录运行清单所绑定的报告。按每个零产出的启用来源计缺口，另外列出冻结计划内应写而漏写的条目。逐条核对译题、原发精度、读者所见时间和 TL;DR 的准确简洁程度。统计有可解码图片的页面，对实际渲染的配图相关度、版式、文字是否简洁生动和直入主题分别评分，记录例子和抽查页数。

整期满分 100。时长和 token 各占 15 分，分别以 1,800 秒和 2,000 万为目标，得分比例为 `max(0, 1 − |实测值 − 目标值| / 目标值)`。低档独立完成度共 10 分，其中 5 分按 Terra 低推理或更低档位的实际请求占比计，另 5 分要求该配置独立完成全部交付。本项衡量当期实跑采用的配置。设备占 10 分，按本测试机 CPU 和 GPU 两项整期平均忙碌率的算术平均计。来源占 15 分，按有新闻的启用来源比例计。日报占 15 分，译题、可见发布时间、TL;DR 等权。图文占 20 分，其中 10 分等权评价图像丰富度、相关性、可读性（桌面与手机平均），另 10 分等权评价写作是否简洁、生动、直接。附实际审阅数量和交付修订。缺测项保留权重，总分以区间表示。

采集开始前在测量窗口启动 `python scripts/sample_edition_resources.py --run RUN.json --stop-file DONE --output RESOURCES.json`，全部产物就绪时创建本次专用的 `DONE` 文件。采样器每五秒记录整机 CPU、内存使用率和可读取的最忙 NVIDIA GPU 的忙碌率。

可选设备回执用最终 run 文件 SHA-256 绑定样本，记录采样次数、时长、范围（`edition` 或 `partial`）、全核归一 CPU、GPU 忙碌率和内存占用比例。注明整机或进程树口径、采样间隔和缺测时段。编辑审阅回执按 SHA-256 绑定报告、图文和视频，各维度提供状态、核对过的不同简报或页数及说明。缺测项留空。原始分项与综合分保存在同一回执。

## 名称与模块

| 名称 | 用途 |
| --- | --- |
| SignalTrail / `signaltrail` | 产品、Skill ID、主 CLI；不再安装 `daily-intel` |
| `signaltrail` | Python 导入包及 `python -m signaltrail.cli` 模块入口 |
| `signaltrail-skill` | Python 发行包；替代旧 `daily-intelligence-skill` 发行包 |
| `DAILY_INTEL_*`、报告 ID | 旧环境变量名称和已存标识继续兼容 |
| SignalTrail 应用数据与浏览器配置目录 | 宿主无关默认路径；仅迁移旧数据时才处理 Hermes 目录 |

操作用动词命名，如 `collect_sources`、`save_report`；数据用名词。
CLI 处理函数采用 `handle_<command>`，放在 `commands/`，负责把参数传给领域函数并输出结果。
`cli.py` 加载配置和绑定数据根，`commands/common.py` 放公共输出及类型化上下文。
领域代码不依赖 CLI 模块。

一个职责能够独立命名和测试时再拆模块。不要为无关操作新建泛称的 `manager`、`helper` 或 `utils`。
当前 `reporting.py` 负责编译和校验，`reports.py` 负责存储和 Markdown；其中的超长函数记为 TD-002，
不要再加一个职责不清的 report 模块。

维护中的函数和类用中文 docstring 解释操作、输入来源及消费内容、输出对下游的意义。
例如“返回已验证的索引路径”比“返回处理结果”有用。行内注释说明不直观的安全、状态、兼容和并发决定。

## 文档与发布

README 介绍用途和首次使用。本文档目录保存使用、开发、路线图和有日期的工程历史。
`references/` 维护详细运行策略，`SKILL.md` 保存智能体步骤及按需读取参考资料的入口。

维护中的工程记录说明目的、状态、负责人和验证日期，英文记录与中文译文一起修改。
单语运行参考、历史记录和生成快照在文档目录中编目。每条规则只维护一处。
用简短示例描述实际行为，删除口号、重复功能表和未经实现验证的细节。
提案标为 Draft，已完成的运行记录标为 Historical。

文档检查器检查本地链接、图片、翻译配对、元数据和当前记录日期；历史日期不因超过半年失效。
注释检查器覆盖维护中的源码模块和维护脚本。

实现仅维护根目录的 `src/`，不提交嵌套 Skill 副本。明确发布时运行
`python scripts/build_hermes_skill.py`，在被忽略的 `dist/signaltrail/` 中生成完整 Skill 包。
脚本名保留历史兼容；Skill 和安装包不要求 Hermes。
构建器的 Git 跟踪白名单包含 `SKILL.md`、Python 源码、配置、Schema、模板、参考资料和资源，
排除运行数据和凭据。生成目录是发布产物；实现与文档以仓库根目录为准，不维护
`skills/signaltrail/` 嵌套副本。发布 GitHub 版本前更新版本号和发布说明、构建安装包并完成仓库检查，
再按项目发布流程发布已审阅的 tag 和构建产物。安装从完整仓库或生成包根目录进行，不能仅安装 `src/`。
仓库重构不会自动更新已安装的 Skill。

未解决问题写入[技术债追踪](exec-plans/tech-debt-tracker.md)，包含证据和退出条件。
已发布变化记入 [CHANGELOG.md](../../CHANGELOG.md)。
