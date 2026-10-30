# 新闻幻灯片

**状态：** 已验证 · **负责人：** 仓库维护者 · **最后验证：** 2026-10-21

新闻幻灯片是从独立索引，或已保存日报及其匹配索引生成的动态 HTML 放映稿。先介绍日报模式，下文独立索引路径可跳过日报写作。每条入选新闻占一页，展示来源、摘要、可用图片、原站 caption 和模型撰写的讲解。候选范围覆盖整份已保存日报中的精选事件与简报，不按发布日期二次筛选，也不从索引中直接添加日报之外的条目。同一原文合并并保留全部来源引用，再按模型生成的重要性分数排序；默认取最重要的 30 条，可用 `slides prepare --max-news N` 设置其他正整数，也可用 `finalize-edition --slides-max-news N` 配置定稿流程。没有按来源预留名额的保证。新一期默认最重要的 30 条；恢复既有运行且未显式指定数量时沿用上次设置，明确修改数量才准备新计划。发布日期未知时保持未知，不以发现、采集或索引更新时间代替。没有图片不影响入选。此投影不改变主日报。有放映文件时，日报 HTML 的“日报图文流与视频”区域会用嵌入式演示替代屏幕上的今日摘要，并保留“独立打开演示”链接；打印时隐藏嵌入演示并恢复摘要。日报 JSON 和 Markdown 保持原样并继续作为事实依据；只要放映投影存在，之后重建日报 HTML 时也会保留演示入口。

视觉参考为 [Frontend Design 示例 site-02](https://mimo.xiaomi.com/mimo-v2-6/assets/frontend/site-02/)：暖灰白背景（`#f3f4ef`）、深绿黑文字（`#1c2422`）、少量陶土橘强调色、大字号衬线标题、错落的编辑式分栏、细分隔线和侧边编号。新闻图片保持原始比例，转场遵循减少动态效果偏好。模板在本地确定性渲染，样式不增加模型调用或生成成本。

在线读取原文时共用一个 HTTPX 连接池；按域名轮转的调度器会在全局槽位空出时补入可执行来源，同时遵守全局和单域并发上限。图片下载也使用有界并发。

图片下载、补图页面请求和公共 DNS-over-HTTPS 查询遵循进程环境中的 `HTTP_PROXY`、`HTTPS_PROXY`、`ALL_PROXY` 和 `NO_PROXY` 设置。本机 DNS 失败或返回代理 fake IP 时，须由公共 DNS 确认目标为公网地址后才下载。内网目标仍会被阻止，重定向目标也要检查。报告的 `media_metrics.candidates` 统计有配图候选的新闻条目数，不是 HTTP 请求次数；备用 URL、缓存复用和重定向都会影响请求数量。

默认在线渲染时，新闻图片合并日报封面图、索引正文图片候选，以及从入选新闻公开页面补充的图片和原始图注。遇到 arXiv 摘要页时，只跟随页面明确提供的同论文 HTML 全文链接补充受支持的正文图片；SVG 图仍不支持。候选按发布者明确提供的 `srcset`、URL 宽度和 DPR 声明择优，并遵循配置的下载预算；实际清晰度受发布者提供的版本及下载成功情况限制。正文内的游戏、推广、订阅和同页推荐容器不计入正文配图；解析为同一内容的候选只展示一次。页面抓取或图片下载失败时保留索引中的原候选。图片补充不会修改已保存的正文证据或访问等级，也不会增加模型调用。候选按图片身份去重，每条新闻不设固定张数上限。图集支持缩略图选择、查看大图、按原始尺寸 100% 查看，以及直接打开原始图片链接；原站 caption 随对应图片保留，缺失时留空，不以 alt 替代。页面优先加载当前新闻与下一条新闻的图片，其余新闻按需加载；同一张本地图片在每次渲染中只编码一次。

Hacker News、Lobsters 等发现型来源仍保留平台提交日期，原网页日期另存于 `metadata.content_source.published_at`；直接发布来源保留原站日期。日期用于如实呈现来源信息，不作为从已保存日报中剔除候选的条件。跨日或含未知日期的聚合事件保留完整来源引用，不删掉旧来源后沿用原摘要。

子命令前加全局 `--compact` 压缩标准输出，保存文件保持完整。每个写作任务以仅含 packet 与绝对 CLI 的新上下文启动。默认保持 30 条，用户明确要求时再改数量。模型复核初选新闻的新近性和重复覆盖；必要时排除过时或重复事件，由后续候选补足数量。单条补证后仍不足，定稿用 `finalize-edition --slides-exclude-event-id EVENT_ID` 排除；独立 `slides prepare` 用 `--exclude-event-id EVENT_ID`，多条可重复选项。准备阶段按后续候选补位并复用输入未变的已接受讲稿，只处理 pending 包。

## 仅从索引制作图文流

用户只要图文流时，先采集索引，由模型按重要性选出并排序 30 条，通过重复 `--item-id` 传入；用户指定其他数量时使用 `--max-news N`。再运行下列命令；CLI 准备阶段自动补取入选条目的缺失或不完整正文并复用已有证据：

```text
signaltrail --data-dir DATA_DIR slides prepare --index INDEX.json --language zh-CN --item-id ID1 --item-id ID2
```

无需日报、简报写作或日报分析。需要显式重试正文获取时，协调者对选定条目运行 `extract-content`，再用返回的新索引准备 packet；写作者不能为凑字数补造细节。此模式由宿主模型按重要性排序选择索引条目，以原文 URL 去重；未提供 ID 时 CLI 仍保留稳定 `source_rank` 兼容路径，技能流程应传入模型选定的 ID。索引没有重要性分数时，不支持正数 `--min-importance`。语言优先使用显式 `--language`，其次 `config.output.language`。日报模式沿用已保存日报的语言，拒绝显式语言冲突。模型直接输出目标语的 `title`、`summary`、`narration`、`video_tldr`、`perspectives`；没有已有分析时视角为空。遵循 packet 的模式专属 Schema 与指令。来源、日期和图片由 Python 附加，未知日期保持未知。随后提交待写包、检查 status 并 render，复用下文命令。独立演示不伪造日报，也不更新日报投影。

用 `--reuse-plan OLD_PLAN.json` 复用写作输入完全一致的已接受条目，可跨索引或日报修订。文字、语言或分析变化需要重新写作；仅图片变化可以复用。prepare 和 status 返回 `reused_count`、`pending_news_count`；已复用条目不生成待写模型包。日报定稿自动传入上一次计划。节省幅度取决于已有可复用内容，不承诺固定耗时或成本降幅；未计量费用继续为 `null`。


## 默认日报流程：准备、写作与渲染

日报定稿时会自动根据已保存报告及对应索引准备幻灯片计划和有界写作包。默认早报/晚报无论 metered 或 unmetered 都必须生成图文流。“报告已保存”表示报告文件可用；只有讲稿全部提交、渲染完成、tail 退出且通过整期验收，才表示“整期交付完成”。可先交付已保存报告与 HTML，同时明确其余步骤仍待完成。运行清单会在
`artifacts.slides.plan_path` 和 `artifacts.slides.packet_paths` 记录路径；准备阶段不会调用模型。
各数据包彼此独立；支持隔离 worker 时最多同时运行三包，一个 worker 完成后按序补入下一个 packet，并逐包提交结果。
没有隔离 worker 时顺序处理。定稿使用 `--defer-tail` 时，执行运行清单中的精确 `tail.command`；
宿主支持并行进程时可与图文写作同时运行，否则先完成 tail。等待它退出后再渲染，因为两项操作都可能更新日报投影。
准备失败不会影响已保存日报，
原因记录在 `artifacts.slides.error`。若要把失败或缺失的计划登记回运行清单，运行
`signaltrail --data-dir DATA_DIR finalize-edition --run RUN.json --report SAVED_REPORT.json --defer-tail`；
单独运行 `slides prepare` 仍可用于独立准备。随后通过 `slides status --plan PLAN.json` 核对批次，
tail 退出后渲染，再运行 `signaltrail --data-dir DATA_DIR edition-status --run RUN.json --require-complete`，
要求 `delivery_complete: true`、`pending_steps` 为空且 `slides.status: rendered`。以该动态命令为准；
run 状态和保存的图文流快照可能早于渲染。未通过时必须披露 `pending_steps`。

## 准备、写作与渲染

渲染时读取图片明确提供的原图链接。已知 CDN 的尺寸变体会归并，不通过猜测 URL 获取原图，高清远程地址不会沿用缩略图的本地缓存文件。图注限制在图片容器内，不借用正文其他位置的引语署名。嵌入演示中打开大图时，查看区域会扩展到日报工具栏上方，关闭后恢复原容器。

从已保存的报告及其对应索引准备幻灯片计划：

```text
signaltrail slides prepare --report REPORT.json --index INDEX.json
```

候选覆盖整份日报中的精选事件与简报；先按原文身份去重、合并来源引用，再按模型生成的重要性分数排序，默认取最重要的 30 条。可用 `slides prepare --max-news N` 指定其他正整数，定稿流程可用 `finalize-edition --slides-max-news N` 配置。此上限适用于整期，不按来源预留名额。恢复时未显式修改数量则沿用已保存设置，显式更改数量会准备新计划。日报外的索引条目不会直接补入；旧日期和未知发布日期仍可入选，未知日期不得由发现或采集时间伪造。无图新闻仍会入选。每个写作数据包包含一组有界新闻，默认每批五条；数据包携带风格说明、输出 Schema、允许采用的分析视角和指定日报证据。

写作时只读取 `packet.payload.model_input`；Schema 位于 `payload.model_input.output_schema`，成本预留单独位于 `payload.budget`。将结果保存为 JSON 后运行 `signaltrail slides submit --packet PACKET.json --input DRAFT.json`。日报模式每个分配事件都要且只要输出一次 `{event_id, narration, video_tldr, perspectives}`。`perspectives` 可以为空，只能选择该事件分析中存在且相关的 `geopolitics`、`markets`、`ai_technology`。模型输出不要重复标题、摘要、来源、图片 URL 或 caption；这些由程序附加。成功提交会复用；无效草稿不会自动触发修复。

每个 worker 只处理一个 packet；最多同时运行三包，一个完成就按序补下一个；没有隔离 worker 时顺序处理。

数据包内含[讲解风格](../../templates/news-slide-style/SKILL.md)，写作端无需再加载额外编辑资料。中文 narration 会硬校验 200–350 个非空白字符，标点计入；英文 narration 没有对应的长度校验。结构校验不代表事实已经独立验证。采集应覆盖可获取的中英文来源并检查整体语言覆盖，不按输出语言过滤来源；用户本次明确选择优先，其次已保存偏好或当前 run，最后默认 `zh-CN`。协调者为日报和 packet 选定同一目标语言，写作者严格遵循 `payload.model_input.language`，不自行重选。保留原文标题和 URL 溯源；不要求每条都同时有中英文材料，不把转载当独立佐证。跨语言核对名称、数字、职务、时态和限定语；重要事实冲突时补证，没有证据就保留未知。

事实核验从采集与选题阶段开始：确认原文主体及职务、动作时态、日期和关键数字；容易造成重大误解的事实，按需查一手材料或独立来源。验证记录留在后台。起稿时在有界证据内复核每个句子及类比带出的断言，保留“涉嫌、计划、声称”等限定语。证据不足时暂停写稿，不得私改冻结的 packet；协调者完成补证后生成新版本 packet，再继续写作；无法补证则删掉无据断言。

正文直接说明事实、机制和观点，避免上一句作说明、下一句紧接“不代表”“不证明”“不意味着”等防御性表述。确有重大隐患需要解释时，统一放入独立的“局限性”段落；重要的事实限定自然交代一次。默认采用鲜明、口语化的新闻脱口秀表达：先在后台挑出一个值得讲的矛盾或观察点，观众只听成稿；不要把核验过程、操作教程或一串限定语写成主体。只把影响结论的“部分机型”“可关闭”等限定自然交代一次。通过长短句和停顿形成节奏，结尾落在有证据支撑的观点或画面，不以知识点罗列收尾。幽默可选，题材不适合时严肃表达；不拿受害者、不确定性或来源缺口开玩笑，不编造引语或人物心理。不要反复用“材料有限”“地缘分析”“后续观察”等套话凑篇幅。调整批大小或 token 门槛时，查看[预算与数据包参考](../../references/news-slides.md)。

使用 `artifacts.slides.plan_path` 与 `artifacts.slides.packet_paths[]` 中的真实路径；每批草稿放在对应 packet 旁并命名为 `batch-N-draft.json`（N 为批次号）。所有批次都提交且 tail 退出后再渲染：

```text
signaltrail --data-dir DATA_DIR slides submit --packet PACKET.json --input DRAFT.json
signaltrail --data-dir DATA_DIR slides status --plan PLAN.json
signaltrail --data-dir DATA_DIR slides render --plan PLAN.json
signaltrail --data-dir DATA_DIR edition-status --run RUN.json --require-complete
```

提交命令追加 `--check-only` 可一次报告全部草稿错误，不保存结果。多批草稿准备好后，运行 `slides submit --plan PLAN.json --draft-dir DRAFT_DIR --check-only`，再去掉 `--check-only` 一起提交合格批次。草稿命名为 `batch-N-draft.json`，也兼容早期的 `slides-draft-N.json`。返回值列出 `accepted`、`pending`、`invalid`、`expected_paths` 和逐批错误。合格但尚未提交时状态为 `ready_to_submit`，只有已接受的批次计为完成。口播文字中不支持的数字表达会在视频导出前报出。

渲染会生成可切换的 HTML 幻灯片、结构化 deck JSON 和 Markdown。新闻标题、摘要和来源引用取自日报；索引提供来源名称、发布时间及已有图片候选。默认在线渲染会读取入选新闻的公开原文页，补充图片和原站 caption，按页面明确提供的 `srcset`、URL 宽度和 DPR 选择候选，并在配置下载预算内缓存成功下载的图片。页面或图片获取失败时保留原候选；此过程不修改正文证据或访问等级，也不调用模型。`--offline` 从已有 deck 和图片文件重建，不抓取页面或下载图片，适用于只调整版式。候选按图片身份去重，实际清晰度取决于原站提供的版本和下载情况，每条新闻不设固定配图上限。图集可选择缩略图、查看大图、按原始尺寸 100% 查看并打开原始图片链接。caption 保留原站抽取文本，缺失时留空，不以 alt 替代。若仍有写作批次待提交或缺失，渲染会停止，不会静默漏掉已分配新闻。状态命令显示已完成和待处理批次。HTML 样式及转场是确定性生成。

CLI 准备与日报定稿会先为入选来源补取缺失或不完整的正文，再冻结写作包；访问失败和提取缺口保留实际状态。仅为已配置的正式和监控来源自动补取正文；未配置来源沿用已有证据。日报与独立索引两种模式都将选定来源的完整可用正文放入 `payload.model_input.news[].evidence[].body`，并携带 `content_status`、`content_quality`、`content_completion`。写作者先通读各来源正文，理解事件过程、机制和关键细节，再组织讲稿。正文按 UTF-8 完整读取，不按字符数截断；默认围绕 64,000 token 输入目标拆批，超长单篇自动扩容；显式 `--max-input-tokens` 仍作硬上限，超限时拒绝并给出已补全文索引路径，调整额度后复用该索引。获取不完整的正文保留原状态及缺口，重大未决风险集中放在局限性段落。在线渲染另行补充图片候选；离线渲染使用已有 deck 与本地图片。

## 批次成本门槛

在 `slides prepare` 上通过 `--max-news` 设置整期数量，并通过 `--batch-size`、`--max-input-tokens`、`--max-output-tokens` 配置每批上限。默认最重要的 30 条、每批五条、输入估算目标 64,000 token（超长单篇自动扩容）、输出估算上限 4,000 token；显式 `--max-input-tokens` 设置硬上限。日报模式每条新闻预留 700 个估算输出 token，独立索引模式还要写标题与摘要，每条约预留 1,000 token；输入估算为序列化数据包 UTF-8 字节数除以 2，再加 512 token 预留。这是粗略体积门槛，与 tokenizer 精确计数无关，也不是美元报价或宿主实际用量保证；除非宿主提供实际用量，否则仍记为未知（`null`）。选中的新闻按需要分多批处理。

模型调用由宿主负责。SignalTrail 负责准备有界数据包和接收结果，不会自动调用模型、重试草稿或额外调用审核模型。

## 本地配音视频

模型基于完整讲解撰写简明 `video_tldr`，建议 60–100 汉字，最多 160 个字符；视频朗读标题和短稿。

```text
signaltrail --data-dir DATA_DIR slides voice-setup --profile PROFILE.json --default
signaltrail --data-dir DATA_DIR slides video-setup
signaltrail --data-dir DATA_DIR slides video --deck DECK.json --output VIDEO.mp4
```

图文稿关联已保存日报时，视频成功导出后会在“日报图文流与视频”区域的“独立打开演示”旁加入“打开视频”。点击后在同一框内播放视频，并可切回图文；“独立打开演示”仍可单独打开放映稿。已存在的桌面日报 HTML 副本也会刷新。后续重建日报或图文 HTML 会保留这些控件，打印时隐藏嵌入区域。独立索引图文稿继续独立交付；日报 JSON 和 Markdown 保留原修订。

默认使用原生 Qwen3-TTS 1.7B Q8。新安装先准备自备的 3–10 秒参考录音和逐字文本，参照 `assets/tts/profile.example.json` 填写配置并注册为默认声线；已有本机注册声线和旧本地包可继续使用。准备命令按操作系统与架构下载原生程序、模型、FFmpeg 和浏览器，`slides video` 也会自动补齐并复用缓存。无需用户安装 Python TTS 或 CUDA 包。首次准备可联网，后续本地合成与渲染复用缓存。Windows ARM64 的 FFmpeg 通过 `--ffmpeg` 指定；Linux 的浏览器系统库与中文字体由 harness 提供。

口播包含标题和 `video_tldr`，语速为 1.08 倍；实测音频时长决定翻页和图片轮播。HTML 暂停后再次播放，从当前新闻开头开始。

Qwen 按有界意群合成每页标题与短稿；先前导出的完整句段缓存仍可复用。数字范围、日期、负数和 CVE 等编号采用各自的朗读规则，显示文字保持原样。原生生成达到帧数上限或 WAV 无效时，该页报错，不写入成功音频缓存。

稿件、语言、音色、处理参数及 WAV 内容匹配时，直接复用整页音频。返回值的 `tts_page_cache_hits` 统计整页命中，`tts_cache_hits` 统计句段命中，`tts_segments_generated` 统计新合成调用。缓存清单保留原始合成证据，阶段诊断记录当前这次导出的耗时。 Qwen 播放音频只压缩连续超过 1 秒、20 毫秒窗 RMS 低于 -45 dBFS 的低能量段；页内保留 0.7 秒、页首末保留 0.2 秒，切口淡入淡出。原生句段和拼接原始 WAV 保持不变，`silence_removed_seconds` 记录缩短时长。

视频截取原图文 HTML 画面，保留文字、图片和原分栏；仅在视频截图时将整个网页缩放至 140%，文字和图片一起放大，图文 HTML 保持原样；视频按原页序和每页原有图片顺序自动切换，包括原有占位画面和远程图片；音频时长决定页面停留时间。

保持输出路径不变，可复用 `OUTPUT.mp4` 旁的 `OUTPUT/page-cache/`。单页视频取决于原 HTML、页序、实测时长以及渲染和编码参数。匹配且不含外部图片的页面可跳过浏览器渲染和编码；包含外部图片的页面重新渲染。标准错误流输出进度，返回的 `diagnostics_path` 记录阶段结果与耗时，`timeline_path` 记录音画时间轴，逐页音色清单保留合成输入和原生日志。`pages_rendered`、`page_clips_generated`、`page_clips_reused` 表示实际执行量。清理时保留当前成品和有用证据，将已被替代的输出目录移入系统回收站。

运行组件来源：[llama.cpp b11981 正式发行](https://github.com/ggml-org/llama.cpp/releases/tag/b11981)、[Qwen3-TTS 1.7B Base GGUF](https://huggingface.co/ggml-org/Qwen3-TTS-12Hz-1.7B-Base-GGUF)、[FFmpeg 程序](https://github.com/imageio/imageio-binaries/tree/master/ffmpeg)、[Playwright 浏览器](https://playwright.dev/python/docs/browsers)。


执行 skill 的 harness 选择设备，优先使用经过实际合成探针确认的 GPU，不可用时回落 CPU。`video-setup` 与 `video` 支持 `--device auto|cpu|cuda|vulkan|metal`，或 `SIGNALTRAIL_TTS_DEVICE`，默认 `auto`。固定 llama.cpp b11981 发行矩阵：Windows/Linux 的 x64、ARM64 提供 CPU、CUDA、Vulkan；macOS 的 x64、ARM64 提供 CPU、Metal。发行包存在与当前机器实际可用性分别由准备和合成探针确认；导出记录实际 provider、模型、设备与耗时。可用 `--tts-executable`、`--model-dir` 复用已有程序与模型。


### 新闻播报

根据完整讲解撰写 `video_tldr`，让标题与短稿互补；按意群组织停连，中英文分别试听数字和专名。详见[新闻播报参考](../../references/news-slides.md#新闻播报)。使用已注册的 Qwen3 参考声线。


### 便携音色包

用 `slides voice-setup --profile PROFILE.json --default` 导入音色。程序将参考录音复制到数据根的 `video-runtime/voices/NAME/`，音色说明以相对路径引用录音，整目录可复制给其他机器的 harness。`slides video --voice NAME` 或 `--voice PROFILE.json` 明确选择音色；省略时依次使用 `SIGNALTRAIL_VOICE`、已注册默认音色。`--reference-id ID` 可选择同音色包中的其他参考，已注册的默认参考不会自动随机切换。

配置采用 `engine: qwen3`、`reference_id` 和 `references: [{id, audio, text, language}]`，录音使用相对配置文件的路径。参数为 `seed: 42`、`context: 4096`、`max_frames: 500`、`speed: 1`、`gain_db: 0`、`peak_limit: 0.794`。新 Qwen 整页合成由标点控制内部停顿，并追加配置中的 0.2 秒结尾停顿；旧句段缓存拼接仍保留 0.45/0.35 秒的标题、句间停顿。参考文字逐字匹配录音；目标播报语言由上游 deck 的 `language` 决定，英文稿在 `slides prepare --language en` 阶段写好。朗读规范化负责展开数字表达，Qwen 负责词语和专名发音，不继承旧引擎的强制拼写映射。

模型和原生程序在准备后本地复用。原始直播、其余候选参考、模型及缓存保留在运行数据目录；公开技能包只携带配置示例，参考录音留在本地。
