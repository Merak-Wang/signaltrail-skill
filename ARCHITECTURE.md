# Architecture

**Status:** Verified · **Owner:** Repository maintainers · **Last verified:** 2026-09-08

This is the code map for SignalTrail. [Runtime contracts](references/system-design.md)
describe data fields and recovery rules; [AGENTS.md](AGENTS.md) covers repository changes.
[中文](docs/zh-CN/ARCHITECTURE.md)

## Report flow

```text
public sources → index → bounded evidence packets → model-authored drafts
→ Python compilation and validation → versioned JSON + Markdown → HTML
→ retryable PDF, optional Notion, independent evaluation
```

Python owns identity, access status, revision allocation, validation, and persistence.
Models select and write within their assigned evidence. External content is data, including
when it appears inside a packet. A model draft becomes a report only after validation passes.

The monitor runs separately: RSS/Atom and static HTML → normalized items → lexical clusters
→ snapshot, source health, and feed cache. It makes no model calls. Formal collection can
proceed when the monitor fails.

## Code map

All modules below live in `src/daily_intelligence/`.

| Responsibility | Modules | Boundary |
| --- | --- | --- |
| Shared types and I/O | `models`, `storage`, `utils`, `runtime`, `access`, `localization`, `taxonomy` | Paths, enums, atomic writes, data-root binding |
| Configuration | `config` | Sources, limits, and runtime options |
| Collection | `adapters`, `feeds`, `prefetch`, `collector`, `clustering` | Fetch, normalize, preserve source status and order |
| Evidence | `content`, `media`, `image_policy`, `monitor` | Article text, images, snapshots, evidence lineage |
| Writing | `context`, `authoring`, `semantics`, `state` | Bounded packets, accepted batches, continuity and cache |
| Report contract | `reporting` | Compile drafts, hydrate evidence, validate schema and cross-field rules |
| Report storage | `reports` | Save reports and evaluations, render Markdown, update derived state |
| Delivery | `local_output`, `notion`, `dashboard` | HTML/PDF, remote copies, read-only monitor UI |
| Workflow | `workflow` | Run checkpoints, deadlines, recovery, evaluator scheduling |
| Usage and budget | `llm_usage/`, `llm_budget`, `evaluation` | Immutable usage events, dispatch reserves, evaluation dossiers |
| Host integration | `hosts/`, `hermes_runner`, `usage_cli` | Metered host execution, hooks and durable-log imports |
| Commands | `cli`, `commands/`, `verification`, `importer` | Parse arguments, bind configuration, call domain functions |

Dependencies point from entry points through orchestration to domain code and shared I/O.
Domain modules must not import `cli` or `commands`. In `commands/`, `parser.py` defines options,
the registry maps names to handlers, and each handler family calls domain functions through
a typed `CommandContext`. `daily-intel` and `signaltrail` invoke the same entry point.

The names `daily_intelligence`, `DAILY_INTEL_*`, and existing report IDs remain for compatibility.
The public product and new CLI name are SignalTrail. See [development](docs/development.md)
before adding another alias or package.

## State and files

`RunStatus` in `workflow.py` defines the foreground lifecycle:

```text
created → collecting → building_context → awaiting_selection
→ extracting_content → awaiting_authoring → finalizing
→ completed | completed_partial | failed
```

`completed_partial` means a local report exists with recorded gaps. PDF, Notion, and evaluation
have separate retryable state; their failure cannot revoke a saved local report.

| Files under the data root | Ownership |
| --- | --- |
| `indexes/`, `content/`, `reports/` | Versioned evidence and report records; existing revisions are not overwritten |
| `context/` | Run-bound authoring inputs and receipts; packet integrity gaps are tracked as TD-007 |
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
each run recomputes importance and status. Analysis uses three stable domain identities.

Usage storage accepts counts, timings, costs, bounded labels, and hashed lineage. It excludes
prompts, responses, reasoning, tool arguments, raw host IDs, and secrets. Unknown observations
remain null. Task locks serialize append and finalization; finalization rejects open calls.
Hashes detect inconsistent local edits, not an attacker able to rewrite the whole ledger.

`signaltrail-hermes` starts metering before Hermes, waits for worker waves, observes auxiliary
requests, and reconciles the same sessions against host counters before sealing. Independent
evaluators use a separate task and local one-shot process. Direct CLI/Cron paths retain their
documented coverage gaps. Adapter formats, accounting semantics, and compatibility limits live
in [usage metering](references/llm-usage.md).

Remaining large compiler, validator, and renderer functions are tracked as TD-002 in the
[technical-debt tracker](docs/exec-plans/tech-debt-tracker.md). Test selection and the full gate
are in the [development guide](docs/development.md).
