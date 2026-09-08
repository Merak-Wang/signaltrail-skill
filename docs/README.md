# Documentation

**Status:** Verified · **Owner:** Repository maintainers · **Last verified:** 2026-09-08

Start with the guide for the work you are doing. English engineering records have Chinese
mirrors under [zh-CN/](zh-CN/README.md).

| Guide | Covers |
| --- | --- |
| [Usage](usage.md) | Installation, data paths, language, sources, metered runs, recovery |
| [Development](development.md) | Test selection, naming, code and documentation conventions |
| [Architecture](../ARCHITECTURE.md) | Module ownership, state, files, model boundaries |
| [Agent instructions](../AGENTS.md) | Rules for changing this repository |
| [Roadmap](roadmap.md) | Draft explainer, verification, audio and video scope; not implemented |
| [Technical debt](exec-plans/tech-debt-tracker.md) | Known implementation gaps and exit conditions |

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
| [Narrative analysis](../references/narrative-analysis.md) | Repairing analysis content |
| [Report contract](../templates/report-contract.md) and [schema](../schemas/report.schema.json) | Draft shape and machine validation |
| [Usage metering](../references/llm-usage.md) | Host adapters, accounting and coverage limits |
| [Windows setup](../references/windows-setup.md) | Hermes installation on Windows |
| [Notion setup](../references/notion-setup.md) and [schema repair](../references/notion-schema-fix.md) | Optional remote delivery |

## History

These completed run records explain decisions and measurements at the time. They are historical,
not current operating instructions. Their original verification dates do not expire.

- [2026-08-25 morning-report acceptance](exec-plans/completed-2026-08-25-morning-report-acceptance.md)
- [2026-08-23 usage and optimization implementation](exec-plans/completed-2026-08-23-llm-usage-optimization-implementation.md)
- [2026-08-05 report regeneration](exec-plans/completed-2026-08-05-morning-report-regeneration.md)
- [Release history](../CHANGELOG.md) and [release notes](../RELEASE_NOTES.md)
- [Example reports](https://github.com/Merak-Wang/signaltrail-skill/blob/main/examples/README.en.md): sanitized historical outputs

`skills/signaltrail/`, `build/`, and `dist/` are generated release/install snapshots.
They are excluded from current-document checks and updated only through an explicit rebuild.
Local ignored audit notes are not public engineering records.

Maintained records use Verified, Draft, or Active; completed records use Historical, and
mechanical snapshots use Generated. Each maintained record states purpose, owner, and date.
See [Development](development.md) for the maintenance rules and checks.
