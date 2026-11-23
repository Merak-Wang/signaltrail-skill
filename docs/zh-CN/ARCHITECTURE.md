# 架构

**状态：** 已验证 · **负责人：** 仓库维护者 · **最后验证：** 2026-11-05

本文说明 SignalTrail 的代码分工。[运行契约](../../references/system-design.md)解释数据字段
和恢复规则，[agent-instructions.md](agent-instructions.md)说明修改仓库时的约束。[English](../../ARCHITECTURE.md)

## 仓库文件

安装完整仓库或生成的 skill 目录：配置、模板和资源位于 `src/` 旁。根目录包含智能体入口 `SKILL.md`、
开发约定 `AGENTS.md`、本架构地图、双语 README、版本与安全及许可证说明，以及 Python 项目配置。

| 位置 | 职责与使用方 |
| --- | --- |
| `src/signaltrail/` | 唯一实现，模块职责见下表 |
| `configs/` | `config` 读取来源及发现配置，`notion` 读取可选发布配置 |
| `schemas/` | 日报和用量契约；日报校验读取 report schema |
| `templates/` | 日报契约与图文写作风格 |
| `assets/news-slides/`、`assets/monitor/` | 图文渲染器和监控页面使用的 HTML、CSS、JavaScript |
| `assets/tts/reference/`、`assets/tts/profile.example.json` | 随包默认参考声线与自定义声线配置示例 |
| `assets/readme/` | 双语 README 引用的产品截图 |
| `scripts/` | 安装、打包、开发检查和测量脚本 |
| `references/` | 按当前流程选读的运行细则 |
| `docs/`、`docs/zh-CN/` | 英文工程记录及中文镜像，索引分别列出当前说明与历史记录 |
| `evals/` | 模块评估负载、质量检查与 Skill 触发案例 |
| `examples/` | 当前与历史公开样例，含日报评估使用的合成文本样例 |
| `.github/workflows/ci.yml` | 仓库 CI 检查 |

发布包的 PowerShell 和 shell 安装入口共用 `scripts/install.py`。包内另含日报及 Codex 调度入口
（`run_signaltrail.py`、`run_codex_edition.py`）、用量工具（`measure_codex_turn.py`、
`measure_codex_exec.py`）以及技能包和 Qwen 语音工作进程的构建脚本。
源码仓库另有 `check_code_comments.py`、`check_docs.py`、`evaluate_modules.py` 和
`benchmark_slide_efficiency.py`，用于开发检查和基准。发布范围由构建脚本白名单定义，与 Python
导入关系分别维护。独立脚本、Schema 和提示词也可以由人、宿主或评估直接使用。

默认构建只读取 Git 已跟踪文件。新运行模块和音色资源须与功能一起纳入版本控制后再发布，
`--include-uncommitted` 用于显式本地构建。本地 `data/` 保存证据、已接受草稿、报告、模型和缓存；
`output/`、`tmp/` 及可选 `benchmarks/` 保存测量与临时工作，`build/`、`dist/` 是生成的分发产物。
这些目录与 `.venv/`、工具缓存、编辑器及智能体本地状态均不进入源码发布包。
保留当前交付、音色资源、恢复备份和必要审阅证据，将确认过时的构建副本和一次性探针移入回收站。

## 数据流程

```text
公开来源 → 规范索引 → 证据包 → 模型草稿
→ Python 编译与校验 → 版本化 JSON + Markdown → HTML/PDF
                                           → 图文幻灯片 → 可选 MP4
```

Python 负责采集、身份、访问状态、修订和持久化。模型在数据包声明的证据范围内选题和写作。
证据读取优先使用网页正文，其次是已保存的 Feed 内容，最后是公开摘要；Feed 内容保留为来源提供的部分证据。

默认 `daily` 运行冻结此前 24 小时的采集窗口，并复用同一本地日期的运行。定稿保存日报并准备图文计划；
整期交付要求全部讲稿批次通过并完成渲染。`edition-status --run RUN.json --require-complete`
独立于报告状态检查待办。见[使用指南](usage.md)。

图文流先按版本上海自然日及冻结上界过滤原文日期，再由模型在写讲稿前合并跨源同事件，按重要性与影响力排列至多50条；
保留来源及审核顺序，不足时交付真实条数。CLI/工作流先返回 `slides_review`，收到决定后才生成讲稿包；
`--max-news`／`--slides-max-news` 调整数量。准备阶段先补取选中新闻正文，再把完整可用正文放入有界写作包。
输入未变时可复用已接受讲稿。独立 `slides prepare --index` 路径根据模型选定的条目 ID 直接制作图文流，
省去日报写作。渲染附加公开网页图片及原始图注；离线渲染复用本地图片。见[新闻幻灯片](news-slides.md)。

视频导出读取已保存的 deck，并按 1920 × 1080 原始尺寸直接截取交付的图文 HTML。画面沿用图文页的版式和完整讲解。
本地 Qwen3-TTS 1.7B Q8 朗读每页标题和
`video_tldr`，实测音频决定页面停留及图片轮播。运行时自动准备原生程序和模型，默认使用随包参考声线，
优先采用通过合成探针的 GPU，不可用时回落 CPU。已构建的 `llama-tts-worker` 在多个句段之间保留模型和参考音频，
Python 合成器逐段发送请求，并在导出完成后关闭进程。维护的源码位于 `src/signaltrail/native/`，
`scripts/build_qwen_worker.py` 基于固定 llama.cpp 源码构建。音频和单页画面缓存用于后续导出。

监控独立采集 RSS/Atom 与静态 HTML，聚类条目并记录来源健康，全程不调用模型。
完整采集复用新鲜监控快照；启用扩展来源均作为正式栏目来源，每源按原发时间从新到旧选取最多15条合格当日条目。首页使用 `assets/monitor/`。
日报与事件 API 提供已保存版本与 `platform/events.sqlite` 长期事件档案；
见[采集与档案接口](platform.md)。

`scripts/run_signaltrail.py` 将 CLI 导入绑定到当前工作区；其 `--advance-edition` 模式接收草稿，
推进分析准备、组装、定稿、尾任务和图文渲染，遇到模型任务时返回。程序校验时跳过在途草稿，
只为当前空闲槽位生成完整作者输入。宿主为每位作者创建新上下文；单独会话仍可使用
`--advance-dispatch` 和 `--dispatch-plan`。作者完成通知触发派发，长进程在工具运行时内等待。
整期由一位协调者直接管理最多三名独立作者、阻塞与交付；阶段变化和批次数不产生额外监督者或接班协调者。恢复使用已保存的继续命令，执行示例见 `SKILL.md`。

研判默认由一个新上下文作者完成。可选 `prepare-analysis --parallel` 路径依次处理选题、
三个领域、综合和组装，各阶段会重复读取共享输入。全局 `--compact` 压缩命令输出，保存文件保留完整内容。

## 代码地图

下表模块均位于 `src/signaltrail/`。

| 职责 | 模块 | 边界 |
| --- | --- | --- |
| 类型与 I/O | `models`、`storage`、`utils`、`runtime`、`access`、`localization`、`taxonomy` | 路径、枚举、原子写入、数据根绑定 |
| 配置 | `config` | 来源、限额和运行选项 |
| 采集 | `adapters`、`browser_collection`、`feeds`、`feed_content`、`prefetch`、`collector`、`clustering`、`article_time` | 抓取、保留精度的日期规范化、首次观测与榜单信号、来源状态和顺序 |
| 采集诊断 | `collection_diagnostics` | 已配置来源覆盖、有界正文缺口建议和本地产物完整性 |
| 采集保留 | `retention` | 将超过七天的采集文件移入回收站，保留运行中依赖和全部报告／媒体产物 |
| 证据 | `content`、`content_extraction`、`pdf_content`、`content_images`、`media`、`image_policy`、`monitor` | 结构化正文块、有界文本 PDF 证据、抽取质量、含上下文的配图候选、快照和证据关联 |
| 写作 | `context`、`brief_selection`、`authoring`、`author_inputs`、`analysis_parallel`、`semantics`、`state` | 同源规范URL去重后按原发时间选取每源最新最多15条当日条目、跨源保视图并复用原文写作、有界数据包、按token切分的有序输入块、已接收批次、可选并行研判、连续状态和缓存 |
| 报告契约 | `reporting` | 编译草稿、补齐证据、校验 Schema 及跨字段规则 |
| 图文共享产物 | `narrative_store` | 不可变图文包、已接受写作和精确修订重放；沿用既有产物格式 |
| 报告存储 | `reports` | 保存报告和评估、渲染 Markdown、更新派生状态 |
| 新闻图文流 | `news_slides`、`slide_reuse`、`slide_images`、`slide_renderer` | 日报或独立索引的有界写作、已接受讲稿复用、原文图片补充与独立动态 HTML 放映 |
| 配音视频 | `slide_video`、`voice_synthesis`、`speech_text`、`qwen_runtime`、`video_runtime` | 朗读规范化、本地 Qwen3 TTS、音画共用时间轴、原生工具准备和 MP4 导出 |
| 交付 | `local_output`、`notion`、`dashboard` | HTML/PDF、远程副本和原有采集监控、日报与事件档案 API |
| 工作流 | `workflow` | 检查点、期限、恢复和评估调度 |
| 用量与预算 | `llm_usage/`、`llm_budget`、`evaluation` | 不可变用量事件、派发预留和评估数据包 |
| 宿主接入 | `hosts/`、`hermes_runner`、`usage_cli` | 可选宿主计量、启动器、Hook 和持久日志导入 |
| 命令 | `cli`、`commands/`、`verification`、`importer` | 参数解析、配置绑定、调用领域函数 |

依赖从入口经过编排流向领域代码和公共 I/O。领域模块不得导入 `cli` 或 `commands`。
`commands/parser.py` 定义参数，注册表把命令映射到处理函数，各命令组通过类型化
`CommandContext` 调用领域代码。`signaltrail` 是统一的主 CLI 入口。

公开 Python 导入包和模块入口为 `signaltrail` 与 `python -m signaltrail.cli`；CLI 命令为
`signaltrail`，Python 发行包为 `signaltrail-skill`。旧 `DAILY_INTEL_*` 环境变量和已保存的报告 ID
继续兼容。旧 Hermes `daily-intelligence` 数据及浏览器配置目录可留在原位置，并通过显式路径继续使用；见[使用指南](usage.md)。

## 状态与文件

`workflow.py` 的 `RunStatus` 定义前台状态：

```text
created → collecting → building_context → awaiting_selection
→ extracting_content → awaiting_authoring → finalizing
→ completed | completed_partial | failed
```

`completed_partial` 表示本地报告已存在，并记录了缺口。PDF、Notion、评估和幻灯片写作/渲染拥有独立的
可重试工作，其失败不能撤回已保存的报告。

| 数据根下的文件 | 归属 |
| --- | --- |
| `indexes/`、`content/`、`reports/` | 版本化证据和报告，不覆盖已有修订 |
| `context/` | 不可变写作输入、有界协调器投影、绑定哈希的会话与回执 |
| `content-checkpoints/` | 绑定输入索引与选中 ID 的完整提取结果；支持索引提交恢复 |
| `runs/` | 原子更新的检查点，包含用量任务引用 |
| `usage/…/events/` | 不可变、仅含允许字段的用量事件，用量合计的事实源 |
| `evaluations/dossiers/` | 绑定报告与索引哈希的不可变输入，当前使用 `-v2.json` |
| `state/` | 派生连续状态和语义缓存 |
| HTML、PDF、Notion | 可重建或重试的投影 |

根索引 `items[]` 是规范视图，`sources[].items[]` 是同步的旧视图。
Schema 1.1–1.5 报告保持可读，新报告使用 2.0 并要求跨视角综合。
原子写入使用唯一同目录临时文件和锁，不可变创建拒绝碰撞；成对报告写入的事务缺口见 TD-010。

## 模型边界

写作包声明输出 Schema 和允许的证据。Python 拒绝额外字段及虚构身份，记录不可变拒绝回执，
最多允许一次预算批准的修复。语义缓存保存稳定译题和摘要，每轮重算重要性和状态。
报告保留三个稳定领域栏目 ID。连续状态另用判断与证据绑定的论点 ID，以及绑定具体论点的
观察项；未提及的信号保持活跃。旧身份不明确的记录保留历史，`analysis-domains.json` 提供
每栏目最新状态投影。跨措辞延续仍属于 TD-039。

用量存储只接受计数、耗时、金额、有界标签和哈希关联；不收录 prompt、回复、推理、工具参数、
原始宿主 ID 或密钥。未知观测保持 null。任务锁串行化追加与封账，封账拒绝未闭合调用。
哈希能够发现不一致的本地修改，不能防御可重写整个账本的攻击者。

核心 CLI 使用 SignalTrail 应用数据目录，不要求 Hermes，也不读取 Hermes 环境文件。通用宿主没有
已审计用量适配器时保持 unmetered。`signaltrail-hermes` 是可选入口，会在 Hermes 前启动计量、
观测受支持的辅助请求，并在封账前与宿主计数对账。评估默认使用外部独立 Agent；仅显式选择时
调度 Hermes。适配器格式和覆盖限制见[用量说明](../../references/llm-usage.md)及
[Hermes 集成参考](../../references/hermes-integration.md)。

编译器、校验器和渲染器中的超长函数仍记为[技术债](exec-plans/tech-debt-tracker.md) TD-002。
模块评估和完整检查见[开发指南](development.md)。

两份来源配置共 45 项，其中 43 项启用，全部启用源按现有栏目映射进入日报；有限公开Feed/页面内的可验证当日原文按原发时间从新到旧选取每源最多15条；采集索引保留完整观察证据和来源状态。
