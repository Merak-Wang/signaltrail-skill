# Development

**Status:** Verified · **Owner:** Repository maintainers · **Last verified:** 2026-11-13

This guide covers local changes and module evaluation. Read [architecture](../ARCHITECTURE.md)
for code ownership and [AGENTS.md](../AGENTS.md) for invariants. [中文](zh-CN/development.md)

## Setup and checks

```sh
python -m venv .venv
# Activate .venv in your shell, then:
python -m pip install -e ".[dev]"
python scripts/evaluate_modules.py --repeat 3
python -m ruff check .
python -m compileall -q src scripts evals
python scripts/check_code_comments.py
python scripts/check_docs.py
git diff --check
```

## Module evaluation

The default evaluation runs complete production paths with fixed external inputs and an isolated
work directory for each sample. Select one or more modules with `--modules` while editing.
The full default run covers the four offline modules below on Windows and Ubuntu.

| Module | Workflow and quality evidence | Performance measures |
| --- | --- | --- |
| `collection` | Collect fixed source responses, resolve dates, enrich articles, and verify the resulting index, coverage, and access status | Stage time, article throughput, HTTP request and response reuse counts |
| `report` | Compile fixed author drafts and source index, check coverage and evidence links, verify Markdown and HTML contents and PDF readability, reject an incomplete draft, and publish a revision | Save and revision time, briefs per second, output sizes |
| `slides` | Prepare and accept fixed slide drafts, render the deck, and verify the delivered presentation | Stage time, pages per second, output size |
| `orchestration` | Dispatch and accept 13 slide batches using the same batch submission functions as the CLI, retain active drafts, repair a rejected batch, and render all 50 pages with a single coordinator | Dispatch rounds, forced handoffs, author occupancy, complete workflow time and page throughput |
| `video` | Export a supplied local deck with the production TTS and video runtime, decode the result, and repeat the export to measure reuse | First and repeat export time, output duration per wall second, cache hits and generated audio segments |

Each sample records the workload, module pass/fail checks, wall time, throughput, Python CPU
time, and peak resident memory for its Python process. Browser, encoder, and TTS subprocesses
are outside the Python CPU and memory measurements. The receipt reports the median and range of
module wall time across samples. The default output is a new directory under
`output/module-evaluations/` with a `results.json` receipt and sample artifacts. Use a fresh path
when specifying `--output` explicitly.

Compare timings on the same machine and runtime with the same workload and cache conditions.
Run comparisons serially without competing video exports or model jobs on the machine.
Pass the earlier receipt as `--baseline` to apply a relative median wall-time limit. The command
below uses a 20% limit and records environment or workload mismatches as incomparable.

```sh
python scripts/evaluate_modules.py --repeat 3 --baseline BASELINE.json --max-regression 0.2
```

Prepare the local video runtime before measuring. Run video separately with the accepted deck,
its data root, and paths to the installed Qwen model, TTS executable, and resident worker. This
keeps installation out of the comparison. The first export may reuse existing audio. Interpret
the first and repeat export times alongside their actual cache hits and generated segment counts.

```sh
python scripts/evaluate_modules.py --modules video --video-deck DECK.json --data-dir DATA --device vulkan --model-dir MODEL --tts-executable EXE --tts-worker WORKER --repeat 1
```

To verify model discovery, omit `--model-dir` and unset `SIGNALTRAIL_TTS_MODEL_DIR`.
Use a run data root without a complete model pair and explicitly supply the installed worker.
The video receipt records the selected pair's directory and any new files in the run's model cache.

Measure model latency and tokens in a separate host run with the same input, model, and scope.
Use the host's request records and `scripts/measure_codex_turn.py` for Codex. The fixed author
drafts in the module evaluation measure the application stages that consume those drafts.

### Whole-edition acceptance

Start a dedicated harness invocation with one request to generate the edition. Measure from the instruction to the final delivery reply and include every attributable model response from the coordinator, writers, retries and delivery checks. Total tokens are the sum of provider-reported input and output over unique responses. Cached input is already part of input and reasoning output is already part of output. Record collection-to-MP4 separately as a production-stage measurement. Label frozen replays and warm caches.

```sh
python scripts/measure_codex_turn.py --completed-turn --log-root CODEX_SESSIONS --root-thread-id THREAD --root-turn-id TURN --run RUN.json --output USAGE.json
python scripts/evaluate_edition.py --run RUN.json --report REPORT.json --deck DECK.json --video VIDEO.mp4 --host-receipt USAGE.json --full-host-measurement --resources RESOURCES.json --editorial REVIEW.json --output SCORECARD.json
```

The full-measurement flag attests that all generation occurred in the measured invocation. For an independently dispatched coordinator, also pass its thread ID as `--subtree-thread-id` when measuring and `--expected-host-subtree-id` when scoring. Mixed development chats and manually selected time windows provide diagnostic usage. Another harness may supply a run-bound receipt with `scope=completed_turn`, `selection=completed_invocation`, start/end and wall time, unique-response input and output counts under `total`, and a model/reasoning response breakdown.

Use the report and deck actually delivered. The tool verifies the deck's report ancestry and records which report the run bound. It counts every enabled source with zero published briefs and separately lists eligible frozen-plan items missing from the report. Inspect translated titles, original publication precision, visible time labels, TL;DR fidelity and concision. Record how many pages have decodable images. Grade the rendered presentation for image relevance, readable layout, concise language and directness, with page examples and sample size.

The joint score is out of 100. Time and tokens carry 15 points each, with the fraction `max(0, 1 - abs(measured - target) / target)` against 1,800 seconds and 20 million tokens. The observed low-capability score awards five points in proportion to the share of calls handled by Terra at low reasoning or below, plus five for completed delivery entirely at that setting. This grades the demonstrated configuration on this workload. Device use carries ten points proportional to the arithmetic mean of average whole-machine CPU and GPU busy percentages on this CPU/GPU test host. Source coverage earns 15 points times the fraction of enabled sources represented. Brief quality earns 15 points across title, visible publication time and TL;DR (equal weights). Slides earn ten points across image richness, image relevance and readability (desktop/mobile averaged) and ten across concision, liveliness and directness. Use the scored artifact versions and include review coverage. An unobserved dimension keeps its fixed weight and produces an interval for the total.

Start `python scripts/sample_edition_resources.py --run RUN.json --stop-file DONE --output RESOURCES.json` in a measurement terminal before launching collection. Create the new `DONE` file when the requested delivery is ready. This sampler measures host-wide CPU and memory and the busiest available NVIDIA GPU every five seconds.

Optional resource receipts bind the final run file by SHA-256 and report sample count, duration, scope (`edition` or `partial`), normalized CPU, GPU busy and memory-use percentages. Identify whole-device vs process-tree observations, sampling interval and missing periods. Editorial receipts bind the report, deck and video files by SHA-256. Each reviewed dimension specifies its status, count of distinct briefs or pages checked, and notes. Omit unobserved measures. Retain the raw dimension results and the combined score in the same receipt.

## Names and modules

| Name | Use |
| --- | --- |
| SignalTrail / `signaltrail` | Product, skill ID, main CLI; `daily-intel` is no longer installed |
| `signaltrail` | Python import package and `python -m signaltrail.cli` module entry point |
| `signaltrail-skill` | Python distribution; replaces the previous `daily-intelligence-skill` distribution |
| `DAILY_INTEL_*`, report IDs | Legacy environment names and stored identifiers remain compatible |
| SignalTrail app data and browser-profile directories | Host-neutral defaults; migrate old Hermes directories only when upgrading existing data |

Use verbs for operations (`collect_sources`, `save_report`) and nouns for data.
CLI handlers use `handle_<command>` and live in `commands/`; they translate options into domain
calls and output, while `cli.py` loads configuration and binds the data root. Shared output
and the typed context live in `commands/common.py`. Keep domain code independent of CLI modules.

Split a module when a coherent responsibility can be named and tested independently.
Avoid creating generic `manager`, `helper`, or `utils` modules for unrelated operations.
`reporting.py` owns compilation/validation and `reports.py` owns storage/Markdown today;
their remaining large functions are TD-002, not a reason to add another ambiguous report module.

Maintained functions and classes use Chinese docstrings explaining the operation, the source
and consumed content of inputs, and the result's downstream meaning. Keep these concrete:
“returns the validated index path” is useful; “returns the result of processing” is not.
Add inline comments for non-obvious safety, state, compatibility, or concurrency choices.

## Documentation and releases

README introduces the product and first run. This directory holds usage, development, the
roadmap, and dated engineering history. `references/` owns detailed runtime policy;
`SKILL.md` contains the agent procedure and conditional links to those references.

Each maintained engineering record states its purpose, status, owner, and verification date.
English records and their Chinese mirrors change together. The documentation index catalogs
single-language runtime references and historical/generated records. Keep one home for each
rule. Write about actual behavior with short examples; remove slogans, repeated feature lists,
and speculative implementation detail. Mark proposals Draft and completed run records Historical.

The documentation checker verifies local links, images, translation pairs, metadata, and current
record dates. Historical dates remain historical; they do not expire after six months.
The comment checker covers the maintained source modules and maintenance scripts.

Maintain one implementation under root `src/`; do not commit a nested skill copy.
For an explicit release request, run `python scripts/build_hermes_skill.py` to generate the
complete skill package in ignored `dist/signaltrail/`. The script name is retained for compatibility;
the Skill and package do not require Hermes. Its Git-tracked allowlist includes
`SKILL.md`, Python source, configuration, schemas, templates, references, and assets, excluding
runtime data and credentials. The generated package is a release artifact; keep the implementation
and documentation at the repository root, with no nested `skills/signaltrail/` copy. For a GitHub
release, update the version and release notes, run the package build and repository checks, then
publish the reviewed tag and generated artifact through the project release process. Install from
the complete checkout or generated package root, never from `src/` alone. A repository refactor
does not update an installed skill automatically.

Unresolved issues belong in the [technical-debt tracker](exec-plans/tech-debt-tracker.md), with
evidence and an exit condition. Record released changes in [CHANGELOG.md](../CHANGELOG.md).
