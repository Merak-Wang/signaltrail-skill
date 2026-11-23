# Architecture

**Status:** Verified · **Owner:** Repository maintainers · **Last verified:** 2026-11-05

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
| `templates/` | Report contract and slide writing style |
| `assets/news-slides/`, `assets/monitor/` | HTML/CSS/JavaScript for the slide renderer and monitor dashboard |
| `assets/tts/reference/`, `assets/tts/profile.example.json` | Bundled default reference voice and example profile for custom voices |
| `assets/readme/` | Product screenshots referenced by both READMEs |
| `scripts/` | Installation, packaging, contributor checks and measurements |
| `references/` | Runtime policies selected by the active workflow |
| `docs/`, `docs/zh-CN/` | English engineering records and Chinese mirrors; current and historical material has separate index entries |
| `evals/` | Module workloads, quality checks, and skill activation examples |
| `examples/` | Current and historical public samples, including the report evaluation's synthetic text seed |
| `.github/workflows/ci.yml` | Repository validation in CI |

The packaged PowerShell and shell installers call the same `scripts/install.py`. The package
also includes the daily CLI and Codex dispatcher (`run_signaltrail.py`, `run_codex_edition.py`),
their usage tools (`measure_codex_turn.py`, `measure_codex_exec.py`) and the skill and Qwen worker
builders. The source checkout additionally contains `check_code_comments.py`,
`check_docs.py`, `evaluate_modules.py`, and `benchmark_slide_efficiency.py` for contributor
checks and benchmarks. Package inclusion follows the build script's allowlist, independently
of Python imports. Scripts, schemas and prompts can be consumed directly by people, hosts or evaluations.

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

Slides first filter original publication to the edition's Asia/Shanghai day and frozen cutoff.
A compact candidate review precedes authoring: the model merges cross-source events and orders
up to 50 by significance and impact, retaining source references and the reviewed order.
Short pools retain their actual count; CLI/workflow wait at `slides_review` before writing packets. `--max-news` / `--slides-max-news` change the limit. Preparation enriches
selected articles before placing their complete available bodies in bounded writing packets.
Accepted writing can be reused when its inputs are unchanged. The independent `slides prepare
--index` path uses model-selected item IDs to produce slides directly, without report authoring.
Rendering attaches public-page images and original captions; offline rendering reuses local images.
See [news slides](docs/news-slides.md).

Video export reads the saved deck and captures the delivered slide HTML at its native 1920 × 1080 viewport.
The frames use the presentation's own layout and displayed narration. Local Qwen3-TTS
1.7B Q8 speaks each title and `video_tldr`; measured audio controls page duration and image rotation.
The runtime prepares native programs and models, uses the bundled reference voice by default,
and prefers a synthesis-verified GPU with CPU fallback. A built `llama-tts-worker` keeps
model weights and reference audio loaded across utterances; the Python synthesizer sends each
segment to that process and closes it after export. The maintained worker source lives under
`src/signaltrail/native/`; `scripts/build_qwen_worker.py` builds against pinned llama.cpp sources.
Audio and page caches support repeat exports.

The monitor independently collects RSS/Atom and static HTML, clusters items and records source
health without model calls. Both source bundles supply regular report sections: 43 of 45 configured IDs are enabled.
Reports select up to 15 eligible current-day articles per source by original publication time, newest first;
finite Feed/page responses retain byte/page bounds. The homepage serves `assets/monitor/`. Report and event
APIs expose saved editions and the persistent `platform/events.sqlite` archive. See [collection and archive APIs](docs/platform.md).

`scripts/run_signaltrail.py` binds CLI imports to the current checkout. Its `--advance-edition`
mode accepts drafts and advances analysis preparation, assembly, finalization, tail and rendering
until model work remains. It skips active drafts during validation and materializes complete inputs
only for the available worker slots. The host creates a fresh context for each author. Individual
sessions retain `--advance-dispatch` and `--dispatch-plan`. Author completion notifications trigger
dispatch; long subprocess waits stay within the tool runtime. One coordinator directly manages
up to three fresh authors, blockers, and delivery receipts. Stage changes and batch counts do not
create supervisor or replacement-coordinator roles; recovery follows saved commands in `SKILL.md`.

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
| Collection retention | `retention` | Recycle collection files older than seven days while preserving active-run evidence and all report/media outputs |
| Evidence | `content`, `content_extraction`, `pdf_content`, `content_images`, `media`, `image_policy`, `monitor` | Structured article blocks, bounded text-PDF evidence, extraction quality, contextual image candidates, snapshots, evidence lineage |
| Writing | `context`, `brief_selection`, `authoring`, `author_inputs`, `analysis_parallel`, `semantics`, `state` | Up to 15 newest eligible entries per source after same-source canonical de-duplication, cross-source views with shared original writing, bounded packets, ordered token-bounded input parts, accepted batches, optional parallel analysis, continuity and cache |
| Report contract | `reporting` | Compile drafts, hydrate evidence, validate schema and cross-field rules |
| Shared slide artifacts | `narrative_store` | Immutable slide packets, accepted writing and exact revision replay; preserves existing artifact formats |
| Report storage | `reports` | Save reports and evaluations, render Markdown, update derived state |
| News slides | `news_slides`, `slide_reuse`, `slide_images`, `slide_renderer` | Report or index-only bounded writing, accepted narration reuse, public-page image refresh, and standalone animated HTML |
| Narrated video | `slide_video`, `voice_synthesis`, `speech_text`, `qwen_runtime`, `video_runtime` | Speech normalization, local Qwen3 TTS, shared audio/image timeline, native tool preparation and MP4 export |
| Delivery | `local_output`, `notion`, `dashboard` | HTML/PDF, remote copies, original collection monitor, retained report/event APIs,  backend |
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
[technical-debt tracker](docs/exec-plans/tech-debt-tracker.md). Module evaluation and the full gate
are in the [development guide](docs/development.md).
