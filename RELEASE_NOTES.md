# SignalTrail 2.1.0

Released 2026-09-23. [中文说明](README.md) · [English overview](README.en.md) ·
[Full changelog](CHANGELOG.md)

## Daily reports with animated news slides

A saved report can now become a navigable HTML presentation, with one story per page,
200–350-character Chinese narration, and selective analysis from the existing evidence.
The daily report embeds the presentation where its on-screen summary appeared, while retaining
an **open standalone HTML** button. Printing keeps the original summary. JSON and Markdown
remain the authoritative report records.

The editorial design uses warm paper, dark ink, serif headlines, fine rules and restrained
terracotta accents. It supports a story directory, keyboard navigation, fullscreen, responsive
layouts and reduced motion. Rendering uses fixed HTML/CSS/JavaScript and makes no model call.

Images combine available article covers and explanatory figures. Explicit high-resolution
variants are preferred; thumbnails are not relabeled as original image bytes. Captions remain
verbatim source text, and unavailable captions stay empty. The gallery includes thumbnails,
a large-image viewer and original-image links. Images without publisher-accessible originals
cannot be upgraded into higher-resolution evidence.

## Bounded writing and faster collection

- Representative stories have no overall count cap. All selected stories are completed in
  resumable batches. The default batch contains at most four stories, with estimated input
  and output token limits; these are payload budgets, not a guaranteed currency ceiling.
- Feed content preserves full descriptions, Atom XHTML and captioned images for selected
  enrichment. HTTP and browser work use bounded concurrency, retaining rate-limit cooldowns.
- Coordinator inputs omit repeated fields. Report rendering reuses image encodings within a
  render, and the current/next story loads before distant images.
- Hermes usage records distinguish retry attempts and reconcile successful calls. Missing
  failed-call observations remain unknown, with partial coverage explicitly reported.
- PDF source groups flow across pages without nearly empty separator pages.

## Installation and upgrading

Download the complete `signaltrail-v2.1.0.zip` from
[GitHub Releases](https://github.com/Merak-Wang/signaltrail-skill/releases/tag/v2.1.0), or clone
this repository. Follow the platform-specific steps in [Usage](docs/usage.md) or
[中文使用指南](docs/zh-CN/usage.md). Keep the full `signaltrail/` directory: templates,
schemas, configuration and assets are required alongside the Python package.

Reinstall the package or run the installer to refresh the CLI entry points and an installed
Hermes skill. This repository now maintains only root `src/`; release packages are generated
under ignored `dist/`. There is no maintained `skills/signaltrail/` source copy.

**Command migration:** replace `daily-intel` with `signaltrail` in scripts and scheduled jobs.
The old command alias is no longer installed. Python imports, `DAILY_INTEL_*` environment
variables, existing data directories and stored report IDs retain their names. Use the same
data directory during an upgrade; do not copy private runtime files into the skill package.

## Experimental features and scope

Research can prepare immutable evidence snapshots alongside a report and later bind a reviewed
reading to the completed daily edition. Research and explainer workflows remain experimental;
current-news admission is blocked pending freshness adapters and acceptance. These paths have
separate evidence/review contracts and do not gate the normal daily report.

TTS and video generation are not included. Remote images require network access unless cached
and embedded. Some publishers do not expose usable originals or captions; gaps remain visible.
Provider usage and prices that were not observed are not reported as zero.

The bilingual README, installation guide, presentation guide, architecture and development
references have been reorganized around current commands. Historical design and execution
records retain their original dates. See the [documentation index](docs/README.md) and
[known gaps](docs/exec-plans/tech-debt-tracker.md).
