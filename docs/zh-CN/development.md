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
| `orchestration` | 经实际 CLI 派发和接收 13 批图文，保留在途草稿、修复失败批次，以单协调者完成 50 页渲染 | 派发轮数、强制交接数、作者占槽、整链时延和页面吞吐 |
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

模型时延与 token 用量使用同一输入、模型和测量范围在宿主中实际运行。Codex 使用宿主请求记录及
`scripts/measure_codex_turn.py` 汇总。模块评估的固定作者稿用于测量消费稿件的应用阶段。

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
