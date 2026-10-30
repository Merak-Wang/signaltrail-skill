# 架构

**状态：** 已验证 · **负责人：** 仓库维护者 · **最后验证：** 2026-10-30

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
| `templates/` | 日报契约、图文写作风格与实验研究、讲解提示词 |
| `assets/news-slides/`、`assets/monitor/` | 图文渲染器和监控页面使用的 HTML、CSS、JavaScript |
| `assets/tts/reference/`、`assets/tts/profile.example.json` | 随包默认参考声线与自定义声线配置示例 |
| `assets/readme/` | 双语 README 引用的产品截图 |
| `scripts/` | 安装、打包、开发检查和测量脚本 |
| `references/` | 按当前流程选读的运行细则 |
| `docs/`、`docs/zh-CN/` | 英文工程记录及中文镜像，索引分别列出当前说明与历史记录 |
| `tests/`、`evals/` | 行为测试及夹具、skill 触发案例 |
| `examples/` | 历史演示和示例 JSON；测试也读取 `sample_report.json` |
| `.github/workflows/ci.yml` | 仓库 CI 检查 |

发布包包含 `scripts/install.ps1`、`install.sh`、`build_hermes_skill.py` 和 `measure_codex_turn.py`。
源码仓库另有 `check_code_comments.py`、`check_docs.py`、`benchmark_slide_efficiency.py`、
`evaluate_research_workflow.py`，用于开发检查和手动基准。发布范围由构建脚本白名单定义，与 Python 导入关系分别维护；
独立脚本、Schema 和提示词也可以由人、宿主或测试直接使用。

默认构建只读取 Git 已跟踪文件。新运行模块和音色资源须与功能一起纳入版本控制后再发布，
`--include-uncommitted` 用于显式本地构建。本地 `data/` 保存证据、已接受草稿、报告、模型和缓存；
`output/`、`tmp/` 及可选 `benchmarks/` 保存测量与临时工作，`build/`、`dist/` 是生成的分发产物。
这些目录与 `.venv/`、工具缓存、编辑器及智能体本地状态均不进入源码发布包。
保留当前交付、音色资源、恢复备份和必要审阅证据，将确认过时的构建副本和一次性探针移入回收站。

## 报告流程

```text
公开来源 → 索引 → 有界证据包 → 模型草稿
→ Python 编译与校验 → 版本化 JSON + Markdown → HTML
→ 可重试的 PDF、可选 Notion、用户明确要求的独立评估
```

Python 负责身份、访问状态、修订分配、校验和持久化。模型只在指定证据范围内选择和写作。
外部内容即使出现在数据包中也仍是数据。模型草稿通过校验后才能成为报告。

监控单独运行：RSS/Atom 和静态 HTML → 规范条目 → 词汇聚类 → 快照、来源健康和 Feed 缓存。
监控不调用模型；监控失败时正式采集仍可继续。

日报定稿会根据已保存日报及其索引准备新闻幻灯片。默认日报无论用量是否计量，都必须完成所有讲稿批次并渲染。报告保存状态与整期交付完成状态分开；使用 `edition-status --run RUN.json --require-complete` 动态验收。图文流候选覆盖整份已保存日报的精选事件与简报；同一原文合并并保留来源引用，再按模型已生成的重要性分数排序，
默认选择最重要的 30 条，可用 `--max-news` 或 `--slides-max-news` 设置其他正整数，不按来源分配名额。
未知发布日期保持未知，无图不影响入选。讲解写作分成有界批次并接收后，在线渲染会在配置媒体预算内
读取公开原文页，补充页面提供的图片候选和原始 caption。有放映时，日报 HTML 在屏幕端以演示
替代摘要并保留独立打开入口，打印时恢复摘要。日报 JSON/Markdown 保持不变。更新图片可复用
已接受讲稿而不增加模型调用；两种写作模式均把索引关联的完整可用正文及提取状态、质量放入模型输入，不为预算截断正文，而以拆批与显式输入上限控制规模；离线渲染
复用已有 deck 和本地图片，不访问网络。
详见[新闻幻灯片工作流](news-slides.md)。

默认版本为 `daily`，每个本地日期复用一次运行，并冻结前 24 小时的采集窗口。
模型基于完整讲解撰写简明 `video_tldr`，视频朗读标题和短稿。`slide_video` 读取已保存的 deck，
调用本地语音程序，测量逐页音频，以同一时间轴驱动图片轮播和 MP4 编码。
`video_runtime` 与 `qwen_runtime` 按操作系统和架构准备原生 Qwen3-TTS 1.7B Q8。
新数据根使用 `assets/tts/reference/` 随包默认声线；用户可参照 `assets/tts/profile.example.json` 注册自定义录音和逐字文本，已有本机注册声线可继续使用。harness 优先使用通过合成探针的 GPU，
不可用时回落 CPU，并记录实际后端。合成阶段复用本地证据、图片和音频。
Qwen 按有界意群合成标题与短稿，匹配的原生音频缓存仍可复用；整页音频缓存跳过重复 PCM 拼接。
视频截取原图文 HTML 画面，保留原文字、图片和分栏，仅在视频截图时将整个网页缩放至 140%，文字和图片一起放大；
视频按原页序和每页原有图片顺序自动切换，音频时长决定页面停留时间。
单页视频按原 HTML、页序、时长及渲染参数缓存；包含外部图片的页面重新渲染。
阶段诊断与独立的音频、画面缓存计数反映实际执行量。

独立索引图文路径使用采集、正文提取与 `slides prepare --index`，无需日报写作或分析。宿主模型先判断索引候选的重要性并按序选择条目，再通过重复 `--item-id` 传入；未指定 ID 时仍支持来源顺序兼容路径。模型直接写目标语标题、摘要与讲稿，再生成独立演示，不更新日报投影。跨修订输入未变的已接受写作可复用，待写数与复用数分别报告。

默认研判由一个新上下文作者完成。并行研判可缩短写作等待，但会跨阶段重复共享输入，仅作为显式可选路径：`prepare-analysis --parallel` 冻结选题，`analysis-stage --stage domains` 准备三个独立领域包，`--stage synthesis` 准备综合包，`--stage assemble` 生成供 `assemble-authoring` 使用的原分析结果。每个 worker 仅以 packet 和绝对 CLI 启动新上下文。全局 `--compact` 压缩标准输出，持久化文件保持完整。

## 代码地图

下表模块均位于 `src/signaltrail/`。

| 职责 | 模块 | 边界 |
| --- | --- | --- |
| 类型与 I/O | `models`、`storage`、`utils`、`runtime`、`access`、`localization`、`taxonomy` | 路径、枚举、原子写入、数据根绑定 |
| 配置 | `config` | 来源、限额和运行选项 |
| 采集 | `adapters`、`browser_collection`、`feeds`、`feed_content`、`prefetch`、`collector`、`clustering` | 抓取、规范化、保留来源状态和顺序 |
| 采集诊断 | `collection_diagnostics` | 已配置来源覆盖、有界正文缺口建议和本地产物完整性 |
| 证据 | `content`、`content_extraction`、`content_images`、`media`、`image_policy`、`monitor` | 结构化正文块、抽取质量、含上下文的配图候选、快照和证据关联 |
| 写作 | `context`、`authoring`、`analysis_parallel`、`semantics`、`state` | 有界数据包、已接收批次、可选并行研判、连续状态和缓存 |
| 报告契约 | `reporting` | 编译草稿、补齐证据、校验 Schema 及跨字段规则 |
| 报告存储 | `reports` | 保存报告和评估、渲染 Markdown、更新派生状态 |
| 新闻图文流 | `news_slides`、`slide_reuse`、`slide_images`、`slide_renderer` | 日报或独立索引的有界写作、已接受讲稿复用、原文图片补充与独立动态 HTML 放映 |
| 配音视频 | `slide_video`、`voice_synthesis`、`speech_text`、`qwen_runtime`、`video_runtime` | 朗读规范化、本地 Qwen3 TTS、音画共用时间轴、原生工具准备和 MP4 导出 |
| 实验讲解 | `narrative`、`narrative_contracts`、`narrative_store`、`narrative_verification`、`story_stream` | 不可变日报子产物、语言审核和解释图；实时新闻准入保持阻断 |
| 实验研究 | `research`、`research_contracts`、`research_delivery` | 冻结正文块、本地问题检索、研究底稿和仅供预览的日报晚绑定；当前准入仍阻断 |
| 交付 | `local_output`、`notion`、`dashboard` | HTML/PDF、远程副本和只读监控界面 |
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
测试选择和完整检查见[开发指南](development.md)。
