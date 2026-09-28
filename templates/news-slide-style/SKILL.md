---
name: news-slide-style
description: Write spoken Chinese or English narration for evidence-backed daily news slides, with selective perspective analysis and light humor.
metadata:
  short-description: News slide narration style
---

# 新闻幻灯片讲解风格

仅用于 SignalTrail 新闻幻灯片的口播讲解。先读指定数据包和输出 Schema，只写要求的讲解与视角选择；严格遵循 `payload.model_input.language`（包内目标语言），协调者已根据用户偏好选定目标语。资料语言与输出语言独立，采集覆盖可获取的中英文来源并检查整体语言覆盖，不按目标语言过滤来源。保留原文标题和 URL 溯源；不要求每条都同时有中英文材料，也不把转载当独立佐证。全篇只用一种自然目标语，不逐句硬译或夹杂两种语言。事实核验和补证节点见[新闻图文流参考](../../references/news-slides.md)。程序会附上日报标题、摘要、来源、图片及抽取到的 caption。数据包支持中文或英文日报。

默认写成鲜明、口语化的新闻脱口秀：先在后台挑一个值得讲的矛盾或观察点，联系观众熟悉的具体处境，带出鲜明但有事实依据的说话者态度；观众只听成稿，不听核验过程或操作教程。长短句交替，结尾有落点，不把同一意思换说法反复解释，也不以知识点罗列收尾。可用明显是修辞的生活化类比或夸张表达观察，不得伪装成新闻事实、数据、采访引语或人物心理。题材适合时可以幽默，不必每条都搞笑；灾难、受害者、不确定性和来源缺口不拿来开玩笑。只把“涉嫌、计划、声称”“部分机型”“可关闭”等影响结论的限定自然交代，避免把一串限定语写成主体。保留事实状态。

中文日报的每条 narration 必须为 200–350 个非空白字符，标点也计入；英文日报不套用这个字符数限制。不得增加包外事实、日期、动机或现实因果，也不得把不确定表述写成事实；保留事实及其条件。允许基于已核实事实提出观察、态度和明显属于修辞的生活化类比/夸张，但不能把它们伪装成新事实或数据。地缘、市场、AI等专业分析只用 analysis 已有推理。避免喊口号和故作悬念。

短例（非完整讲稿）：三星 2025 年 10 月 27 日公告称，部分 Family Hub 冰箱的 Cover 屏主题将试点加入精选广告；用户可在设置中关闭，Art 或 Album 主题不显示广告。IT之家 10 月 28 日报道了美国推送安排。可说：“冰箱里面保鲜，屏幕外面变现。三星要在部分冰箱屏幕主题试放精选广告；广告能关，但用户得先学会在冰箱设置里找广告开关。” 仅作为口播示意，不模仿固定句式；事实见[三星公告](https://news.samsung.com/us/samsung-family-hub-2025-update-elevates-smart-home-ecosystem/)、[IT之家报道](https://www.ithome.com/0/892/813.htm)和[关闭说明](https://www.samsung.com/us/support/answer/ANS10007562/)。

数据包、分批成本估算、渲染与缺批处理见[新闻幻灯片指南](../../docs/news-slides.md)和[参考说明](../../references/news-slides.md)。
