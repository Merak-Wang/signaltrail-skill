# 新闻图文流运行参考

**权威语言：** 中文（单语运行参考）

**状态：** 已验证的独立投影 · **负责人：** 仓库维护者 · **最后对照代码：** 2026-11-11

本流程从已保存日报及其索引生成独立动态 HTML。日报定稿会自动准备计划和写作包，并将路径登记在 `artifacts.slides`。本地报告可先保存并交付，但这只表示“报告已保存”；完成全部讲稿提交、渲染及整期交付验收后，才能称为“整期交付完成”。默认日报无论 metered 或 unmetered 都必须完成图文流。Python 从整份日报中去重，并按模型已生成的重要性分数选择有界批次，附加来源与图片；准备阶段不额外调用模型。原日报 JSON/Markdown 不变。有放映文件时，日报 HTML 屏幕端以嵌入式演示替代今日摘要，并保留“打开图文演示”独立入口；打印时隐藏演示并恢复摘要。准备失败记录在 `artifacts.slides.error`，不撤销本地日报。整期恢复时运行 `finalize-edition --run RUN.json --report SAVED_REPORT.json --defer-tail` 重新登记计划；单独运行 `slides prepare` 仍可独立准备，但不会更新运行清单。此流程不进入实验讲解的主张账本和独立审核流程。

图文流与视频仅纳入版本日期对应的上海本地自然日新闻；候选按同源规范地址去重后，按原发时间从新到旧选取每源最多15条。直接来源使用可验证的原文发表日期，发现型来源使用 metadata.content_source.published_at；平台提交、榜单、抓取及索引更新时间不作新发布时间。未知或更早的原文日期不得凑入今日流；实质更新须有当日新增事实和来源日期依据。主日报仍使用既有24小时采集窗口。

子命令前加全局 `--compact` 压缩标准输出，保存文件保持完整。每个写作任务以仅含 packet 与绝对 CLI 的新上下文启动。默认上限 50 条，当日合格独立事件不足时交付实际条数，用户可明确设置其他上限。模型复核初选新闻的新近性和重复覆盖；必要时通过重复 `--slides-exclude-event-id` 排除过时或重复事件，由后续候选补足数量。单条补证后仍不足，定稿用 `finalize-edition --slides-exclude-event-id EVENT_ID` 排除；独立 `slides prepare` 用 `--exclude-event-id EVENT_ID`，多条可重复选项。准备阶段按后续候选补位并复用输入未变的已接受讲稿，只处理 pending 包。

## 仅从索引制作图文流

用户只要图文流时，先采集索引，由模型按重要性选出并排序 50 条，通过重复 `--item-id` 传入；用户指定其他数量时使用 `--max-news N`。再运行下列命令；CLI 准备阶段自动补取入选条目的缺失或不完整正文并复用已有证据：

```text
signaltrail --data-dir DATA_DIR slides prepare --index INDEX.json --language zh-CN --item-id ID1 --item-id ID2
```

无需日报、简报写作或日报分析。需要显式重试正文获取时，协调者对选定条目运行 `extract-content`，再用返回的新索引准备 packet；写作者不能为凑字数补造细节。此模式由宿主模型按重要性排序选择索引条目，以原文 URL 去重；未提供 ID 时 CLI 仍保留稳定 `source_rank` 兼容路径，技能流程应传入模型选定的 ID。索引没有重要性分数时，不支持正数 `--min-importance`。语言优先使用显式 `--language`，其次 `config.output.language`。日报模式沿用已保存日报的语言，拒绝显式语言冲突。模型直接输出目标语的 `title`、`summary`、`narration`、`video_tldr`、`perspectives`；没有已有分析时视角为空。遵循 packet 的模式专属 Schema 与指令。来源、日期和图片由 Python 附加，未知日期保持未知。随后提交待写包、检查 status 并 render，复用下文命令。独立演示不伪造日报，也不更新日报投影。

用 `--reuse-plan OLD_PLAN.json` 复用写作输入完全一致的已接受条目，可跨索引或日报修订。文字、语言或分析变化需要重新写作；仅图片变化可以复用。prepare 和 status 返回 `reused_count`、`pending_news_count`；已复用条目不生成待写模型包。日报定稿自动传入上一次计划。未计量费用为 `null`。


## 准备与续写

```text
signaltrail slides prepare --report REPORT.json --index INDEX.json
signaltrail slides prepare --report REPORT.json --index INDEX.json --max-news 50 --batch-size 5 --max-output-tokens 4000
signaltrail slides prepare --report REPORT.json --index INDEX.json --item-id ID_A --item-id ID_B
signaltrail slides input --packet PACKET.json
signaltrail slides submit --packet PACKET.json --input DRAFT.json
signaltrail slides submit --plan PLAN.json --draft-dir DRAFT_DIR --check-only
signaltrail slides submit --plan PLAN.json --draft-dir DRAFT_DIR
signaltrail slides status --plan PLAN.json
signaltrail slides render --plan PLAN.json
signaltrail slides render --plan PLAN.json --offline
```

批量草稿命名为 `batch-N-draft.json`，兼容 `slides-draft-N.json`。预检与正式提交共用校验规则，`--check-only` 一次返回全部字段错误，不写入接受结果或拒绝回执。返回的 `accepted` 为已接受路径，`pending` 为全部未接受批次，`invalid` 为错误批次；合格待提交的状态为 `ready_to_submit`。正式批量提交接收合格草稿并复用已接受结果，缺失或不合格草稿保持待处理。摘要批次可用 `submit-authoring-batch --run RUN.json --all [--check-only]` 执行同样流程。

写讲稿前先运行 `slides review --report REPORT.json --index INDEX.json`，浏览候选50条及需要的候补，合并不同来源报道的同一事件、排除旧闻。模型一次保存 `selected_event_ids`（最终保留顺序）、`exclude_event_ids`、`merge_groups`（每组首项保留，其余合并来源），用 `slides prepare --report REPORT.json --index INDEX.json --review REVIEW.json` 应用。自动规则判定日期资格，模型判定实质事件和语义重复；不按标题相似度自动合并。默认至多50条，不足则报告实际条数，不用旧闻补齐。无图不影响资格。每批默认五条。

准备阶段补取正文后、派发任何讲稿作者前，协调者必须浏览全部最终入选新闻（最多50条）及实际替补的证据。一次紧凑投影查看已有 `plan.payload.news[].evidence` 的来源标题、正文首段、正文长度、访问状态及可用Feed；只有投影留下具体疑问时再读相关全文。仅有标题、作者简介、照片说明或串错的文章不算正文。充分的Feed证据可注明其部分来源并收窄讲稿；证据不足时先从已审核候补中替换。同一轮完成最终证据审核，并按原文日期、版本自然日及冻结上界复核资格，再派发作者。

独立图文计划已有已接受讲稿时，可用 `finalize-edition --slides-review REVIEW.json --slides-reuse-plan OLD_PLAN.json` 将可复用讲稿绑定到新日报修订。显式计划优先于当前计划及上版日报计划；复用仍按本次审核、日期资格和写作输入身份判定。

`prepare` 返回 `plan_path` 和 `packet_paths`；正式日报应直接采用 run manifest 的 `artifacts.slides.plan_path` 与 `artifacts.slides.packet_paths[]`，并保留每个文件的真实绝对路径。每名作者执行一次 `slides input --packet PACKET.json`，读取命令返回的完整模型输入。该命令在验证已保存包后，以紧凑 JSON 原样输出 `payload.model_input`，包括全部正文、风格指引、Schema、日报摘要、来源访问等级、相关分析和适用的视频标题上下文；旧包同样支持。预算由程序从 `payload.budget` 执行。不要再把整期日报、所有批次、历史对话、图片字节或 HTML 模板塞进每个模型请求，也无需另读同一风格文件。Windows 写作宿主使用 UTF-8 输出，Python 入口可加 `-X utf8`，完整读取命令输出且不设置截断上限。

各 packet 相互独立。支持隔离 worker 时最多同时运行 3 个，每个 worker 只读取和提交自己的包；一个 worker 完成后按序补入下一个 packet。没有隔离 worker 时顺序处理。Hermes 集成可用 `delegate_task` 实现并发调度，但这不是 packet 合同要求的 API。日报使用 `--defer-tail` 时执行清单中的 `tail.command`；只有宿主支持并行进程时才与讲稿同时运行。全部批次通过且尾任务退出后再运行 `slides render`，避免 PDF/评估尾任务与日报 HTML 投影更新并发。无论是否计量，整期验收都要包含 `edition-status --run RUN.json --require-complete`。以该命令的动态结果为准；不得根据 `run.status`、可能过期的 manifest 图文流快照或 tail 单独推断完成。

日报模式每批一次写作，输出 `{"slides": [{"event_id": "...", "narration": "...", "video_tldr": "...", "perspectives": []}]}`。每个指定事件必须出现一次；中文讲解按非空白字符硬校验 200–350 字，标点计入。英文没有这个字符区间限制，但仍受 Schema 字段长度及批次输出估算限制。视角可以不选，只能选该事件已有分析中的 `geopolitics`、`markets`、`ai_technology`。不要在输出中重写标题、摘要、来源、图片或 caption。

## 事实核验与口播

材料语言与输出语言独立：采集覆盖可获取的中英文来源并检查整体语言覆盖，不按目标语言过滤来源；用户本次明确语言优先，其次已保存偏好或当前 run，最后默认 `zh-CN`。协调者按此为日报与 packet 选定同一目标语言，写稿者严格遵循 `payload.model_input.language`，不自行重选。全篇用自然中文或自然英文表达，不逐句硬译或夹杂两种语言。保留原文标题和 URL 供追溯；不强求每条都有中英文来源，也不把转载当独立佐证。跨语言核对名称、数字、职务、时态和限定语，关键事实冲突时补证，没有证据就保留未知。

核验从采集与选题阶段开始：确认原文的主体及职务、动作时态、日期和关键数字；容易造成重大误解的事实，按需查一手材料或独立来源。验证结果与来源留在后台记录，不把核验过程塞进口播。起稿时在现有有界证据内逐句复核事实，也复核类比或比喻带出的断言；保留“涉嫌、计划、声称”等限定语，不能把表态写成已发生事实。若证据不足以支撑某句且确有补证价值，暂停写稿并交协调者处理；冻结的 packet 不得私改。协调者完成补证后生成新版本 packet 再继续写作；无法补证则删去无据断言。

结构校验负责格式，事实核验遵循前述证据要求。正文直接说明事实、机制和观点，避免上一句作说明、下一句紧接“不代表”“不证明”“不意味着”等防御性表述。确有重大隐患需要解释时，统一放入独立的“局限性”段落；重要的事实限定自然交代一次。默认写成鲜明、口语化的新闻脱口秀：先在后台挑出一个值得讲的矛盾或观察点，观众只听成稿；不要把核验过程、操作教程或一串限定语写成主体，影响结论的“部分机型”“可关闭”等限定自然交代一次即可。结尾落在有证据支撑的观点或画面，不以知识点罗列收尾。幽默可选，题材不适合时严肃表达；不拿受害者、来源缺口或不确定性取笑，不编造引语或人物心理，也不堆“材料有限”“地缘分析”“后续观察”等套话。

成功提交后通过 `status` 查看待完成批号，恢复时复用已接受的结果。重复提交相同稿件返回已有产物，不重复生成版本；同一批已经接受另一份稿件时会拒绝。无效草稿不会自动请求修复模型。`render` 要求全部批次完成，缺批时拒绝整期渲染，避免静默漏新闻。

## 每批成本控制

默认每批最多五条；输入估算以 64,000 token 为默认拆批目标，超长单篇自动扩容，输出估算上限 4,000 token。输入按序列化 `model_input` 的 UTF-8 字节数除以 2 向上取整，再加 512 token 预留；日报模式输出为每条新闻预留 700 token；独立索引模式还要撰写标题与摘要，每条约预留 1,000 token。任一限制不能容纳下一条时另起一批；显式 `--max-input-tokens` 为硬上限；单篇超限时拒绝并给出已补全文索引路径，调整额度后用该索引重试，正文始终不截断。提交时也检查实际稿件的输出规模估算。

这些是规模估算门槛，不是 tokenizer 精确计数、实际账单或费用保证。宿主支持输出 token 参数时，应同时使用包里的 `max_output_tokens`；更大的隐藏上下文、推理 token 和宿主额外重试仍可能增加实际成本。模型调用由宿主执行，本模块不会直接调用服务商 API，也不会自动增加写作或审核调用。没有实际计量时，输入 token、输出 token、费用均为 `null`，不得写成零或把估算当实测。

改版式、切换图片、打印和重新渲染都不需要模型。

## 图文与来源

图片下载、补图页面请求和公共 DNS-over-HTTPS 查询遵循进程环境中的 `HTTP_PROXY`、`HTTPS_PROXY`、`ALL_PROXY` 和 `NO_PROXY`。本机 DNS 失败或返回代理 fake IP 时，使用公共 DNS 确认公网地址；无法确认或解析到内网地址时不下载，重定向的每个目标同样检查。报告的 `media_metrics.candidates` 是有配图候选的新闻条目数，`failed` 是全部候选均失败的条目数，均不是实际 HTTP 请求次数；备用图片、缓存复用和重定向会改变请求数量。

网络恢复后，已有失败缓存仍按 `media.cache_failure_retry_minutes` 到期重试，不会立即重新请求。验收可使用隔离的新数据目录，保留原目录及缓存。

标题、摘要和来源引用来自日报，索引补充来源名称、时间以及已有封面图和正文图候选。默认在线 `render` 补充正文图片和原站 caption。完整且未截断的正文提取已提供同页图片时，要求原始、最终和图文来源 URL 除片段外完全一致，并核对正文及提取器指纹后复用；缺失证据、不同 URL、arXiv 摘要页或显式 refresh 继续抓取。`sources_fetched` 与 `source_pages_reused` 分别计量；文章请求共用 HTTPX 连接池，并按域名轮转补足空闲并发槽位，同时遵守全局和单域上限。图片下载也使用有界并发。候选依据页面明确的 `srcset`、URL 宽度与 DPR 声明选择，并按媒体配置预算下载缓存。实际清晰度取决于发布者提供的版本及下载结果。页面抓取或下载失败时保留已有索引候选。此过程不改写正文证据、正文状态或访问等级，也不增加模型调用。候选图片按 URL/图片身份去重，每条新闻不设固定图片上限。图集支持缩略图切换、查看大图、按原始尺寸 100% 查看，以及打开原始图片链接。更新图片候选时可复用已接受的讲稿。

日报与独立索引模式都在准备阶段补取选中来源的缺失或不完整正文，限于已配置的正式与监控来源；
未配置来源沿用已有证据。完整可用正文放入 `payload.model_input.news[].evidence[].body`，同时保留
`content_status`、`content_quality` 和 `content_completion`。作者先通读正文，再组织讲稿。
本地 Markdown 的 YAML 元数据头不进入正文。仅有 Comments 入口或 Article URL、Comments URL、Points、# Comments 的 Feed 记录不作为正文复用，历史文件读取同样排除；真实短句和描述继续可用。若一个事件仅剩这类记录，准备在建包前报出 `evidence_gaps`，列明 event/item 与原始、富化索引路径，协调者补证或补位后重试；原索引及其限流、验证等观测保留。
响应式同图关系与发布方缩放地址在下载前合并，优先最高分辨率；同一视口的格式替代与普通回退图共享分组，不同视口的独立构图保留。缓存中同一原图的高清版本也参与选择。图文图片预算按选中的唯一文件计数和累计字节；下载后才识别出的近似副本仍产生实际下载流量。旧报告引用的缓存文件按既有保留策略处理。

正文完整读取；输入规模通过前述分包与显式预算控制。在线渲染另行补图，离线渲染复用已有 deck 和本地图片。

caption 保留网站抽取原文，缺失时不显示；alt、标题和模型描述不能替代原图注。模板对文本转义，来源与图片外链只接受 HTTP(S)。本地缓存图片内嵌到单文件 HTML；尚未缓存的远程配图需要网络，失败时保留原图注并显示图片不可用。

清单 JSON 和 Markdown 随讲解版本保存；HTML 是可重建投影。页面支持目录、键盘翻页、全屏、图片缩略图和大图查看、原始尺寸查看、转场、手机布局、减少动画偏好和无脚本连续阅读。内容依照已保存日报时间，不宣称是重新核验的实时新闻。HTML 提供自动放映按钮，并按每页时间分配图片轮播；视频导出使用本地 TTS 与同一时间轴。

## 本地配音视频

模型基于完整讲解撰写简明 `video_tldr`，建议 60–100 汉字，最多 160 个字符；视频朗读标题和短稿。

```text
signaltrail --data-dir DATA_DIR slides video-setup
signaltrail --data-dir DATA_DIR slides video --deck DECK.json --output VIDEO.mp4
```

默认使用原生 Qwen3-TTS 1.7B Q8 与随包参考声线 `neutral-a`。技能包含 `assets/tts/reference/profile.json` 和 3.33 秒参考录音；新数据根自动使用该声线，已有本机注册声线和旧本地包可继续使用。自定义声线可准备 3–10 秒录音及逐字文本，参照 `assets/tts/profile.example.json` 填写并注册。准备命令按操作系统与架构下载原生程序、模型、FFmpeg 和浏览器，`slides video` 也会自动补齐并复用缓存。无需用户安装 Python TTS 或 CUDA 包。首次准备可联网，后续本地合成与渲染复用缓存。Windows ARM64 的 FFmpeg 通过 `--ffmpeg` 指定；Linux 的浏览器系统库与中文字体由 harness 提供。

口播包含标题和 `video_tldr`，语速为 1.08 倍；实测音频时长决定翻页和图片轮播。HTML 暂停后再次播放，从当前新闻开头开始。

Qwen 按有界意群合成标题和短稿；完整旧句段缓存仍可复用。整页音频缓存匹配稿件、语言、音色和处理参数后直接复用。数字范围、负数、日期与 CVE 等编号按对应规则展开。日志确认达到帧数上限时，仅将失败原段按原标点或词界拆分一次；连续中文可在接近中点的字间拆分，模型、设备、音色和完整文字沿用。已完成句段复用缓存；子段仍超帧或 WAV 无效时报告失败。逐页音色清单保留实际朗读文本、原生调用及设备，`frame_limit_recoveries` 保存失败原段、拆分结果及原始日志；阶段诊断记录本轮执行结果和耗时。

视频按 140% 整页缩放截取图文 HTML。在截图浏览器中应用视频版式，让屏幕讲解与配音共用 `video_tldr`，保留标题、摘要、来源名、图片、图注和分栏。交互式图文保留完整讲解和来源链接。视频按原页序和每页原有图片顺序自动切换，音频时长决定页面停留时间。相同输出路径旁的 `page-cache/` 分别保存整页音频和画面片段。画面内容、页序、音频时长或渲染编码参数变化时重新生成画面片段，包含外部图片的页面也重新渲染。Qwen 成品音频仅压缩连续超过 1 秒、20 毫秒窗 RMS 低于 -45 dBFS 的低能量段，页内保留 0.7 秒、页首末保留 0.2 秒，并在切口淡入淡出；原生句段和拼接原始 WAV 保持不变，音色清单的 `silence_removed_seconds` 记录缩短时长。返回的 `tts_page_cache_hits`、`tts_cache_hits`、`tts_segments_generated` 分别统计整页命中、句段命中和新合成调用，`page_clips_generated` 与 `page_clips_reused` 统计画面编码和复用。清理旧导出目录时使用系统回收站，保留当前成品与所需诊断。

运行组件来源：[llama.cpp b11981 正式发行](https://github.com/ggml-org/llama.cpp/releases/tag/b11981)、[Qwen3-TTS 1.7B Base GGUF](https://huggingface.co/ggml-org/Qwen3-TTS-12Hz-1.7B-Base-GGUF)、[FFmpeg 程序](https://github.com/imageio/imageio-binaries/tree/master/ffmpeg)、[Playwright 浏览器](https://playwright.dev/python/docs/browsers)。


执行 skill 的 harness 选择设备，优先使用经过实际合成探针确认的 GPU，不可用时回落 CPU。`video-setup` 与 `video` 支持 `--device auto|cpu|cuda|vulkan|metal`，或 `SIGNALTRAIL_TTS_DEVICE`，默认 `auto`。固定 llama.cpp b11981 发行矩阵：Windows/Linux 的 x64、ARM64 提供 CPU、CUDA、Vulkan；macOS 的 x64、ARM64 提供 CPU、Metal。发行包存在与当前机器实际可用性分别由准备和合成探针确认；导出记录实际 provider、模型、设备与耗时。可用 `--tts-executable`、`--model-dir` 复用已有程序与模型。

隔离数据根同样应复用兼容的常驻 worker，可用 `SIGNALTRAIL_TTS_WORKER` 指定已有程序。
运行时还会查找当前数据根、模型目录旁、原生程序旁与已绑定默认数据根的 worker，并探测其自身后端。
`video-setup` 的 `execution_mode` 为 `resident` 时，模型和参考音色只加载一次；`oneshot` 会对每个未缓存语段重新加载。
`auto` 优先选择兼容的常驻 GPU；显式设备不匹配 worker 时继续使用原生 CLI，并报告原因。
没有 worker 时继续导出，无需默认编译新程序。


## 新闻播报

### 整期视频标题

首个待写包在根级同时输出 `video_title` 与 `slides`；标题根据包内前六条已选新闻的标题／摘要、随后至多十二条标题及实际条数编写，单独对应整期视频，不改日报 `title` 或逐页新闻标题。后续包不重复命名，不为标题单独调用模型。准备时将这部分上下文与128个估算输出 token 纳入首包预算。

标题优先交代具体主体、关键变化和有依据的影响，把辨识度最高的词放在前面。多个独立事件使用并列或“本期观察”，不得把独立新闻连接成未经证实的因果链，不扩大袭击对象、损失、确定性或影响范围。中文约18–30字、英文约6–12词仅为本项目建议；事实准确和表达完整优先。条数、日期与品牌适合作短尾缀，不以“今日全球要闻50条”作主要吸引点，也不使用虚假惊悚、空泛悬念或无依据的最高级。

依据：[YouTube 标题建议](https://support.google.com/youtube/answer/12340300?hl=en)强调准确、简短、重要词前置及品牌／期号后置；[YouTube 搜索与推荐指导](https://support.google.com/youtube/answer/141805?hl=en)要求标题与实际内容相符；[B站官方培训材料](https://activity.hdslb.com/blackboard/static/20211213/8107ad751d93dfbfa35a37497f2bc6fe/WIg87to0d7.pdf)强调简练、准确并避免夸张和内容不符。这些原则作为写作指导，不冒充平台统一字数限制。

渲染保存 `deck.video_title`；视频导出选择顺序为显式 `--title`、已接受的 `video_title`、旧 `deck.title`。命名变化不重写证据和讲稿；旧包按旧 Schema 接收。全部讲稿可复用且选题次序不变时可沿用旧标题，尚无独立标题的旧计划继续使用原图文稿标题。

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

模型和原生程序在准备后本地复用。原始直播、其余候选参考、模型及缓存保留在运行数据目录；技能包携带默认短参考及配置示例，自定义参考录音留在本地。

新计划先返回 `review_required`，在模型完成候选审核前不创建讲稿写作包。日报定稿使用 `--slides-review REVIEW.json` 接收决定，交付待办为 `slides_review`。时间上界采用冻结 collection_window.end 或本版 generated_at；精确时间晚于上界者排除，当天纯日期仍保留日精度。既有历史计划不因新门禁强制返工。

审核先合并跨源同事件、确认今日资格，再按受影响人数/地区/行业、政策经济科技安全影响程度、持续性或不可逆性、证据充分度排列；热门榜单或同分来源顺序不代替判断。`selected_event_ids` 是最终有序列表，合并来源不占额外条数；可附简短排序理由，不采用伪精确固定权重。

当日合格候选为0时返回 `no_items` 和本版无可选新闻说明，不要求模型生成空审核文件；工作流明确提示补采当前来源或只交日报。
