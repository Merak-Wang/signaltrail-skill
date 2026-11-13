# Documentation

**Status:** Verified · **Owner:** Repository maintainers · **Last verified:** 2026-11-02

Start with the guide for the work you are doing. English engineering records have Chinese
mirrors under [zh-CN/](zh-CN/README.md).

| Guide | Covers |
| --- | --- |
| [Usage](usage.md) | Installation, data paths, language, sources, metered runs, recovery |
| [Collection extensions and archive APIs](platform.md) | Collection monitor, RSSHub/Crawl4AI, discovery briefs, and report/event archive APIs |
| [Development](development.md) | Module evaluation, naming, code and documentation conventions |
| [Architecture](../ARCHITECTURE.md) | Module ownership, state, files, model boundaries |
| [Agent instructions](../AGENTS.md) | Rules for changing this repository |
| [News slides](news-slides.md) | Report and index inputs, illustrated presentations, local video, and voice setup |
| [Roadmap](roadmap.md) | Maintained daily report, slides and video scope |
| [Technical debt](exec-plans/tech-debt-tracker.md) | Known implementation gaps and exit conditions |

[Output examples](https://github.com/Merak-Wang/signaltrail-skill/blob/main/examples/README.en.md): current daily reports, illustrated slides, narrated video, and historical samples.

## Directory roles

| Location | Purpose |
| --- | --- |
| `docs/` | Engineering guides, architecture, development and usage. |
| `references/` | Detailed runtime policies and recovery instructions linked by the skill. |
| `docs/research/` | Dated research and experimental proposals. |
| `docs/exec-plans/` | Historical implementation records and the active technical-debt tracker. |
| `examples/` | Current and historical report, slide, and video examples, including synthetic evaluation inputs. |
| `evals/` | Module workloads, quality checks, and Skill trigger examples. |

## Historical research

Dated records under `docs/research/` preserve earlier collection and experimental proposals.
The independent explainer and research prototypes were retired on 2026-11-07.
The maintained workflow produces daily reports, illustrated slides and narrated video.

## Runtime references

These are maintained, Chinese-authoritative runtime documents, owned by repository maintainers.
They keep their own verification date. The schema-repair note is historical and in English.
Read only the reference needed for the task.

| Reference | Use it for |
| --- | --- |
| [SKILL.md](../SKILL.md) | Agent execution steps; English runtime entry point |
| [Runbook](../references/runbook.md) | Stage recovery and operational checks |
| [System contracts](../references/system-design.md) | Data fields, state and artifact contracts |
| [Editorial policy](../references/editorial-policy.md) | Source selection, evidence, access and ordering |
| [News slides reference](../references/news-slides.md) | Batch payloads, token estimate gates and complete rendering requirements |
| [Narrative analysis](../references/narrative-analysis.md) | Repairing analysis content |
| [Report contract](../templates/report-contract.md) and [schema](../schemas/report.schema.json) | Draft shape and machine validation |
| [Usage metering](../references/llm-usage.md) | Host adapters, accounting and coverage limits |
| [Hermes integration](../references/hermes-integration.md) | Optional Hermes metering and evaluator setup |
| [Windows setup](../references/windows-setup.md) | Hermes installation on Windows |
| [Notion setup](../references/notion-setup.md) and [schema repair](../references/notion-schema-fix.md) | Optional remote delivery |

## History

These completed run records explain decisions and measurements at the time. They are historical,
not current operating instructions. Their original verification dates do not expire.

- [2026-09-12 runtime cost optimization](exec-plans/completed-2026-09-12-runtime-cost-optimization.md)
- [2026-09-11 Report A code review](exec-plans/completed-2026-09-11-report-a-code-review.md)
- [2026-08-25 morning-report acceptance](exec-plans/completed-2026-08-25-morning-report-acceptance.md)
- [2026-08-23 usage and optimization implementation](exec-plans/completed-2026-08-23-llm-usage-optimization-implementation.md)
- [2026-08-05 report regeneration](exec-plans/completed-2026-08-05-morning-report-regeneration.md)
- [Release history](../CHANGELOG.md) and [release notes](../RELEASE_NOTES.md)
