# 报告 A：信息搜集来源核查与实现

**用途：** 将报告 A 第三部分与已核查的一手来源、实际采集行为对应起来。
**状态：** 已验证
**负责人：** 仓库维护者
**最后验证：** 2026-09-11

[English](../../research/2026-09-11-collection-evidence.md)

## 已核查来源

报告正文及其 `appendix/research_sources.json` 标出了以下来源。2026-09-11 已打开核对官方页面。
这些材料说明能力与接口，不构成抓取准确率排名，也不授权绕过发布者的访问限制。

| 报告编号 | 一手来源 | 工程处理 |
| --- | --- | --- |
| 13 | [RSSHub](https://github.com/DIYgod/RSSHub) | 现有 RSS/Atom 入口可读取已确认的 RSSHub 路由。本次没有加入未经测试的路由或公共实例。 |
| 14 | [Mozilla Readability](https://github.com/mozilla/readability) | 正文 HTML、文本与元信息分开；抽取 HTML 展示前仍需清洗。SignalTrail 继续生成自己的文本投影。 |
| 15 | [Trafilatura](https://trafilatura.readthedocs.io/en/latest/) 与[抽取 API](https://trafilatura.readthedocs.io/en/latest/corefunctions.html) | 新增可选本地候选抽取器，排除评论，请求保留表格、链接和格式；实际安装的 2.2.0 已完成集成检查。 |
| 16 | [Crawl4AI](https://docs.crawl4ai.com/) | 作为浏览器抽取参考；现有 Playwright 提供一次有界升级，没有新增第二套浏览器框架。 |
| 17 | [Firecrawl Scrape](https://docs.firecrawl.dev/features/scrape) | API 请求成功与目标页面状态分开。保留为未来 Provider 选项，不声称已安装或完成真实站点效果评测。 |
| 18 | [Tavily Extract](https://docs.tavily.com/documentation/api-reference/endpoint/extract) | 作为抽取服务参考；没有引入凭据或外部 API 调用。 |
| 19 | [Parallel Search](https://docs.parallel.ai/search/search-quickstart) | 搜索摘录仅作发现材料，不改标为完整正文证据。 |
| 20 | [GDELT](https://www.gdeltproject.org/) | 作为全球媒体发现参考；已配置来源覆盖不能代表全球事件频率或完整度。 |

第三部分还引用了编号 2：[被审阅提交中的 SKILL.md](https://github.com/Merak-Wang/signaltrail-skill/blob/c324c5e8529ae22268b2bd53a7b8394f3f8af26f/SKILL.md)，
实际运行仍以当前仓库契约为准。编号 12 是用户的 16 页私人附件《我的 AI 实践：橘鸦 AI 早报》；
研究包只有书目信息，没有附上该 PDF。本次没有重新阅读这份附件，也不声称取得作者未公开的实现。

## 已实现行为

`collection_diagnostics` 在上下文中加入地区 × 主题 × 来源角色的已配置覆盖单元。
它读取根级规范条目，排除监控历史保留项，明确保留失败、限流和未采集的来源。
新索引在 `source_policies` 留存配置维度；旧索引明确标记使用当前配置回退。
角色沿用现有来源角色，不推断政策制定者、劳动者等主体分类；来源数量不等于独立核验数量，
未配置地区也不属于这份诊断的覆盖范围。
监控快照也记录本次刷新的覆盖，包含本次选中的发现来源；其他轮次的历史记录不增加该计数。

上下文还包含 `enrichment_plan`，最多给出正文硬上限数量的缺口建议。
它按来源轮询并保留来源内候选顺序，记录缺失字段、请求来源角色和单动作尝试上限，
不虚构事件身份或主张充分性。协调器仍按编辑重要性显式选择 ID。
已耗尽尝试或受阻的动作不会自动再次推荐。这尚不是任意搜索、主张驱动研究，
也没有实现经过标定的收益/成本评分。

内置抽取器继续保留具体区域的短公告。质量记录新增标题词面覆盖、无显式表头的数值表格、
截断与尚未验证的语义/媒体字段。无表头的数值表格保留单元格，但正文最多为 partial；
标题词面覆盖只用于诊断，不作为语义判定门禁。可选 Trafilatura 仅在基线不足时运行，
只读取已清除脚本、隐藏区域和相关推荐的 HTML。它不能通过删掉内容消除具体正文区域的缺口，
被采用的候选仍为 partial。缺依赖、异常或空结果保留基线，并记录原因。

结构化正文记录输入 SHA-256、字节数、输入类型和截断范围，以及生成器身份、质量及页面自述的
作者、发布者和语言。索引分别记录结构化 JSON 和 Markdown 哈希。缓存复用在存在哈希时复核，
并检查文件解析后仍位于数据根内；没有哈希的旧文件继续可读。浏览器指纹覆盖排除隐藏元素后的
可见 DOM 快照，不冒充原始网络响应。页面声明也不证明作者身份或独立转载关系。

符合条件的部分正文现在会尝试一次浏览器补全。访问限制、不支持的类型、明确的 HTTP 截断，
以及带显式不完整提示的部分正文，不触发该升级。HTTP/浏览器尝试及最终正文缺口停止原因，
与实际选用的证据分开记录。失败或无改进的尝试保留之前可用的正文。
指标区分可用内容、结构上完整的内容和带缺口交付。紧凑质量观测进入摘要和分析输入，
写作 worker 的既有工具边界继续保留。

浏览器在来源配置时限内等待可见正文文字，不再把空容器已挂载视为就绪。
离线无头 Edge 样例包含延迟插入的文章、CSS 隐藏文本和表格，复现了旧路径只读到 Loading 的问题，
修复等待条件后通过。浏览器结果保留了结构化表格并排除隐藏文字；即使开启公共 HTTP 留存，
仍未保存浏览器会话 HTML。

## 配置

旧配置继续使用内置抽取器，并默认不留存原始响应。启用本地候选抽取器时，先在项目环境安装可选依赖：

```sh
python -m pip install -e ".[extraction]"
```

再将以下设置合并到 CLI 使用的配置：

```yaml
collection:
  item_order: source
  fallback_extractor: trafilatura
  retain_public_html: false
```

需要审计且允许留存的公共响应可设置 `retain_public_html: true`，将有界 HTTP 输入保存为
可用结构化证据旁的 `.response.bin`，该文件不会作为网页展示。不保存 Cookie、响应头、挑战页
或浏览器会话 HTML。默认只保存输入指纹。这些产物属于被忽略的运行数据根，不得提交仓库。

普通日报 Top15、显式补全选择、每次 run 累计 12 篇上限、根级/嵌套索引同步与发布快照边界保留。
运行细节归[编辑政策](../../../references/editorial-policy.md)及
[系统契约](../../../references/system-design.md)维护。

## 验证与后续缺口

行为测试覆盖输入与产物哈希、缓存被修改、原响应留存开关、无表头表格、可选依赖缺失/失败、
真实本地 Trafilatura 抽取、单次浏览器升级、保留部分证据、不可变索引修订、来源覆盖、
有界建议队列以及质量传入作者包。这些测试使用构造页面，不代表真实站点抽取准确率。

最终全仓库验证：**479 项测试通过，耗时 50.46 秒**，包含已安装的 Trafilatura 适配器。
Ruff、compileall、中文代码注释、文档与 `git diff --check` 全部通过，另行运行的离线 Edge 验证也通过。
Feed 失败回归确认旧缓存仍能阅读，但不会增加本次覆盖计数。

多语语料验收见 TD-040；逐主张来源关系、主体覆盖及缺口驱动搜索见 TD-041。
本次没有启用托管采集/搜索服务或新的全球发现 Feed。
