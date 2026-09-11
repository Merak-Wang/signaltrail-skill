# 双语讲解实验流程

**状态：** 实施中（Active） · **负责人：** 仓库维护者 · **最后验证：** 2026-09-08

本文说明已实现的日报子产物流程和边界。[English](../explainers.md)

`signaltrail explainer` 可以冻结证据、接收共享主张账本、保存独立中英文稿、准备隔离的语义与双语
审核，并输出 HTML 图文流。它在已保存日报后运行，组合讲解和有条件研判，不修改父报告、索引或连续状态。

当前交付为实验快照流程。`render --mode current` 会明确失败：自动更正链再取证、经过校准的逐主张
过期规则、与宿主完整计量连接的模型调度、真实读者理解测试和多宿主连续验收仍待完成。
`verified_snapshot` 只表示确切稿件对所给证据获得了结构完整的支持性模型审核，
不表示底层新闻经过独立取证或仍然是最新事实。命令不会自动调用模型或对外发布。

## 运行流程

复用既有数据根，使用每一步返回的确切产物路径。默认要求父运行 `completed`；
`--experimental` 只允许为 `completed_partial` 生成有说明的预览。
首版冻结全部精选事件及原始片段，不把普通简报文案视为独立证据，也不偷偷扩大检索范围。

```text
signaltrail explainer prepare --run RUN.json --experimental
signaltrail explainer ledger --packet PACKET.json --input CLAIMS.json
signaltrail explainer script --ledger LEDGER.json --input ZH.json --author-context AUTHOR_CONTEXT
signaltrail explainer script --ledger LEDGER.json --input EN.json --author-context AUTHOR_CONTEXT
signaltrail explainer review-packet --script ZH_SCRIPT.json
signaltrail explainer review-packet --script EN_SCRIPT.json
signaltrail explainer review --packet ZH_REVIEW_PACKET.json --input ZH_REVIEW.json --reviewer-context ZH_REVIEW_CONTEXT
signaltrail explainer review --packet EN_REVIEW_PACKET.json --input EN_REVIEW.json --reviewer-context EN_REVIEW_CONTEXT
signaltrail explainer bilingual-packet --zh-review ZH_RECEIPT.json --en-review EN_RECEIPT.json
signaltrail explainer bilingual --packet BILINGUAL_PACKET.json --input BILINGUAL_REVIEW.json --reviewer-context BILINGUAL_CONTEXT
signaltrail explainer story --script ZH_SCRIPT.json --script EN_SCRIPT.json --bilingual BILINGUAL_RECEIPT.json
signaltrail explainer render --story STORY.json
signaltrail explainer status --script ZH_SCRIPT.json
```

`payload.output_schema` 是实际执行的输出契约，claim ID 和片段 ID 由 Python 分配。
上下文标识由宿主提供，落盘只存摘要。作者与审核者必须使用真实隔离上下文；不同字符串只是防误用检查，
不是安全隔离，也不是模型独立性的证明。用量明确记为 `unmetered`，未知计数保留 null，不能推导精确节省。

两种语言从同一账本分别写作。必讲主张须出现在正文 beat，不能只在标题装饰性挂引用。
图形节点文案写入脚本，纳入独立核验。每种语言有初始稿和一次修复，格式与语义错误共享额度；
精确重放不再扣次数，两种语言可以分别恢复。修改账本需要重新审核下游。

审核者从完整脚本重新抽取断言。接收器要求所有片段恰好覆盖一次，包括标题、转场和视觉标签，
检查原文引用、授权片段、主张登记和必讲覆盖。反驳、证据不足、未登记断言、关键遗漏或
critical/major 问题均保留 Draft，不能用质量分数抵消。判断语义正确仍依赖审核质量。

## 阅读与视觉复核

没有双语回执也可生成明确标注 Draft 的单语或双语预览，便于独立恢复。有回执时必须绑定确切语言对。
渲染器原样展示脚本文字，提供来源链接和可展开的主张详情，用已登记标签绘制原创解释图。
并列关系或叙述顺序不会画成事实因果箭头。本版不准入外部照片；完整正文始终是确定性备用方案。
共享中文账本仅在英文页的可选审计详情里显示，并标记 `lang="zh-CN"`。

在桌面和手机宽度检查两种语言，保存数据根内 PNG 截图，再按 `narrative_contracts.py` 中
`VISUAL_SCHEMA` 提交确切投影摘要、全部 card ID 和截图相对路径：

```text
signaltrail explainer visual-review --projection PROJECTION.json --input VISUAL_REVIEW.json
```

未实际观察的一端应记为 `unavailable`。接收器能核对绑定和图片签名，不能证明截图确实经过阅读。
任何 HTML 或布局变动都需要新投影和视觉复核。本轮不生成语音时长或视频资产。

## 持久化与恢复

记录位于 `narratives/<report-id>-<packet-hash>/`。阶段修订在会话锁内分配；先写临时目录中的 JSON
与权威 Markdown，再原子改名提交，用 JSON 硬链接索引修订。目录提交后若索引创建中断，精确重放会补索引，
不重复分配修订。已保存内容不可覆盖，Markdown 单独绑定字节摘要。加载器递归核对父文件字节和当前策略，
不扫描最新回执替代明确依赖，也不相信作者自报通过。

锁被持有时立即失败，应等待持有进程完成再重试。孤立锁只能在确认原进程不再活动后清除。
临时目录不算已提交记录。投影失败不影响 story 和父报告，可精确重放恢复。
摘要能识别不一致编辑，无法防御可重写全部文件和摘要的本地攻击者。

新流程通过不可变 packet 与提交锁隔离上游 TD-007/TD-025，未全局修复这两项。
实时准入和正式验收继续记录在[路线图](roadmap.md)与[技术债](exec-plans/tech-debt-tracker.md)。
