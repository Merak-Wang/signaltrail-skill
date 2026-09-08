# 2026-08-23 LLM Usage and Optimization Implementation

**Purpose:** Preserve the accepted implementation boundary, measured optimization evidence,
artifact lineage, and unresolved follow-up from the 2026-08-23 usage work.
**Status:** Historical
**Owner:** Repository maintainers
**Last verified:** 2026-08-28

## Outcome

The accepted deterministic scope provides:

- harness-neutral packet authoring and an immutable usage ledger; built-in usage adapters are
  Hermes, Codex, and OpenClaw, while other hosts remain unmetered or add a Python adapter;
- validated task/run lifecycles, hashed lineage, phase/batch/author/repair/evaluation correlation,
  unknown-preserving summaries, and observed-plus-reserved token gates;
- receiver-enforced brief/analysis schemas, one-repair receipts, stable analysis identities, and
  semantic-cache separation of content-stable text from run-relative state;
- hash-bound evaluator preflight and dossiers, with automatic scheduling and reconciliation in the
  Hermes Cron integration; and
- deferred, size-receipted PDF delivery with same-revision reuse and print-bound image resampling.

The 2026-08-23 experiment and 2026-08-24 evaluator recovery remain the measured authority. The
[active narrative plan](../roadmap.md) owns later delivery gates.

## Qualified External Acceptance

`projection-ab-v2` held the index, clean skeleton, cache decision snapshot, model/provider, output
contract, and file-only capability surface constant. Brief packet bytes fell 41.6%; analysis packet
bytes fell 79.5%. Both analysis arms passed first submission with zero validation errors or warnings.
Projected analysis used 5 calls and 174,588 exact tokens versus control's 9 calls and 584,418 exact
tokens: −44.4% calls and −70.1% tokens. Wall time changed +0.5%, and projected output tokens rose
11.8%; acceptance is limited to isolated analysis-phase resource use.

Control brief usage has two open calls, so 658,525 known tokens remain a lower bound; projected
brief usage is 228,465 exact tokens. Both reports validated. The recovered evaluator matrix was
31/33/33/31, below the 34/45 total and dimension floors. Control dossier/full usage was 227,083
exact versus 1,419,766 known; projected dossier/full usage was 736,545 known versus 489,658 exact.
The crossed results reject dossier parity, stable end-to-end savings, and quality acceptance.

A persisted completion stopped evaluation preflight and scheduling without another job. Hermes job
`c71034b5b9bb` reconciled from `scheduled` to `failed / host_job_error`. Original hash-bound drafts
rebuilt an object-sharing projection fault without another model call and preserved the faulty copy.

## Artifact Lineage and Persistent Decisions

Lineage is relative to the bound `DATA_DIR`:

```text
runs/... -> indexes/... -> context/...-authoring/* -> reports/... -> evaluations/dossiers/... -> evaluations/...
usage/YYYY-MM-DD/<task-id>/events/*.json -> run.llm_usage.tasks[] and evaluator parent_task_id
```

Persistent decisions:

- missing terminal usage remains `partial` and known token totals remain lower bounds;
- optimization acceptance requires the recorded quality floors and a comparable clean lifecycle;
- evaluator completion is keyed by report ID and content hash before any scheduler action;
- Hermes job reconciliation remains an integration-layer result; packet and ledger contracts remain
  harness-neutral; and
- authoritative evidence remains append-only, with derived projections rebuilt from canonical sources.

## External Acceptance Still Required

Provider and host evidence remains required in the
[technical-debt tracker](tech-debt-tracker.md#open-items):

- [TD-020](tech-debt-tracker.md#open-items): Hermes scheduled-evaluator hook routing;
- [TD-030](tech-debt-tracker.md#open-items): Hermes per-child least-privilege toolsets;
- [TD-031](tech-debt-tracker.md#open-items): stable controlled optimization quality and lifecycle
  evidence; and
- [TD-032](tech-debt-tracker.md#open-items): comparable root-like provider-turn evidence.

## Verification

Acceptance used the repository's full test, lint, compile, code-comment, documentation, and diff
gate. Focused regression coverage remains in the LLM usage, usage CLI, budget, evaluation,
authoring, semantics, reporting, architecture, and desktop-delivery test families.
