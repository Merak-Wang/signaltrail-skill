# 开发指南

**状态：** 已验证 · **负责人：** 仓库维护者 · **最后验证：** 2026-09-23

本文说明本地开发和测试选择。代码归属见[架构](ARCHITECTURE.md)，不变量见
[AGENTS.md](AGENTS.md)。[English](../development.md)

## 环境与检查

```sh
python -m venv .venv
# 在当前 shell 激活 .venv，然后运行：
python -m pip install -e ".[dev]"
python -m pytest
python -m ruff check .
python -m compileall -q src tests scripts
python scripts/check_code_comments.py
python scripts/check_docs.py
git diff --check
```

单元测试使用临时数据目录和模拟的网络、宿主响应，不需要生产数据、浏览器登录、Notion 凭据或
模型调用。CI 覆盖 Windows、Ubuntu 和 Python 3.11、3.12。编辑时运行相关测试，提交前运行全量检查。

协调器 Context 投影保留候选顺序和选题证据，只省略 `url`、`image_url` 与 `discovered_at`。
完整权威 Context 不变，Brief packet 仍独立由权威 Context 构建。

Hermes 重试可能复用请求 ID。观察器用请求 ID 和宿主开始时间配对每次尝试的 hook，
再用成功调用数和已知 token 与宿主数据库对账。数据库总量匹配不代表失败调用的缺失用量已知。

| 改动 | 相关测试 |
| --- | --- |
| CLI 参数、别名、分派 | `tests/test_cli.py` |
| 来源配置与过滤 | `tests/test_config.py`、`tests/test_normalize.py`、`tests/test_collector.py` |
| Feed、监控、聚类 | `tests/test_feeds.py`、`tests/test_monitor.py`、`tests/test_clustering.py` |
| 上下文与写作 | `tests/test_context.py`、`tests/test_authoring.py`、`tests/test_semantics.py` |
| 报告契约与持久化 | `tests/test_reporting.py`、`tests/test_report_persistence.py`、`tests/test_storage.py` |
| 运行状态与评估 | `tests/test_workflow.py`、`tests/test_evaluation_workflow.py`、`tests/test_evaluation.py` |
| 浏览器验证与 Notion | `tests/test_verification.py`、`tests/test_notion.py` |
| 本地交付与媒体 | `tests/test_desktop_delivery.py`、`tests/test_content.py`、`tests/test_media.py` |
| 新闻图文流 | `tests/test_news_slides.py`、`tests/test_slide_renderer.py` |
| 实验研究与讲解 | `tests/test_research.py`、`tests/test_story_stream.py`、`tests/test_narrative.py`、`tests/test_narrative_store.py`、`tests/test_narrative_verification.py` |
| 用量与宿主接入 | `tests/test_llm_usage*.py`、`tests/test_usage_cli.py`、`tests/test_hermes_runner.py` |
| 打包与文档 | `tests/test_hermes_package.py`、`tests/test_docs.py`、`tests/test_code_comments.py` |

共用报告构造函数放在 `tests/report_helpers.py`。只有多个测试需要相同准备步骤时才提取共享代码。
仅输入和预期结果不同的用例可参数化；不同的失败和恢复场景分别写清。
不要用固定句子测试文案，也不要为了减少测试数量删除回归覆盖。

## 名称与模块

| 名称 | 用途 |
| --- | --- |
| SignalTrail / `signaltrail` | 产品、Skill ID、主 CLI；不再安装 `daily-intel` |
| `signaltrail` | Python 导入包及 `python -m signaltrail.cli` 模块入口 |
| `signaltrail-skill` | Python 发行包；替代旧 `daily-intelligence-skill` 发行包 |
| `DAILY_INTEL_*`、报告 ID | 旧环境变量名称和已存标识继续兼容 |
| Hermes `signaltrail/` 数据与浏览器配置目录 | 当前默认路径；显式迁移时将旧 `daily-intelligence/` 目录改名 |

操作用动词命名，如 `collect_sources`、`save_report`；数据用名词。
CLI 处理函数采用 `handle_<command>`，放在 `commands/`，负责把参数传给领域函数并输出结果。
`cli.py` 加载配置和绑定数据根，`commands/common.py` 放公共输出及类型化上下文。
领域代码不依赖 CLI 模块。

一个职责能够独立命名和测试时再拆模块。不要为无关操作新建泛称的 `manager`、`helper` 或 `utils`。
当前 `reporting.py` 负责编译和校验，`reports.py` 负责存储和 Markdown；其中的超长函数记为 TD-002，
不要再加一个职责不清的 report 模块。

维护中的函数和类用中文 docstring 解释操作、输入来源及消费内容、输出对下游的意义。
例如“返回已验证的索引路径”比“返回处理结果”有用。行内注释说明不直观的安全、状态、兼容和并发决定。

## 文档与发布

README 介绍用途和首次使用。本文档目录保存使用、开发、路线图和有日期的工程历史。
`references/` 维护详细运行策略，`SKILL.md` 保存智能体步骤及按需读取参考资料的入口。

维护中的工程记录说明目的、状态、负责人和验证日期，英文记录与中文译文一起修改。
单语运行参考、历史记录和生成快照在文档目录中编目。每条规则只维护一处。
用简短示例描述实际行为，删除口号、重复功能表和未经实现验证的细节。
提案标为 Draft，已完成的运行记录标为 Historical。

文档检查器检查本地链接、图片、翻译配对、元数据和当前记录日期；历史日期不因超过半年失效。
注释检查器覆盖维护中的源码模块和维护脚本。

实现仅维护根目录的 `src/`，不提交嵌套 Skill 副本。明确发布时运行
`python scripts/build_hermes_skill.py`，在被忽略的 `dist/signaltrail/` 中生成完整 Skill 包。
构建器的 Git 跟踪白名单包含 `SKILL.md`、Python 源码、配置、Schema、模板、参考资料和资源，
排除运行数据和凭据。生成目录是发布产物；实现与文档以仓库根目录为准，不维护
`skills/signaltrail/` 嵌套副本。发布 GitHub 版本前更新版本号和发布说明、构建安装包并完成仓库检查，
再按项目发布流程发布已审阅的 tag 和构建产物。安装从完整仓库或生成包根目录进行，不能仅安装 `src/`。
仓库重构不会自动更新已安装的 Skill。

未解决问题写入[技术债追踪](exec-plans/tech-debt-tracker.md)，包含证据和退出条件。
已发布变化记入 [CHANGELOG.md](../../CHANGELOG.md)。
