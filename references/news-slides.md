# 新闻图文流运行参考

**权威语言：** 中文（单语运行参考）

**状态：** 已验证的独立投影 · **负责人：** 仓库维护者 · **最后对照代码：** 2026-10-21

本流程从已保存日报及其索引生成独立动态 HTML。日报定稿会自动准备计划和写作包，并将路径登记在 `artifacts.slides`。本地报告可先保存并交付，但这只表示“报告已保存”；完成全部讲稿提交、渲染及整期交付验收后，才能称为“整期交付完成”。默认日报无论 metered 或 unmetered 都必须完成图文流。Python 从整份日报中去重，并按模型已生成的重要性分数选择有界批次，附加来源与图片；准备阶段不额外调用模型。原日报 JSON/Markdown 不变。有放映文件时，日报 HTML 屏幕端以嵌入式演示替代今日摘要，并保留“打开图文演示”独立入口；打印时隐藏演示并恢复摘要。准备失败记录在 `artifacts.slides.error`，不撤销本地日报。整期恢复时运行 `finalize-edition --run RUN.json --report SAVED_REPORT.json --defer-tail` 重新登记计划；单独运行 `slides prepare` 仍可独立准备，但不会更新运行清单。此流程不进入实验讲解的主张账本和独立审核流程。

图文流的候选范围是整份已保存日报中的精选事件与简报，不再按来源发布时间或报告日期二次筛选。来源发布日期缺失时继续保持未知；不得用发现时间、采集时间或索引更新时间补造日期。Hacker News、Lobsters 等发现型来源仍保留平台提交日期，原网页日期另存于 `metadata.content_source.published_at`；直接发布来源保留原站日期。跨日或含未知日期的聚合事件保留其完整来源引用，不删旧来源后沿用原摘要。

子命令前加全局 `--compact` 压缩标准输出，保存文件保持完整。每个写作任务以仅含 packet 与绝对 CLI 的新上下文启动。默认保持 30 条，用户明确要求时再改数量。模型复核初选新闻的新近性和重复覆盖；必要时通过重复 `--slides-exclude-event-id` 排除过时或重复事件，由后续候选补足数量。单条补证后仍不足，定稿用 `finalize-edition --slides-exclude-event-id EVENT_ID` 排除；独立 `slides prepare` 用 `--exclude-event-id EVENT_ID`，多条可重复选项。准备阶段按后续候选补位并复用输入未变的已接受讲稿，只处理 pending 包。

## 仅从索引制作图文流

用户只要图文流时，先采集索引，由模型按重要性选出并排序 30 条，通过重复 `--item-id` 传入；用户指定其他数量时使用 `--max-news N`。再运行下列命令；CLI 准备阶段自动补取入选条目的缺失或不完整正文并复用已有证据：

```text
signaltrail --data-dir DATA_DIR slides prepare --index INDEX.json --language zh-CN --item-id ID1 --item-id ID2
```

无需日报、简报写作或日报分析。需要显式重试正文获取时，协调者对选定条目运行 `extract-content`，再用返回的新索引准备 packet；写作者不能为凑字数补造细节。此模式由宿主模型按重要性排序选择索引条目，以原文 URL 去重；未提供 ID 时 CLI 仍保留稳定 `source_rank` 兼容路径，技能流程应传入模型选定的 ID。索引没有重要性分数时，不支持正数 `--min-importance`。语言优先使用显式 `--language`，其次 `config.output.language`。日报模式沿用已保存日报的语言，拒绝显式语言冲突。模型直接输出目标语的 `title`、`summary`、`narration`、`video_tldr`、`perspectives`；没有已有分析时视角为空。遵循 packet 的模式专属 Schema 与指令。来源、日期和图片由 Python 附加，未知日期保持未知。随后提交待写包、检查 status 并 render，复用下文命令。独立演示不伪造日报，也不更新日报投影。

用 `--reuse-plan OLD_PLAN.json` 复用写作输入完全一致的已接受条目，可跨索引或日报修订。文字、语言或分析变化需要重新写作；仅图片变化可以复用。prepare 和 status 返回 `reused_count`、`pending_news_count`；已复用条目不生成待写模型包。日报定稿自动传入上一次计划。节省幅度取决于已有可复用内容，不承诺固定耗时或成本降幅；未计量费用继续为 `null`。


## 准备与续写

```text
signaltrail slides prepare --report REPORT.json --index INDEX.json
signaltrail slides prepare --report REPORT.json --index INDEX.json --max-news 50 --batch-size 5 --max-output-tokens 4000
signaltrail slides prepare --report REPORT.json --index INDEX.json --item-id ID_A --item-id ID_B
signaltrail slides submit --packet PACKET.json --input DRAFT.json
signaltrail slides submit --plan PLAN.json --draft-dir DRAFT_DIR --check-only
signaltrail slides submit --plan PLAN.json --draft-dir DRAFT_DIR
signaltrail slides status --plan PLAN.json
signaltrail slides render --plan PLAN.json
signaltrail slides render --plan PLAN.json --offline
```

批量草稿命名为 `batch-N-draft.json`，兼容 `slides-draft-N.json`。预检与正式提交共用校验规则，`--check-only` 一次返回全部字段错误，不写入接受结果或拒绝回执。返回的 `accepted` 为已接受路径，`pending` 为全部未接受批次，`invalid` 为错误批次；合格待提交的状态为 `ready_to_submit`。正式批量提交接收合格草稿并复用已接受结果，缺失或不合格草稿保持待处理。摘要批次可用 `submit-authoring-batch --run RUN.json --all [--check-only]` 执行同样流程。

候选覆盖整份已保存日报，包括其中全部精选事件和简报；不从日报之外的索引条目扩充。先按原文身份去重并合并来源引用，再按模型生成的重要性分数排序，默认准备最重要的 30 条。可用 `slides prepare --max-news N` 设置其他正整数；`finalize-edition --slides-max-news N` 用于定稿流程的日常配置。没有按来源分配名额的保证，某来源可能在前 N 条中没有入选。新一期默认最重要的 30 条；恢复既有运行且未显式指定数量时沿用上次设置，明确修改数量才准备新计划。日期缺失或来源日期不同不再排除候选；日期值应忠实保留未知，不能用发现、采集或更新时间代替。没有图片不影响入选。此选择只影响图文流，不改变主日报。每个写作数据包仍是一组有界新闻，默认每批五条。

`prepare` 返回 `plan_path` 和 `packet_paths`；正式日报应直接采用 run manifest 的 `artifacts.slides.plan_path` 与 `artifacts.slides.packet_paths[]`，并保留每个文件的真实绝对路径。写作宿主只发送每个包的 `payload.model_input`；Schema 位于 `payload.model_input.output_schema`，预算位于 `payload.budget`。不要把整期日报、所有批次、历史对话、图片字节或 HTML 模板再塞进每个模型请求。包内已经有风格指引、日报摘要、来源访问等级和与本事件相关的条件分析。

各 packet 相互独立。支持隔离 worker 时最多同时运行 3 个，每个 worker 只读取和提交自己的包；一个 worker 完成后按序补入下一个 packet。没有隔离 worker 时顺序处理。Hermes 集成可用 `delegate_task` 实现并发调度，但这不是 packet 合同要求的 API。日报使用 `--defer-tail` 时执行清单中的 `tail.command`；只有宿主支持并行进程时才与讲稿同时运行。全部批次通过且尾任务退出后再运行 `slides render`，避免 PDF/评估尾任务与日报 HTML 投影更新并发。无论是否计量，整期验收都要包含 `edition-status --run RUN.json --require-complete`。以该命令的动态结果为准；不得根据 `run.status`、可能过期的 manifest 图文流快照或 tail 单独推断完成。

日报模式每批一次写作，输出 `{"slides": [{"event_id": "...", "narration": "...", "video_tldr": "...", "perspectives": []}]}`。每个指定事件必须出现一次；中文讲解按非空白字符硬校验 200–350 字，标点计入。英文没有这个字符区间限制，但仍受 Schema 字段长度及批次输出估算限制。视角可以不选，只能选该事件已有分析中的 `geopolitics`、`markets`、`ai_technology`。不要在输出中重写标题、摘要、来源、图片或 caption。

## 事实核验与口播

材料语言与输出语言独立：采集覆盖可获取的中英文来源并检查整体语言覆盖，不按目标语言过滤来源；用户本次明确语言优先，其次已保存偏好或当前 run，最后默认 `zh-CN`。协调者按此为日报与 packet 选定同一目标语言，写稿者严格遵循 `payload.model_input.language`，不自行重选。全篇用自然中文或自然英文表达，不逐句硬译或夹杂两种语言。保留原文标题和 URL 供追溯；不强求每条都有中英文来源，也不把转载当独立佐证。跨语言核对名称、数字、职务、时态和限定语，关键事实冲突时补证，没有证据就保留未知。

核验从采集与选题阶段开始：确认原文的主体及职务、动作时态、日期和关键数字；容易造成重大误解的事实，按需查一手材料或独立来源。验证结果与来源留在后台记录，不把核验过程塞进口播。起稿时在现有有界证据内逐句复核事实，也复核类比或比喻带出的断言；保留“涉嫌、计划、声称”等限定语，不能把表态写成已发生事实。若证据不足以支撑某句且确有补证价值，暂停写稿并交协调者处理；冻结的 packet 不得私改。协调者完成补证后生成新版本 packet 再继续写作；无法补证则删去无据断言。

结构、Schema、字数和引用校验只能说明格式符合要求，不代表事实经过独立验证。正文直接说明事实、机制和观点，避免上一句作说明、下一句紧接“不代表”“不证明”“不意味着”等防御性表述。确有重大隐患需要解释时，统一放入独立的“局限性”段落；重要的事实限定自然交代一次。默认写成鲜明、口语化的新闻脱口秀：先在后台挑出一个值得讲的矛盾或观察点，观众只听成稿；不要把核验过程、操作教程或一串限定语写成主体，影响结论的“部分机型”“可关闭”等限定自然交代一次即可。结尾落在有证据支撑的观点或画面，不以知识点罗列收尾。幽默可选，题材不适合时严肃表达；不拿受害者、来源缺口或不确定性取笑，不编造引语或人物心理，也不堆“材料有限”“地缘分析”“后续观察”等套话。

成功提交后通过 `status` 查看待完成批号，恢复时复用已接受的结果。重复提交相同稿件返回已有产物，不重复生成版本；同一批已经接受另一份稿件时会拒绝。无效草稿不会自动请求修复模型。`render` 要求全部批次完成，缺批时拒绝整期渲染，避免静默漏新闻。

## 每批成本控制

默认每批最多五条；输入估算以 64,000 token 为默认拆批目标，超长单篇自动扩容，输出估算上限 4,000 token。输入按序列化 `model_input` 的 UTF-8 字节数除以 2 向上取整，再加 512 token 预留；日报模式输出为每条新闻预留 700 token；独立索引模式还要撰写标题与摘要，每条约预留 1,000 token。任一限制不能容纳下一条时另起一批；显式 `--max-input-tokens` 为硬上限；单篇超限时拒绝并给出已补全文索引路径，调整额度后用该索引重试，正文始终不截断。提交时也检查实际稿件的输出规模估算。

这些是规模估算门槛，不是 tokenizer 精确计数、实际账单或费用保证。宿主支持输出 token 参数时，应同时使用包里的 `max_output_tokens`；更大的隐藏上下文、推理 token 和宿主额外重试仍可能增加实际成本。模型调用由宿主执行，本模块不会直接调用服务商 API，也不会自动增加写作或审核调用。没有实际计量时，输入 token、输出 token、费用均为 `null`，不得写成零或把估算当实测。

默认最多准备 30 条代表新闻，修改 `--max-news` 可自定义条数；批次输入/输出预算仍分别约束单批大小。改版式、切换图片、打印和重新渲染都不需要模型。

## 图文与来源

图片下载、补图页面请求和公共 DNS-over-HTTPS 查询遵循进程环境中的 `HTTP_PROXY`、`HTTPS_PROXY`、`ALL_PROXY` 和 `NO_PROXY`。本机 DNS 失败或返回代理 fake IP 时，使用公共 DNS 确认公网地址；无法确认或解析到内网地址时不下载，重定向的每个目标同样检查。报告的 `media_metrics.candidates` 是有配图候选的新闻条目数，`failed` 是全部候选均失败的条目数，均不是实际 HTTP 请求次数；备用图片、缓存复用和重定向会改变请求数量。

网络恢复后，已有失败缓存仍按 `media.cache_failure_retry_minutes` 到期重试，不会立即重新请求。验收可使用隔离的新数据目录，保留原目录及缓存。

标题、摘要和来源引用来自日报，索引补充来源名称、时间以及已有封面图和正文图候选。默认在线 `render` 还会读取入选新闻的公开原文页，补充正文图片和原站 caption；文章请求共用 HTTPX 连接池，并按域名轮转补足空闲并发槽位，同时遵守全局和单域上限。图片下载也使用有界并发。候选依据页面明确的 `srcset`、URL 宽度与 DPR 声明选择，并按媒体配置预算下载缓存。实际清晰度受发布者提供的版本、访问情况和下载结果限制，不保证每张图都能取得原尺寸。页面抓取或下载失败时保留已有索引候选。此过程不改写正文证据、正文状态或访问等级，也不增加模型调用。候选图片按 URL/图片身份去重，每条新闻不设固定图片上限。图集支持缩略图切换、查看大图、按原始尺寸 100% 查看，以及打开原始图片链接。更新图片候选时可复用已接受的讲稿。

CLI 准备与日报定稿会先为入选来源补取缺失或不完整的正文，再冻结写作包；访问失败和提取缺口保留实际状态。仅为已配置的正式和监控来源自动补取正文；未配置来源沿用已有证据。日报与独立索引两种模式都将选定来源的完整可用正文放入 `payload.model_input.news[].evidence[].body`，并携带 `content_status`、`content_quality`、`content_completion`。写作者先通读各来源正文，理解事件过程、机制和关键细节，再组织讲稿。正文按 UTF-8 完整读取，不按字符数截断；默认围绕 64,000 token 输入目标拆批，超长单篇自动扩容；显式 `--max-input-tokens` 仍作硬上限，超限时拒绝并给出已补全文索引路径，调整额度后复用该索引。获取不完整的正文保留原状态及缺口，重大未决风险集中放在局限性段落。在线渲染另行补充图片候选；离线渲染使用已有 deck 与本地图片。

caption 保留网站抽取原文，缺失时不显示；alt、标题和模型描述不能替代原图注。模板对文本转义，来源与图片外链只接受 HTTP(S)。本地缓存图片内嵌到单文件 HTML；尚未缓存的远程配图需要网络，失败时保留原图注并显示图片不可用。

清单 JSON 和 Markdown 随讲解版本保存；HTML 是可重建投影。页面支持目录、键盘翻页、全屏、图片缩略图和大图查看、原始尺寸查看、转场、手机布局、减少动画偏好和无脚本连续阅读。内容依照已保存日报时间，不宣称是重新核验的实时新闻。HTML 提供自动放映按钮，并按每页时间分配图片轮播；视频导出使用本地 TTS 与同一时间轴。

## 本地配音视频

模型基于完整讲解撰写简明 `video_tldr`，建议 60–100 汉字，最多 160 个字符；视频朗读标题和短稿。

```text
signaltrail --data-dir DATA_DIR slides voice-setup --profile PROFILE.json --default
signaltrail --data-dir DATA_DIR slides video-setup
signaltrail --data-dir DATA_DIR slides video --deck DECK.json --output VIDEO.mp4
```

默认使用原生 Qwen3-TTS 1.7B Q8。新安装先准备自备的 3–10 秒参考录音和逐字文本，参照 `assets/tts/profile.example.json` 填写配置并注册为默认声线；已有本机注册声线和旧本地包可继续使用。准备命令按操作系统与架构下载原生程序、模型、FFmpeg 和浏览器，`slides video` 也会自动补齐并复用缓存。无需用户安装 Python TTS 或 CUDA 包。首次准备可联网，后续本地合成与渲染复用缓存。Windows ARM64 的 FFmpeg 通过 `--ffmpeg` 指定；Linux 的浏览器系统库与中文字体由 harness 提供。

口播包含标题和 `video_tldr`，语速为 1.08 倍；实测音频时长决定翻页和图片轮播。HTML 暂停后再次播放，从当前新闻开头开始。

Qwen 按有界意群合成标题和短稿；完整旧句段缓存仍可复用。整页音频缓存匹配稿件、语言、音色和处理参数后直接复用。数字范围、负数、日期与 CVE 等编号按对应规则展开；达到生成帧数上限或 WAV 无效时报告失败。逐页音色清单保留实际朗读文本、原生调用及设备，阶段诊断记录本轮执行结果和耗时。

视频截取原图文 HTML，保留原文字、图片和分栏；仅在视频截图时将整个网页缩放至 140%，文字和图片一起放大，图文 HTML 保持原样；按原页序和每页原有图片顺序自动切换，音频时长决定页面停留时间。相同输出路径旁的 `page-cache/` 保存单页缓存；原 HTML、页序、音频时长或渲染编码参数变化时重新生成，包含外部图片的页面重新渲染。Qwen 成品音频仅压缩连续超过 1 秒、20 毫秒窗 RMS 低于 -45 dBFS 的低能量段，页内保留 0.7 秒、页首末保留 0.2 秒，并在切口淡入淡出；原生句段和拼接原始 WAV 保持不变，音色清单的 `silence_removed_seconds` 记录缩短时长。返回的 `tts_page_cache_hits`、`tts_cache_hits`、`tts_segments_generated` 分别统计整页命中、句段命中和新合成调用，`page_clips_generated` 与 `page_clips_reused` 统计画面编码和复用。清理旧导出目录时使用系统回收站，保留当前成品与所需诊断。

运行组件来源：[llama.cpp b11981 正式发行](https://github.com/ggml-org/llama.cpp/releases/tag/b11981)、[Qwen3-TTS 1.7B Base GGUF](https://huggingface.co/ggml-org/Qwen3-TTS-12Hz-1.7B-Base-GGUF)、[FFmpeg 程序](https://github.com/imageio/imageio-binaries/tree/master/ffmpeg)、[Playwright 浏览器](https://playwright.dev/python/docs/browsers)。


执行 skill 的 harness 选择设备，优先使用经过实际合成探针确认的 GPU，不可用时回落 CPU。`video-setup` 与 `video` 支持 `--device auto|cpu|cuda|vulkan|metal`，或 `SIGNALTRAIL_TTS_DEVICE`，默认 `auto`。固定 llama.cpp b11981 发行矩阵：Windows/Linux 的 x64、ARM64 提供 CPU、CUDA、Vulkan；macOS 的 x64、ARM64 提供 CPU、Metal。发行包存在与当前机器实际可用性分别由准备和合成探针确认；导出记录实际 provider、模型、设备与耗时。可用 `--tts-executable`、`--model-dir` 复用已有程序与模型。


## 新闻播报

图文写作应便于听觉理解，视频直接朗读已有文字：

- 一句表达一个主要事实，拆开多层定语、嵌套从句和连续并列项，用熟悉的词解释必要的专业概念。
- 标题提示主题，摘要交代变化，讲解补充关键原因、影响或限定。
- 按完整意思划分意群，保持姓名、机构名、数字和单位的完整；转折、因果与并列关系应听得清楚。停连依据语义组织，不能机械地为每个逗号插入同样静音。
- 每句选定需要听众记住的信息焦点，形成轻重主次；背景保持连贯，复杂信息给足辨识空间，句末明确收束。具体表达取决于所选语音模型的控制能力。
- 中文和英文分别按自然句法写作；检查日期、金额、百分比、型号、缩写及专名的读音。事实精度由写稿阶段确定，合成程序不自行四舍五入。
- 根据完整讲解写 `video_tldr`，建议 60–100 汉字、最多 160 个字符；朗读标题和短稿，语速为 1.08 倍，实测音频时长决定页面停留时间。
- 选型试听至少包括中文、英文、数字、缩写和长机构名，核对主体、动作、结果能否听一遍理解，并检查停连、重点与整体节奏。

上述写作原则参考 [BBC 官方广播与播客写作教学](https://teach.files.bbci.co.uk/youngreporter/Resources-Making-news-for-radio-or-podcasts-Transcript.pdf)；停连、重音和语气节奏参考[中国传媒大学播音课程](https://px.mdedu.cuc.edu.cn/Location/Course/01/)及[播音教师表达训练说明](https://mkszyxy.cuc.edu.cn/2026/0330/c2344a268328/page.htm)。每页结构和试听清单是本项目的实施方案，固定停顿毫秒数不是行业标准。

使用已注册的 Qwen3 参考声线；交付时记录实际模型、语言、设备、时长及本次试听结果。


### 便携音色包

用 `slides voice-setup --profile PROFILE.json --default` 导入音色。程序将参考录音复制到数据根的 `video-runtime/voices/NAME/`，音色说明以相对路径引用录音，整目录可复制给其他机器的 harness。`slides video --voice NAME` 或 `--voice PROFILE.json` 明确选择音色；省略时依次使用 `SIGNALTRAIL_VOICE`、已注册默认音色。`--reference-id ID` 可选择同音色包中的其他参考，已注册的默认参考不会自动随机切换。

配置采用 `engine: qwen3`、`reference_id` 和 `references: [{id, audio, text, language}]`，录音使用相对配置文件的路径。参数为 `seed: 42`、`context: 4096`、`max_frames: 500`、`speed: 1`、`gain_db: 0`、`peak_limit: 0.794`。新 Qwen 整页合成由标点控制内部停顿，并追加 0.2 秒结尾停顿；旧句段缓存拼接仍保留 0.45/0.35 秒的标题、句间停顿。参考文字逐字匹配录音；目标播报语言由上游 deck 的 `language` 决定，英文稿在 `slides prepare --language en` 阶段写好。朗读规范化负责展开数字表达，Qwen 负责词语和专名发音，不继承旧引擎的强制拼写映射。

模型和原生程序在准备后本地复用。原始直播、其余候选参考、模型及缓存保留在运行数据目录；公开技能包只携带配置示例，参考录音留在本地。
