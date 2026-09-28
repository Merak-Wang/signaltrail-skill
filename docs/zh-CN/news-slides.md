# 新闻幻灯片

**状态：** 已验证 · **负责人：** 仓库维护者 · **最后验证：** 2026-09-23

新闻幻灯片是从已保存日报及其匹配索引生成的独立动态 HTML 放映稿。每条入选新闻占一页，展示来源、摘要、可用图片、原站 caption 和模型撰写的讲解。候选范围覆盖整份已保存日报中的精选事件与简报，不按发布日期二次筛选，也不从索引中直接添加日报之外的条目。同一原文合并并保留全部来源引用，再按重要性降序排列；默认取前 50 条，可用 `slides prepare --max-news N` 设置其他正整数，也可用 `finalize-edition --slides-max-news N` 配置定稿流程。没有按来源预留名额的保证。新一期默认前 50 条；恢复既有运行且未显式指定数量时沿用上次设置，明确修改数量才准备新计划。发布日期未知时保持未知，不以发现、采集或索引更新时间代替。没有图片不影响入选。此投影不改变主日报。有放映文件时，日报 HTML 会在屏幕上用嵌入式演示替代今日摘要，并保留“打开图文演示”独立入口；打印时隐藏嵌入演示并恢复摘要。日报 JSON 和 Markdown 保持原样并继续作为事实依据；只要放映投影存在，之后重建日报 HTML 时也会保留演示入口。

视觉参考为 [Frontend Design 示例 site-02](https://mimo.xiaomi.com/mimo-v2-6/assets/frontend/site-02/)：暖灰白背景（`#f3f4ef`）、深绿黑文字（`#1c2422`）、少量陶土橘强调色、大字号衬线标题、错落的编辑式分栏、细分隔线和侧边编号。新闻图片保持原始比例，转场遵循减少动态效果偏好。模板在本地确定性渲染，样式不增加模型调用或生成成本。

在线读取原文时共用一个 HTTPX 连接池；按域名轮转的调度器会在全局槽位空出时补入可执行来源，同时遵守全局和单域并发上限。图片下载也使用有界并发。

默认在线渲染时，新闻图片合并日报封面图、索引正文图片候选，以及从入选新闻公开页面补充的图片和原始图注。遇到 arXiv 摘要页时，只跟随页面明确提供的同论文 HTML 全文链接补充受支持的正文图片；SVG 图仍不支持。候选按发布者明确提供的 `srcset`、URL 宽度和 DPR 声明择优，并遵循配置的下载预算；实际清晰度受发布者提供的版本及下载成功情况限制。正文内的游戏、推广、订阅和同页推荐容器不计入正文配图；解析为同一内容的候选只展示一次。页面抓取或图片下载失败时保留索引中的原候选。图片补充不会修改已保存的正文证据或访问等级，也不会增加模型调用。候选按图片身份去重，每条新闻不设固定张数上限。图集支持缩略图选择、查看大图、按原始尺寸 100% 查看，以及直接打开原始图片链接；原站 caption 随对应图片保留，缺失时留空，不以 alt 替代。页面优先加载当前新闻与下一条新闻的图片，其余新闻按需加载；同一张本地图片在每次渲染中只编码一次。

Hacker News、Lobsters 等发现型来源仍保留平台提交日期，原网页日期另存于 `metadata.content_source.published_at`；直接发布来源保留原站日期。日期用于如实呈现来源信息，不作为从已保存日报中剔除候选的条件。跨日或含未知日期的聚合事件保留完整来源引用，不删掉旧来源后沿用原摘要。

## 默认日报流程：准备、写作与渲染

日报定稿时会自动根据已保存报告及对应索引准备幻灯片计划和有界写作包。默认早报/晚报无论 metered 或 unmetered 都必须生成图文流。“报告已保存”表示报告文件可用；只有讲稿全部提交、渲染完成、tail 退出且通过整期验收，才表示“整期交付完成”。可先交付已保存报告与 HTML，同时明确其余步骤仍待完成。运行清单会在
`artifacts.slides.plan_path` 和 `artifacts.slides.packet_paths` 记录路径；准备阶段不会调用模型。
各数据包彼此独立，每波最多并行写作三包；等整波返回后再启动下一波，并逐包提交结果。SignalTrail 的 Hermes 集成通过
`delegate_task(background=False)` 同步等待整波返回，并将 `max_concurrent_children` 限制为三。若定稿使用
`--defer-tail`，可在后台执行运行清单中的精确 `tail.command`，同时完成图文讲稿；保留进程句柄和退出码，
并等尾任务退出后再渲染，因为尾任务与幻灯片渲染都可能更新日报投影。准备失败不会影响已保存日报，
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

候选覆盖整份日报中的精选事件与简报；先按原文身份去重、合并来源引用，再按重要性降序排列，默认取前 50 条。可用 `slides prepare --max-news N` 指定其他正整数，定稿流程可用 `finalize-edition --slides-max-news N` 配置。此上限适用于整期，不按来源预留名额。恢复时未显式修改数量则沿用已保存设置，显式更改数量会准备新计划。日报外的索引条目不会直接补入；旧日期和未知发布日期仍可入选，未知日期不得由发现或采集时间伪造。无图新闻仍会入选。每个写作数据包包含一组有界新闻，默认每批四条；数据包携带风格说明、输出 Schema、允许采用的分析视角和指定日报证据。

写作时只读取 `packet.payload.model_input`；Schema 位于 `payload.model_input.output_schema`，成本预留单独位于 `payload.budget`。将结果保存为 JSON 后运行 `signaltrail slides submit --packet PACKET.json --input DRAFT.json`。每个分配事件都要且只要输出一次 `{event_id, narration, perspectives}`。`perspectives` 可以为空，只能选择该事件分析中存在且相关的 `geopolitics`、`markets`、`ai_technology`。模型输出不要重复标题、摘要、来源、图片 URL 或 caption；这些由程序附加。成功提交会复用；无效草稿不会自动触发修复。

每个 worker 只处理一个 packet；最多同时运行三包，当前波次全部返回后再分发下一波。

数据包内含[讲解风格](../../templates/news-slide-style/SKILL.md)，写作端无需再加载额外编辑资料。中文 narration 会硬校验 200–350 个非空白字符，标点计入；英文 narration 没有对应的长度校验。结构校验不代表事实已经独立验证。采集应覆盖可获取的中英文来源并检查整体语言覆盖，不按输出语言过滤来源；用户本次明确选择优先，其次已保存偏好或当前 run，最后默认 `zh-CN`。协调者为日报和 packet 选定同一目标语言，写作者严格遵循 `payload.model_input.language`，不自行重选。保留原文标题和 URL 溯源；不要求每条都同时有中英文材料，不把转载当独立佐证。跨语言核对名称、数字、职务、时态和限定语；重要事实冲突时补证，没有证据就保留未知。

事实核验从采集与选题阶段开始：确认原文主体及职务、动作时态、日期和关键数字；容易造成重大误解的事实，按需查一手材料或独立来源。验证记录留在后台。起稿时在有界证据内复核每个句子及类比带出的断言，保留“涉嫌、计划、声称”等限定语。证据不足时暂停写稿，不得私改冻结的 packet；协调者完成补证后生成新版本 packet，再继续写作；无法补证则删掉无据断言。

默认采用鲜明、口语化的新闻脱口秀表达：先在后台挑出一个值得讲的矛盾或观察点，观众只听成稿；不要把核验过程、操作教程或一串限定语写成主体。只把影响结论的“部分机型”“可关闭”等限定自然交代一次。通过长短句和停顿形成节奏，结尾落在有证据支撑的观点或画面，不以知识点罗列收尾。幽默可选，题材不适合时严肃表达；不拿受害者、不确定性或来源缺口开玩笑，不编造引语或人物心理。不要反复用“材料有限”“地缘分析”“后续观察”等套话凑篇幅。调整批大小或 token 门槛时，查看[预算与数据包参考](../../references/news-slides.md)。

使用 `artifacts.slides.plan_path` 与 `artifacts.slides.packet_paths[]` 中的真实路径；每批草稿放在对应 packet 旁并命名为 `batch-N-draft.json`（N 为批次号）。所有批次都提交且 tail 退出后再渲染：

```text
signaltrail --data-dir DATA_DIR slides submit --packet PACKET.json --input DRAFT.json
signaltrail --data-dir DATA_DIR slides status --plan PLAN.json
signaltrail --data-dir DATA_DIR slides render --plan PLAN.json
signaltrail --data-dir DATA_DIR edition-status --run RUN.json --require-complete
```

渲染会生成可切换的 HTML 幻灯片、结构化 deck JSON 和 Markdown。新闻标题、摘要和来源引用取自日报；索引提供来源名称、发布时间及已有图片候选。默认在线渲染会读取入选新闻的公开原文页，补充图片和原站 caption，按页面明确提供的 `srcset`、URL 宽度和 DPR 选择候选，并在配置下载预算内缓存成功下载的图片。页面或图片获取失败时保留原候选；此过程不修改正文证据或访问等级，也不调用模型。`--offline` 从已有 deck 和图片文件重建，不抓取页面或下载图片，适用于只调整版式。候选按图片身份去重，实际清晰度取决于原站提供的版本和下载情况，每条新闻不设固定配图上限。图集可选择缩略图、查看大图、按原始尺寸 100% 查看并打开原始图片链接。caption 保留原站抽取文本，缺失时留空，不以 alt 替代。若仍有写作批次待提交或缺失，渲染会停止，不会静默漏掉已分配新闻。状态命令显示已完成和待处理批次。HTML 样式及转场是确定性生成。

`slides prepare` 只读取传入的已保存日报和索引，不会联网抓取网页或调用模型。整份报告是候选范围；`index.items[].published_at` 仅作为来源日期信息，不用于筛除候选，缺失日期保持未知。若需要先补充正文证据，可对选定条目运行正式的 `extract-content` 命令，再用其返回的富化索引准备幻灯片。该命令提取文章正文并生成新索引修订；在线渲染则另行从入选新闻公开页面补充图片。仅图片元数据变化时可复用已接受讲稿，无需再次调用模型。

## 批次成本门槛

在 `slides prepare` 上通过 `--max-news` 设置整期数量，并通过 `--batch-size`、`--max-input-tokens`、`--max-output-tokens` 配置每批上限。默认前 50 条、每批四条、输入估算 12,000 token、输出估算 4,000 token。输出按每条新闻预留 700 个估算 token；输入估算为序列化数据包 UTF-8 字节数除以 2，再加 512 token 预留。这是粗略体积门槛，与 tokenizer 精确计数无关，也不是美元报价或宿主实际用量保证；除非宿主提供实际用量，否则仍记为未知（`null`）。选中的新闻按需要分多批处理。

模型调用由宿主负责。SignalTrail 负责准备有界数据包和接收结果，不会自动调用模型、重试草稿或额外调用审核模型。
