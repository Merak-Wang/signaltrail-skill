# 采集扩展与研究接口

实时采集与当前监控快照命中同一来源、同一规范文章时，保留实时排序和访问状态；缺失摘要及身份匹配的有效 Feed 正文可从快照补充，过期和纯导航内容不参与补充。

**状态：** 已验证 · **负责人：** 仓库维护者 · **最后验证：** 2026-11-02

本文介绍本地采集监控、发现来源补充、RSSHub、Crawl4AI，以及供集成使用的日报、事件与研究接口。[English](../platform.md)

## 采集监控与日报交付

日报通过 [SKILL.md](../../SKILL.md) 按需生成。以下命令仅为可选的采集检查工具。服务默认只读，不启动定时采集；没有快照时也不自动采集。生成日报无需启动服务。

```sh
signaltrail --data-dir DATA_DIR refresh-monitor
signaltrail --data-dir DATA_DIR serve --open
```

使用生成日报时的同一个绝对数据根。默认地址为 `http://127.0.0.1:8765`。监控工具展示采集新闻、词汇聚类、来源健康和待验证来源；刷新与聚类不调用模型。正式日报及其投影按 [SKILL.md](../../SKILL.md) 的完整日报流程生成和交付。

原题、目标语言译题、摘要与研判继续遵循已保存报告的语言契约。版本化 JSON／Markdown 是权威记录；报告 HTML、PDF、图文讲解与视频沿用既有交付路径。

`/api/editions`、`/api/edition` 提供日报目录查询，事件、关注与研究接口供其他客户端集成。日报 API 只返回实际生成的语言版本；缺少所请求语言时返回 `unavailable`、请求的日期版次与可用版本。

长期事件、文章、关注与研究记录保存在 `DATA_DIR/platform/events.sqlite`。归档同步复用监控器完整的有效分组，沿用其配置阈值与故事身份，仅为缺少分组或分组混入导航链接的文章重新聚类。事件 API 在日报与事件有关联时可投影对应的证据、标题、摘要与分析。

## 研究一个事件

保留的研究 API 接收已归档事件、问题、可选研究视角与语言，任务记录提供等待／执行／完成／失败状态，以及保存的研究结果和来源。研究通过 API 或下列命令接入。研究服务冻结事件证据供本地宿主读取，使用单个工作线程，并复用相同的活动任务。研究会调用宿主模型；阅读、Feed 采集与事件排序不调用模型。

服务默认复用已安装的 Hermes 命令及其模型配置。启动 `serve` 前可设置 `SIGNALTRAIL_RESEARCH_PROVIDER` 和／或 `SIGNALTRAIL_RESEARCH_MODEL`，仅覆盖自动 Hermes 研究子进程所用的提供方与模型。留空时继承已有 Hermes 配置；Hermes 全局配置保持原值。这两个变量不作用于 `SIGNALTRAIL_RESEARCH_COMMAND`，自定义命令的参数数组完全由用户指定。任务的 `worker` 字段记录执行后端和显式选择的提供方／模型。可以通过 `SIGNALTRAIL_RESEARCH_COMMAND` 配置其他本地宿主：值为包含 `{packet}` 与 `{output}` 占位符的 JSON 参数数组。命令读取 UTF-8 JSON 证据包，把声明的结果 JSON 写入输出路径。启动 `serve` 前配置该命令。

```text
SIGNALTRAIL_RESEARCH_COMMAND=["your-agent-command","--packet","{packet}","--output","{output}"]
SIGNALTRAIL_RESEARCH_TIMEOUT_SECONDS=180
SIGNALTRAIL_RESEARCH_COOLDOWN_HOURS=6
```

宿主不可用时，任务进入 `awaiting_model`，保留证据包供外部宿主处理。显式设置空命令数组 `[]` 可选择这种外部宿主方式。任务保留具体执行错误，完成后结果关联到原事件。

使用当前 Skill 宿主处理等待任务时，先列出任务、读取返回的冻结证据包，按包内要求写结果 JSON，再提交：

```sh
signaltrail --data-dir DATA_DIR platform-research list --status awaiting_model
signaltrail --data-dir DATA_DIR platform-research submit --job JOB_ID --input RESULT.json
signaltrail --data-dir DATA_DIR platform-research run --job JOB_ID
```

服务运行期间，已关注事件出现实质新证据时还会调度研究，默认冷却六小时。重复证据和相同内容的转载不触发新分析。

## 发现来源配置

[发现来源配置](../../configs/discovery-sources.yaml)覆盖国际、国内、市场、科技与开源信息。编辑来源的 Feed 地址和 `enabled` 设置调整采集范围；实际可用性在监控的来源健康中查看。发现来源配置 `report_target: 0` 和 `report_max: 0`，入选共享补充池后按实际选题数参与日报。

## 采集窗口与来源顺序

核心来源缓存资格统一使用该期冻结的 `collection_window`。陈旧 Feed 响应、历史保留项以及明确在窗口外的发布时间不计作可跳过来源刷新的当前覆盖；缺少发布时间仍保持未知。

按需生成日报时，近期快照还会对照新启用来源、变更的 Feed 入口和各来源自己的 `checked_at`，只补采缺失、变更或过期的来源。局部更新保留其他来源原有观测时间。陈旧 Feed 条目继续可读，同时允许备用 Feed 发现与静态 HTML 回退；当前 Feed 或 HTML 材料替换相同 URL 的陈旧副本。

采集结束后，非 discovery 来源按“明确窗内条目→未知日期／历史条目”稳定分区，分区内保留原顺序，出版方排名继续保存在 `metadata.source_rank`。`role=discovery` 的论文和代码仓库榜单保留排名语义。核心来源目标数保持原值。

简报编排按 canonical URL 为每篇文章分配一个位置。依照现有来源与条目顺序扫描，遇到重复便从该来源后续唯一文章补位，保留来源目标、栏目配额和原始排名；压缩写作输入也包含这些后续候选。唯一文章不足时，`brief_plan.shortfall_count` 记录实际短缺。同标题或同事件的不同地址报道分别保留。发现共享池与已选核心文章排重；未选尾部候选不会挤掉发现文章。

发表、修订和观测时间分别保存。ISO、RFC 和明确的 `YYYY/MM/DD` 日期统一格式；没有时分秒的日期保留日粒度，由 `metadata.published_precision` 标识。`updated_at` 保存来源修订时间，`first_discovered_at` 保存保留记录中的最早观测。纯日期与冻结窗口按日区间重叠判断，标记 `published_date_overlap` 和 `WATCH`；未知发表时间也使用 `WATCH`。

研究榜单保留原排名与原发表日期。相邻快照比较产生 `new_listing`、`reappeared`、`rank_rise` 或 `updated`，并保存稳定的 `signal_at`。首次没有基线时为 `bootstrap_watch`，普通刷新沿用原信号时间。旧论文和项目可以凭窗口内的榜单信号进入研究雷达，状态为 `WATCH`；排名上升表达已有研究重新受到关注。

已经保存的 Feed 字段还通过 `feed_content_path`、字符数与独立的部分证据标记提供给简报和分析作者。直接读取 JSON 的 text/blocks 不增加网络操作，也不将 Feed 材料升格为已验证的文章全文。

## 将发现来源纳入后续日报

`collection.discovery_brief_limit: 30` 为新一期完整采集／日报启用共享补充简报池；设为 `0` 关闭，允许范围为 `0..120`。默认 30 个名额按国际 15、市场 6、科技 9 分配，每个来源最多两条；领域不足时按国际／市场／科技顺序补空位。

选取复用新鲜监控快照。新闻使用日报冻结 24 小时窗口内的发表时间或重叠发表日期；论文和项目还可凭本期榜单信号入选。排除陈旧缓存、历史保留项和明确的未来发表日期，按 canonical URL 去重。显式按来源定向采集不追加该池。新索引只为实际入选的发现来源记录一至两条简报策略，再进入正常简报与三视角分析流程。已生成的历史日报保持原版本。

## 正文补证

`enrichment_plan` 综合重要度、可观察的结构缺口、已有 Feed 材料、有界抓取成本，以及已选来源和领域的递减优先级，排列补证建议。同一 canonical URL 最多一个动作；协调者在原有每轮上限内决定最终 ID，作者继续读取有界 packet。

HTTP 与浏览器共用具体正文区域和结构表格抽取。明确声明的表头与跨行跨列保留，数值表格缺少显式表头时继续记录缺口。文本 PDF 复用有界 HTTP 响应，由 `pypdf` 提取至多 80 页并保存页码，证据状态为 `partial`；扫描、加密或不可读文件保留元数据与 Feed 底稿。

Trafilatura 已列入基础依赖，作为内置抽取仍有缺口时的默认本地备用器；已有完整正文直接复用。具体正文区域与表格继续保留；替换已有部分正文时，候选须按字符加权保留至少 70% 的实质文字块。候选可以补出更多文字，直播报道大幅缩短时保留原正文。`fallback_extractor: none` 关闭这项比较。

归档事件的 Feed、标题或描述发生实质变化时，关联正文进入重验；更新成功前，研究 packet 使用当前 Feed 或描述。新取得的部分正文可以替换过期全文；仅发现时间变化时继续复用正文。每个研究任务冻结自己的证据包。

```yaml
collection:
  discovery_brief_limit: 30
```

## 使用 RSSHub 扩展来源

RSSHub 作为外部服务运行。配置可访问的自托管实例和来源路由；`feed_urls` 内的原生 Feed 优先使用。[平台来源示例](../../configs/platform-sources.example.yaml)提供完整的发现来源配置。

默认来源目录使用原生 Feed，目前没有启用 RSSHub 路由。配置实例和路由后，适配器才参与实际采集；普通日报生成不会启动 RSSHub 服务。

```yaml
rsshub:
  base_url: http://127.0.0.1:1200
sources:
  - id: rsshub_updates
    name: RSSHub Updates
    url: https://t.me/s/awesomeRSSHub
    feed_urls: []
    rsshub_route: /telegram/channel/awesomeRSSHub
    module: technology
    category: open_source
    role: discovery
    report_target: 0
    report_max: 0
```

运行 `signaltrail --config configs/platform-sources.example.yaml --data-dir DATA_DIR refresh-monitor` 采集示例。先将地址与路由替换为实际部署的实例。路由可用性取决于上游网站和该实例；示例路由尚未进行部署验收。RSSHub 使用 [AGPL-3.0](https://github.com/DIYgod/RSSHub/blob/master/LICENSE) 许可证。

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
