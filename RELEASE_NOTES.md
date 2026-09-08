# Release notes

## Source update — 2026-09-08

- `signaltrail` is now the preferred CLI name. `daily-intel`, Python imports, environment
  variables, data directories, and stored report IDs remain compatible.
- CLI handlers are separated by responsibility. Tests for workflow, context, verification,
  storage, evaluation, and Notion now live beside tests of the same subsystem.
- Documentation has one index, a shorter README, usage and development guides, and one Draft
  roadmap. Historical records keep their original dates. English engineering records have
  matching Chinese translations.
- `signaltrail-hermes` starts usage tracking before the host and includes supported worker,
  auxiliary, and independent-evaluation calls. Use this entry point for audited Hermes runs;
  direct CLI/Cron entry points retain documented coverage limits. Missing observations remain
  unknown. This update does not claim that end-to-end cost and latency targets have all passed.
- The evaluator dossier now checks featured-event ordering within each section and uses a new
  `-v2.json` path, preserving earlier immutable dossiers.

Reinstall the editable package to expose the new command. This source update does not rebuild
the checked-in release snapshot or replace an installed skill. See [Usage](docs/usage.md)
and [usage metering](references/llm-usage.md).

## Version 2.0.0

Version 2.0 introduced the local monitor, 32 report sources and 51 discovery sources,
cross-source clustering, Chinese/English output, and three-perspective analysis with synthesis.
HTML is delivered first; PDF, requested Notion delivery, and independent evaluation follow.
JSON and Markdown remain the versioned original records.

Older report schemas and source-index views remain readable. Source access failures stay
explicit, and interactive verification is opt-in. See the [changelog](CHANGELOG.md) for the
development history and [known gaps](docs/exec-plans/tech-debt-tracker.md) for current limits.
