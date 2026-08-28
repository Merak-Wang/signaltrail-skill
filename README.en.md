# SignalTrail

[简体中文](README.md) | [English](README.en.md)

> Signals distilled. Sources intact.

SignalTrail is a local-first [Hermes Agent](https://hermes-agent.nousresearch.com/)
skill for repeatable editorial reporting. It collects approved public sources,
clusters duplicate coverage, and helps Hermes produce a Chinese or English briefing
with visible evidence, explicit source health, and continuity across editions. It
turns scattered signals into a reviewable decision trail that teams can brief,
archive, and revisit.

[Inside a report](#inside-a-report) · [Report gallery](#report-gallery) · [Quick start](#quick-start) ·
[Engineering records](docs/README.md) ·
[Hermes skill](SKILL.md)

[![Hermes Agent](https://img.shields.io/badge/Hermes-Agent-6C5CE7?style=flat-square)](https://hermes-agent.nousresearch.com/)
[![License](https://img.shields.io/github/license/Merak-Wang/signaltrail-skill?style=flat-square)](LICENSE)

![SignalTrail report preview](https://raw.githubusercontent.com/Merak-Wang/signaltrail-skill/main/assets/readme/morning-report-preview.png)

## Inside a report

Schema 2.0 puts the full collection view, selected evidence, analysis, and quality
boundaries into one searchable report:

- The source index preserves every brief's original title, URL, time, access state,
  and source order. The editorial layer then selects 6–10 evidence events without
  pretending that the full collection contains only a handful of items.
- Geopolitics, AI/technology, and markets each receive a four-to-seven-paragraph
  reader narrative with expandable argument and evidence. Cross-perspective synthesis
  states shared conclusions, key disagreements, transmission chains, and watch signals.
- Independent evaluation is bound to the immutable report content hash and exposes
  nine dimension scores, evidence gaps, and acceptance boundaries. Search, the
  collapsible table of contents, portable desktop HTML, and responsive mobile reading
  all use the same report revision.

| Cross-perspective synthesis | Independent quality evaluation |
| --- | --- |
| ![Cross-perspective synthesis](https://raw.githubusercontent.com/Merak-Wang/signaltrail-skill/main/assets/readme/analysis-synthesis-preview.png) | ![Independent quality evaluation](https://raw.githubusercontent.com/Merak-Wang/signaltrail-skill/main/assets/readme/quality-evaluation-preview.png) |

<p align="center">
  <img src="https://raw.githubusercontent.com/Merak-Wang/signaltrail-skill/main/assets/readme/mobile-report-preview.png" width="390" alt="SignalTrail mobile report view">
</p>
<p align="center"><sub>The same report remains searchable, navigable, and readable in a 390 px viewport.</sub></p>

## What the product delivers

SignalTrail turns a large daily reading queue into a consistent decision artifact:

- **Reader-ready morning and evening reports** in HTML and PDF, with Markdown and
  JSON retained as durable local records.
- **Traceable coverage** that preserves the original title, source, link, publication
  time, and any access limitation instead of presenting an opaque summary.
- **A seven-section editorial view** spanning international, domestic, military,
  markets, technology, research papers, and open-source projects.
- **Three analytical lenses plus synthesis** for geopolitics, AI/technology, and
  markets, including shared signals, disagreements, and what to watch next.
- **A zero-model-token local monitor** for feed refresh, caching, deduplication,
  clustering, and source-health review. Model work begins only for report selection,
  target-language writing, and analysis.
- **Bounded generation with rejection receipts**. Briefs and analysis must satisfy
  structured constraints; an invalid submission gets at most one budget-gated repair,
  with a hash-bound receipt that excludes the draft body.
- **Auditable model usage** stored as immutable, allowlisted counts by run and phase.
  Missing coverage remains `unknown` or `unmetered` instead of being presented as an
  exact token baseline.
- **Local ownership by default** with versioned files, a portable desktop HTML copy,
  and optional Notion delivery.

The bundled configuration separates 32 core reporting sources from 51 discovery
sources. Every formal source has `report_target: 15` and `report_max: 15`: when at
least fifteen candidates exist, the report uses the first fifteen in the current
index order; otherwise it uses the candidates actually available. Discovery sources
keep both values at zero, broadening the signal surface without silently expanding
the editorial or model budget.

A full run can require up to 480 ordinary briefs. SignalTrail limits authoring to
the planned Top-15 gaps, splits them into at most 12 bounded packets, and processes
those packets in waves of three under Hermes' default concurrency. The default full
run's 60-minute limit is a hard guard that stops new stages, not a committed delivery
SLA. When delivery must land exactly at 06:00 or 18:00, start earlier and leave margin
for provider latency, access verification, and bounded retries.

## Report gallery

The current gallery first preserves hundreds of searchable briefs as a full collection
view, then selects a small evidence set for analysis. “Complete coverage” and
“editorial selection” are deliberately separate layers.

| Current schema 2.0 edition | Full collection view | Selection and analysis | Independent evaluation |
| --- | ---: | ---: | --- |
| [2026-08-25 morning r1](https://github.com/Merak-Wang/signaltrail-skill/blob/main/examples/reports/2026-08-25-morning-r1.html) | 30/32 formal sources produced output · 424 briefs | 8 evidence events · 3 domain analyses · 1 cross-perspective synthesis | 37/45 |

This is a historical run snapshot. Its independent evaluation accepted the current
quality boundary while disclosing that most items had metadata-level evidence and
that some WATCH items were stale or lacked publication times. The full run took
3,974 seconds, above the 3,600-second hard budget, so it is not an SLA-compliant
benchmark. The HTML contains no credentials or local runtime paths, but its 136 images
use public-source URLs; full viewing requires a network connection, and those external
images may disappear or change.

The preserved compatibility editions below use schema 1.5 and the earlier
**Daily Intelligence** masthead:

| Historical edition | Coverage processed | Editorial result | Decision themes |
| --- | ---: | ---: | --- |
| [2026-07-24 morning r3](https://github.com/Merak-Wang/signaltrail-skill/blob/main/examples/reports/2026-07-24-morning-r3.html) | 24 sources · 197 updates | 10 priority events | Energy, tariffs, and AI capital efficiency |
| [2026-07-25 morning r1](https://github.com/Merak-Wang/signaltrail-skill/blob/main/examples/reports/2026-07-25-morning-r1.html) | 29 sources · 235 updates | 10 priority events | Energy corridors, technology regulation, and agent engineering |

GitHub may display the HTML source; download the file and open it locally for the full
report experience.

Fixture data and gallery notes are documented in
[examples/README.en.md](https://github.com/Merak-Wang/signaltrail-skill/blob/main/examples/README.en.md).

## Product fit

SignalTrail is designed for individual researchers and small teams that already use
Hermes and want a repeatable report they can inspect, archive, and modify locally.
It is especially useful when “why this item is here” and “what failed to load” matter
as much as the summary.

It is not an enterprise intelligence platform. It does not include paid research,
social-firehose coverage, mobile clients, SSO, RBAC, or an SLA. It also does not
bypass login, CAPTCHA, paywalls, rate limits, or other access controls.

| Need | SignalTrail approach |
| --- | --- |
| Daily executive readout | Fixed morning/evening structure with concise editorial selection |
| Evidence review | Original source identity, title, URL, time, and status remain visible |
| Ongoing situational awareness | Local monitor, story clusters, source health, and verification queue |
| Bilingual delivery | One selected output language across content, interface, PDF, and Markdown |
| Durable ownership | Local JSON/Markdown source of truth; rebuildable HTML/PDF projections |
| Remote handoff | Optional Notion metadata page with a portable HTML attachment |

## Quick start

### Requirements

- Git and Python 3.11 or newer
- A configured [Hermes Agent](https://hermes-agent.nousresearch.com/) and Hermes
  Gateway
- Microsoft Edge on Windows; the installer provisions Playwright Chromium on macOS
  and Linux

### Install from GitHub

Windows:

```powershell
git clone https://github.com/Merak-Wang/signaltrail-skill.git
cd signaltrail-skill
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install.ps1
```

macOS or Linux:

```bash
git clone https://github.com/Merak-Wang/signaltrail-skill.git
cd signaltrail-skill
bash ./scripts/install.sh
```

On a new Ubuntu or Debian machine, install the Chromium system libraries after the
script completes:

```bash
python -m playwright install-deps chromium
```

The installer synchronizes the skill to `skills/research/signaltrail` and installs
the backward-compatible `daily-intel` command:

```text
daily-intel --help
```

Upgrading does not rename or split the established
`$HERMES_HOME/daily-intelligence` data root. Resource discovery also accepts the
legacy `skills/research/merak-brief` and `skills/research/daily-intelligence`
locations. After confirming the new `/signaltrail` skill works, remove the old
skill directories if Hermes shows legacy brand entries.

### Ask Hermes for the first report

```text
Use SignalTrail to create today's Chinese morning report as local HTML and PDF.
```

Or:

```text
Use SignalTrail to create an English evening brief, highlight what changed today,
and add tomorrow's watch signals.
```

The default output language is `zh-CN`. Select English per run:

```text
daily-intel run-edition --edition morning --language en
```

Or set the long-term choice in `configs/sources.yaml`:

```yaml
output:
  language: zh-CN  # zh-CN or en
```

The selected language controls summaries, analysis, labels, HTML, PDF, and Markdown.
Original headlines remain unchanged; a translated title is added only when needed.

## How it works

```mermaid
flowchart LR
    A["Collect approved public sources"] --> B["Normalize, deduplicate, and cluster"]
    B --> C["Select bounded evidence packets"]
    C --> D["Author in Chinese or English"]
    D --> E["Validate schema, citations, state, and language"]
    E --> F["Deliver desktop HTML immediately"]
    F --> G["Complete PDF, optional Notion, and evaluation as a retryable tail"]
```

Collection failures do not stop healthy sources. A failed, rate-limited, or
verification-pending source keeps that status and its recovery path; it is never
silently converted to `no_items`. If the index contains candidates but brief
authoring or validation did not finish, the report names every affected source and
its validated/planned count even when sibling sources in that section succeeded; it
must not describe those candidates as uncollected or let the source vanish silently.

Before dispatching a brief, analysis, repair, or evaluation stage, the budget gate
rebuilds the observed lower bound from immutable usage events and adds versioned
downstream reserves. Crossing the limit stops new stages while preserving completed
indexes, drafts, and report artifacts. Semantic cache reuse is also limited to titles
and summaries whose content fingerprint, language, and independent-evaluation state
still match and whose item remains inside the current source plan; an old item outside
the Top 15 cannot be used to fill a coverage gap.

## Local intelligence desk

Refresh and inspect the monitor:

```text
daily-intel refresh-monitor
daily-intel monitor-status
```

Open the localhost desk and refresh while the process is running:

```text
daily-intel serve --open --refresh-minutes 30
```

The desk listens on `127.0.0.1` by default. Installation does not register a system
service; unattended refresh requires the process to remain running or an
OS-level scheduled task.

Edit the source portfolio directly:

- Core report sources: [configs/sources.yaml](configs/sources.yaml)
- Discovery sources: [configs/discovery-sources.yaml](configs/discovery-sources.yaml)

All sources share `collection.item_order`. The default `source` mode gives a formal
source its original page, ranking, or feed Top1–15. In `published_at` mode, the
formal report takes the first fifteen from the current index after valid publication
times are sorted newest first; missing and tied times retain stable input order. A
source-level `item_order` can override the global value. Both modes preserve the
original `source_rank`, and ordinary briefs are not reordered by `importance`.
Hugging Face Papers uses the Trending list, so `source` mode follows its current Top
ranking even when it contains papers published in earlier years.

## Output contract

| Artifact | Role |
| --- | --- |
| `reports/YYYY-MM-DD/EDITION-rN.json` | Versioned structured record; existing revisions are never overwritten |
| `reports/YYYY-MM-DD/EDITION-rN.md` | Reviewable and diff-friendly archive |
| `reports/YYYY-MM-DD/EDITION-rN.html` | Full local reading edition |
| `reports/YYYY-MM-DD/EDITION-rN.pdf` | Print/share edition; images are resampled to print bounds, with duration, byte size, and the default 50 MiB soft budget recorded |
| `reports/index.html` | Local archive by date and revision |
| `Desktop/daily-intelligence-…html` | Portable single-file reading copy with images embedded |
| `evaluations/dossiers/REPORT_ID.json` | Read-only independent-evaluation input bound to report and index hashes |
| `usage/YYYY-MM-DD/TASK_ID/events/*.json` | Immutable model-usage audit events with no prompt or generated body |
| Notion | Optional metadata page plus portable HTML attachment |

By default, report history lives under
`%LOCALAPPDATA%\hermes\daily-intelligence\reports` on Windows or
`~/.hermes/daily-intelligence/reports` on macOS and Linux. When `HERMES_HOME` is set,
the same `daily-intelligence/reports` path is created beneath it.

Notion is optional. Without Notion credentials, every local artifact remains
available. If desktop delivery, PDF rendering, or Notion delivery fails, the
versioned local record remains intact and the failed projection can be retried.

## Hermes community package

`SKILL.md` follows the Hermes/Agent Skills layout: public metadata is at the
frontmatter root, Hermes discovery/configuration lives under `metadata.hermes`, and
procedural detail is progressively disclosed through `references/`, `templates/`,
and deterministic scripts.

Build the publication directory from an allowlist of Git-tracked files:

```text
python scripts/build_hermes_skill.py
```

The command validates metadata, directory naming, required runtime files, forbidden
runtime paths, file sizes, and common secret patterns, then writes
`dist/signaltrail`. Publish that directory—not the repository root:

```text
hermes skills publish ABSOLUTE_PATH/dist/signaltrail --to github --repo OWNER/REPOSITORY
```

The absolute path avoids ambiguity with the Hermes local skill root. Review
`git status`, the generated file list, and the Hermes security scan before opening
the community pull request.

## Documentation

- Repository map: [AGENTS.md](AGENTS.md)
- Architecture: [ARCHITECTURE.md](ARCHITECTURE.md)
- Engineering record catalog: [docs/README.md](docs/README.md)
- Skill procedure: [SKILL.md](SKILL.md)
- Operations and recovery: [references/runbook.md](references/runbook.md)
- Editorial and evidence policy:
  [references/editorial-policy.md](references/editorial-policy.md)
- Detailed architecture and state model:
  [references/system-design.md](references/system-design.md)
- Model-usage audit and host integration:
  [references/llm-usage.md](references/llm-usage.md)
- Windows setup: [references/windows-setup.md](references/windows-setup.md)
- Notion setup: [references/notion-setup.md](references/notion-setup.md)
- Current quality score: [docs/quality-score.md](docs/quality-score.md)
- Release history: [CHANGELOG.md](CHANGELOG.md)

## Development

```text
python -m pip install -e ".[dev]"
python -m ruff check .
python -m pytest
python -m compileall -q src tests scripts
python scripts/check_code_comments.py
python scripts/check_docs.py
```

Update tests for any source filter, status model, validation, or publishing change.
Never commit runtime `data/`, browser profiles, cookies, account screenshots,
authenticated HTML, or secrets.

## License

[MIT](LICENSE) © Wang Mingfeng
