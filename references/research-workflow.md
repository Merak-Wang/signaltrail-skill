# 并行研究运行参考

**权威语言：** 中文（单语运行参考）
**负责人：** 仓库维护者
**状态：** 实验工作流；日报准入仍阻断
**最后对照代码：** 2026-09-23

本参考描述的研究命令是实验工作流，不属于正式日报发布路径。研究不加入日报完成等待；宿主
可为日报保留资源并为研究任务独立计量。命令本身不自动调用模型或搜索网站。当前组合阅读只生成
`preview` 投影，`current` 模式明确拒绝；准入适配和实时接收仍待实现。默认只写所需语言。

## 问题与冻结资料

从本轮规范索引选择最多 24 篇已批准文章，问题最多 12 个，每篇最多 8000 字符。
标题、描述和结构正文块共同消耗字符限额，截断明确记录。未取得正文保持原状态，不能升级为全文。
问题可以指向成本、资源、准入、历史变化、反证和未来检验；没有证据的视角不强行补写。

```json
{"questions":[{"key":"cost","domain":"ai_technology","question":"算力成本 compute cost",
"weight":1,"state":"not_evidenced","evidence_span_ids":[],"gap":"缺同业务量、同质量的账单"}]}
```

```text
signaltrail research prepare --index INDEX.json --item-id ITEM_ID --cutoff 2026-09-20T09:00:00+08:00 --questions QUESTIONS.json
signaltrail research search --snapshot SNAPSHOT.json --query "compute cost" --limit 6
signaltrail research select --snapshot SNAPSHOT.json --limit 6
signaltrail research questions --snapshot SNAPSHOT.json --input FINDINGS.json
```

`FINDINGS.json` 使用同一 questions 结构；状态为 `answered / partial / contested / not_evidenced`。
除未建立外都需定位片段；未回答问题需具体 gap。未提及的问题保留。
检索输出只是候选，需读原文后判断。BM25 使用英文词项和中文二元组，没有自动翻译或向量检索。
发现源可通过 `prepare --discovery MONITOR.json` 与本轮索引一起选取显式 ID；不向日报索引追加数据。所选 Feed 正文块可以进入研究，正文状态不会因此自动升格。新材料经原采集工具进入索引后，用 `prepare --previous SNAPSHOT.json` 冻结新快照。
问题文件可为 `{"questions":[]}` 以沿用旧问题；变化证据会清除旧回答支持。

来源 metadata 可记录 `original_record_url` 或 `original_record_id`、`source_role`、`language`、
`speaker`、`reporting_scope`、`publisher_caption`。这些字段是人工/采集器的来源记录，不是独立认证。
相同原始记录与同文指纹用于减少重复；未知来源保持未知，不能把域名数算成佐证数。

## 底稿、成稿和审核

读取快照的 `payload.memo_output_schema`，提交 `memo / analyses / claims`。
分析写清 `conditions / counterargument / watch`；主张引用 `analysis_keys / question_keys`
和具体 `evidence_span_ids`。Python 分配研究分析、事件、主张 ID，并复用原账本检查。
底稿是研究工作记录，不直接当成已审核正文；想向读者呈现的判断应进入脚本并审核。

```text
signaltrail research memo --snapshot SNAPSHOT.json --input MEMO.json
signaltrail explainer script --ledger LEDGER.json --input SCRIPT.json --author-context AUTHOR_CONTEXT
signaltrail explainer review-packet --script SCRIPT_REVISION.json
signaltrail explainer review --packet REVIEW_PACKET.json --input REVIEW.json --reviewer-context ISOLATED_CONTEXT
signaltrail explainer story --script SCRIPT_REVISION.json --review REVIEW_RECEIPT.json
signaltrail explainer render --story STORY.json
```

写作时只读取[中文风格卡](../templates/research-style-zh.md)或[英文风格卡](../templates/research-style-en.md)。
双语请求仍用共同账本、两份单语审核和既有双语一致性流程。每种语言初稿加一次修复。
表格为可选 `beat.table`：`headers` 与 `rows` 的每个单元格以及 `editorial_caption` 均为
`{"text":"...","claim_ids":[...]}`；原创建表的 `publisher_caption` 必须为 null。
程序检查列数和引用，独立审核逐项检查数字、单位、限定、归因和因果。表格不用图片也能离线阅读。
现有外部照片限制保留；未知图片权限不靠 URL 可访问替代。

## 日报完成后晚绑定

关系文件形如 `{"relations":[{"research_analysis_id":"RA-...","report_analysis_id":"ANALYSIS-MARKETS",
"relation":"qualifies"}]}`；值必须使用实际返回 ID。无相关原分析时可为空列表。

```text
signaltrail research bind --story STORY.json --run RUN.json --relations RELATIONS.json
signaltrail research render --binding BINDING.json
signaltrail research evaluate --snapshot SNAPSHOT.json
```

正常绑定要求支持性审核和完成日报。`bind --experimental` 允许明确标识的草稿或部分完成预览。
组合 HTML 在三视角和综合之后追加图文；Markdown 在原报告后追加研究附录。
旧文件不更新，新关系或新脚本产生新修订。`--mode current` 仍拒绝。
阅读页语义审核、视觉检查、真实读者理解和生产时延分别记录，不用一个自评分取代。
