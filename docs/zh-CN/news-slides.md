# 新闻幻灯片与配音视频

**状态：** 已验证 · **负责人：** 仓库维护者 · **最后验证：** 2026-11-02

从已保存日报或独立采集的索引制作图文 HTML 演示，并按需导出配音 MP4。每条新闻独立成页，包含来源、摘要、可用图片和模型撰写的讲解。[English](../news-slides.md)

## 选择输入

| 输入 | 选题与输出 |
| --- | --- |
| 已保存日报及匹配索引 | 合并重复原文、保留引用，按模型生成的重要性分数排序日报中的事件与简报，默认选择 50 条。 |
| 独立索引 | 由宿主模型按重要性选择并排序 50 个条目 ID，通过重复 `--item-id` 传入；未传 ID 时 CLI 按来源排名选择。 |

用 `--max-news N` 设置其他正整数。日报定稿使用 `--slides-max-news N`；恢复运行时沿用此前数量，明确修改后才调整。选题不按来源预留名额，缺图或发布日期未知不影响入选。

```sh
signaltrail --data-dir DATA_DIR slides prepare --report REPORT.json --index INDEX.json
signaltrail --data-dir DATA_DIR slides prepare --index INDEX.json --language zh-CN --item-id ID1 --item-id ID2
```

日报模式沿用已保存日报的语言。独立索引模式优先使用 `--language`，其次使用配置的输出语言。独立路径生成单独演示；日报路径同时更新其 HTML 投影。

## 写作与渲染

准备阶段补取缺失或不完整正文，再生成有界写作包。包内提供完整可用正文、提取状态、写作要求和输出 Schema。默认每批五条，输入估算目标 64,000 token，输出额度 4,000 token。单篇较长时默认输入额度自动扩容；显式 `--max-input-tokens` 为硬上限。正文始终完整保留。

写作证据去除本地 Markdown 元数据头，排除仅含评论入口、原文链接或评分的 Feed 记录。入选事件仅有这类记录且没有实质正文或描述时，准备阶段在创建写作包前停止，并列出 event ID、item ID、原始及富化索引路径，供补证或补位。已保存的访问和限流观测继续保留，有实质内容的短描述仍可使用。

即使首次计划尚未创建，日报定稿入口仍保存结构化缺证列表与富化索引。同报告、同来源索引的重试复用这些证据及已完成的访问尝试。`edition-status --require-complete` 显示 `evidence_required`，并给出排除受影响 event ID 的补位命令。

每名作者执行一次 `slides input --packet PACKET.json`，读取完整、紧凑的 `payload.model_input`。命令验证已保存的包，原样输出全部正文、当前讲解风格、输出 Schema 和适用的视频标题上下文，也支持此前保存的旧包。日报模式填写 `event_id`、`narration`、`video_tldr` 和允许的 `perspectives`；独立索引模式还要撰写目标语言的标题和摘要。中文讲解为 200–350 个非空白字符。遵循输入内嵌的讲解风格，准确保留事实限定。详细写作和预算规则见[运行参考](../../references/news-slides.md)。

```sh
signaltrail --data-dir DATA_DIR slides input --packet PACKET.json
signaltrail --data-dir DATA_DIR slides submit --packet PACKET.json --input DRAFT.json
signaltrail --data-dir DATA_DIR slides status --plan PLAN.json
signaltrail --data-dir DATA_DIR slides render --plan PLAN.json
```

使用 prepare 返回或 `artifacts.slides` 登记的真实 plan、packet 路径。隔离 worker 最多同时处理三个包；草稿以 `batch-N-draft.json` 保存于 packet 旁。批量预检用 `slides submit --plan PLAN.json --draft-dir DRAFT_DIR --check-only`，去掉 `--check-only` 后接收合格批次。全部批次接收后才能渲染。

用 `--reuse-plan OLD_PLAN.json` 复用写作输入未变的已接受条目。日报定稿自动传入上一次计划。文字、语言或分析改变时重新写作；只改图片可复用讲稿。prepare 和 status 返回 `reused_count` 与 `pending_news_count`。

每期日报都包含已渲染演示。若定稿延后了交付尾任务，执行记录中的 `tail.command`，等其退出后再渲染。整期完成使用下列命令验收：

```sh
signaltrail --data-dir DATA_DIR edition-status --run RUN.json --require-complete
```

结果应为 `delivery_complete: true`、无待办步骤且幻灯片已渲染。恢复方法见[运行手册](../../references/runbook.md)。

## 图片与日报阅读

在线渲染从公开文章页补充配图和原站图注。同一张照片有多种尺寸时，先取分辨率最高的版本；下载失败或超出预算时再尝试较小版本。图库中每张照片只保留可用的最高分辨率副本，离线重排已有图片时也遵循这条规则。读者可以查看缩略图、放大图片或打开原图。原站未提供图注时留空。

发布方自动生成的裁切图、缩略图按原始照片归组，不同照片保留顺序和原站图注。对已有图文稿执行离线渲染，可生成应用此规则的新版本。

```sh
signaltrail --data-dir DATA_DIR slides render --plan PLAN.json --offline
```

离线渲染复用已保存演示和本地图片。版式调整与补图均无需模型调用。本地模板参考 [MiMo site-02](https://mimo.xiaomi.com/mimo-v2-6/assets/frontend/site-02/)，使用衬线标题、编辑式分栏和保持原始比例的图片。

日报 HTML 内嵌演示并提供独立打开链接，打印时恢复日报摘要。视频导出后，可在同一区域切换演示和视频，桌面 HTML 副本也会更新。版本化 JSON 和 Markdown 保留日报原始记录。

## 导出视频

模型根据完整讲解撰写 `video_tldr`，中文目标为 60–100 字，上限 160 字。视频逐页朗读标题和短稿。首个待写包还会根据入选新闻生成整期 `video_title`。导出标题依次使用显式 `--title`、`video_title`、演示标题。

```sh
signaltrail --data-dir DATA_DIR slides video-setup
signaltrail --data-dir DATA_DIR slides video --deck DECK.json --output VIDEO.mp4
```

默认引擎为原生 Qwen3-TTS 1.7B Q8，使用随包提供的参考音色。准备阶段下载对应平台的程序、模型、FFmpeg 和浏览器，后续复用缓存。实际合成探测通过后优先使用 GPU，否则回退 CPU。需要时用 `--device auto|cpu|cuda|vulkan|metal` 指定。Windows ARM64 需显式传入 `--ffmpeg`；Linux 需要浏览器系统库和中文字体。

视频保留演示原有文字、图片、分栏及页序，整页以 140% 缩放捕获。实测音频时长驱动换页和图片轮播，语音以 1.08 倍速播放。匹配的语音片段、整页音频和视频片段可复用缓存。保持输出路径稳定，可复用相邻工作目录。导出返回视频、时间线、诊断、实际设备和缓存计数。

截图时直接将 CSS 动画推进到结束状态。每张选中图片最多等待 30 秒；超时后采用原有的图片不可用布局，并在诊断中记录 `render_image` / `timed_out`、事件及图号，其余画面继续导出。

导出时由单个工作线程预取下一页语音，主线程使用同一个浏览器会话截图并编码当前页。每页先取得实测音频时长，再确定画面时间线。导出失败后，已完成的逐页缓存可用于重跑。`tts_seconds`、`render_seconds` 和 `encode_seconds` 分别记录各阶段执行时间，其中的工作可以重叠；`pipeline_seconds` 记录语音、截图和逐页编码共同消耗的墙钟时间，截止到最终音频拼接和 MP4 合并之前。

自定义音色时，用短录音和准确转录填写 [profile.example.json](../../assets/tts/profile.example.json)，再注册和选择：

```sh
signaltrail --data-dir DATA_DIR slides voice-setup --profile PROFILE.json --default
signaltrail --data-dir DATA_DIR slides video --deck DECK.json --output VIDEO.mp4 --voice NAME
```

注册录音复制到 `video-runtime/voices/NAME/`，以相对路径保存。`--reference-id ID` 选择配置中的其他参考录音。省略音色参数时优先使用 `SIGNALTRAIL_VOICE`，其次为已注册默认音色。合成语言由演示决定。

## 局限性

图片数量和分辨率取决于原站及下载结果，论文 SVG 图片暂不支持。token 估算用于控制写作包大小，实际用量由宿主适配器记录，未计量时为 `null`。结构校验检查写作合同，事实审阅贯穿采集、选题和写作。网络策略、发音、音频处理与缓存细节见[运行参考](../../references/news-slides.md)。

固定 seed 的 GPU 冷合成在不同运行中仍可能产生波形和时长变化。每页画面跟随本次音频的实测时长，重复导出在输入匹配时复用已保存的音频。
