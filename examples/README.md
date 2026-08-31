# 示例

**状态：** 当前展示与合成测试 Fixture
**最后验证：** 2026-08-31

[简体中文](README.md) | [English](README.en.md)

本目录提供当前成品和合成测试数据。

## 当前 schema 2.0 展示

[下载 2026-08-25 晨报 r1 HTML](https://github.com/Merak-Wang/signaltrail-skill/raw/refs/heads/main/examples/reports/2026-08-25-morning-r1.html)是当前完整运行示例：

- 32 个配置来源中有 30 个产生输出，共保留 424 条 briefs；
- 编辑层精选 8 个证据事件，并形成 3 份领域研判和 1 份跨视角综合；
- 独立质量评估为 37/45，同时披露数据时效与证据限制；
- HTML 引用 136 个公网图片 URL，打开完整图文内容时需要网络连接；
- 存档不包含凭证或本地运行路径。

下载 HTML 后在本地浏览器打开，即可查看完整交互阅读体验。公网图片由外部来源托管，
其可用性可能随时间变化。

## 合成测试数据

`sample_input.json` 和 `sample_report.json` 用于自动化测试、兼容性校验和输出渲染，
不代表当前报告契约。

- 人物、机构、事件、日期与分析均为合成内容。
- `news.example`、`wire.example` 是保留示例域名，不对应真实媒体。
- 测试数据仅用于工程验证，不承担事实来源或编辑模板作用。
