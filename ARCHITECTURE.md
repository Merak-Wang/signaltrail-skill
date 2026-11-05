# Architecture

**Status:** Verified · **Owner:** Repository maintainers · **Last verified:** 2026-11-02

This is the code map for SignalTrail. [Runtime contracts](references/system-design.md)
describe data fields and recovery rules; [AGENTS.md](AGENTS.md) covers repository changes.
[中文](docs/zh-CN/ARCHITECTURE.md)

## Repository files

Install the complete checkout or generated skill directory: configuration, templates and assets
live beside `src/`. The root holds agent instructions (`SKILL.md`), contributor rules (`AGENTS.md`),
this architecture map, bilingual READMEs, release/security/license records, and Python configuration.

| Location | Purpose and consumer |
| --- | --- |
| `src/signaltrail/` | The single implementation; module responsibilities are listed below |
| `configs/` | `config` reads source/discovery settings; `notion` reads optional delivery settings |
| `schemas/` | Report and usage contracts; report validation reads the report schema |
| `templates/` | Report contract, slide writing style and experimental research/explainer prompts |
| `assets/news-slides/`, `assets/monitor/` | HTML/CSS/JavaScript for the slide renderer and monitor dashboard |
| `assets/tts/reference/`, `assets/tts/profile.example.json` | Bundled default reference voice and example profile for custom voices |
| `assets/readme/` | Product screenshots referenced by both READMEs |
| `scripts/` | Installation, packaging, contributor checks and measurements |
| `references/` | Runtime policies selected by the active workflow |
| `docs/`, `docs/zh-CN/` | English engineering records and Chinese mirrors; current and historical material has separate index entries |
| `tests/`, `evals/` | Behavior tests and fixtures; skill activation examples |
| `examples/` | Current and historical public samples; tests also consume `sample_report.json` |
| `.github/workflows/ci.yml` | Repository validation in CI |

The package includes `scripts/install.ps1`, `install.sh`, `build_hermes_skill.py` and
`measure_codex_turn.py`. The source checkout additionally contains `check_code_comments.py`,
`check_docs.py`, `benchmark_slide_efficiency.py` and `evaluate_research_workflow.py` for contributor
checks and manual benchmarks. Package inclusion follows the build script's allowlist, independently
of Python imports. Scripts, schemas and prompts can be consumed directly by people, hosts or tests.

Default builds include Git-tracked files only. Add new runtime modules and voice assets to version
control with the feature before release; `--include-uncommitted` is an explicit local build option.
Local `data/` holds evidence, accepted writing, reports, models and caches. `output/`, `tmp/` and
optional `benchmarks/` hold local measurements and temporary work; `build/` and `dist/` are generated
distribution artifacts. These directories, `.venv/`, tool caches, and local editor/agent state are
excluded from source packaging. Keep current deliveries, voice assets, recovery backups and needed
audit evidence; recycle confirmed obsolete build copies and disposable probes.

## Data flow

```text
public sources → canonical index → evidence packets → model drafts
→ Python compilation and validation → versioned JSON + Markdown → HTML/PDF
                                                     → slides → optional MP4
```

Python owns collection, identity, access status, revisions and persistence. Models select
and write from the evidence declared in their packets. Article bodies take precedence over
saved Feed content, followed by public descriptions. Feed content remains partial provider evidence.

The default `daily` run freezes a trailing 24-hour collection window and reuses the same local
date's run. Finalization saves the report and prepares slides; all narration batches and a rendered
deck are required for daily delivery. `edition-status --run RUN.json --require-complete` checks
remaining work independently of report status. See [usage](docs/usage.md).

Slides merge duplicate original stories, retain source references and select the top 50 by
model-authored importance. `--max-news` / `--slides-max-news` change the limit. Preparation enriches
selected articles before placing their complete available bodies in bounded writing packets.
Accepted writing can be reused when its inputs are unchanged. The independent `slides prepare
--index` path uses model-selected item IDs to produce slides directly, without report authoring.
Rendering attaches public-page images and original captions; offline rendering reuses local images.
See [news slides](docs/news-slides.md).

Video export reads the saved deck and captures its HTML at 140% whole-page zoom. Local Qwen3-TTS
1.7B Q8 speaks each title and `video_tldr`; measured audio controls page duration and image rotation.
The runtime prepares native programs and models, uses the bundled reference voice by default,
and prefers a synthesis-verified GPU with CPU fallback. Audio and page caches support repeat exports.

The monitor independently collects RSS/Atom and static HTML, clusters items and records source
health without model calls. Its snapshot can supplement full collection with up to 30 discovery
briefs by default. The homepage serves `assets/monitor/`. Report, event and asynchronous research
APIs expose saved editions and the persistent `platform/events.sqlite` archive; configured research
hosts perform model work. See [collection and research APIs](docs/platform.md).

Analysis normally uses one fresh-context author. The optional `prepare-analysis --parallel`
path separates selection, three domains, synthesis and assembly; its stages repeat shared input.
Global `--compact` bounds command output while saved artifacts retain complete contents.

## Code map

All modules below live in `src/signaltrail/`.

| Responsibility | Modules | Boundary |
| --- | --- | --- |
| Shared types and I/O | `models`, `storage`, `utils`, `runtime`, `access`, `localization`, `taxonomy` | Paths, enums, atomic writes, data-root binding |
| Configuration | `config` | Sources, limits, and runtime options |
| Collection | `adapters`, `browser_collection`, `feeds`, `feed_content`, `prefetch`, `collector`, `clustering`, `article_time` | Fetch, normalize dates without inventing precision, retain first observations and listing signals, preserve source status and order |
| Collection diagnostics | `collection_diagnostics` | Configured-source coverage, bounded body-gap suggestions, local artifact integrity |
| Evidence | `content`, `content_extraction`, `pdf_content`, `content_images`, `media`, `image_policy`, `monitor` | Structured article blocks, bounded text-PDF evidence, extraction quality, contextual image candidates, snapshots, evidence lineage |
| Writing | `context`, `brief_selection`, `authoring`, `analysis_parallel`, `semantics`, `state` | Canonical-URL unique brief allocation with source-tail replacement and actual shortfalls, bounded packets, accepted batches, optional parallel analysis, continuity and cache |
| Report contract | `reporting` | Compile drafts, hydrate evidence, validate schema and cross-field rules |
| Report storage | `reports` | Save reports and evaluations, render Markdown, update derived state |
| News slides | `news_slides`, `slide_reuse`, `slide_images`, `slide_renderer` | Report or index-only bounded writing, accepted narration reuse, public-page image refresh, and standalone animated HTML |
| Narrated video | `slide_video`, `voice_synthesis`, `speech_text`, `qwen_runtime`, `video_runtime` | Speech normalization, local Qwen3 TTS, shared audio/image timeline, native tool preparation and MP4 export |
| Experimental explainers | `narrative`, `narrative_contracts`, `narrative_store`, `narrative_verification`, `story_stream` | Immutable report children, language reviews, diagrams; current-news admission blocked |
| Experimental research | `research`, `research_contracts`, `research_delivery` | Frozen blocks, local question retrieval, scoped memos and preview-only late report binding; current admission blocked |
| Delivery | `local_output`, `notion`, `dashboard` | HTML/PDF, remote copies, original collection monitor, retained report/event APIs, and asynchronous research backend |
| Workflow | `workflow` | Run checkpoints, deadlines, recovery, evaluator scheduling |
| Usage and budget | `llm_usage/`, `llm_budget`, `evaluation` | Immutable usage events, dispatch reserves, evaluation dossiers |
| Host integration | `hosts/`, `hermes_runner`, `usage_cli` | Optional host metering, launchers, hooks and durable-log imports |
| Commands | `cli`, `commands/`, `verification`, `importer` | Parse arguments, bind configuration, call domain functions |

Dependencies point from entry points through orchestration to domain code and shared I/O.
Domain modules must not import `cli` or `commands`. In `commands/`, `parser.py` defines options,
the registry maps names to handlers, and each handler family calls domain functions through
a typed `CommandContext`. `signaltrail` is the main CLI entry point.

The public Python import and module entry point are `signaltrail` and `python -m signaltrail.cli`;
the command is `signaltrail`, and the distribution is `signaltrail-skill`. Legacy `DAILY_INTEL_*`
environment variables and stored report IDs remain compatible. Old Hermes `daily-intelligence`
data and browser-profile directories can remain in place with explicit path settings; see [usage](docs/usage.md).

## State and files

`RunStatus` in `workflow.py` defines the foreground lifecycle:

```text
created → collecting → building_context → awaiting_selection
→ extracting_content → awaiting_authoring → finalizing
→ completed | completed_partial | failed
```

`completed_partial` means a local report exists with recorded gaps. PDF, Notion, evaluation, and
slide writing/rendering have separate retryable work; their failure cannot revoke a saved local report.

| Files under the data root | Ownership |
| --- | --- |
| `indexes/`, `content/`, `reports/` | Versioned evidence and report records; existing revisions are not overwritten |
| `context/` | Immutable authoring inputs, bounded coordinator projections, hash-bound sessions and receipts |
| `content-checkpoints/` | Completed extraction results bound to an input index and selected IDs; safe index-commit recovery |
| `runs/` | Atomic mutable checkpoints, including references to usage tasks |
| `usage/…/events/` | Immutable, allowlisted usage events; authoritative for usage totals |
| `evaluations/dossiers/` | Immutable inputs bound to report/index hashes; current dossiers use `-v2.json` |
| `state/` | Derived continuity and semantic cache |
| HTML, PDF, Notion | Rebuildable or retryable projections |

Root index `items[]` is canonical; `sources[].items[]` is the synchronized legacy view.
Reports from schema 1.1–1.5 remain readable; new reports use 2.0 and require cross-perspective
synthesis. Atomic writes use unique sibling files and locks. Immutable creation refuses
collisions; paired report writes still have the transaction gap recorded as TD-010.

## Model boundary

Authoring packets declare their output schema and authorized evidence. Python rejects extra
fields and invented identities, records immutable rejection receipts, and allows at most one
budget-approved repair. The semantic cache stores stable translated titles and summaries;
each run recomputes importance and status. Reports keep three stable analysis-domain IDs.
Continuity state uses separate claim-and-evidence thesis IDs and thesis-bound watchers;
omitted signals remain active. Legacy ambiguous rows retain their history, and
`analysis-domains.json` provides the latest column projection. Cross-wording continuation
remains TD-039.

Usage storage accepts counts, timings, costs, bounded labels, and hashed lineage. It excludes
prompts, responses, reasoning, tool arguments, raw host IDs, and secrets. Unknown observations
remain null. Task locks serialize append and finalization; finalization rejects open calls.
Hashes detect inconsistent local edits, not an attacker able to rewrite the whole ledger.

The core CLI uses a SignalTrail application data directory and does not require Hermes or read
Hermes environment files. General host execution may be unmetered unless an audited usage adapter
is available. The optional `signaltrail-hermes` launcher starts metering before Hermes, observes
supported auxiliary requests, and reconciles sessions against host counters before sealing.
Evaluator scoring defaults to an external independent agent; Hermes scheduling is an explicit
backend choice. Adapter formats and coverage limits live in [usage metering](references/llm-usage.md)
and the [Hermes integration reference](references/hermes-integration.md).

Remaining large compiler, validator, and renderer functions are tracked as TD-002 in the
[technical-debt tracker](docs/exec-plans/tech-debt-tracker.md). Test selection and the full gate
are in the [development guide](docs/development.md).
