# 采集扩展与档案接口

实时采集与当前监控快照命中同一来源、同一规范文章时，保留实时排序和访问状态；缺失摘要及身份匹配的有效 Feed 正文可从快照补充，过期和纯导航内容不参与补充。

**状态：** 已验证 · **负责人：** 仓库维护者 · **最后验证：** 2026-11-11

本文介绍本地采集监控、发现来源补充、RSSHub、Crawl4AI，以及供集成使用的日报与事件档案接口。[English](../platform.md)

## 采集监控与日报交付

日报通过 [SKILL.md](../../SKILL.md) 按需生成。以下命令仅为可选的采集检查工具。服务默认只读，不启动定时采集；没有快照时也不自动采集。生成日报无需启动服务。

```sh
signaltrail --data-dir DATA_DIR refresh-monitor
signaltrail --data-dir DATA_DIR serve --open
```

使用生成日报时的同一个绝对数据根。默认地址为 `http://127.0.0.1:8765`。监控工具展示采集新闻、词汇聚类、来源健康和待验证来源；刷新与聚类不调用模型。正式日报及其投影按 [SKILL.md](../../SKILL.md) 的完整日报流程生成和交付。

原题、目标语言译题、摘要与研判继续遵循已保存报告的语言契约。版本化 JSON／Markdown 是权威记录；报告 HTML、PDF、图文讲解与视频沿用既有交付路径。

`/api/editions`、`/api/edition` 提供日报目录查询，事件与关注接口供其他客户端集成。日报 API 只返回实际生成的语言版本；缺少所请求语言时返回 `unavailable`、请求的日期版次与可用版本。

长期事件、文章与关注记录保存在 `DATA_DIR/platform/events.sqlite`。归档同步复用监控器完整的有效分组，沿用其配置阈值与故事身份，仅为缺少分组或分组混入导航链接的文章重新聚类。事件 API 在日报与事件有关联时可投影对应的证据、标题、摘要与分析。


## 发现来源配置

[扩展来源配置](../../configs/discovery-sources.yaml)覆盖国际、国内、市场、军事、技术新闻与论文；启用条目进入现有正式日报栏目，实际可用性见来源健康。旧配置的零目标不限制入选，新版索引策略记录每源实际入选数量。

## 采集窗口与来源顺序

日报来源会读取配置中有限页面的全部文章，达到旧有 15 条目标后仍继续检查这些页面。显式限制条数的来源才按原文日期与冻结上界判断缓存覆盖是否充足；昨日文章、未知原文日期和上榜时间不计入该门槛。陈旧 Feed 与历史保留项仍排除。

按需生成日报时，近期快照还会对照新启用来源、变更的 Feed 入口和各来源自己的 `checked_at`，只补采缺失、变更或过期的来源。局部更新保留其他启用来源的观测时间。刷新时从当前快照移除已删除或停用来源的条目和健康记录，历史档案继续保留。陈旧 Feed 条目继续可读，同时允许备用 Feed 发现与静态 HTML 回退；当前 Feed 或 HTML 材料替换相同 URL 的陈旧副本。

采集结束后，非 discovery 来源按“明确窗内条目→未知日期／历史条目”稳定分区，分区内保留原顺序，出版方排名继续保存在 `metadata.source_rank`。`role=discovery` 的论文和代码仓库榜单保留排名语义。核心来源目标数保持原值。

简报编排对合格当日原文同源去重后，按原发时间从新到旧选取每源最多15条。同源规范URL去重，跨源各保item_id、引用及原始source_rank，相同原文复用写作；过滤后不重编号。跨出版方同一事件的语义合并与影响力排序单独用于图文视频。

采集索引保留实际观察到的完整文章集合及访问状态。在当日筛选之前，对缺少原文日期的文章有界读取网页元数据，按规范 URL 合并请求，并复用此前已取得的日期。发布日期来自出版方元数据、文章 JSON-LD 或经核对的列表字段；更新、上榜和采集时间各自保留。各出版方的文章路径规则排除导航链接。已成功取得历史或无日期文章的来源保持采集成功，本版写作数量可以为零。

通过本版筛选的文章可利用日期探测取得的完整 HTML。沿用原正文抽取器保存可复用的全文、结构化块和图片引用，正文补证选中该文章时直接复用，省去第二次 HTTP 请求。截断响应、不完整正文和缺表头等证据缺口继续走原补证流程。浏览器响应只在内存中处理，不保存原始 HTML。

微博保留官方入口，并配置公开 60s API 作为备用；每条热榜记录 `listing_endpoint`，热度排名没有原文发布时间。Hugging Face 论文页使用 `paper.publishedAt`，`submittedOnDailyAt` 仍表示上榜观测。“几小时前”等相对时间须补得原文日期后才能参与当日筛选。研究目录只提供年或月时保留其精度限制。

Google News 条目声明的日期与已确认的发布者日期分开。静态包装页可访问但没有原文日期时，使用无账号浏览器执行其正常公开跳转，读取发布者的日期元数据。完整的发布者 HTML 可按相同规则复用正文。实际访问失败继续保留，解析到的原文地址仍可供后续正文补证使用。话题合辑页排除出文章候选。

发表、修订和观测时间分别保存。ISO、RFC 和明确的 `YYYY/MM/DD` 日期统一格式；没有时分秒的日期保留日粒度，由 `metadata.published_precision` 标识。`updated_at` 保存来源修订时间，`first_discovered_at` 保存保留记录中的最早观测。纯日期与冻结窗口按日区间重叠判断，标记 `published_date_overlap` 和 `WATCH`；未知发表时间也使用 `WATCH`。

研究榜单保留原排名与原发表日期。相邻快照比较产生 `new_listing`、`reappeared`、`rank_rise` 或 `updated`，并保存稳定的 `signal_at`。首次没有基线时为 `bootstrap_watch`，普通刷新沿用原信号时间。旧论文和项目可以凭窗口内的榜单信号进入研究雷达，状态为 `WATCH`；排名上升表达已有研究重新受到关注。

已经保存的 Feed 字段还通过 `feed_content_path`、字符数与独立的部分证据标记提供给简报和分析作者。直接读取 JSON 的 text/blocks 不增加网络操作，也不将 Feed 材料升格为已验证的文章全文。

## 将发现来源纳入后续日报

两个配置文件中的启用来源均进入现有日报栏目。默认配置共 45 个来源 ID，其中 43 个启用。每源从有限公开Feed/页面响应中选取本版上海自然日、冻结上界之前的最新最多15条可验证原文；字节和配置页面边界保持有限。未知/旧原文、平台提交和上榜时间不作今日资格。同源canonical去重，跨源保展示位置、相同原文复用写作。旧共享30池和每源1/2限额不再限制日报；图文/视频另做语义事件合并并按影响力选至多50条。

默认配置停用 IRNA English (`irna_en`) 和 Emirates News Agency (`wam_en`)。

## 正文补证

`enrichment_plan` 综合重要度、可观察的结构缺口、已有 Feed 材料、有界抓取成本，以及已选来源和领域的递减优先级，排列补证建议。同一 canonical URL 最多一个动作；协调者在原有每轮上限内决定最终 ID，作者继续读取有界 packet。

HTTP 与浏览器共用具体正文区域和结构表格抽取。明确声明的表头与跨行跨列保留，数值表格缺少显式表头时继续记录缺口。文本 PDF 复用有界 HTTP 响应，由 `pypdf` 提取至多 80 页并保存页码，证据状态为 `partial`；扫描、加密或不可读文件保留元数据与 Feed 底稿。

Trafilatura 已列入基础依赖，作为内置抽取仍有缺口时的默认本地备用器；已有完整正文直接复用。具体正文区域与表格继续保留；替换已有部分正文时，候选须按字符加权保留至少 70% 的实质文字块。候选可以补出更多文字，直播报道大幅缩短时保留原正文。`fallback_extractor: none` 关闭这项比较。



## 使用 RSSHub 扩展来源

RSSHub 作为外部服务运行。复制[平台来源模板](../../configs/platform-sources.example.yaml)，将 `rsshub.base_url` 设为自己的实例地址。在 `sources` 中添加来源，为每项填写 `id`、`name`、`url` 和 `rsshub_route`。SignalTrail 优先使用 `feed_urls` 中的原生 Feed。

配置完成后运行 `signaltrail --config CONFIG_FILE --data-dir DATA_DIR refresh-monitor`。路由可用性取决于上游网站和 RSSHub 实例。RSSHub 使用 [AGPL-3.0](https://github.com/DIYgod/RSSHub/blob/master/LICENSE) 许可证。

## 可选 Crawl4AI 正文抽取

在 SignalTrail 所用 Python 环境安装可选依赖和浏览器运行时：

```sh
python -m pip install -e ".[crawl4ai]"
crawl4ai-setup
```

```yaml
collection:
  browser_extractor: crawl4ai
```

默认 `browser_extractor: auto` 先执行 HTTP。选中文章确需渲染时，非交互运行优先使用已安装的 Crawl4AI SDK，其余使用 Playwright；可见窗口请求使用 Playwright。显式 `playwright` 或 `crawl4ai` 选择对应后端。每篇只尝试一个浏览器，启动失败时保留已有 HTTP 材料及错误。Crawl4AI 保留正文、可用的图片和视频候选供阅读使用，Feed 继续走原有采集流程。

Crawl4AI 的 [LICENSE](https://github.com/unclecode/crawl4ai/blob/main/LICENSE) 包含 Apache-2.0 正文与附加署名要求：

This product includes software developed by UncleCode (https://x.com/unclecode) as part of the Crawl4AI project (https://github.com/unclecode/crawl4ai).
