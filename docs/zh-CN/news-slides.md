# 新闻幻灯片与配音视频

**状态：** 已验证 · **负责人：** 仓库维护者 · **最后验证：** 2026-11-11

从已保存日报或独立采集的索引制作图文 HTML 演示，并按需导出配音 MP4。每条新闻独立成页，展示标题、完整讲解、来源和可用配图。保存的图文稿另附编辑摘要。[English](../news-slides.md)

## 选择输入

| 输入 | 选题与输出 |
| --- | --- |
| 已保存日报及匹配索引 | 审阅当日候选，合并同一事件并保留引用，按影响排序，默认选择至多 50 条。 |
| 独立索引 | 由宿主模型按重要性选择并排序 50 个条目 ID，通过重复 `--item-id` 传入；未传 ID 时 CLI 按来源排名选择。 |

用 `--max-news N` 设置其他正整数。日报定稿使用 `--slides-max-news N`；恢复运行时沿用此前数量，明确修改后才调整。选题不按来源预留名额，缺图不影响入选；发布日期未知不得纳入今日流。

```sh
signaltrail --data-dir DATA_DIR slides prepare --report REPORT.json --index INDEX.json
signaltrail --data-dir DATA_DIR slides prepare --index INDEX.json --language zh-CN --item-id ID1 --item-id ID2
```

日报模式沿用已保存日报的语言。索引选题绑定日报时，若主来源独立对应一条精选事件，图文采用其编辑标题，来源详情保留原题。独立索引模式优先使用 `--language`，其次使用配置的输出语言。独立路径生成单独演示；日报路径同时更新其 HTML 投影。

## 写作与渲染

审核候选先按当日资格和同源规范地址去重，再按原发时间从新到旧选取每源最多15条。准备阶段补取缺失或不完整正文，再生成有界写作包。包内提供完整可用正文、提取状态、写作要求和输出 Schema。默认每批五条，输入估算目标 64,000 token，输出额度 4,000 token。单篇较长时默认输入额度自动扩容；显式 `--max-input-tokens` 为硬上限。正文始终完整保留。

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

完整且未截断的原文提取结果可以复用同页图片，原始 URL、最终 URL 与图文来源 URL 除片段外必须完全一致。证据缺失、URL 变化和显式刷新仍抓取发布页；图片下载、清晰度筛选和图注保留照常执行。指标分别记录 `sources_fetched` 与 `source_pages_reused`。

在线渲染从公开文章页补充配图和原站图注。同一张照片有多种尺寸时，先取分辨率最高的版本；下载失败或超出预算时再尝试较小版本。图库中每张照片只保留可用的最高分辨率副本，离线重排已有图片时也遵循这条规则。读者可以查看缩略图、放大图片或打开原图。原站未提供图注时留空。

分享图来自页面 head 声明，正文配图来自选中的正文区域。重新读取发布页成功后，移除无法在本次提取中确认原图身份的旧页面候选。页面访问失败时可以回退到索引已有候选。

选图时排除已确认的订阅横幅。多篇报道共用同一个照片文件时，各自保留原有图注和媒体署名。

下载前将响应式 `srcset`、同一视口的 `picture` 格式替代、回退图片及已知发布方缩放地址归为同一张图；本地缓存中匹配的更高清版本也参与选择。选中的文件只占一份图文图片预算；需要下载后才能识别的不同编码或尺寸版本，已产生的下载流量仍然存在。旧报告引用的已有文件继续按正常保留策略管理。

BBC Feed 缩略图通过原站公开尺寸地址优先尝试 1920 像素版本，已有低清缓存时也会尝试升级；保存尺寸来自下载文件的实际像素。BBC 路径尺寸和 WordPress 查询尺寸按同一原图与裁切归并，签名和不同裁切继续区分。图文目录在标题下显示来源名，日报目录可直接跳到每个来源分组。

发布方生成的裁切图和缩略图按原始照片归组。若唯一一张已缓存的正文图，其替代文字与绑定原文的标题相同，则将它用作首图。其他照片保留相对顺序和原站图注。手机端依次展示标题、来源、图集和讲解，缩小的导航栏为首图留出更多空间。对已有图文稿执行离线渲染，可生成应用此规则的新版本。

```sh
signaltrail --data-dir DATA_DIR slides render --plan PLAN.json --offline
```

离线渲染复用已保存演示和本地图片。版式调整与补图均无需模型调用。本地模板参考 [MiMo site-02](https://mimo.xiaomi.com/mimo-v2-6/assets/frontend/site-02/)，使用衬线标题、编辑式分栏和保持原始比例的图片。

日报 HTML 内嵌演示并提供独立打开链接，打印时恢复日报摘要，并提供直达本期各领域研判和跨视角综合的链接。视频导出后，可在同一区域切换演示和视频，桌面 HTML 副本也会更新。版本化 JSON 和 Markdown 保留日报原始记录。

## 导出视频

需要成片时，可在图文写作期间启动 `slides prefetch-speech --plan PLAN.json --output FINAL.mp4 --follow-seconds 900`。程序随已接收讲稿到达而逐页合成，共用一个常驻语音模型。最终导出沿用同一输出路径和配音选项，等待预合成进程退出后再启动 `slides video`。回执分别记录新合成页、缓存命中和剩余任务。

模型根据完整讲解撰写 `video_tldr`，中文目标为 60–100 字，上限 160 字。视频逐页朗读标题和短稿。首个待写包还会根据入选新闻生成整期 `video_title`。导出标题依次使用显式 `--title`、`video_title`、演示标题。

```sh
signaltrail --data-dir DATA_DIR slides video-setup
signaltrail --data-dir DATA_DIR slides video --deck DECK.json --output VIDEO.mp4
```

默认引擎为原生 Qwen3-TTS 1.7B Q8，使用随包提供的参考音色。准备阶段下载对应平台的程序、模型、FFmpeg 和浏览器，后续复用缓存。实际合成探测通过后优先使用 GPU，否则回退 CPU。需要时用 `--device auto|cpu|cuda|vulkan|metal` 指定。Windows ARM64 需显式传入 `--ffmpeg`；Linux 需要浏览器系统库和中文字体。

视频以 100% 比例截取 1920 × 1080 的图文 HTML 页面。画面沿用交互式图文的版式、完整讲解、来源链接、图注和控件。配音以 1.08 倍速朗读标题和短稿，实测音频时长驱动换页和图片轮播。语音片段、整页音频和画面片段分别复用匹配的缓存。保持输出路径稳定，可复用相邻工作目录。导出返回视频、时间线、诊断、实际设备和缓存计数。

重复导出会核对有序音频与画面片段、时长、编码器、标题设置及已有 MP4 的文件指纹。命中回执时返回 `video_cache_hit`，省去最终音频拼接与封装，另行报告核对耗时。导出回执记录本次提交的图文修订和最终 MP4 的 SHA-256，供整期验收核对。

共享页面缓存的导出使用操作系统文件锁。活动导出拒绝并发写入，进程退出或被强制终止时操作系统释放持有权，锁文件保留在磁盘。导出器核对旧版锁记录的进程号，并将失效的旧版锁迁移为兼容标记。旧版导出器会拒绝该标记，同一输出后续使用新版导出器继续或重试。

截图时直接将 CSS 动画推进到结束状态。每张选中图片最多等待 30 秒；超时后采用原有的图片不可用布局，并在诊断中记录 `render_image` / `timed_out`、事件及图号，其余画面继续导出。

Qwen 日志确认某句段达到帧数上限时，程序按原标点或词界拆分该段一次；连续中文可在接近中点的字间拆分。已完成句段继续复用缓存，合成沿用同一模型、设备、音色和完整文字。子段仍达到上限时停止导出并保留诊断。音色清单的 `frame_limit_recoveries` 记录失败原段、拆分结果和原始日志。

导出时由单个工作线程预取下一页语音，主线程使用同一个浏览器会话截图并编码当前页。每页先取得实测音频时长，再确定画面时间线。导出失败后，已完成的逐页缓存可用于重跑。`tts_seconds`、`render_seconds` 和 `encode_seconds` 分别记录各阶段执行时间，其中的工作可以重叠；`pipeline_seconds` 记录语音、截图和逐页编码共同消耗的墙钟时间，截止到最终音频拼接和 MP4 合并之前。

自定义音色时，用短录音和准确转录填写 [profile.example.json](../../assets/tts/profile.example.json)，再注册和选择：

```sh
signaltrail --data-dir DATA_DIR slides voice-setup --profile PROFILE.json --default
signaltrail --data-dir DATA_DIR slides video --deck DECK.json --output VIDEO.mp4 --voice NAME
```

注册录音复制到 `video-runtime/voices/NAME/`，以相对路径保存。`--reference-id ID` 选择配置中的其他参考录音。省略音色参数时优先使用 `SIGNALTRAIL_VOICE`，其次为已注册默认音色。合成语言由演示决定。

审阅返回全部合格候选，`--max-news` 仅限制最终入选数量。`slides review --model-input` 通过列名和来源表一次定义的紧凑格式，保留相同标题、证据摘要、来源身份、发表时间与访问状态，减少重复字段名、来源名称和 URL；原始 URL 仍可按保留的条目 ID 在索引中定位。

## 局限性

图片数量和分辨率取决于原站及下载结果，论文 SVG 图片暂不支持。token 估算用于控制写作包大小，实际用量由宿主适配器记录，未计量时为 `null`。结构校验检查写作合同，事实审阅贯穿采集、选题和写作。网络策略、发音、音频处理与缓存细节见[运行参考](../../references/news-slides.md)。

固定 seed 的 GPU 冷合成在不同运行中仍可能产生波形和时长变化。每页画面跟随本次音频的实测时长，重复导出在输入匹配时复用已保存的音频。

视频导出会在 `DATA_DIR/video-runtime/qwen3/worker/`、显式原生程序旁、已选模型目录的兄弟 `worker/` 和已绑定的默认数据根中查找已有 `llama-tts-worker`，也可用 `SIGNALTRAIL_TTS_WORKER` 显式指定。程序探测 worker 自身支持的设备，后端匹配时让模型和参考音色常驻，连续合成各段讲稿。各段继续保存 WAV、帧数诊断和专名检查结果，导出结束后释放进程。
`--model-dir` 优先于 `SIGNALTRAIL_TTS_MODEL_DIR`，可以显式指定首次下载的缓存目录。两者均未设置时，程序依次在本轮模型缓存、显式 worker 和原生程序附近及其标准安装目录、已绑定默认数据根中查找完整的 Q8 模型与投影器文件对。自动发现的文件对原地复用，均缺失时才下载至本轮模型缓存。
`video-setup` 和视频导出会报告 `execution_mode`、`worker_path` 或 `tts_worker_executable` 及选择原因。`auto` 优先复用可用的常驻 GPU 后端，Windows 优先常驻 Vulkan，其次常驻 CUDA；显式指定设备优先。没有匹配 worker 时用 `execution_mode: oneshot` 沿用原生 CLI，并说明每个未缓存语段会重新加载模型。隔离数据根应复用兼容 worker；缺少 worker 时可以继续，无需为此默认构建程序。

写讲稿前运行 `slides review --report REPORT.json --index INDEX.json`，审核今日候选与候补，再用 `slides prepare --review REVIEW.json` 应用决定。JSON含 `selected_event_ids`、`exclude_event_ids`、`merge_groups`（组首项保留），合并事件保留所有来源引用。合并时，保留使用相关原图的同事件报道。候选中的配图提示由后续下载另行确认，排序仍按新闻影响。日期资格按版本日期及上海自然日判定；发现来源使用原网页发表日期。未知日期、旧闻、上榜/抓取时间不纳入今日流。模型先审核实质变化与同一事件的跨源报道，不足50条时交付真实条数。

准备阶段补取正文后、派发任何讲稿作者前，协调者必须浏览全部最终入选新闻（最多50条）及实际替补的证据。一次紧凑投影查看已有 `plan.payload.news[].evidence` 的来源标题、正文首段、正文长度、访问状态及可用Feed；只有投影留下具体疑问时再读相关全文。仅有标题、作者简介、照片说明或串错的文章不算正文。充分的Feed证据可注明其部分来源并收窄讲稿；证据不足时先从已审核候补中替换。同一轮完成最终证据审核，并按原文日期、版本自然日及冻结上界复核资格，再派发作者。

独立图文计划已有已接受讲稿时，可用 `finalize-edition --slides-review REVIEW.json --slides-reuse-plan OLD_PLAN.json` 将可复用讲稿绑定到新日报修订。显式计划优先于当前计划及上版日报计划；复用仍按本次审核、日期资格和写作输入身份判定。

显式计划已经完成且其渲染 HTML 与已保存日报的图文相同时，定稿可以恢复运行清单的关联。日报、索引和审核须与现有计划匹配，恢复过程保留已交付文件。

新的CLI准备和日报定稿先返回 `review_required`，不生成讲稿包。模型保存决定后，用 `slides prepare --review REVIEW.json` 或 `finalize-edition --slides-review REVIEW.json` 继续；交付状态显示 `slides_review` 待办。既有历史计划可继续恢复。精确发布时间晚于本版冻结上界的条目排除，当日日精度证据保留其原始精度。

候选审核先合并跨源事件、核对今日资格，再综合受影响人数/地区/行业、政策经济科技安全影响程度、持续性或不可逆性、证据充分度排序。`selected_event_ids` 的顺序直接进入最终图文流；热榜或来源顺序不代替影响判断，可附简短排序理由。

当日候选为0时返回 `no_items`，明确提示补采当前来源或只交日报，不要求生成空审核文件。
